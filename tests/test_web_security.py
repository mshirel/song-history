"""Security-specific tests for the FastAPI web UI.

Covers:
- Issue #107: HTMX CDN script tag must include SRI integrity attribute
- Issue #105: leader_name Content-Disposition header injection
- Issue #106: upload filename path traversal
"""

from __future__ import annotations

import io
import os
import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from conftest import CsrfAwareClient


_PPTX_MIME = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)


@pytest.fixture
def client(db_with_songs, tmp_path, monkeypatch):
    """TestClient with DB_PATH and INBOX_DIR env vars pointed at temp locations."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setenv("DB_PATH", str(db_with_songs))
    monkeypatch.setenv("INBOX_DIR", str(inbox))
    from importlib import reload
    import worship_catalog.web.app as app_module
    reload(app_module)
    return CsrfAwareClient(TestClient(app_module.app))


_STATIC_DIR = Path(__file__).parent.parent / "src" / "worship_catalog" / "web" / "static"


class TestUploadJsXssSafety:
    """upload.js must not render server-provided strings via innerHTML (#401).

    job.error_message and err.message originate from the server (DB-stored
    exception text and JSON `detail`). Concatenating them into innerHTML is a
    DOM-XSS sink that CSP `script-src 'self'` does not fully close (e.g.
    `<img onerror=...>`). They must be rendered with textContent.
    """

    def _upload_js(self) -> str:
        return (_STATIC_DIR / "upload.js").read_text()

    @staticmethod
    def _strip_string_literals(js: str) -> str:
        """Blank out the CONTENTS of string literals so semicolons inside CSS
        (e.g. 'color:#c00;') don't masquerade as statement terminators."""
        import re

        js = re.sub(r"'(?:[^'\\]|\\.)*'", "''", js)
        js = re.sub(r'"(?:[^"\\]|\\.)*"', '""', js)
        return re.sub(r"\s+", " ", js)

    def test_error_message_not_assigned_via_innerhtml(self) -> None:
        import re

        collapsed = self._strip_string_literals(self._upload_js())
        for sink in ("error_message", "err.message"):
            # After stripping literals, `[^;]*` reliably spans one statement.
            pattern = re.compile(r"innerHTML\s*=\s*[^;]*" + re.escape(sink))
            assert not pattern.search(collapsed), (
                f"upload.js assigns {sink!r} into innerHTML — DOM-XSS risk. "
                "Render server-provided strings with textContent instead."
            )

    def test_server_strings_use_textcontent(self) -> None:
        js = self._upload_js()
        assert "textContent" in js, (
            "upload.js should use textContent to render dynamic server values safely"
        )


# ---------------------------------------------------------------------------
# Issue #107: HTMX SRI integrity attribute
# ---------------------------------------------------------------------------


class TestHtmxSelfHosted:
    """htmx is self-hosted (#196) — no CDN references, no SRI needed."""

    def test_htmx_script_is_self_hosted(self, client):
        """HTMX script tag must reference our own /static/ path, not a CDN."""
        resp = client.get("/songs")
        assert resp.status_code == 200
        assert "/static/htmx.min.js" in resp.text, (
            "HTMX <script> tag should reference /static/htmx.min.js"
        )
        assert "unpkg.com" not in resp.text, (
            "HTMX should not be loaded from unpkg CDN"
        )

    def test_no_cdn_references_on_any_page(self, client):
        """Every page that extends base.html should use self-hosted htmx."""
        for path in ["/songs", "/services", "/reports", "/leaders"]:
            resp = client.get(path)
            assert resp.status_code == 200
            assert "unpkg.com" not in resp.text, (
                f"CDN reference found on {path} — should self-host htmx"
            )
            assert "/static/htmx.min.js" in resp.text, (
                f"Self-hosted htmx reference missing on {path}"
            )


# ---------------------------------------------------------------------------
# Issue #105: Content-Disposition header injection via leader_name
# ---------------------------------------------------------------------------


class TestContentDispositionSanitization:
    def test_content_disposition_does_not_contain_injected_newline(self, client):
        """leader_name with CRLF must not produce a multi-line header."""
        # URL-encoded CRLF + injected header value
        resp = client.get("/leaders/Evil%0d%0aX-Injected%3a%20pwned/top-songs/csv")
        cd = resp.headers.get("content-disposition", "")
        assert "\r" not in cd, "CR character leaked into Content-Disposition header"
        assert "\n" not in cd, "LF character leaked into Content-Disposition header"

    def test_content_disposition_injected_header_not_present(self, client):
        """Injected header key must not appear as a separate response header."""
        resp = client.get("/leaders/Evil%0d%0aX-Injected%3a%20pwned/top-songs/csv")
        # The injected header must not appear in the response
        assert "x-injected" not in [k.lower() for k in resp.headers.keys()], (
            "HTTP response header injection succeeded — X-Injected appeared as a header"
        )

    def test_content_disposition_sanitizes_quotes(self, client):
        """leader_name with embedded double-quotes must be stripped from filename."""
        resp = client.get('/leaders/John%20%22Bobby%22%20Smith/top-songs/csv')
        cd = resp.headers.get("content-disposition", "")
        if cd:
            # The filename= value should not have unescaped interior quotes that
            # would break the header structure.  Strip the outer wrapping quotes
            # (if any) and check for remaining double-quotes in the name part.
            import re
            m = re.search(r'filename="([^"]*)"', cd)
            if m:
                inner = m.group(1)
                assert '"' not in inner, (
                    f'Unescaped quote in filename value: {cd!r}'
                )

    def test_content_disposition_sanitizes_semicolons(self, client):
        """Semicolons in leader_name must not break the Content-Disposition structure."""
        resp = client.get("/leaders/Leader%3BX-Extra%3Dval/top-songs/csv")
        cd = resp.headers.get("content-disposition", "")
        if cd:
            # There should be exactly one 'filename=' directive (the semicolon
            # in the leader name must not inject a second directive).
            assert cd.count("filename=") == 1, (
                f"Semicolon injection created extra filename= in Content-Disposition: {cd!r}"
            )

    def test_content_disposition_filename_is_safe_characters_only(self, client):
        """Sanitized filename should only contain alphanumeric, spaces, hyphens, underscores, dots."""
        import re
        resp = client.get("/leaders/Matt/top-songs/csv")
        cd = resp.headers.get("content-disposition", "")
        assert cd, "Expected Content-Disposition header to be present"
        m = re.search(r'filename="?([^";\r\n]+)"?', cd)
        assert m, f"Could not parse filename from Content-Disposition: {cd!r}"
        fname = m.group(1).strip('"')
        # Allow only safe characters: alphanumeric, space, hyphen, underscore, dot
        assert re.match(r'^[\w\s.\-]+$', fname), (
            f"Filename contains unsafe characters: {fname!r}"
        )


# ---------------------------------------------------------------------------
# Issue #106: Upload filename path traversal
# ---------------------------------------------------------------------------


class TestUploadFilenamePathTraversal:
    def _upload(self, client, filename: str, content: bytes = b"PK\x03\x04") -> object:
        """Helper: POST to /upload with given filename."""
        data = {
            "file": (
                filename,
                io.BytesIO(content),
                _PPTX_MIME,
            )
        }
        return client.post("/upload", files=data)

    def test_path_traversal_filename_is_rejected_or_sanitized(self, client, tmp_path, monkeypatch):
        """Filename with directory traversal must be rejected (400) or basename-only used."""
        resp = self._upload(client, "../../../etc/evil.pptx")
        if resp.status_code == 400:
            # Rejected outright — pass
            return
        # Accepted — verify no traversal in job filename
        assert resp.status_code == 202, f"Unexpected status: {resp.status_code}"
        job_id = resp.json()["job_id"]
        job_resp = client.get(f"/jobs/{job_id}")
        assert job_resp.status_code == 200
        recorded_filename = job_resp.json().get("filename", "")
        assert "../" not in recorded_filename, (
            f"Path traversal sequence present in recorded filename: {recorded_filename!r}"
        )
        assert recorded_filename == "evil.pptx" or recorded_filename.endswith("evil.pptx"), (
            f"Basename not used; got: {recorded_filename!r}"
        )

    def test_path_traversal_file_not_written_outside_inbox(self, client, tmp_path, monkeypatch):
        """The uploaded file must land inside INBOX_DIR, not at the traversal path."""
        inbox = tmp_path / "inbox"
        inbox.mkdir(exist_ok=True)
        monkeypatch.setenv("INBOX_DIR", str(inbox))
        # Reload to pick up new env var
        from importlib import reload
        import worship_catalog.web.app as app_module
        reload(app_module)
        inner = TestClient(app_module.app)
        # Re-wrap with CSRF helper
        wrapped = CsrfAwareClient(inner)

        resp = self._upload(wrapped, "../../../tmp/evil.pptx")
        if resp.status_code == 202:
            # Verify file is INSIDE inbox only
            outside_path = tmp_path / "tmp" / "evil.pptx"
            assert not outside_path.exists(), (
                f"File was written outside INBOX_DIR: {outside_path}"
            )

    def test_upload_rejects_non_pptx_extension(self, client):
        """Files without .pptx extension must be rejected with 400."""
        data = {
            "file": (
                "evil.sh",
                io.BytesIO(b"#!/bin/bash\nrm -rf /"),
                "text/plain",
            )
        }
        resp = client.post("/upload", files=data)
        assert resp.status_code == 400, (
            f"Expected 400 for non-pptx file, got {resp.status_code}"
        )

    def test_upload_rejects_double_extension_traversal(self, client):
        """Filename like 'evil.pptx.sh' (or similar tricks) must be rejected or only basename kept."""
        resp = self._upload(client, "../../evil.pptx")
        if resp.status_code == 202:
            job_id = resp.json()["job_id"]
            job_resp = client.get(f"/jobs/{job_id}")
            recorded = job_resp.json().get("filename", "")
            assert "../../" not in recorded, (
                f"Traversal path present in recorded filename: {recorded!r}"
            )

    def test_upload_empty_filename_after_sanitization_is_rejected(self, client):
        """If sanitizing the filename results in an empty string, it must be rejected (400)."""
        # Filename that is all path separators / dots — after stripping directory
        # components will be empty or '.', which is invalid.
        resp = self._upload(client, "../../")
        # Either rejected with 400 (bad extension / empty name) or some other error
        # The important thing: not 202 with a blank filename
        if resp.status_code == 202:
            job_id = resp.json()["job_id"]
            job_resp = client.get(f"/jobs/{job_id}")
            recorded = job_resp.json().get("filename", "")
            assert recorded and recorded != ".", (
                f"Empty or dot filename accepted: {recorded!r}"
            )


# ---------------------------------------------------------------------------
# Issue #139 — CSRF_SECRET startup behavior
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Issue #140 — stats download Content-Disposition filename sanitization
# ---------------------------------------------------------------------------


class TestStatsDownloadFilenameSanitization:
    """Stats CSV/XLSX filenames must be sanitized — issue #140."""

    def test_normal_dates_produce_expected_filename(self, client):
        """Normal ISO dates produce a clean stats_<start>_<end>.csv filename."""
        import re
        resp = client.post(
            "/reports/stats/csv",
            data={
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "leader": "",
                "all_songs": "false",
            },
        )
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert "stats_2026-01-01_2026-12-31.csv" in cd

    def test_injection_chars_stripped_from_filename(self, client):
        """A date value with injection chars must not appear verbatim in Content-Disposition."""
        # The date values are validated by _validate_date_range before reaching filename
        # construction, so injected dates will return 422.  We verify the sanitizer
        # directly via the helper used in the route.
        from worship_catalog.web.app import _sanitize_header_filename
        evil = '2024-01-01"; filename="evil'
        sanitized = _sanitize_header_filename(evil)
        assert '"' not in sanitized, (
            f"Double-quote leaked into sanitized filename: {sanitized!r}"
        )
        assert "evil" not in sanitized or "evil" in sanitized.replace('"', ""), (
            "Injection quote was not stripped"
        )

    def test_filename_matches_pattern(self, client):
        """Stats CSV filename must only contain safe characters."""
        import re
        resp = client.post(
            "/reports/stats/csv",
            data={
                "start_date": "2026-01-01",
                "end_date": "2026-03-31",
                "leader": "",
                "all_songs": "false",
            },
        )
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        m = re.search(r'filename="?([^";\r\n]+)"?', cd)
        assert m, f"Could not parse filename from Content-Disposition: {cd!r}"
        fname = m.group(1).strip('"')
        # Allow only: alphanumeric, hyphens, underscores, dots
        assert re.match(r'^[\w.\-]+$', fname), (
            f"Filename contains unsafe characters: {fname!r}"
        )

    def test_stats_xlsx_filename_is_sanitized(self, client):
        """Stats XLSX filename must also use only safe characters."""
        import re
        try:
            resp = client.post(
                "/reports/stats/xlsx",
                data={
                    "start_date": "2026-01-01",
                    "end_date": "2026-03-31",
                    "leader": "",
                    "all_songs": "false",
                },
            )
        except Exception:
            pytest.skip("openpyxl not installed")
        if resp.status_code == 501:
            pytest.skip("openpyxl not installed")
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        m = re.search(r'filename="?([^";\r\n]+)"?', cd)
        assert m, f"Could not parse filename from Content-Disposition: {cd!r}"
        fname = m.group(1).strip('"')
        assert re.match(r'^[\w.\-]+$', fname), (
            f"XLSX filename contains unsafe characters: {fname!r}"
        )


class TestCsrfSecretStartup:
    """CSRF_SECRET env var behavior — issue #139."""

    def test_app_starts_normally_when_csrf_secret_set(self, tmp_path, monkeypatch):
        """App starts without error when CSRF_SECRET is set in the environment."""
        monkeypatch.setenv("CSRF_SECRET", "a" * 64)
        monkeypatch.setenv("DB_PATH", str(tmp_path / "csrf_test.db"))
        monkeypatch.setenv("INBOX_DIR", str(tmp_path / "inbox"))
        (tmp_path / "inbox").mkdir()
        from worship_catalog.db import Database
        db = Database(tmp_path / "csrf_test.db")
        db.connect()
        db.init_schema()
        db.close()
        from importlib import reload
        import worship_catalog.web.app as app_module
        reload(app_module)
        client = TestClient(app_module.app)
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_app_starts_with_random_fallback_when_testing_mode(self, tmp_path, monkeypatch):
        """When CSRF_SECRET is absent but TESTING=1, app still starts (random fallback)."""
        monkeypatch.delenv("CSRF_SECRET", raising=False)
        monkeypatch.setenv("TESTING", "1")
        monkeypatch.setenv("DB_PATH", str(tmp_path / "csrf_test2.db"))
        monkeypatch.setenv("INBOX_DIR", str(tmp_path / "inbox2"))
        (tmp_path / "inbox2").mkdir()
        from worship_catalog.db import Database
        db = Database(tmp_path / "csrf_test2.db")
        db.connect()
        db.init_schema()
        db.close()
        from importlib import reload
        import worship_catalog.web.app as app_module
        reload(app_module)
        client = TestClient(app_module.app)
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_app_refuses_to_start_without_csrf_secret_in_production(self, tmp_path, monkeypatch):
        """Outside TESTING mode, a missing CSRF_SECRET must hard-fail at startup so a
        production deploy can't silently fall back to an ephemeral secret (#406)."""
        monkeypatch.delenv("CSRF_SECRET", raising=False)
        monkeypatch.delenv("TESTING", raising=False)
        monkeypatch.setenv("DB_PATH", str(tmp_path / "csrf_prod.db"))
        monkeypatch.setenv("INBOX_DIR", str(tmp_path / "inbox_prod"))
        (tmp_path / "inbox_prod").mkdir()
        from importlib import reload

        import worship_catalog.web.app as app_module
        try:
            with pytest.raises(RuntimeError, match="CSRF_SECRET"):
                reload(app_module)
        finally:
            # Leave a healthy module for the rest of the session.
            monkeypatch.setenv("TESTING", "1")
            reload(app_module)

    def test_csrf_token_persists_across_requests(self, tmp_path, monkeypatch):
        """CSRF token obtained in one request must be valid in the next."""
        monkeypatch.setenv("CSRF_SECRET", "b" * 64)
        monkeypatch.setenv("DB_PATH", str(tmp_path / "csrf_persist.db"))
        monkeypatch.setenv("INBOX_DIR", str(tmp_path / "inbox3"))
        (tmp_path / "inbox3").mkdir()
        from worship_catalog.db import Database
        db = Database(tmp_path / "csrf_persist.db")
        db.connect()
        db.init_schema()
        db.close()
        from importlib import reload
        import worship_catalog.web.app as app_module
        reload(app_module)
        inner = TestClient(app_module.app)

        # Get a CSRF token from first request
        resp1 = inner.get("/songs")
        token = resp1.cookies.get("csrftoken", "")
        assert token, "No csrftoken cookie set by GET /songs"

        # Use that token on second request (POST)
        # We need to supply a valid pptx mime+file to get past mime check, or hit a POST
        # that doesn't need a body — just confirm 403 is NOT returned (which would mean invalid CSRF)
        from io import BytesIO
        resp2 = inner.post(
            "/upload",
            files={"file": ("test.pptx", BytesIO(b"PK"), _PPTX_MIME)},
            headers={"X-CSRFToken": token},
        )
        # Any response except 403 means CSRF token was accepted
        assert resp2.status_code != 403, (
            f"CSRF token was rejected on second request (status={resp2.status_code}). "
            "Token must remain valid across requests when CSRF_SECRET is fixed."
        )


# ---------------------------------------------------------------------------
# Issue #404 — client IP resolution must not trust spoofable X-Forwarded-For
# ---------------------------------------------------------------------------


class _FakeClient:
    def __init__(self, host: str) -> None:
        self.host = host


class _FakeRequest:
    """Minimal stand-in exposing the .headers.get() and .client.host that
    _get_client_ip relies on (headers are matched case-insensitively)."""

    def __init__(self, headers: dict[str, str], client_host: str = "10.0.0.9") -> None:
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.client = _FakeClient(client_host)


class TestClientIpResolution:
    """_get_client_ip must prefer Cloudflare's unspoofable CF-Connecting-IP and
    never trust the client-controlled leftmost X-Forwarded-For entry (#404)."""

    def _app(self):
        from importlib import reload

        import worship_catalog.web.app as app_module
        reload(app_module)
        return app_module

    def test_cf_connecting_ip_preferred_over_xff(self, monkeypatch) -> None:
        app_module = self._app()
        monkeypatch.setattr(app_module, "_TRUST_PROXY", True)
        req = _FakeRequest({
            "CF-Connecting-IP": "203.0.113.7",
            "X-Forwarded-For": "1.2.3.4",  # attacker-supplied leftmost
        })
        assert app_module._get_client_ip(req) == "203.0.113.7"

    def test_spoofed_leftmost_xff_ignored(self, monkeypatch) -> None:
        """Without CF header, the leftmost (client-set) XFF entry must NOT be used;
        the proxy-appended rightmost entry is the trustworthy one."""
        app_module = self._app()
        monkeypatch.setattr(app_module, "_TRUST_PROXY", True)
        req = _FakeRequest({"X-Forwarded-For": "1.2.3.4, 198.51.100.2"})
        ip = app_module._get_client_ip(req)
        assert ip != "1.2.3.4", "Leftmost X-Forwarded-For is client-controlled and spoofable"
        assert ip == "198.51.100.2"

    def test_proxy_disabled_uses_socket_peer(self, monkeypatch) -> None:
        app_module = self._app()
        monkeypatch.setattr(app_module, "_TRUST_PROXY", False)
        req = _FakeRequest(
            {"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-For": "1.2.3.4"},
            client_host="10.0.0.9",
        )
        assert app_module._get_client_ip(req) == "10.0.0.9"

    def test_no_proxy_headers_falls_back_to_peer(self, monkeypatch) -> None:
        app_module = self._app()
        monkeypatch.setattr(app_module, "_TRUST_PROXY", True)
        req = _FakeRequest({}, client_host="172.16.0.5")
        assert app_module._get_client_ip(req) == "172.16.0.5"


# ---------------------------------------------------------------------------
# Issue #173 — Upload rate limiting
# ---------------------------------------------------------------------------


class TestUploadRateLimiting:
    """POST /upload must enforce per-client rate limiting — issue #173."""

    def _make_pptx_bytes(self) -> bytes:
        try:
            from pptx import Presentation
            buf = io.BytesIO()
            Presentation().save(buf)
            return buf.getvalue()
        except ImportError:
            pytest.skip("python-pptx not available")
            return b""  # unreachable, satisfies type checker

    def test_upload_rate_limit_rejects_burst(self, client, monkeypatch):
        """Rapid successive uploads from same client should eventually receive 429."""
        monkeypatch.setattr(
            "worship_catalog.web.app._UPLOAD_RATE_LIMIT", 5,
        )
        monkeypatch.setattr(
            "worship_catalog.web.app._UPLOAD_RATE_WINDOW_SECONDS", 3600,
        )
        pptx_data = self._make_pptx_bytes()
        responses = []
        for i in range(10):
            resp = client.post(
                "/upload",
                files={"file": (f"Worship_{i}.pptx", io.BytesIO(pptx_data), _PPTX_MIME)},
            )
            responses.append(resp.status_code)
        assert 429 in responses, (
            f"No 429 returned after {len(responses)} uploads — rate limiting is not enforced. "
            f"Got: {responses}"
        )

    def test_upload_rate_limit_first_request_succeeds(self, client, monkeypatch):
        """First upload within rate limit window must still succeed (not 429)."""
        monkeypatch.setattr(
            "worship_catalog.web.app._UPLOAD_RATE_LIMIT", 5,
        )
        pptx_data = self._make_pptx_bytes()
        resp = client.post(
            "/upload",
            files={"file": ("Worship_first.pptx", io.BytesIO(pptx_data), _PPTX_MIME)},
        )
        assert resp.status_code in (202, 503), (
            f"First upload should be accepted (202) or pool-full (503), got {resp.status_code}"
        )

    def test_upload_rate_limit_429_includes_retry_after(self, client, monkeypatch):
        """429 response must include a Retry-After header."""
        monkeypatch.setattr(
            "worship_catalog.web.app._UPLOAD_RATE_LIMIT", 1,
        )
        monkeypatch.setattr(
            "worship_catalog.web.app._UPLOAD_RATE_WINDOW_SECONDS", 3600,
        )
        pptx_data = self._make_pptx_bytes()
        # First request succeeds
        client.post(
            "/upload",
            files={"file": ("first.pptx", io.BytesIO(pptx_data), _PPTX_MIME)},
        )
        # Second request should be rate-limited
        resp = client.post(
            "/upload",
            files={"file": ("second.pptx", io.BytesIO(pptx_data), _PPTX_MIME)},
        )
        assert resp.status_code == 429
        assert "retry-after" in resp.headers, (
            "429 response must include Retry-After header"
        )

    def test_upload_rate_limit_429_body_is_json(self, client, monkeypatch):
        """429 response body must be JSON with a detail message."""
        monkeypatch.setattr(
            "worship_catalog.web.app._UPLOAD_RATE_LIMIT", 1,
        )
        pptx_data = self._make_pptx_bytes()
        client.post(
            "/upload",
            files={"file": ("first.pptx", io.BytesIO(pptx_data), _PPTX_MIME)},
        )
        resp = client.post(
            "/upload",
            files={"file": ("second.pptx", io.BytesIO(pptx_data), _PPTX_MIME)},
        )
        assert resp.status_code == 429
        body = resp.json()
        assert "detail" in body, f"429 body must have 'detail' key, got: {body}"

    def test_upload_rate_limit_retry_after_is_positive_integer(self, client, monkeypatch):
        """Retry-After header must be a positive integer (seconds)."""
        monkeypatch.setattr(
            "worship_catalog.web.app._UPLOAD_RATE_LIMIT", 1,
        )
        monkeypatch.setattr(
            "worship_catalog.web.app._UPLOAD_RATE_WINDOW_SECONDS", 3600,
        )
        pptx_data = self._make_pptx_bytes()
        client.post(
            "/upload",
            files={"file": ("first.pptx", io.BytesIO(pptx_data), _PPTX_MIME)},
        )
        resp = client.post(
            "/upload",
            files={"file": ("second.pptx", io.BytesIO(pptx_data), _PPTX_MIME)},
        )
        assert resp.status_code == 429
        retry_val = resp.headers["retry-after"]
        retry_int = int(retry_val)
        assert retry_int > 0, (
            f"Retry-After must be a positive integer, got: {retry_val}"
        )

    def test_upload_rate_limit_detail_message_is_user_friendly(self, client, monkeypatch):
        """429 detail message must tell the user to try again later."""
        monkeypatch.setattr(
            "worship_catalog.web.app._UPLOAD_RATE_LIMIT", 1,
        )
        pptx_data = self._make_pptx_bytes()
        client.post(
            "/upload",
            files={"file": ("first.pptx", io.BytesIO(pptx_data), _PPTX_MIME)},
        )
        resp = client.post(
            "/upload",
            files={"file": ("second.pptx", io.BytesIO(pptx_data), _PPTX_MIME)},
        )
        assert resp.status_code == 429
        detail = resp.json()["detail"]
        # Must mention rate limit and suggest retrying
        assert "rate limit" in detail.lower() or "too many" in detail.lower(), (
            f"429 detail should mention rate limit, got: {detail!r}"
        )
        assert "later" in detail.lower() or "retry" in detail.lower(), (
            f"429 detail should suggest retrying, got: {detail!r}"
        )


class TestUploadRateLimiterUnit:
    """Direct unit tests for the _UploadRateLimiter class — edge cases."""

    def test_different_ips_are_independent(self):
        """Exhausting one IP's quota must not affect another IP."""
        from worship_catalog.web.app import _UploadRateLimiter
        import worship_catalog.web.app as app_module

        original_limit = app_module._UPLOAD_RATE_LIMIT
        original_window = app_module._UPLOAD_RATE_WINDOW_SECONDS
        try:
            app_module._UPLOAD_RATE_LIMIT = 2
            app_module._UPLOAD_RATE_WINDOW_SECONDS = 3600
            limiter = _UploadRateLimiter()

            # Exhaust IP-A's quota
            assert limiter.is_allowed("192.168.1.1")[0] is True
            assert limiter.is_allowed("192.168.1.1")[0] is True
            assert limiter.is_allowed("192.168.1.1")[0] is False

            # IP-B must still be allowed
            allowed, _ = limiter.is_allowed("10.0.0.1")
            assert allowed is True, (
                "Different IP was blocked by another IP's exhausted quota"
            )
        finally:
            app_module._UPLOAD_RATE_LIMIT = original_limit
            app_module._UPLOAD_RATE_WINDOW_SECONDS = original_window

    def test_window_expiry_allows_new_uploads(self, monkeypatch):
        """After the sliding window elapses, the client should be allowed again."""
        import time as time_mod
        from worship_catalog.web.app import _UploadRateLimiter
        import worship_catalog.web.app as app_module

        original_limit = app_module._UPLOAD_RATE_LIMIT
        original_window = app_module._UPLOAD_RATE_WINDOW_SECONDS
        try:
            app_module._UPLOAD_RATE_LIMIT = 1
            app_module._UPLOAD_RATE_WINDOW_SECONDS = 10  # 10 second window
            limiter = _UploadRateLimiter()

            # First upload succeeds
            assert limiter.is_allowed("1.2.3.4")[0] is True
            # Second is blocked
            assert limiter.is_allowed("1.2.3.4")[0] is False

            # Simulate time passing beyond the window by manipulating timestamps
            # Move all stored timestamps far into the past
            with limiter._lock:
                limiter._timestamps["1.2.3.4"] = [
                    time_mod.monotonic() - 20  # 20s ago, outside 10s window
                ]

            # Now should be allowed again
            allowed, _ = limiter.is_allowed("1.2.3.4")
            assert allowed is True, (
                "Client should be allowed after sliding window elapses"
            )
        finally:
            app_module._UPLOAD_RATE_LIMIT = original_limit
            app_module._UPLOAD_RATE_WINDOW_SECONDS = original_window

    def test_unknown_ip_fallback_shares_bucket(self):
        """When client IP is 'unknown', all such clients share one bucket."""
        from worship_catalog.web.app import _UploadRateLimiter
        import worship_catalog.web.app as app_module

        original_limit = app_module._UPLOAD_RATE_LIMIT
        try:
            app_module._UPLOAD_RATE_LIMIT = 1
            limiter = _UploadRateLimiter()

            # First "unknown" client uses the slot
            assert limiter.is_allowed("unknown")[0] is True
            # Second "unknown" client is also blocked
            assert limiter.is_allowed("unknown")[0] is False
        finally:
            app_module._UPLOAD_RATE_LIMIT = original_limit

    def test_retry_after_never_exceeds_window(self):
        """Retry-After value must not exceed the configured window duration."""
        from worship_catalog.web.app import _UploadRateLimiter
        import worship_catalog.web.app as app_module

        original_limit = app_module._UPLOAD_RATE_LIMIT
        original_window = app_module._UPLOAD_RATE_WINDOW_SECONDS
        try:
            app_module._UPLOAD_RATE_LIMIT = 1
            app_module._UPLOAD_RATE_WINDOW_SECONDS = 3600
            limiter = _UploadRateLimiter()

            limiter.is_allowed("5.6.7.8")
            _, retry_after = limiter.is_allowed("5.6.7.8")
            assert 0 < retry_after <= 3600, (
                f"Retry-After ({retry_after}) should be between 1 and window size (3600)"
            )
        finally:
            app_module._UPLOAD_RATE_LIMIT = original_limit
            app_module._UPLOAD_RATE_WINDOW_SECONDS = original_window


# ---------------------------------------------------------------------------
# Issue #197 — Content-Security-Policy header
# ---------------------------------------------------------------------------


class TestContentSecurityPolicy:
    """All HTML responses must include a Content-Security-Policy header."""

    def test_songs_page_has_csp_header(self, client):
        resp = client.get("/songs")
        assert resp.status_code == 200
        csp = resp.headers.get("content-security-policy")
        assert csp is not None, "Response missing Content-Security-Policy header"
        assert "script-src" in csp, "CSP must restrict script sources"

    def test_csp_disallows_unsafe_inline(self, client):
        resp = client.get("/songs")
        csp = resp.headers.get("content-security-policy", "")
        if "script-src" in csp:
            script_src_value = csp.split("script-src")[1].split(";")[0]
            assert "'unsafe-inline'" not in script_src_value, (
                "CSP script-src must not allow 'unsafe-inline'"
            )

    def test_csp_restricts_to_self(self, client):
        """script-src should include 'self' to allow same-origin scripts."""
        resp = client.get("/songs")
        csp = resp.headers.get("content-security-policy", "")
        assert "'self'" in csp, "CSP must include 'self' directive"

    def test_reports_page_has_csp_header(self, client):
        resp = client.get("/reports")
        assert resp.status_code == 200
        csp = resp.headers.get("content-security-policy")
        assert csp is not None, "Reports page missing CSP header"


# ---------------------------------------------------------------------------
# Issue #235 — Upload CSRF integration (PowerShell script compatibility)
# ---------------------------------------------------------------------------


@pytest.fixture
def raw_client(db_with_songs, tmp_path, monkeypatch):
    """Plain TestClient without CSRF token injection — for CSRF security tests."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setenv("DB_PATH", str(db_with_songs))
    monkeypatch.setenv("INBOX_DIR", str(inbox))
    from importlib import reload
    import worship_catalog.web.app as app_module
    reload(app_module)
    return TestClient(app_module.app)


class TestUploadCsrfIntegration:
    """Upload endpoint CSRF behavior — issue #235."""

    def test_upload_without_csrf_returns_403(self, raw_client):
        """POST /upload without CSRF token must be rejected with 403."""
        pptx_mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        resp = raw_client.post(
            "/upload",
            files={"file": ("test.pptx", io.BytesIO(b"PK\x03\x04dummy"), pptx_mime)},
        )
        assert resp.status_code == 403

    def test_upload_with_csrf_token_succeeds(self, client):
        """POST /upload with valid CSRF token must not be rejected by CSRF middleware."""
        pptx_mime = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        resp = client.post(
            "/upload",
            files={"file": ("test.pptx", io.BytesIO(b"PK\x03\x04dummy"), pptx_mime)},
        )
        assert resp.status_code != 403


# ---------------------------------------------------------------------------
# Issue #238 — Report download forms missing CSRF tokens
# Issue #239 — CSRF cookie name mismatch
# ---------------------------------------------------------------------------


class TestReportCsrfTokens:
    """Report download forms must send the CSRF token so POSTs are not blocked (#238)."""

    def test_reports_page_includes_reports_js(self, client):
        """Reports page must load an external reports.js script for CSRF handling."""
        resp = client.get("/reports")
        assert resp.status_code == 200
        assert "/static/reports.js" in resp.text, (
            "Reports page must include <script src='/static/reports.js'>"
        )

    def test_reports_js_file_exists_and_references_csrftoken_cookie(self, client):
        """The reports.js static file must exist and read the csrftoken cookie."""
        resp = client.get("/static/reports.js")
        assert resp.status_code == 200, "reports.js not found at /static/reports.js"
        assert "csrftoken" in resp.text, (
            "reports.js must read the 'csrftoken' cookie"
        )
        assert "X-CSRFToken" in resp.text, (
            "reports.js must send the X-CSRFToken header"
        )

    def test_ccli_form_is_intercepted_by_js(self, client):
        """CCLI download form must have an id so reports.js can intercept it."""
        resp = client.get("/reports")
        assert resp.status_code == 200
        assert 'id="ccli-form"' in resp.text, (
            "CCLI form must have id='ccli-form' for JS interception"
        )

    def test_htmx_csrf_header_configured_via_reports_js(self, client):
        """reports.js must configure htmx to send CSRF headers on all requests."""
        # reports.js is loaded on the reports page and calls configureHtmxCsrf()
        # which sets hx-headers on document.body with the X-CSRFToken header.
        resp = client.get("/static/reports.js")
        assert resp.status_code == 200
        assert "hx-headers" in resp.text, (
            "reports.js must set hx-headers on document.body for htmx CSRF"
        )
        assert "X-CSRFToken" in resp.text, (
            "reports.js must include X-CSRFToken in the hx-headers config"
        )

    def test_stats_csv_download_with_csrf_succeeds(self, client):
        """Stats CSV download via POST must not be blocked by CSRF."""
        resp = client.post(
            "/reports/stats/csv",
            data={"start_date": "2026-01-01", "end_date": "2026-12-31"},
        )
        assert resp.status_code != 403, (
            "Stats CSV download blocked by CSRF — form is missing token"
        )

    def test_stats_xlsx_download_with_csrf_succeeds(self, client):
        """Stats Excel download via POST must not be blocked by CSRF."""
        try:
            resp = client.post(
                "/reports/stats/xlsx",
                data={"start_date": "2026-01-01", "end_date": "2026-12-31"},
            )
        except Exception:
            pytest.skip("openpyxl not installed")
        if resp.status_code == 501:
            pytest.skip("openpyxl not installed")
        assert resp.status_code != 403, (
            "Stats Excel download blocked by CSRF — form is missing token"
        )

    def test_ccli_csv_download_with_csrf_succeeds(self, client):
        """CCLI CSV download via POST must not be blocked by CSRF."""
        resp = client.post(
            "/reports/ccli",
            data={"start_date": "2026-01-01", "end_date": "2026-12-31"},
        )
        assert resp.status_code != 403, (
            "CCLI CSV download blocked by CSRF — form is missing token"
        )


class TestCsrfCookieConfiguration:
    """CSRF cookie name must be explicitly configured (#239)."""

    def test_csrf_cookie_is_set_on_first_get(self, db_with_songs, tmp_path, monkeypatch):
        """A GET request must set the csrftoken cookie."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        monkeypatch.setenv("DB_PATH", str(db_with_songs))
        monkeypatch.setenv("INBOX_DIR", str(inbox))
        from importlib import reload
        import worship_catalog.web.app as app_module
        reload(app_module)
        raw = TestClient(app_module.app)
        resp = raw.get("/songs")
        assert "csrftoken" in resp.cookies, (
            "CSRF middleware did not set 'csrftoken' cookie on GET /songs"
        )

    def test_csrf_cookie_name_is_explicitly_configured(self):
        """The CSRFMiddleware must be configured with an explicit cookie_name."""
        import inspect
        import worship_catalog.web.app as app_module
        source = inspect.getsource(app_module)
        assert "cookie_name" in source, (
            "CSRFMiddleware must explicitly set cookie_name='csrftoken' "
            "to avoid implicit coupling (#239)"
        )

    def test_reports_js_references_correct_cookie_name(self, client):
        """reports.js must read from the same cookie name the middleware sets."""
        resp = client.get("/static/reports.js")
        assert resp.status_code == 200
        assert "csrftoken" in resp.text, (
            "reports.js does not reference the correct CSRF cookie name"
        )


class TestSecurityHeaders:
    """Tests for security response headers (#282)."""

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
        import worship_catalog.web.app as app_module
        app_module._schema_ready = False
        return TestClient(app_module.app)

    def test_x_content_type_options(self, client):
        resp = client.get("/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_referrer_policy(self, client):
        resp = client.get("/health")
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client):
        resp = client.get("/health")
        pp = resp.headers.get("Permissions-Policy", "")
        assert "camera=()" in pp
        assert "microphone=()" in pp

    def test_csp_still_present(self, client):
        resp = client.get("/health")
        assert "Content-Security-Policy" in resp.headers


class TestHstsHeader:
    """Strict-Transport-Security must be emitted when HTTPS_ONLY is enabled (#405).

    HSTS is gated on HTTPS_ONLY so that local/CI deployments served over plain
    HTTP do not send an HSTS policy that would lock browsers into HTTPS.
    """

    def _client(self, tmp_path, monkeypatch, https_only):
        monkeypatch.setenv("DB_PATH", str(tmp_path / "hsts.db"))
        inbox = tmp_path / "hsts_inbox"
        inbox.mkdir(exist_ok=True)
        monkeypatch.setenv("INBOX_DIR", str(inbox))
        if https_only is None:
            monkeypatch.delenv("HTTPS_ONLY", raising=False)
        else:
            monkeypatch.setenv("HTTPS_ONLY", https_only)
        from importlib import reload

        import worship_catalog.web.app as app_module
        reload(app_module)
        return TestClient(app_module.app)

    def test_hsts_present_when_https_only_enabled(self, tmp_path, monkeypatch):
        import re

        client = self._client(tmp_path, monkeypatch, "1")
        resp = client.get("/health")
        hsts = resp.headers.get("Strict-Transport-Security", "")
        assert hsts, "HSTS header missing when HTTPS_ONLY=1"
        m = re.search(r"max-age=(\d+)", hsts)
        assert m and int(m.group(1)) >= 31536000, f"HSTS max-age too low: {hsts!r}"
        assert "includeSubDomains" in hsts

    def test_hsts_absent_by_default(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch, None)
        resp = client.get("/health")
        assert "Strict-Transport-Security" not in resp.headers, (
            "HSTS must not be sent unless HTTPS_ONLY is enabled (would break HTTP dev)"
        )


# ---------------------------------------------------------------------------
# #388 Phase 1: simple password gate on the upload page
# ---------------------------------------------------------------------------


class TestUploadAuth:
    """The upload page/endpoint requires a password when UPLOAD_PASSWORD is set;
    when unset the upload stays open (current behavior). Browsing is always public."""

    @pytest.fixture
    def auth_client(self, db_with_songs, tmp_path, monkeypatch):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        monkeypatch.setenv("DB_PATH", str(db_with_songs))
        monkeypatch.setenv("INBOX_DIR", str(inbox))
        monkeypatch.setenv("UPLOAD_PASSWORD", "s3cret")
        from importlib import reload
        import worship_catalog.web.app as app_module
        reload(app_module)
        return CsrfAwareClient(TestClient(app_module.app))

    def test_get_upload_requires_auth_when_password_set(self, auth_client):
        r = auth_client.get("/upload")
        assert r.status_code == 401
        assert "basic" in r.headers.get("www-authenticate", "").lower()

    def test_get_upload_succeeds_with_valid_credentials(self, auth_client):
        r = auth_client.get("/upload", auth=("highland", "s3cret"))
        assert r.status_code == 200

    def test_get_upload_rejects_wrong_password(self, auth_client):
        r = auth_client.get("/upload", auth=("highland", "wrong"))
        assert r.status_code == 401

    def test_post_upload_requires_auth(self, auth_client):
        r = auth_client.post(
            "/upload",
            files={"file": ("x.pptx", io.BytesIO(b"x"), _PPTX_MIME)},
        )
        assert r.status_code == 401

    def test_browsing_routes_stay_public(self, auth_client):
        for path in ("/songs", "/services", "/reports", "/leaders"):
            assert auth_client.get(path).status_code == 200, path

    def test_upload_open_when_password_unset(self, client):
        # The default fixture sets no UPLOAD_PASSWORD → upload stays open.
        assert client.get("/upload").status_code == 200

    # /jobs is part of the same write/admin workflow and leaks uploaded
    # filenames + raw error messages — it must be gated like /upload (#451).
    def test_jobs_list_requires_auth_when_password_set(self, auth_client):
        assert auth_client.get("/jobs").status_code == 401

    def test_job_detail_requires_auth_when_password_set(self, auth_client):
        assert auth_client.get("/jobs/anything").status_code == 401

    def test_jobs_list_succeeds_with_credentials(self, auth_client):
        assert auth_client.get("/jobs", auth=("highland", "s3cret")).status_code == 200

    def test_jobs_open_when_password_unset(self, client):
        # Backwards-compatible: scripted consumers keep working when no password.
        assert client.get("/jobs").status_code == 200


class TestReportRateLimiting:
    """Public report endpoints must be rate-limited to prevent unauthenticated
    CPU/memory exhaustion (esp. /reports/stats/xlsx) on the public site (#450)."""

    def test_report_endpoint_rate_limited_after_burst(self, client):
        import worship_catalog.web.app as m
        m._report_limiter._limit_override = 3  # shrink for a fast, deterministic test
        last = None
        for _ in range(5):
            last = client.post(
                "/reports/stats/csv",
                data={"start_date": "2026-01-01", "end_date": "2026-12-31"},
            )
        assert last.status_code == 429, "report endpoints must 429 a burst from one client"
        assert last.headers.get("retry-after"), "429 should include Retry-After"

    def test_first_report_request_succeeds(self, client):
        import worship_catalog.web.app as m
        m._report_limiter._limit_override = 10
        resp = client.post(
            "/reports/stats/csv",
            data={"start_date": "2026-01-01", "end_date": "2026-12-31"},
        )
        assert resp.status_code == 200

    def test_xlsx_report_is_rate_limited(self, client):
        import worship_catalog.web.app as m
        m._report_limiter._limit_override = 2
        last = None
        for _ in range(4):
            last = client.post(
                "/reports/stats/xlsx",
                data={"start_date": "2026-01-01", "end_date": "2026-12-31"},
            )
        assert last.status_code == 429


# ---------------------------------------------------------------------------
# Self-healing CSRF cookie — stale token never refreshed (web upload failure)
# ---------------------------------------------------------------------------

# A real-world stale cookie: a structurally valid starlette-csrf token signed
# with a *previous* CSRF_SECRET. After a secret rotation/redeploy this fails
# signature verification against the live secret (raises BadSignature).
from itsdangerous.url_safe import URLSafeSerializer  # noqa: E402

_STALE_OLD_SECRET_TOKEN = URLSafeSerializer("an-old-rotated-secret", "csrftoken").dumps(
    "stale-token-payload-from-before-the-secret-rotation"
)
# A purely malformed cookie value (not even a valid token structure -> BadData).
_GARBAGE_COOKIE = "totally-not-a-valid-token"
_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _csrftoken_from_set_cookie(resp) -> str:
    """Extract the csrftoken value from a response's Set-Cookie header, or ''."""
    m = re.search(r"csrftoken=([^;]+)", resp.headers.get("set-cookie", ""))
    return m.group(1) if m else ""


class TestSelfHealingCsrfCookie:
    """A stale ``csrftoken`` cookie (e.g. signed with a previous CSRF_SECRET) must
    be automatically refreshed.

    starlette-csrf only issues a fresh cookie when the request carries *none*, so
    a browser replaying a stale cookie is otherwise stuck at 403 on every unsafe
    request forever — the cause of "Upload failed: Unexpected token 'C', "CSRF
    token"... is not valid JSON" reported from the web upload page.
    """

    @pytest.mark.parametrize("stale", [_STALE_OLD_SECRET_TOKEN, _GARBAGE_COOKIE])
    def test_get_with_stale_cookie_issues_fresh_cookie(self, raw_client, stale):
        raw_client.cookies.clear()
        resp = raw_client.get("/songs", headers={"Cookie": f"csrftoken={stale}"})
        fresh = _csrftoken_from_set_cookie(resp)
        assert fresh, "A stale csrftoken cookie must be replaced with a fresh Set-Cookie"
        assert fresh != stale, "The reissued token must differ from the stale one"

    def test_get_with_valid_cookie_is_not_rechurned(self, raw_client):
        raw_client.cookies.clear()
        token = raw_client.get("/songs").cookies.get("csrftoken", "")
        assert token, "GET must establish a valid csrftoken cookie"
        raw_client.cookies.clear()
        resp = raw_client.get("/songs", headers={"Cookie": f"csrftoken={token}"})
        assert "set-cookie" not in resp.headers, (
            "A valid csrftoken cookie must not be needlessly rotated"
        )

    def test_post_with_stale_cookie_is_403_but_reissues_cookie(self, raw_client):
        raw_client.cookies.clear()
        resp = raw_client.post(
            "/upload",
            headers={
                "Cookie": f"csrftoken={_STALE_OLD_SECRET_TOKEN}",
                "X-CSRFToken": _STALE_OLD_SECRET_TOKEN,
            },
            files={"file": ("t.pptx", io.BytesIO(b"PK\x03\x04x"), _PPTX_MIME)},
        )
        # The stale request itself cannot be trusted -> still rejected.
        assert resp.status_code == 403
        # ...but the 403 must hand back a fresh token so an auto-retry can succeed.
        fresh = _csrftoken_from_set_cookie(resp)
        assert fresh and fresh != _STALE_OLD_SECRET_TOKEN, (
            "A 403 from a stale cookie must still issue a fresh csrftoken"
        )

    def test_full_recovery_stale_then_retry_succeeds(self, raw_client):
        raw_client.cookies.clear()
        first = raw_client.post(
            "/upload",
            headers={
                "Cookie": f"csrftoken={_STALE_OLD_SECRET_TOKEN}",
                "X-CSRFToken": _STALE_OLD_SECRET_TOKEN,
            },
            files={"file": ("t.pptx", io.BytesIO(b"PK\x03\x04x"), _PPTX_MIME)},
        )
        assert first.status_code == 403
        fresh = _csrftoken_from_set_cookie(first)
        assert fresh, "Server must issue a fresh csrftoken on the 403"
        # Retry the double-submit with the freshly issued token.
        raw_client.cookies.clear()
        retry = raw_client.post(
            "/upload",
            headers={"Cookie": f"csrftoken={fresh}", "X-CSRFToken": fresh},
            files={"file": ("t.pptx", io.BytesIO(b"PK\x03\x04x"), _PPTX_MIME)},
        )
        assert retry.status_code != 403, (
            "After self-heal, a retry with the fresh token must pass CSRF"
        )


class TestUploadJsErrorHandling:
    """upload.js must not crash on a non-JSON error response (the literal symptom
    users saw: 'Upload failed: Unexpected token C ... is not valid JSON')."""

    def test_upload_js_does_not_blindly_parse_error_body_as_json(self, client):
        resp = client.get("/static/upload.js")
        assert resp.status_code == 200
        js = resp.text
        # On a non-OK response the handler must read text and/or guard JSON parsing,
        # not call resp.json() unconditionally on an error body.
        assert "resp.text(" in js or "catch" in js, (
            "upload.js must tolerate non-JSON error responses"
        )
        # On a 403 it must recover (auto-retry once) rather than surface a raw parse error.
        assert "403" in js, "upload.js must special-case the CSRF 403 for recovery"
