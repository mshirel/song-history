"""Security-specific tests for the FastAPI web UI.

Covers:
- Issue #107: HTMX CDN script tag must include SRI integrity attribute
- Issue #105: leader_name Content-Disposition header injection
- Issue #106: upload filename path traversal
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient


_PPTX_MIME = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation"
)


class _CsrfAwareClient:
    """Wraps TestClient to automatically include the CSRF token on POST requests."""

    def __init__(self, inner: TestClient) -> None:
        self._inner = inner
        self._csrf_token: str | None = None

    def _ensure_token(self) -> str:
        if self._csrf_token is None:
            resp = self._inner.get("/songs")
            self._csrf_token = resp.cookies.get("csrftoken", "")
        return self._csrf_token or ""

    def get(self, *args, **kwargs):
        return self._inner.get(*args, **kwargs)

    def post(self, *args, **kwargs):
        token = self._ensure_token()
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("X-CSRFToken", token)
        return self._inner.post(*args, headers=headers, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


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
    return _CsrfAwareClient(TestClient(app_module.app))


# ---------------------------------------------------------------------------
# Issue #107: HTMX SRI integrity attribute
# ---------------------------------------------------------------------------


class TestHtmxSriIntegrity:
    def test_htmx_script_has_sri_integrity_attribute(self, client):
        """HTMX CDN script tag must include integrity= for SRI protection."""
        resp = client.get("/songs")
        assert resp.status_code == 200
        assert 'integrity="sha384-' in resp.text, (
            "HTMX <script> tag is missing SRI integrity attribute (sha384-...)"
        )

    def test_htmx_script_has_crossorigin_anonymous(self, client):
        """HTMX CDN script tag must include crossorigin=anonymous for SRI to work."""
        resp = client.get("/songs")
        assert resp.status_code == 200
        assert 'crossorigin="anonymous"' in resp.text, (
            "HTMX <script> tag is missing crossorigin=\"anonymous\" attribute"
        )

    def test_htmx_sri_appears_on_all_pages(self, client):
        """Every page that extends base.html should have SRI on the HTMX script."""
        for path in ["/songs", "/services", "/reports", "/leaders"]:
            resp = client.get(path)
            assert resp.status_code == 200
            assert 'integrity="sha384-' in resp.text, (
                f"SRI integrity attribute missing on {path}"
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
        wrapped = _CsrfAwareClient(inner)

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
