"""Tests for report_service extracted service layer (#25)."""

import pytest


class TestReportService:
    @pytest.fixture
    def temp_db(self, tmp_path):
        from worship_catalog.db import Database
        db = Database(tmp_path / "test.db")
        db.connect()
        db.init_schema()
        yield db
        db.close()

    def test_compute_stats_data_importable_from_services(self):
        from worship_catalog.services.report_service import compute_stats_data
        assert callable(compute_stats_data)

    def test_compute_stats_data_returns_required_keys(self, temp_db):
        from worship_catalog.services.report_service import compute_stats_data
        data = compute_stats_data(temp_db, "0000-01-01", "9999-12-31", None, True)
        for key in ("sorted_songs", "song_credits", "services", "total_performances",
                    "total_events", "leader_breakdown", "leader_service_counts"):
            assert key in data, f"missing key: {key}"

    def test_compute_stats_data_empty_db(self, temp_db):
        from worship_catalog.services.report_service import compute_stats_data
        data = compute_stats_data(temp_db, "0000-01-01", "9999-12-31", None, True)
        assert data["sorted_songs"] == []
        assert data["total_performances"] == 0

    def test_compute_stats_data_counts_songs(self, temp_db):
        from worship_catalog.services.report_service import compute_stats_data
        # Insert minimal data
        svc_id = temp_db.insert_or_update_service(
            service_date="2026-01-01", service_name="Sunday AM",
            source_file="test.pptx", source_hash="abc123",
            song_leader=None, preacher=None, sermon_title=None,
        )
        song_id = temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
        temp_db.insert_service_song(service_id=svc_id, song_id=song_id, ordinal=1,
                                    song_edition_id=None, first_slide_index=1,
                                    last_slide_index=3, occurrences=1)
        temp_db.insert_or_get_copy_event(service_id=svc_id, song_id=song_id,
                                          song_edition_id=None, reproduction_type="projection",
                                          count=1, reportable=True)
        data = compute_stats_data(temp_db, "0000-01-01", "9999-12-31", None, True)
        assert len(data["sorted_songs"]) == 1
        assert data["sorted_songs"][0][0] == "Amazing Grace"
        assert data["total_performances"] == 1

    def test_web_app_uses_report_service(self):
        """web/app.py _compute_stats delegates to report_service.compute_stats_data."""
        import inspect
        from worship_catalog.web import app as web_app
        from worship_catalog.services import report_service  # noqa: F401
        # The web _compute_stats should either be removed or call report_service
        src = inspect.getsource(web_app)
        assert "report_service" in src or "compute_stats_data" in src
