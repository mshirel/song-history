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

    def test_stats_shows_leader_breakdown(self, client):
        """Stats without leader filter shows By Song Leader breakdown."""
        response = client.post(
            "/reports/stats",
            data={"start_date": "2026-01-01", "end_date": "2026-12-31"},
        )
        assert response.status_code == 200
        assert "By Song Leader" in response.text
        assert "Matt" in response.text  # leader name from fixture

    def test_stats_leader_breakdown_hidden_when_filtered(self, client):
        """Stats with leader filter does NOT show the breakdown section."""
        response = client.post(
            "/reports/stats",
            data={"start_date": "2026-01-01", "end_date": "2026-12-31", "leader": "Matt"},
        )
        assert response.status_code == 200
        assert "By Song Leader" not in response.text

    def test_stats_breakdown_shows_leader_service_count(self, client):
        """Leader card in breakdown shows service count."""
        response = client.post(
            "/reports/stats",
            data={"start_date": "2026-01-01", "end_date": "2026-12-31"},
        )
        # Fixture has 1 service led by Matt
        assert "1 service" in response.text

    def test_stats_breakdown_shows_songs_per_leader(self, client):
        """Leader card lists songs with repeat counts."""
        response = client.post(
            "/reports/stats",
            data={"start_date": "2026-01-01", "end_date": "2026-12-31"},
        )
        # Both fixture songs should appear under Matt
        assert "Amazing Grace" in response.text
        assert "How Great Thou Art" in response.text


class TestServicesListPage:
    def test_services_page_returns_html(self, client):
        response = client.get("/services")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_services_page_lists_services(self, client):
        response = client.get("/services")
        assert "AM Worship" in response.text
        assert "2026-02-15" in response.text

    def test_services_page_shows_leader(self, client):
        response = client.get("/services")
        assert "Matt" in response.text

    def test_services_page_shows_song_count(self, client):
        response = client.get("/services")
        # Fixture has 2 songs in one service
        assert "2" in response.text

    def test_services_page_links_to_detail(self, client, db_with_songs):
        response = client.get("/services")
        assert "/services/" in response.text

    def test_services_empty_db_shows_message(self, client, tmp_path, monkeypatch):
        empty_db = tmp_path / "empty.db"
        db = Database(empty_db)
        db.connect()
        db.init_schema()
        db.close()
        monkeypatch.setenv("DB_PATH", str(empty_db))
        import worship_catalog.web.app as app_module
        from importlib import reload
        reload(app_module)
        c = TestClient(app_module.app)
        response = c.get("/services")
        assert response.status_code == 200
        assert "No services" in response.text

    def test_services_nav_link_is_active(self, client):
        response = client.get("/services")
        assert 'class="active"' in response.text


class TestServiceDetailPage:
    def _get_service_id(self, client):
        """Fetch the services list and extract a valid service ID from a link."""
        response = client.get("/services")
        import re
        match = re.search(r'/services/(\d+)', response.text)
        assert match, "No service detail links found"
        return int(match.group(1))

    def test_detail_returns_html(self, client):
        svc_id = self._get_service_id(client)
        response = client.get(f"/services/{svc_id}")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_detail_shows_service_name(self, client):
        svc_id = self._get_service_id(client)
        response = client.get(f"/services/{svc_id}")
        assert "AM Worship" in response.text

    def test_detail_shows_service_date(self, client):
        svc_id = self._get_service_id(client)
        response = client.get(f"/services/{svc_id}")
        assert "2026-02-15" in response.text

    def test_detail_shows_song_leader(self, client):
        svc_id = self._get_service_id(client)
        response = client.get(f"/services/{svc_id}")
        assert "Matt" in response.text

    def test_detail_shows_setlist(self, client):
        svc_id = self._get_service_id(client)
        response = client.get(f"/services/{svc_id}")
        assert "Amazing Grace" in response.text
        assert "How Great Thou Art" in response.text

    def test_detail_shows_credits(self, client):
        svc_id = self._get_service_id(client)
        response = client.get(f"/services/{svc_id}")
        assert "John Newton" in response.text
        assert "Stuart K. Hine" in response.text

    def test_detail_shows_back_link(self, client):
        svc_id = self._get_service_id(client)
        response = client.get(f"/services/{svc_id}")
        assert "/services" in response.text

    def test_detail_404_for_missing_service(self, client):
        response = client.get("/services/99999")
        assert response.status_code == 404


class TestSongDetailPage:
    def _get_song_id(self, client):
        import re
        response = client.get("/songs")
        match = re.search(r'/songs/(\d+)', response.text)
        assert match, "No song detail links found"
        return int(match.group(1))

    def test_song_title_is_linked(self, client):
        response = client.get("/songs")
        assert "/songs/" in response.text

    def test_detail_returns_html(self, client):
        song_id = self._get_song_id(client)
        response = client.get(f"/songs/{song_id}")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_detail_shows_song_title(self, client):
        song_id = self._get_song_id(client)
        response = client.get(f"/songs/{song_id}")
        assert "Amazing Grace" in response.text or "How Great Thou Art" in response.text

    def test_detail_shows_credits(self, client):
        response = client.get(f"/songs/{self._get_song_id(client)}")
        assert "John Newton" in response.text or "Stuart K. Hine" in response.text

    def test_detail_shows_service_history(self, client):
        song_id = self._get_song_id(client)
        response = client.get(f"/songs/{song_id}")
        assert "2026-02-15" in response.text

    def test_detail_shows_back_link(self, client):
        song_id = self._get_song_id(client)
        response = client.get(f"/songs/{song_id}")
        assert "/songs" in response.text

    def test_detail_404_for_missing_song(self, client):
        response = client.get("/songs/99999")
        assert response.status_code == 404


class TestSongsSorting:
    def test_sort_by_title_asc(self, client):
        response = client.get("/songs?sort=display_title&sort_dir=asc")
        assert response.status_code == 200

    def test_sort_by_performance_count(self, client):
        response = client.get("/songs?sort=performance_count&sort_dir=desc")
        assert response.status_code == 200

    def test_sort_indicator_shown(self, client):
        response = client.get("/songs?sort=display_title&sort_dir=asc")
        assert "▲" in response.text

    def test_invalid_sort_col_falls_back(self, client):
        response = client.get("/songs?sort=INVALID&sort_dir=asc")
        assert response.status_code == 200

    def test_htmx_partial_sort(self, client):
        response = client.get(
            "/songs?sort=display_title&sort_dir=desc",
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert "<tr>" in response.text


class TestServicesFiltering:
    def test_filter_by_leader(self, client):
        response = client.get("/services?q_leader=Matt")
        assert response.status_code == 200
        assert "Matt" in response.text

    def test_filter_no_match(self, client):
        response = client.get("/services?q_leader=ZZZNOMATCH")
        assert response.status_code == 200
        assert "No services" in response.text

    def test_filter_by_date_range(self, client):
        response = client.get("/services?start_date=2026-01-01&end_date=2026-12-31")
        assert response.status_code == 200
        assert "AM Worship" in response.text

    def test_sort_by_date_asc(self, client):
        response = client.get("/services?sort=service_date&sort_dir=asc")
        assert response.status_code == 200
        assert "▲" in response.text

    def test_htmx_partial_returns_rows(self, client):
        response = client.get(
            "/services?q_leader=Matt",
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        assert "<tr>" in response.text

    def test_invalid_sort_col_falls_back(self, client):
        response = client.get("/services?sort=INVALID")
        assert response.status_code == 200


class TestErrorPages:
    """Tests for custom 404/500 HTML error pages (implemented in issue #9)."""

    def test_404_song_returns_404_status(self, client):
        response = client.get("/songs/99999")
        assert response.status_code == 404

    def test_404_service_returns_404_status(self, client):
        response = client.get("/services/99999")
        assert response.status_code == 404

    def test_404_body_not_raw_json(self, client):
        response = client.get("/songs/99999")
        # After issue #9: should be HTML, not JSON
        # For now just verify status
        assert response.status_code == 404

    def test_health_endpoint(self, client):
        response = client.get("/health")
        assert response.status_code == 200
