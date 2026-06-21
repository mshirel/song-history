"""Missing-services report computation (#480).

Identifies which expected Sunday morning/evening services are absent from the
database over a lookback window, distinguishing genuine gaps from slots that
have been intentionally marked excluded.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from worship_catalog.db import Database
from worship_catalog.service_slots import (
    EXPECTED_SLOTS,
    WINDOW_OPTIONS,
    classify_service_slot,
    get_data_collection_start,
    normalize_window_days,
    resolve_window,
    sundays_in_range,
)

STATUS_PRESENT: str = "present"
STATUS_MISSING: str = "missing"
STATUS_EXCLUDED: str = "excluded"


def compute_missing_services(
    db: Database, days: int, today: date
) -> dict[str, Any]:
    """Compute the missing-services report for *days* back from *today*.

    *today* is injected (not read from the clock) so the result is deterministic
    and testable. Returns a dict consumed by the HTML partial and JSON API:

      - window_days / window_label: the resolved lookback selection
      - start_date / end_date / collection_start: ISO date bounds
      - weeks: newest-first list of ``{date, slots, has_missing}`` where each
        slot is ``{slot, status, service, reason}``
      - uncategorized: in-range services whose name maps to no slot
      - summary: counts (sundays, expected, present, missing, excluded,
        uncategorized)
    """
    days = normalize_window_days(days)
    start_str, end_str = resolve_window(days, today)
    start = date.fromisoformat(start_str)
    end = date.fromisoformat(end_str)

    # Build a (date, slot) -> service map for everything stored in range.
    present: dict[tuple[str, str], dict[str, Any]] = {}
    uncategorized: list[dict[str, Any]] = []
    for svc in db.query_services(start_str, end_str):
        slot = classify_service_slot(svc.get("service_name"))
        if slot is None:
            uncategorized.append(svc)
            continue
        present[(svc["service_date"], slot)] = svc

    exclusions = {
        (e["service_date"], e["service_slot"]): e.get("reason")
        for e in db.query_exclusions(start_str, end_str)
    }

    counts = {STATUS_PRESENT: 0, STATUS_MISSING: 0, STATUS_EXCLUDED: 0}
    weeks: list[dict[str, Any]] = []
    for sunday in sundays_in_range(start, end):
        iso = sunday.isoformat()
        slots: list[dict[str, Any]] = []
        has_missing = False
        for slot in EXPECTED_SLOTS:
            key = (iso, slot)
            if key in present:
                status, service, reason = STATUS_PRESENT, present[key], None
            elif key in exclusions:
                status, service, reason = STATUS_EXCLUDED, None, exclusions[key]
            else:
                status, service, reason = STATUS_MISSING, None, None
                has_missing = True
            counts[status] += 1
            slots.append(
                {"slot": slot, "status": status, "service": service, "reason": reason}
            )
        weeks.append({"date": iso, "slots": slots, "has_missing": has_missing})

    weeks.reverse()  # newest Sunday first — most actionable at the top

    sundays_count = len(weeks)
    return {
        "window_days": days,
        "window_label": WINDOW_OPTIONS[str(days)],
        "start_date": start_str,
        "end_date": end_str,
        "collection_start": get_data_collection_start().isoformat(),
        "weeks": weeks,
        "uncategorized": uncategorized,
        "summary": {
            "sundays": sundays_count,
            "expected": sundays_count * len(EXPECTED_SLOTS),
            "present": counts[STATUS_PRESENT],
            "missing": counts[STATUS_MISSING],
            "excluded": counts[STATUS_EXCLUDED],
            "uncategorized": len(uncategorized),
        },
    }
