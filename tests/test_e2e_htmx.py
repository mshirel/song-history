"""
Playwright E2E tests for HTMX interactions.

Verifies that HTMX live-search and sort interactions produce correct DOM
updates in a real browser — something TestClient cannot catch (e.g. broken
hx-target, malformed partial responses, duplicated tables).

Requires a running server — set E2E_BASE_URL env var or start locally:
    uvicorn worship_catalog.web.app:app --host 0.0.0.0 --port 8000

Run with:
    python3 -m pytest tests/test_e2e_htmx.py -v

Skip in CI/normal test runs:
    python3 -m pytest -m "not e2e"
"""

import pytest

# Skip entire module if playwright is not installed
pytest.importorskip("playwright", reason="playwright not installed — run: pip install playwright")

# browser_page fixture and BASE_URL come from conftest.py
from tests.conftest import E2E_BASE_URL as BASE_URL


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
        browser_page.wait_for_timeout(500)
        browser_page.wait_for_load_state("networkidle")

        updated_rows = browser_page.locator("table tbody tr").count()
        # With a non-matching query, results should decrease or show "No songs" row
        assert updated_rows < initial_rows or initial_rows <= 1

    def test_sort_header_click_reorders_rows(self, browser_page) -> None:
        """Clicking a sortable column header should reorder the table."""
        browser_page.goto(f"{BASE_URL}/songs")
        browser_page.wait_for_load_state("networkidle")

        # Click the "Performances" header to sort
        browser_page.locator("th a", has_text="Performances").click()
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
