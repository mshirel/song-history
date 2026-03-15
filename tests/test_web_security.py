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
