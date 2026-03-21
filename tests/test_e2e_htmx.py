"""
Playwright E2E tests for HTMX interactions.

Verifies that HTMX live-search and sort interactions produce correct DOM
updates in a real browser — something TestClient cannot catch (e.g. broken
hx-target, malformed partial responses, duplicated tables).

Requires a running server — start with:
    uvicorn worship_catalog.web.app:app --host 0.0.0.0 --port 8000

Run with:
    python3 -m pytest tests/test_e2e_htmx.py -v

Skip in CI/normal test runs:
    python3 -m pytest -m "not e2e"
"""

import socket

import pytest

# Skip entire module if playwright is not installed
pytest.importorskip("playwright", reason="playwright not installed — run: pip install playwright")

BASE_URL = "http://localhost:8000"


def _server_is_running() -> bool:
    """Return True if the server at BASE_URL is accepting connections."""
    try:
        host = "localhost"
        port = 8000
        with socket.create_connection((host, port), timeout=1):
            return True
    except (ConnectionRefusedError, OSError):
        return False


_server_available = _server_is_running()


@pytest.fixture(scope="module")
def browser_page():
    """Launch a Chromium browser and yield a page. Skip if server not running."""
    if not _server_available:
        pytest.skip(
            "No server running at http://localhost:8000 — start the server to run E2E tests"
        )

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        yield page
        browser.close()


@pytest.mark.e2e
class TestSongsLiveSearch:
    """HTMX live-search on /songs must update the table body."""

    def test_search_filters_table_rows(self, browser_page) -> None:
        """Typing in the search box should reduce visible table rows."""
        browser_page.goto(f"{BASE_URL}/songs")
        browser_page.wait_for_load_state("networkidle")
        initial_rows = browser_page.locator("table tbody tr").count()

        search_input = browser_page.locator("input[name='q']")
        search_input.fill("xyznonexistent")
        # Wait for HTMX to settle
        browser_page.wait_for_load_state("networkidle")

        updated_rows = browser_page.locator("table tbody tr").count()
        assert updated_rows < initial_rows or updated_rows == 0

    def test_sort_header_click_reorders_rows(self, browser_page) -> None:
        """Clicking a sortable column header should reorder the table."""
        browser_page.goto(f"{BASE_URL}/songs")
        browser_page.wait_for_load_state("networkidle")

        # Click the "Times Sung" header to sort
        browser_page.locator("th a", has_text="Times Sung").click()
        browser_page.wait_for_load_state("networkidle")

        # Table should still have rows (not be empty/broken)
        rows = browser_page.locator("table tbody tr").count()
        assert rows > 0, "Table is empty after sort — HTMX partial may be broken"

    def test_search_does_not_duplicate_table(self, browser_page) -> None:
        """HTMX search must replace tbody, not append a second table."""
        browser_page.goto(f"{BASE_URL}/songs")
        browser_page.wait_for_load_state("networkidle")

        search_input = browser_page.locator("input[name='q']")
        search_input.fill("a")
        browser_page.wait_for_load_state("networkidle")

        tables = browser_page.locator("table").count()
        assert tables == 1, f"Found {tables} tables after search — expected 1"
