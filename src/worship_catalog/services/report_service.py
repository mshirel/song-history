"""Shared stats report computation logic (#25)."""

from __future__ import annotations

from typing import Any

from worship_catalog.db import Database


def compute_stats_data(
    db: Database,
    start_date: str,
    end_date: str,
    leader: str | None,
    all_songs: bool,
) -> dict[str, Any]:
    """Compute stats report data, shared by HTML, CSV, Excel routes, and CLI.

    Returns a dict with keys:
      - services: list of service dicts
      - sorted_songs: list of (title, count) tuples
      - song_credits: dict of title -> credits string
      - total_performances: int
      - total_events: int
      - leader_breakdown: dict of leader -> list of (title, count)
      - leader_service_counts: dict of leader -> int
    """
    services = db.query_services(start_date, end_date, song_leader=leader or None)
    service_ids = [s["id"] for s in services]
    events = db.query_copy_events(start_date, end_date, service_ids=service_ids or None)

    # Count distinct services per song title (not raw copy-event rows).
    # A song with multiple copy events in one service (e.g., projection + recording)
    # must contribute exactly 1 to its count, not N (#97).
    song_service_ids: dict[str, set[int]] = {}
    song_credits: dict[str, str] = {}
    for e in events:
        title = e["display_title"]
        song_service_ids.setdefault(title, set()).add(e["service_id"])
        if title not in song_credits:
            parts = [e.get("words_by") or "", e.get("music_by") or ""]
            song_credits[title] = " / ".join(p for p in parts if p)
    song_counts: dict[str, int] = {t: len(sids) for t, sids in song_service_ids.items()}

    sorted_songs = sorted(song_counts.items(), key=lambda x: -x[1])
    if not all_songs:
        sorted_songs = sorted_songs[:20]

    leader_breakdown: dict[str, list[tuple[str, int]]] = {}
    if not leader:
        service_leader_map = {s["id"]: (s.get("song_leader") or "Unknown") for s in services}
        ldr_song_services: dict[str, dict[str, set[int]]] = {}
        for e in events:
            ldr = service_leader_map.get(e["service_id"], "Unknown")
            title = e["display_title"]
            ldr_song_services.setdefault(ldr, {}).setdefault(title, set()).add(e["service_id"])
        leader_breakdown = {
            ldr: sorted(
                [(t, len(sids)) for t, sids in songs.items()],
                key=lambda x: (-x[1], x[0].lower()),
            )
            for ldr, songs in sorted(
                ldr_song_services.items(),
                key=lambda kv: -sum(len(v) for v in kv[1].values()),
            )
        }

    leader_service_counts: dict[str, int] = {
        s.get("song_leader") or "Unknown": 0 for s in services
    }
    for s in services:
        ldr = s.get("song_leader") or "Unknown"
        leader_service_counts[ldr] = leader_service_counts.get(ldr, 0) + 1

    return {
        "services": services,
        "sorted_songs": sorted_songs,
        "song_credits": song_credits,
        "total_performances": sum(song_counts.values()),
        "total_events": len(events),
        "leader_breakdown": leader_breakdown,
        "leader_service_counts": leader_service_counts,
    }
