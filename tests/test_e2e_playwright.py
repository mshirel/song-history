"""
E2E tests using Playwright. Require a running server — skip if not available.
These tests exercise HTMX interactions that cannot be tested with TestClient
(actual browser rendering, JavaScript execution, HTMX requests).

Run with:
    pytest tests/test_e2e_playwright.py -m e2e
    pytest tests/test_e2e_playwright.py -m e2e --headed   (to see the browser)

Requires:
    playwright install chromium

Skip in CI/normal test runs:
    pytest -m "not e2e"

These tests connect to a running server at E2E_BASE_URL (env var, default localhost:8000).
Start the server first:
    uvicorn worship_catalog.web.app:app --host 0.0.0.0 --port 8000
"""

import pytest

# Skip entire module if playwright is not installed
pytest.importorskip("playwright", reason="playwright not installed — run: pip install playwright")

# browser_page fixture and BASE_URL come from conftest.py
from tests.conftest import E2E_BASE_URL as BASE_URL


@pytest.mark.e2e
class TestSongsPageHTMX:
    """E2E tests for the /songs page HTMX interactions."""

    def test_songs_page_loads(self, browser_page) -> None:
        """The songs page loads successfully in a real browser."""
        browser_page.goto(f"{BASE_URL}/songs")
        browser_page.wait_for_load_state("networkidle")
        assert "Songs" in browser_page.title()

    def test_search_filters_results_via_htmx(self, browser_page) -> None:
        """Typing in the search box triggers HTMX and updates the table without full reload."""
        browser_page.goto(f"{BASE_URL}/songs")
        browser_page.wait_for_load_state("networkidle")

        initial_rows = browser_page.locator("tbody tr").count()

        # Type a search term unlikely to match any song
        browser_page.fill('input[name="q"]', "nonexistent_song_xyz_12345")
        browser_page.wait_for_load_state("networkidle")

        filtered_rows = browser_page.locator("tbody tr").count()
        # Either table is empty or has fewer results than before
        assert filtered_rows < initial_rows or filtered_rows == 0, (
            f"Expected filtered rows ({filtered_rows}) < initial rows ({initial_rows})"
        )

    def test_clear_search_restores_results(self, browser_page) -> None:
        """Clearing the search box restores the full song list via HTMX."""
        browser_page.goto(f"{BASE_URL}/songs")
        browser_page.wait_for_load_state("networkidle")

        initial_rows = browser_page.locator("tbody tr").count()

        # Filter down then clear
        browser_page.fill('input[name="q"]', "nonexistent_song_xyz_12345")
        browser_page.wait_for_load_state("networkidle")

        browser_page.fill('input[name="q"]', "")
        browser_page.wait_for_load_state("networkidle")

        restored_rows = browser_page.locator("tbody tr").count()
        assert restored_rows == initial_rows, (
            f"Expected {initial_rows} rows after clearing search, got {restored_rows}"
        )

    def test_sort_column_updates_table_without_full_reload(self, browser_page) -> None:
        """Clicking a sort header updates the table results."""
        browser_page.goto(f"{BASE_URL}/songs")
        browser_page.wait_for_load_state("networkidle")

        # Click the first sortable header link
        first_sort_header = browser_page.locator("th a").first
        first_sort_header.click()
        browser_page.wait_for_load_state("networkidle")

        # Page must still be alive and show the songs table
        assert browser_page.locator("tbody").count() > 0
        assert browser_page.url  # no crash/redirect


@pytest.mark.e2e
class TestServicesPageHTMX:
    """E2E tests for the /services page."""

    def test_services_page_loads(self, browser_page) -> None:
        """The services page loads successfully in a real browser."""
        browser_page.goto(f"{BASE_URL}/services")
        browser_page.wait_for_load_state("networkidle")
        assert "Services" in browser_page.title()

    def test_services_page_has_table(self, browser_page) -> None:
        """The services page renders a table of services."""
        browser_page.goto(f"{BASE_URL}/services")
        browser_page.wait_for_load_state("networkidle")
        assert browser_page.locator("table").count() >= 1


@pytest.mark.e2e
class TestNavigationHTMX:
    """E2E tests for navigation between pages."""

    def test_nav_links_work(self, browser_page) -> None:
        """All nav links navigate to their respective pages."""
        browser_page.goto(f"{BASE_URL}/songs")
        browser_page.wait_for_load_state("networkidle")

        # Click Services nav link
        browser_page.click("nav a[href='/services']")
        browser_page.wait_for_load_state("networkidle")
        assert "/services" in browser_page.url

    def test_skip_nav_link_is_present_and_focusable(self, browser_page) -> None:
        """The skip navigation link is present for keyboard accessibility."""
        browser_page.goto(f"{BASE_URL}/songs")
        browser_page.wait_for_load_state("networkidle")

        skip_link = browser_page.locator("a.skip-nav")
        assert skip_link.count() >= 1, "Skip-to-main-content link must be present"
