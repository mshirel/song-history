"""
UAT acceptance tests for the Highland Worship Catalog web UI.

Covers:
- #242: Upload form E2E (CSRF cookie, JS errors, invalid file handling)
- #243: Report form CSRF and download (CCLI CSV, stats HTMX, stats CSV)
- #244: Navigation and page-load (nav links, logo, htmx script, detail pages)
- #245: HTMX search and filter (songs search + sort, services date filter)
- #246: Leader navigation (top songs link, CSV download, back link)

These tests require:
1. Playwright installed: pip install playwright && playwright install chromium
2. A running server (or set E2E_BASE_URL env var):
   uvicorn worship_catalog.web.app:app --host 0.0.0.0 --port 8000

Run with:
    python3 -m pytest tests/test_uat_acceptance.py -v

Skip in CI / normal test runs:
    python3 -m pytest -m "not e2e"
"""

from __future__ import annotations

from typing import Any

import pytest

# Skip entire module if playwright is not installed
pytest.importorskip("playwright", reason="playwright not installed -- run: pip install playwright")

# browser_page fixture and BASE_URL come from conftest.py
from tests.conftest import E2E_BASE_URL as BASE_URL

# ---------------------------------------------------------------------------
# #242 -- Upload form E2E
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestUploadFormE2E:
    """UAT for #242: upload form CSRF, JS errors, invalid file handling."""

    def test_upload_page_loads_without_js_errors(self, browser_page: Any) -> None:
        """The upload page must load without JavaScript console errors."""
        errors: list[str] = []
        browser_page.on("pageerror", lambda err: errors.append(str(err)))
        browser_page.goto(f"{BASE_URL}/upload")
        browser_page.wait_for_load_state("networkidle")
        assert not errors, f"JavaScript errors on upload page: {errors}"

    def test_upload_form_has_csrf_cookie(self, browser_page: Any) -> None:
        """Loading /upload must set a csrftoken cookie for the JS to read."""
        browser_page.goto(f"{BASE_URL}/upload")
        browser_page.wait_for_load_state("networkidle")
        cookies = browser_page.context.cookies()
        csrf_cookies = [c for c in cookies if c["name"] == "csrftoken"]
        assert csrf_cookies, "No csrftoken cookie set on /upload page"

    def test_upload_submit_with_invalid_file_shows_error(self, browser_page: Any) -> None:
        """Submitting a non-PPTX file must show an error message, not silently fail."""
        browser_page.goto(f"{BASE_URL}/upload")
        browser_page.wait_for_load_state("networkidle")

        # Create a small text file and upload it
        browser_page.set_input_files('input[type="file"]', {
            "name": "not-a-pptx.txt",
            "mimeType": "text/plain",
            "buffer": b"This is not a PPTX file",
        })
        browser_page.click('button[type="submit"]')
        browser_page.wait_for_selector("#upload-result", state="attached", timeout=5000)
        # Give the async fetch a moment to populate the result div
        browser_page.wait_for_timeout(1000)
        result_text = browser_page.text_content("#upload-result")
        assert result_text and (
            "failed" in result_text.lower()
            or "error" in result_text.lower()
            or "invalid" in result_text.lower()
            or "pptx" in result_text.lower()
        ), f"Expected error message for invalid file, got: {result_text}"

    def test_upload_button_is_enabled_before_submit(self, browser_page: Any) -> None:
        """Upload button must be enabled before submission."""
        browser_page.goto(f"{BASE_URL}/upload")
        browser_page.wait_for_load_state("networkidle")
        btn = browser_page.locator('button[type="submit"]')
        assert btn.is_enabled(), "Upload button should be enabled before submission"


# ---------------------------------------------------------------------------
# #243 -- Report form CSRF and download
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestReportFormsE2E:
    """UAT for #243: report forms must work with CSRF in a real browser."""

    def test_no_javascript_errors_on_reports_page(self, browser_page: Any) -> None:
        """Reports page must load without JavaScript console errors."""
        errors: list[str] = []
        browser_page.on("pageerror", lambda err: errors.append(str(err)))
        browser_page.goto(f"{BASE_URL}/reports")
        browser_page.wait_for_load_state("networkidle")
        assert not errors, f"JavaScript errors on reports page: {errors}"

    def test_ccli_form_downloads_csv(self, browser_page: Any) -> None:
        """CCLI report form must produce a CSV file download, not a 403."""
        browser_page.goto(f"{BASE_URL}/reports")
        browser_page.wait_for_load_state("networkidle")

        browser_page.fill("#ccli-from", "2026-01-01")
        browser_page.fill("#ccli-to", "2026-12-31")

        with browser_page.expect_download() as download_info:
            browser_page.click('form[action="/reports/ccli"] button[type="submit"]')

        download = download_info.value
        assert download.suggested_filename.endswith(".csv"), (
            f"Expected CSV download, got filename: {download.suggested_filename}"
        )

    def test_stats_form_renders_results_via_htmx(self, browser_page: Any) -> None:
        """Stats form must render results inline (HTMX), not navigate away or 403."""
        browser_page.goto(f"{BASE_URL}/reports")
        browser_page.wait_for_load_state("networkidle")

        browser_page.fill("#stats-from", "2026-01-01")
        browser_page.fill("#stats-to", "2026-12-31")
        browser_page.click('form[hx-post="/reports/stats"] button[type="submit"]')

        # Wait for HTMX to update the results area
        browser_page.wait_for_selector("#stats-result .stat-box", timeout=5000)
        result_text = browser_page.text_content("#stats-result")
        assert result_text and "Services" in result_text, (
            "Stats result did not render service count"
        )

    def test_stats_csv_download_from_results(self, browser_page: Any) -> None:
        """After generating stats, the CSV download button must work."""
        browser_page.goto(f"{BASE_URL}/reports")
        browser_page.wait_for_load_state("networkidle")

        browser_page.fill("#stats-from", "2026-01-01")
        browser_page.fill("#stats-to", "2026-12-31")
        browser_page.click('form[hx-post="/reports/stats"] button[type="submit"]')
        browser_page.wait_for_selector("#stats-result .stat-box", timeout=10000)
        # Wait for HTMX afterSwap to bind the download form handlers
        browser_page.wait_for_timeout(500)

        # Click the CSV download button in the results
        csv_btn = browser_page.locator("#stats-csv-form button")
        if csv_btn.count() > 0:
            with browser_page.expect_download(timeout=15000) as download_info:
                csv_btn.click()
            download = download_info.value
            assert download.suggested_filename.endswith(".csv")


# ---------------------------------------------------------------------------
# #244 -- Navigation and page-load
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestNavigationE2E:
    """UAT for #244: every nav link resolves to a working page."""

    NAV_LINKS = ["/songs", "/services", "/reports", "/leaders", "/upload"]

    @pytest.mark.parametrize("path", NAV_LINKS)
    def test_nav_link_loads_without_errors(self, browser_page: Any, path: str) -> None:
        """Each nav link must load with status 200 and no JS errors."""
        errors: list[str] = []
        browser_page.on("pageerror", lambda err: errors.append(str(err)))
        response = browser_page.goto(f"{BASE_URL}{path}")
        browser_page.wait_for_load_state("networkidle")
        assert response.status == 200, f"{path} returned status {response.status}"
        assert not errors, f"JS errors on {path}: {errors}"

    def test_all_nav_links_present_in_header(self, browser_page: Any) -> None:
        """Every expected nav link must be present in the page header."""
        browser_page.goto(f"{BASE_URL}/songs")
        browser_page.wait_for_load_state("networkidle")
        nav_links = browser_page.locator("nav a").all_text_contents()
        expected = {"Songs", "Services", "Reports", "Leaders", "Upload"}
        actual = {link.strip() for link in nav_links}
        assert expected.issubset(actual), f"Missing nav links: {expected - actual}"

    def test_logo_image_loads(self, browser_page: Any) -> None:
        """Highland logo must load without 404."""
        browser_page.goto(f"{BASE_URL}/songs")
        browser_page.wait_for_load_state("networkidle")
        logo = browser_page.locator("nav img.brand-logo")
        assert logo.count() == 1, "Logo image not found in nav"
        is_loaded: bool = logo.evaluate("img => img.naturalWidth > 0")
        assert is_loaded, "Logo image failed to load (naturalWidth=0)"

    def test_htmx_script_loads(self, browser_page: Any) -> None:
        """htmx.min.js must load successfully (not blocked by CSP or 404)."""
        failed_resources: list[str] = []
        browser_page.on(
            "requestfailed",
            lambda req: failed_resources.append(req.url)
            if "htmx" in req.url
            else None,
        )
        browser_page.goto(f"{BASE_URL}/songs")
        browser_page.wait_for_load_state("networkidle")
        assert not failed_resources, f"htmx failed to load: {failed_resources}"
        htmx_version: str | None = browser_page.evaluate(
            "typeof htmx !== 'undefined' ? htmx.version : null"
        )
        assert htmx_version is not None, (
            "htmx is not initialized (script may have failed)"
        )

    def test_song_detail_from_songs_page(self, browser_page: Any) -> None:
        """Clicking a song link on /songs must navigate to a valid song detail page."""
        browser_page.goto(f"{BASE_URL}/songs")
        browser_page.wait_for_load_state("networkidle")
        first_song_link = browser_page.locator("#song-tbody tr td a").first
        if first_song_link.count() > 0:
            first_song_link.click()
            browser_page.wait_for_load_state("networkidle")
            assert "/songs/" in browser_page.url
            assert browser_page.locator("h1").count() > 0

    def test_service_detail_from_services_page(self, browser_page: Any) -> None:
        """Clicking a service link on /services must navigate to a valid detail page."""
        browser_page.goto(f"{BASE_URL}/services")
        browser_page.wait_for_load_state("networkidle")
        detail_link = browser_page.locator("#services-tbody tr td a").first
        if detail_link.count() > 0:
            detail_link.click()
            browser_page.wait_for_load_state("networkidle")
            assert "/services/" in browser_page.url
            assert browser_page.locator("h1").count() > 0


# ---------------------------------------------------------------------------
# #245 -- HTMX search and filter
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestHTMXInteractionsE2E:
    """UAT for #245: HTMX search/filter interactions work in a real browser."""

    def test_songs_search_preserves_sort_state(self, browser_page: Any) -> None:
        """Typing a search term must not reset the active sort column."""
        browser_page.goto(f"{BASE_URL}/songs?sort=display_title&sort_dir=asc")
        browser_page.wait_for_load_state("networkidle")

        # Verify hidden sort input carries the sort value
        sort_val = browser_page.input_value('input[name="sort"]')
        assert sort_val == "display_title", (
            f"Sort hidden input should be 'display_title', got '{sort_val}'"
        )

        # Type a search term
        browser_page.fill('input[name="q"]', "grace")
        browser_page.wait_for_timeout(500)
        browser_page.wait_for_load_state("networkidle")

        # Table should still have a tbody (not broken by lost sort params)
        assert browser_page.locator("#song-tbody").count() > 0, (
            "Song tbody disappeared after search"
        )

    def test_services_date_filter_updates_table(self, browser_page: Any) -> None:
        """Setting a date filter on services must update the table via HTMX."""
        browser_page.goto(f"{BASE_URL}/services")
        browser_page.wait_for_load_state("networkidle")

        initial_html = browser_page.locator("#services-tbody").inner_html()

        # Set a far-future date range that should return no results
        # Use the visible date input (not the hidden one)
        date_inputs = browser_page.locator(
            '.form-grid input[type="date"][name="start_date"]'
        )
        date_inputs.fill("2099-01-01")
        browser_page.wait_for_timeout(500)
        browser_page.wait_for_load_state("networkidle")

        updated_html = browser_page.locator("#services-tbody").inner_html()
        assert initial_html != updated_html or "No services" in updated_html, (
            "HTMX filter did not update the table"
        )

    def test_songs_sort_click_works_in_browser(self, browser_page: Any) -> None:
        """Clicking a sort column header must re-sort the table."""
        browser_page.goto(f"{BASE_URL}/songs")
        browser_page.wait_for_load_state("networkidle")

        # Click "Title" column header to sort by title
        browser_page.click('th a[href*="sort=display_title"]')
        browser_page.wait_for_load_state("networkidle")

        assert "sort=display_title" in browser_page.url, (
            "Sort column click did not update URL"
        )

    def test_songs_search_does_not_duplicate_table(self, browser_page: Any) -> None:
        """HTMX search must replace tbody content, not append a second table."""
        browser_page.goto(f"{BASE_URL}/songs")
        browser_page.wait_for_load_state("networkidle")

        browser_page.fill('input[name="q"]', "a")
        browser_page.wait_for_timeout(500)
        browser_page.wait_for_load_state("networkidle")

        tables = browser_page.locator("table").count()
        assert tables == 1, f"Found {tables} tables after search -- expected 1"


# ---------------------------------------------------------------------------
# #246 -- Leader navigation
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestLeaderPagesE2E:
    """UAT for #246: leader page navigation, CSV download, back link."""

    def test_leaders_page_links_to_top_songs(self, browser_page: Any) -> None:
        """Each leader row must have a working 'Top Songs' link."""
        browser_page.goto(f"{BASE_URL}/leaders")
        browser_page.wait_for_load_state("networkidle")

        top_songs_link = browser_page.locator('a[href*="/top-songs"]').first
        if top_songs_link.count() > 0:
            top_songs_link.click()
            browser_page.wait_for_load_state("networkidle")
            assert "/leaders/" in browser_page.url
            assert "top-songs" in browser_page.url

    def test_leader_csv_download(self, browser_page: Any) -> None:
        """Leader top songs CSV download must produce a file."""
        browser_page.goto(f"{BASE_URL}/leaders")
        browser_page.wait_for_load_state("networkidle")

        top_songs_link = browser_page.locator('a[href*="/top-songs"]').first
        if top_songs_link.count() > 0:
            top_songs_link.click()
            browser_page.wait_for_load_state("networkidle")

            csv_link = browser_page.locator('a[href*="/csv"]')
            if csv_link.count() > 0:
                with browser_page.expect_download() as download_info:
                    csv_link.click()
                download = download_info.value
                assert download.suggested_filename.endswith(".csv")

    def test_back_to_leaders_link(self, browser_page: Any) -> None:
        """'Back to Leaders' link on top-songs page must return to /leaders."""
        browser_page.goto(f"{BASE_URL}/leaders")
        browser_page.wait_for_load_state("networkidle")

        top_songs_link = browser_page.locator('a[href*="/top-songs"]').first
        if top_songs_link.count() > 0:
            top_songs_link.click()
            browser_page.wait_for_load_state("networkidle")

            # Use main content area to avoid matching the nav bar's /leaders link
            back_link = browser_page.locator('main a[href="/leaders"]')
            assert back_link.count() > 0, "Back to Leaders link not found in main content"
            back_link.click()
            browser_page.wait_for_load_state("networkidle")
            assert browser_page.url.rstrip("/").endswith("/leaders")

    def test_leaders_page_loads_without_errors(self, browser_page: Any) -> None:
        """Leaders page must load with status 200 and no JS errors."""
        errors: list[str] = []
        browser_page.on("pageerror", lambda err: errors.append(str(err)))
        response = browser_page.goto(f"{BASE_URL}/leaders")
        browser_page.wait_for_load_state("networkidle")
        assert response.status == 200, f"/leaders returned status {response.status}"
        assert not errors, f"JS errors on /leaders: {errors}"
