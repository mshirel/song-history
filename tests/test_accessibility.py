"""Accessibility tests — ARIA landmarks, skip nav, form labels, page titles (#87).

These tests run against the FastAPI TestClient and verify static HTML structure.
They define what the templates MUST provide; if they fail, fix the templates.
"""

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient


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
    return TestClient(app_module.app)


class TestAriaLandmarks:
    """Pages must include HTML5 landmark elements or ARIA role equivalents."""

    def test_songs_page_has_main_landmark(self, client: TestClient) -> None:
        """The songs page must have a <main> element or role="main"."""
        resp = client.get("/songs")
        assert resp.status_code == 200
        assert "<main" in resp.text or 'role="main"' in resp.text

    def test_songs_page_has_nav_landmark(self, client: TestClient) -> None:
        """The songs page must have a <nav> element or role="navigation"."""
        resp = client.get("/songs")
        assert resp.status_code == 200
        assert "<nav" in resp.text or 'role="navigation"' in resp.text

    def test_songs_page_has_header_landmark(self, client: TestClient) -> None:
        """The songs page must have a <header> element or role="banner"."""
        resp = client.get("/songs")
        assert resp.status_code == 200
        assert "<header" in resp.text or 'role="banner"' in resp.text

    def test_services_page_has_main_landmark(self, client: TestClient) -> None:
        resp = client.get("/services")
        assert resp.status_code == 200
        assert "<main" in resp.text or 'role="main"' in resp.text

    def test_services_page_has_header_landmark(self, client: TestClient) -> None:
        resp = client.get("/services")
        assert resp.status_code == 200
        assert "<header" in resp.text or 'role="banner"' in resp.text

    def test_reports_page_has_main_landmark(self, client: TestClient) -> None:
        resp = client.get("/reports")
        assert resp.status_code == 200
        assert "<main" in resp.text or 'role="main"' in resp.text


class TestSkipNavigation:
    """Pages must provide a skip-to-main-content link for keyboard users."""

    def test_songs_page_has_skip_nav_link(self, client: TestClient) -> None:
        """A 'Skip to main content' link must appear as the first focusable element."""
        resp = client.get("/songs")
        assert resp.status_code == 200
        text_lower = resp.text.lower()
        assert "skip" in text_lower, "No skip navigation link found"
        assert "#main" in resp.text or "#maincontent" in resp.text, (
            "Skip nav link must target #main or #maincontent anchor"
        )

    def test_services_page_has_skip_nav_link(self, client: TestClient) -> None:
        resp = client.get("/services")
        assert resp.status_code == 200
        assert "skip" in resp.text.lower()
        assert "#main" in resp.text or "#maincontent" in resp.text

    def test_reports_page_has_skip_nav_link(self, client: TestClient) -> None:
        resp = client.get("/reports")
        assert resp.status_code == 200
        assert "skip" in resp.text.lower()
        assert "#main" in resp.text or "#maincontent" in resp.text


class TestPageTitles:
    """Every page must have a meaningful <title> tag."""

    def _extract_title(self, html: str) -> str:
        match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        return match.group(1).strip()

    def test_songs_page_title_is_meaningful(self, client: TestClient) -> None:
        resp = client.get("/songs")
        title = self._extract_title(resp.text)
        assert len(title) > 0, "Title must not be empty"
        assert title.lower() not in ("app", "worship catalog"), (
            f"Title '{title}' is too generic — must include the page name"
        )
        assert "song" in title.lower() or "Songs" in title

    def test_services_page_title_is_meaningful(self, client: TestClient) -> None:
        resp = client.get("/services")
        title = self._extract_title(resp.text)
        assert len(title) > 0
        assert "service" in title.lower() or "Services" in title

    def test_reports_page_title_is_meaningful(self, client: TestClient) -> None:
        resp = client.get("/reports")
        title = self._extract_title(resp.text)
        assert len(title) > 0
        assert "report" in title.lower() or "Reports" in title

    def test_leaders_page_title_is_meaningful(self, client: TestClient) -> None:
        resp = client.get("/leaders")
        title = self._extract_title(resp.text)
        assert len(title) > 0
        assert "leader" in title.lower() or "Leaders" in title


class TestFormLabels:
    """All <input> elements must have an associated <label> or aria-label."""

    def test_search_input_has_label_or_aria_label(self, client: TestClient) -> None:
        """The songs search input must have a label or aria-label for accessibility."""
        resp = client.get("/songs")
        assert resp.status_code == 200
        # Accept either a <label for="..."> or aria-label attribute on the input
        has_label = 'for="q"' in resp.text or 'for="search"' in resp.text
        has_aria = 'aria-label=' in resp.text
        assert has_label or has_aria, (
            "Search input has no accessible label. "
            "Add <label for='q'> or aria-label='Search' to the input."
        )


class TestAriaSortHeaders:
    """Tests for aria-sort on sortable table headers (#305)."""

    def test_songs_default_sort_has_aria_sort(self, client: TestClient) -> None:
        resp = client.get("/songs")
        assert resp.status_code == 200
        assert 'aria-sort="descending"' in resp.text

    def test_songs_asc_sort_has_aria_ascending(self, client: TestClient) -> None:
        resp = client.get("/songs?sort=display_title&sort_dir=asc")
        assert 'aria-sort="ascending"' in resp.text

    def test_services_sort_has_aria_sort(self, client: TestClient) -> None:
        resp = client.get("/services?sort=service_date&sort_dir=desc")
        assert 'aria-sort="descending"' in resp.text


class TestAriaLiveRegions:
    """Tests for aria-live on HTMX swap targets (#306)."""

    def test_songs_table_has_aria_live(self, client: TestClient) -> None:
        resp = client.get("/songs")
        assert 'aria-live="polite"' in resp.text

    def test_services_table_has_aria_live(self, client: TestClient) -> None:
        resp = client.get("/services")
        assert 'aria-live="polite"' in resp.text

    def test_reports_result_has_aria_live(self, client: TestClient) -> None:
        resp = client.get("/reports")
        assert 'aria-live="polite"' in resp.text

    def test_upload_result_has_aria_live(self, client: TestClient) -> None:
        resp = client.get("/upload")
        assert 'aria-live="assertive"' in resp.text or 'role="alert"' in resp.text


class TestErrorPageContrast:
    """Tests for error page text contrast (#307)."""

    def test_404_heading_not_low_contrast(self, client: TestClient) -> None:
        """The 404 status code heading should not use #ccc (low contrast)."""
        resp = client.get("/nonexistent-page-xyz")
        assert resp.status_code == 404
        # The heading uses inline style; verify it does NOT use #ccc
        assert "color:#ccc;\">404" not in resp.text
        assert "color: #ccc;\">404" not in resp.text
        # Should use a darker color instead
        assert "color:#666;\">404" in resp.text or "color: #666;\">404" in resp.text
