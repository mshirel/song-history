"""Self-healing CSRF middleware.

``starlette_csrf.CSRFMiddleware`` only issues a fresh ``csrftoken`` cookie when
the incoming request carries *none*. If a browser holds a token signed with a
previous ``CSRF_SECRET`` (e.g. after a secret rotation or redeploy), that stale
cookie is replayed on every request, always fails signature verification, and
is *never* replaced — leaving the user permanently stuck at HTTP 403 on every
unsafe request until they manually clear cookies. The user-visible symptom on
the web upload page is::

    Upload failed: Unexpected token 'C', "CSRF token"... is not valid JSON

(the client trying to ``JSON.parse`` the middleware's ``CSRF token verification
failed`` plain-text 403 body).

:class:`SelfHealingCSRFMiddleware` detects an incoming ``csrftoken`` cookie that
fails to deserialize and strips it from the request scope before the upstream
middleware runs. The upstream middleware then behaves exactly as if no cookie
was sent: the unsafe request is still rejected (a request bearing an
unverifiable token genuinely cannot be trusted), but the response now carries a
brand-new, valid ``Set-Cookie`` so the very next request — including an
automatic client retry — succeeds.
"""

from __future__ import annotations

from typing import Literal, cast

from itsdangerous import BadData
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send
from starlette_csrf import CSRFMiddleware  # type: ignore[attr-defined]

_SameSite = Literal["lax", "strict", "none"]


class SelfHealingCSRFMiddleware(CSRFMiddleware):
    """CSRFMiddleware that refreshes a stale/invalid ``csrftoken`` cookie."""

    def _cookie_is_valid(self, token: str) -> bool:
        """Return ``True`` only if ``token`` verifies against the current secret.

        Any malformed or wrong-secret token (``BadData`` covers ``BadSignature``
        and structurally invalid payloads) is treated as invalid.
        """
        try:
            self.serializer.loads(token)
        except BadData:
            return False
        return True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Strip an unverifiable incoming cookie so (a) the upstream middleware
        # reissues a fresh one on safe requests, and (b) its ``_csrf_tokens_match``
        # never calls ``loads`` on a malformed value (which would raise an
        # uncaught ``BadData`` and 500 on POST).
        if scope["type"] in ("http", "websocket"):
            cookie = Request(scope).cookies.get(self.cookie_name)
            if cookie is not None and not self._cookie_is_valid(cookie):
                _strip_cookie_from_scope(scope, self.cookie_name)
        await super().__call__(scope, receive, send)

    def _get_error_response(self, request: Request) -> Response:
        """Reject the request, but attach a fresh, valid ``csrftoken`` cookie.

        The upstream 403 path bypasses the cookie-setting ``send`` wrapper, so
        without this a browser holding a stale token would never receive a usable
        one. Issuing a new token on the 403 lets the client retry immediately and
        succeed; it does not aid an attacker (a cross-origin caller still cannot
        read the cookie).
        """
        response: Response = super()._get_error_response(request)
        response.set_cookie(
            self.cookie_name,
            self._generate_csrf_token(),
            path=self.cookie_path,
            secure=self.cookie_secure,
            httponly=self.cookie_httponly,
            samesite=cast(_SameSite, self.cookie_samesite),
            domain=self.cookie_domain,
        )
        return response


def _strip_cookie_from_scope(scope: Scope, name: str) -> None:
    """Remove a single named cookie from the request's ``cookie`` header in place.

    Downstream readers (the upstream CSRF middleware) then see the request as if
    that cookie was never sent, so a fresh, valid cookie is issued on the
    response. The ``cookie`` header is dropped entirely when no other cookies
    remain.
    """
    prefix = f"{name}="
    new_headers: list[tuple[bytes, bytes]] = []
    for key, value in scope.get("headers", []):
        if key.lower() == b"cookie":
            remaining = [
                pair.strip()
                for pair in value.decode("latin-1").split(";")
                if pair.strip() and not pair.strip().startswith(prefix)
            ]
            if remaining:
                new_headers.append((key, "; ".join(remaining).encode("latin-1")))
            continue
        new_headers.append((key, value))
    scope["headers"] = new_headers
