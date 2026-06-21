"""Unit tests for the missing-services report (slot classifier + compute)."""

from datetime import date, timedelta

import pytest

from worship_catalog.db import Database
from worship_catalog.service_slots import (
    DEFAULT_WINDOW_DAYS,
    SLOT_EVENING,
    SLOT_MORNING,
    classify_service_slot,
    get_data_collection_start,
    normalize_window_days,
    resolve_window,
)
from worship_catalog.services.missing_services_report import compute_missing_services

# A known Sunday used as a deterministic "today" so the window math is stable.
SUNDAY_TODAY = date(2026, 6, 21)
COLLECTION_START = date(2026, 3, 1)  # first Sunday in March 2026


def _make_db(tmp_path):
    db = Database(tmp_path / "missing.db")
    db.connect()
    db.init_schema()
    return db


def _add_service(db, service_date: str, service_name: str) -> int:
    return db.insert_or_update_service(
        service_date=service_date,
        service_name=service_name,
        source_file="x.pptx",
        source_hash=f"hash-{service_date}-{service_name}",
    )


class TestClassifyServiceSlot:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("Morning Worship", SLOT_MORNING),
            ("Evening Worship", SLOT_EVENING),
            ("AM Worship", SLOT_MORNING),
            ("PM Worship", SLOT_EVENING),
            ("Sunday AM", SLOT_MORNING),
            ("Sunday PM", SLOT_EVENING),
            ("morning service", SLOT_MORNING),
            ("Wednesday Bible Class", None),
            ("", None),
            (None, None),
        ],
    )
    def test_classification(self, name, expected):
        assert classify_service_slot(name) == expected

    def test_am_not_matched_inside_words(self):
        # "am"/"pm" must be whole-word, not substrings of unrelated words.
        assert classify_service_slot("Sermon Camp") is None


class TestWindowResolution:
    def test_default_window_constant(self):
        assert DEFAULT_WINDOW_DAYS == 90

    def test_collection_start_is_first_sunday_in_march(self):
        start = get_data_collection_start()
        assert start == COLLECTION_START
        assert start.weekday() == 6  # Sunday

    def test_90_day_window_start_is_today_minus_90(self):
        start_str, end_str = resolve_window(90, SUNDAY_TODAY)
        assert end_str == SUNDAY_TODAY.isoformat()
        assert start_str == (SUNDAY_TODAY - timedelta(days=90)).isoformat()

    def test_long_window_clamps_to_collection_start(self):
        start_str, end_str = resolve_window(730, SUNDAY_TODAY)
        # 2 years back is well before data collection began — clamp to the floor.
        assert start_str == COLLECTION_START.isoformat()
        assert end_str == SUNDAY_TODAY.isoformat()

    @pytest.mark.parametrize(
        "given,expected",
        [("90", 90), ("180", 180), (365, 365), (730, 730), ("999", 90), (None, 90), ("x", 90)],
    )
    def test_normalize_window_days(self, given, expected):
        assert normalize_window_days(given) == expected


class TestComputeMissingServices:
    @pytest.mark.integration
    def test_long_window_first_week_is_collection_start(self, tmp_path):
        db = _make_db(tmp_path)
        data = compute_missing_services(db, days=730, today=SUNDAY_TODAY)
        db.close()
        # Weeks are newest-first; the earliest (last) week is the collection start.
        assert data["weeks"][-1]["date"] == COLLECTION_START.isoformat()
        assert data["start_date"] == COLLECTION_START.isoformat()

    @pytest.mark.integration
    def test_all_sundays_missing_when_db_empty(self, tmp_path):
        db = _make_db(tmp_path)
        data = compute_missing_services(db, days=90, today=SUNDAY_TODAY)
        db.close()
        summary = data["summary"]
        # Every Sunday slot is missing; present/excluded are zero.
        assert summary["present"] == 0
        assert summary["excluded"] == 0
        assert summary["missing"] == summary["expected"]
        assert summary["expected"] == summary["sundays"] * 2

    @pytest.mark.integration
    def test_per_slot_present_missing_and_excluded(self, tmp_path):
        db = _make_db(tmp_path)
        # 2026-06-14 is the Sunday before our 'today'. Add only the morning service.
        sunday = "2026-06-14"
        _add_service(db, sunday, "Morning Worship")
        # Mark that Sunday's evening as intentionally excluded.
        db.add_exclusion(sunday, SLOT_EVENING, reason="No evening service (fellowship meal)")

        data = compute_missing_services(db, days=90, today=SUNDAY_TODAY)
        db.close()

        week = next(w for w in data["weeks"] if w["date"] == sunday)
        slots = {s["slot"]: s for s in week["slots"]}
        assert slots[SLOT_MORNING]["status"] == "present"
        assert slots[SLOT_MORNING]["service"]["service_name"] == "Morning Worship"
        assert slots[SLOT_EVENING]["status"] == "excluded"
        assert slots[SLOT_EVENING]["reason"] == "No evening service (fellowship meal)"

    @pytest.mark.integration
    def test_uncategorized_service_is_surfaced_not_counted_as_present(self, tmp_path):
        db = _make_db(tmp_path)
        # A midweek service on a Sunday-less slot name — cannot fill a Sunday slot.
        _add_service(db, "2026-06-17", "Wednesday Bible Class")
        data = compute_missing_services(db, days=90, today=SUNDAY_TODAY)
        db.close()
        assert data["summary"]["uncategorized"] == 1
        assert data["summary"]["present"] == 0

    @pytest.mark.integration
    def test_window_metadata_present(self, tmp_path):
        db = _make_db(tmp_path)
        data = compute_missing_services(db, days=180, today=SUNDAY_TODAY)
        db.close()
        assert data["window_days"] == 180
        assert data["window_label"] == "Last 180 days"
        assert data["end_date"] == SUNDAY_TODAY.isoformat()
