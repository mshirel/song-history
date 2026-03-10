"""Tests for the FastAPI + HTMX web UI."""

import json
import os
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from starlette.testclient import TestClient

from worship_catalog.db import Database


@pytest.fixture
def db_with_songs(tmp_path):
    """Create a minimal test DB with one service, two songs, and copy events."""
    db_path = tmp_path / "test.db"
    db = Database(db_path)
    db.connect()
    db.init_schema()

    song_id1 = db.insert_or_get_song("amazing grace", "Amazing Grace")
    song_id2 = db.insert_or_get_song("how great thou art", "How Great Thou Art")

    edition_id1 = db.insert_or_get_song_edition(
        song_id1, words_by="John Newton", music_by=None, arranger=None
    )
    edition_id2 = db.insert_or_get_song_edition(
        song_id2, words_by="Stuart K. Hine", music_by="Stuart K. Hine", arranger=None
    )

    service_id = db.insert_or_update_service(
        service_date="2026-02-15",
        service_name="AM Worship",
        source_file="test.pptx",
        source_hash="abc123",
        song_leader="Matt",
    )

    db.insert_service_song(service_id, song_id1, ordinal=1, song_edition_id=edition_id1)
    db.insert_service_song(service_id, song_id2, ordinal=2, song_edition_id=edition_id2)

    db.insert_or_get_copy_event(service_id, song_id1, "projection", song_edition_id=edition_id1)
    db.insert_or_get_copy_event(service_id, song_id2, "projection", song_edition_id=edition_id2)

    db.close()
    return db_path


@pytest.fixture
def client(db_with_songs, monkeypatch):
    """TestClient with DB_PATH env var pointed at the test DB."""
    monkeypatch.setenv("DB_PATH", str(db_with_songs))
    from worship_catalog.web import app as web_app
    from importlib import reload
    import worship_catalog.web.app as app_module
    reload(app_module)
    return TestClient(app_module.app)


class TestRootRedirect:
    def test_root_redirects_to_songs(self, client):
        response = client.get("/", follow_redirects=False)
        assert response.status_code in (301, 302, 307, 308)
        assert response.headers["location"].endswith("/songs")


class TestSongsPage:
    def test_songs_page_returns_html(self, client):
        response = client.get("/songs")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_songs_page_contains_song_titles(self, client):
        response = client.get("/songs")
        assert "Amazing Grace" in response.text
        assert "How Great Thou Art" in response.text

    def test_songs_page_contains_credits(self, client):
        response = client.get("/songs")
        assert "John Newton" in response.text
        assert "Stuart K. Hine" in response.text

    def test_songs_search_filters_results(self, client):
        response = client.get("/songs?q=Amazing")
        assert response.status_code == 200
        assert "Amazing Grace" in response.text
        # HTMX partial or full page — either way only matching song shown
        assert "How Great Thou Art" not in response.text

    def test_songs_htmx_request_returns_partial(self, client):
        """HTMX requests return table rows only (no full page nav)."""
        response = client.get("/songs?q=Amazing", headers={"HX-Request": "true"})
        assert response.status_code == 200
        assert "Amazing Grace" in response.text
        # Partial should NOT include the full <nav> chrome
        assert "<nav" not in response.text

    def test_songs_empty_search_returns_all(self, client):
        response = client.get("/songs?q=")
        assert response.status_code == 200
        assert "Amazing Grace" in response.text
        assert "How Great Thou Art" in response.text

    def test_songs_search_no_match_shows_empty(self, client):
        response = client.get("/songs?q=xyznotasong", headers={"HX-Request": "true"})
        assert response.status_code == 200
        assert "No songs found" in response.text


class TestReportsPage:
    def test_reports_page_returns_html(self, client):
        response = client.get("/reports")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_reports_page_has_ccli_form(self, client):
        response = client.get("/reports")
        assert "ccli" in response.text.lower()
        assert 'action="/reports/ccli"' in response.text

    def test_reports_page_has_stats_form(self, client):
        response = client.get("/reports")
        assert "stats" in response.text.lower()
        assert "/reports/stats" in response.text


class TestCCLIReport:
    def test_ccli_returns_csv(self, client):
        response = client.post(
            "/reports/ccli",
            data={"start_date": "2026-01-01", "end_date": "2026-12-31"},
        )
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "attachment" in response.headers["content-disposition"]

    def test_ccli_csv_has_header_row(self, client):
        response = client.post(
            "/reports/ccli",
            data={"start_date": "2026-01-01", "end_date": "2026-12-31"},
        )
        first_line = response.text.splitlines()[0]
        assert "Date" in first_line
        assert "Title" in first_line
        assert "Reproduction Type" in first_line

    def test_ccli_csv_contains_song_data(self, client):
        response = client.post(
            "/reports/ccli",
            data={"start_date": "2026-01-01", "end_date": "2026-12-31"},
        )
        assert "Amazing Grace" in response.text or "How Great Thou Art" in response.text

    def test_ccli_empty_range_returns_header_only(self, client):
        response = client.post(
            "/reports/ccli",
            data={"start_date": "2020-01-01", "end_date": "2020-01-31"},
        )
        assert response.status_code == 200
        lines = [l for l in response.text.splitlines() if l.strip()]
        assert len(lines) == 1  # header row only

    def test_ccli_filename_includes_dates(self, client):
        response = client.post(
            "/reports/ccli",
            data={"start_date": "2026-02-01", "end_date": "2026-02-28"},
        )
        cd = response.headers["content-disposition"]
        assert "2026-02-01" in cd
        assert "2026-02-28" in cd


class TestStatsReport:
    def test_stats_returns_html(self, client):
        response = client.post(
            "/reports/stats",
            data={"start_date": "2026-01-01", "end_date": "2026-12-31"},
        )
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_stats_shows_song_titles(self, client):
        response = client.post(
            "/reports/stats",
            data={"start_date": "2026-01-01", "end_date": "2026-12-31"},
        )
        assert "Amazing Grace" in response.text or "How Great Thou Art" in response.text

    def test_stats_shows_summary_counts(self, client):
        response = client.post(
            "/reports/stats",
            data={"start_date": "2026-01-01", "end_date": "2026-12-31"},
        )
        # Summary stat boxes should show counts
        assert "1" in response.text  # at least 1 service

    def test_stats_leader_filter(self, client):
        """Leader filter returns only that leader's services."""
        response = client.post(
            "/reports/stats",
            data={"start_date": "2026-01-01", "end_date": "2026-12-31", "leader": "Matt"},
        )
        assert response.status_code == 200
        assert "Amazing Grace" in response.text  # Matt led this service

    def test_stats_leader_filter_no_match(self, client):
        """Leader filter with no matching services shows empty state."""
        response = client.post(
            "/reports/stats",
            data={"start_date": "2026-01-01", "end_date": "2026-12-31", "leader": "Nobody"},
        )
        assert response.status_code == 200
        assert "No services found" in response.text

    def test_stats_empty_range_shows_no_services(self, client):
        response = client.post(
            "/reports/stats",
            data={"start_date": "2020-01-01", "end_date": "2020-01-31"},
        )
        assert response.status_code == 200
        assert "No services found" in response.text

    def test_stats_htmx_partial_no_nav(self, client):
        """HTMX POST returns partial HTML (no full page nav)."""
        response = client.post(
            "/reports/stats",
            data={"start_date": "2026-01-01", "end_date": "2026-12-31"},
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        # stats_result.html partial is returned directly — no <nav>
        assert "<nav" not in response.text
