"""Tests for report_service extracted service layer (#25)."""

import pytest

from worship_catalog.db import Database
from worship_catalog.services.report_service import compute_stats_data


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
        for key in ("sorted_songs", "song_credits", "services", "events",
                    "total_performances", "total_events", "leader_breakdown",
                    "leader_service_counts"):
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

    def test_cli_stats_delegates_to_compute_stats_data(self):
        """cli.py stats command must delegate to report_service.compute_stats_data (#167)."""
        import inspect
        from worship_catalog import cli
        # Click wraps the function; get source of the callback or the module
        src = inspect.getsource(cli)
        # Find the stats function body — it should reference compute_stats_data
        assert "compute_stats_data" in src, (
            "CLI stats command should call compute_stats_data() "
            "instead of reimplementing the same logic"
        )

    def test_compute_stats_data_credits_include_arranger(self, temp_db):
        """song_credits should include arranger when present (#167)."""
        from worship_catalog.services.report_service import compute_stats_data

        svc_id = temp_db.insert_or_update_service(
            service_date="2026-01-01", service_name="Sunday AM",
            source_file="test.pptx", source_hash="abc123",
            song_leader=None, preacher=None, sermon_title=None,
        )
        song_id = temp_db.insert_or_get_song("amazing grace", "Amazing Grace")
        edition_id = temp_db.insert_or_get_song_edition(
            song_id=song_id, publisher=None,
            words_by="John Newton", music_by="Edwin Excell",
            arranger="James Last",
        )
        temp_db.insert_service_song(
            service_id=svc_id, song_id=song_id, ordinal=1,
            song_edition_id=edition_id, first_slide_index=1,
            last_slide_index=3, occurrences=1,
        )
        temp_db.insert_or_get_copy_event(
            service_id=svc_id, song_id=song_id,
            song_edition_id=edition_id, reproduction_type="projection",
            count=1, reportable=True,
        )
        data = compute_stats_data(temp_db, "0000-01-01", "9999-12-31", None, True)
        credits = data["song_credits"].get("Amazing Grace", "")
        assert "James Last" in credits, (
            f"Arranger should appear in credits string, got: {credits!r}"
        )


class TestComputeStatsDataExtended:
    """Extended tests for compute_stats_data (#340)."""

    @pytest.fixture
    def seeded_db(self, tmp_path):
        db = Database(tmp_path / "test.db")
        db.connect()
        db.init_schema()
        s1 = db.insert_or_get_song("song a", "Song A")
        s2 = db.insert_or_get_song("song b", "Song B")
        svc1 = db.insert_or_update_service(
            "2026-01-10", "AM", "a.pptx", "h1", song_leader="Matt"
        )
        svc2 = db.insert_or_update_service(
            "2026-01-17", "AM", "b.pptx", "h2", song_leader="John"
        )
        db.insert_service_song(svc1, s1, ordinal=1)
        db.insert_service_song(svc1, s2, ordinal=2)
        db.insert_service_song(svc2, s1, ordinal=1)
        db.insert_or_get_copy_event(svc1, s1, "projection")
        db.insert_or_get_copy_event(svc1, s2, "projection")
        db.insert_or_get_copy_event(svc2, s1, "projection")
        yield db
        db.close()

    def test_leader_filter_returns_only_matching(self, seeded_db):
        data = compute_stats_data(seeded_db, "2020-01-01", "2030-12-31", "Matt", False)
        assert len(data["services"]) == 1
        assert data["services"][0]["song_leader"] == "Matt"

    def test_leader_filter_excludes_others(self, seeded_db):
        data = compute_stats_data(seeded_db, "2020-01-01", "2030-12-31", "Matt", False)
        leaders = [s["song_leader"] for s in data["services"]]
        assert "John" not in leaders

    def test_all_songs_false_limits_to_top_20(self, tmp_path):
        db = Database(tmp_path / "top20.db")
        db.connect()
        db.init_schema()
        svc = db.insert_or_update_service("2026-01-01", "AM", "a.pptx", "h1")
        for i in range(25):
            sid = db.insert_or_get_song(f"song {i}", f"Song {i}")
            db.insert_service_song(svc, sid, ordinal=i + 1)
            db.insert_or_get_copy_event(svc, sid, "projection")
        data = compute_stats_data(db, "2020-01-01", "2030-12-31", None, False)
        assert len(data["sorted_songs"]) == 20
        db.close()

    def test_all_songs_true_returns_all(self, tmp_path):
        db = Database(tmp_path / "all.db")
        db.connect()
        db.init_schema()
        svc = db.insert_or_update_service("2026-01-01", "AM", "a.pptx", "h1")
        for i in range(25):
            sid = db.insert_or_get_song(f"song {i}", f"Song {i}")
            db.insert_service_song(svc, sid, ordinal=i + 1)
            db.insert_or_get_copy_event(svc, sid, "projection")
        data = compute_stats_data(db, "2020-01-01", "2030-12-31", None, True)
        assert len(data["sorted_songs"]) == 25
        db.close()

    def test_date_boundary_includes_exact_match(self, seeded_db):
        data = compute_stats_data(seeded_db, "2026-01-10", "2026-01-10", None, False)
        assert len(data["services"]) == 1
        assert data["services"][0]["service_date"] == "2026-01-10"

    def test_leader_breakdown_present_when_no_filter(self, seeded_db):
        data = compute_stats_data(seeded_db, "2020-01-01", "2030-12-31", None, False)
        assert "Matt" in data["leader_breakdown"]
        assert "John" in data["leader_breakdown"]

    def test_leader_breakdown_empty_when_filter_set(self, seeded_db):
        data = compute_stats_data(seeded_db, "2020-01-01", "2030-12-31", "Matt", False)
        assert data["leader_breakdown"] == {}
