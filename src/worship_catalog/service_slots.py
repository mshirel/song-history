"""Service-slot classification and missing-services report constants (#480).

A worship week is expected to have two services: a morning and an evening slot.
This module classifies a stored ``service_name`` into one of those slots and
holds the constants the missing-services report depends on (the data-collection
floor and the selectable lookback windows).
"""

from __future__ import annotations

import os
import re
from datetime import date, timedelta

SLOT_MORNING: str = "morning"
SLOT_EVENING: str = "evening"
# Order matters: the report renders/iterates slots in this order.
EXPECTED_SLOTS: tuple[str, str] = (SLOT_MORNING, SLOT_EVENING)
VALID_SLOTS: frozenset[str] = frozenset(EXPECTED_SLOTS)

# Highland began formally collecting service data on the first Sunday of March
# 2026. The report never reports gaps earlier than this, even for wide windows.
# Overridable via the DATA_COLLECTION_START env var (ISO YYYY-MM-DD).
_DEFAULT_COLLECTION_START: str = "2026-03-01"

DEFAULT_WINDOW_DAYS: int = 90
# Insertion order is preserved and drives the template's selector options.
WINDOW_OPTIONS: dict[str, str] = {
    "90": "Last 90 days",
    "180": "Last 180 days",
    "365": "Last 1 year",
    "730": "Last 2 years",
}

# Whole-word AM/PM matchers so older "AM Worship" / "Sunday PM" naming maps to a
# slot without matching "am"/"pm" buried inside unrelated words.
_AM_RE = re.compile(r"\bam\b", re.IGNORECASE)
_PM_RE = re.compile(r"\bpm\b", re.IGNORECASE)


def get_data_collection_start() -> date:
    """Return the earliest date the report will consider (the collection floor)."""
    raw = os.environ.get("DATA_COLLECTION_START", _DEFAULT_COLLECTION_START).strip()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return date.fromisoformat(_DEFAULT_COLLECTION_START)


def classify_service_slot(service_name: str | None) -> str | None:
    """Map a stored ``service_name`` to ``morning``/``evening`` (or None).

    Production data uses "Morning Worship" / "Evening Worship"; older or
    hand-entered data may use "AM Worship" / "PM Worship". Anything that matches
    neither (midweek classes, special events) returns None and does not fill a
    Sunday slot.
    """
    if not service_name:
        return None
    lowered = service_name.lower()
    if "morning" in lowered or _AM_RE.search(service_name):
        return SLOT_MORNING
    if "evening" in lowered or _PM_RE.search(service_name):
        return SLOT_EVENING
    return None


def normalize_window_days(days: int | str | None) -> int:
    """Coerce a requested window to a supported size, falling back to the default."""
    try:
        key = str(int(days))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_WINDOW_DAYS
    return int(key) if key in WINDOW_OPTIONS else DEFAULT_WINDOW_DAYS


def resolve_window(days: int, today: date) -> tuple[str, str]:
    """Return (start_iso, end_iso) for *days* back from *today*, clamped to floor.

    The start never precedes ``get_data_collection_start()`` so the report does
    not flag "gaps" from before data collection began.
    """
    start = today - timedelta(days=days)
    floor = get_data_collection_start()
    if start < floor:
        start = floor
    return start.isoformat(), today.isoformat()


def sundays_in_range(start: date, end: date) -> list[date]:
    """List every Sunday in the inclusive ``[start, end]`` range, ascending."""
    offset = (6 - start.weekday()) % 7  # weekday(): Mon=0 .. Sun=6
    first_sunday = start + timedelta(days=offset)
    out: list[date] = []
    current = first_sunday
    while current <= end:
        out.append(current)
        current += timedelta(days=7)
    return out
