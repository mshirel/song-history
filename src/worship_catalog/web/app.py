"""FastAPI + HTMX web UI for the worship catalog."""

from __future__ import annotations

import csv
import io
import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from worship_catalog.db import Database
from worship_catalog.log_config import RequestLoggingMiddleware, setup as _setup_logging

_setup_logging()
_log = logging.getLogger("worship_catalog.web")

app = FastAPI(title="Worship Catalog")
app.add_middleware(RequestLoggingMiddleware)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _get_db() -> Database:
    db_path = Path(os.environ.get("DB_PATH", "data/worship.db"))
    db = Database(db_path)
    db.connect()
    db.init_schema()
    return db


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=RedirectResponse)
async def root():
    return RedirectResponse(url="/songs")


@app.get("/songs", response_class=HTMLResponse)
async def songs(request: Request, q: Optional[str] = Query(default=None)):
    db = _get_db()
    rows = _query_songs(db, q)
    db.close()

    if request.headers.get("HX-Request"):
        # HTMX partial — return just the table body
        return templates.TemplateResponse(
            request, "songs_rows.html", {"songs": rows}
        )
    return templates.TemplateResponse(
        request, "songs.html", {"songs": rows, "q": q or ""}
    )


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request):
    return templates.TemplateResponse(request, "reports.html")


@app.post("/reports/ccli")
async def reports_ccli(
    start_date: str = Form(...),
    end_date: str = Form(...),
):
    db = _get_db()
    events = db.query_copy_events(start_date, end_date)
    db.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Service", "Title", "CCLI#", "Reproduction Type", "Count"])
    for e in events:
        credits_parts = [e.get("words_by") or "", e.get("music_by") or ""]
        credits = " / ".join(p for p in credits_parts if p) or ""
        writer.writerow([
            e["service_date"],
            e["service_name"],
            e["display_title"],
            credits,
            e["reproduction_type"],
            e["count"],
        ])

    _log.info("CCLI report generated", extra={"start_date": start_date, "end_date": end_date, "rows": len(events)})
    output.seek(0)
    filename = f"ccli_report_{start_date}_{end_date}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/reports/stats", response_class=HTMLResponse)
async def reports_stats(
    request: Request,
    start_date: str = Form(...),
    end_date: str = Form(...),
    leader: str = Form(default=""),
    all_songs: bool = Form(default=False),
):
    db = _get_db()
    services = db.query_services(start_date, end_date, song_leader=leader or None)
    service_ids = [s["id"] for s in services]
    events = db.query_copy_events(start_date, end_date, service_ids=service_ids or None)
    db.close()

    # Aggregate song counts
    song_counts: dict[str, int] = {}
    song_credits: dict[str, str] = {}
    for e in events:
        title = e["display_title"]
        song_counts[title] = song_counts.get(title, 0) + 1
        if title not in song_credits:
            parts = [e.get("words_by") or "", e.get("music_by") or ""]
            song_credits[title] = " / ".join(p for p in parts if p)

    sorted_songs = sorted(song_counts.items(), key=lambda x: -x[1])
    if not all_songs:
        sorted_songs = sorted_songs[:20]

    # Build per-leader breakdown (only when not already filtered to one leader)
    leader_breakdown: dict[str, list[tuple[str, int]]] = {}
    if not leader:
        service_leader_map = {s["id"]: (s.get("song_leader") or "Unknown") for s in services}
        ldr_song_services: dict[str, dict[str, set]] = {}
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
    # Build per-leader service count for display
    leader_service_counts = {
        s.get("song_leader") or "Unknown": 0 for s in services
    }
    for s in services:
        ldr = s.get("song_leader") or "Unknown"
        leader_service_counts[ldr] = leader_service_counts.get(ldr, 0) + 1

    _log.info(
        "Stats report generated",
        extra={"start_date": start_date, "end_date": end_date, "leader": leader or None,
               "services": len(services), "unique_songs": len(song_counts)},
    )
    return templates.TemplateResponse(
        request,
        "stats_result.html",
        {
            "start_date": start_date,
            "end_date": end_date,
            "leader": leader,
            "services": services,
            "sorted_songs": sorted_songs,
            "song_credits": song_credits,
            "total_performances": sum(song_counts.values()),
            "total_events": len(events),
            "all_songs": all_songs,
            "leader_breakdown": leader_breakdown,
            "leader_service_counts": leader_service_counts,
        },
    )


@app.get("/services", response_class=HTMLResponse)
async def services_list(request: Request):
    db = _get_db()
    services = _query_all_services(db)
    db.close()
    return templates.TemplateResponse(request, "services.html", {"services": services})


@app.get("/services/{service_id}", response_class=HTMLResponse)
async def service_detail(request: Request, service_id: int):
    db = _get_db()
    service = _query_service_by_id(db, service_id)
    if not service:
        db.close()
        _log.warning("Service not found", extra={"service_id": service_id})
        raise HTTPException(status_code=404, detail="Service not found")
    songs = _query_service_songs(db, service_id)
    db.close()
    return templates.TemplateResponse(
        request, "service_detail.html", {"service": service, "songs": songs}
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _query_songs(db: Database, search: Optional[str] = None) -> list[dict]:
    """Return all songs with performance count, optionally filtered by search term."""
    cursor = db.conn.cursor()
    if search:
        like = f"%{search}%"
        cursor.execute(
            """
            SELECT s.id, s.display_title, s.canonical_title,
                   se.words_by, se.music_by, se.arranger,
                   COUNT(DISTINCT ss.service_id) AS performance_count
            FROM songs s
            LEFT JOIN song_editions se ON se.song_id = s.id
            LEFT JOIN service_songs ss ON ss.song_id = s.id
            WHERE LOWER(s.display_title) LIKE LOWER(?)
               OR LOWER(COALESCE(se.words_by, '')) LIKE LOWER(?)
               OR LOWER(COALESCE(se.music_by, '')) LIKE LOWER(?)
            GROUP BY s.id
            ORDER BY performance_count DESC, s.display_title
            """,
            (like, like, like),
        )
    else:
        cursor.execute(
            """
            SELECT s.id, s.display_title, s.canonical_title,
                   se.words_by, se.music_by, se.arranger,
                   COUNT(DISTINCT ss.service_id) AS performance_count
            FROM songs s
            LEFT JOIN song_editions se ON se.song_id = s.id
            LEFT JOIN service_songs ss ON ss.song_id = s.id
            GROUP BY s.id
            ORDER BY performance_count DESC, s.display_title
            """
        )
    return [dict(row) for row in cursor.fetchall()]


def _query_all_services(db: Database) -> list[dict]:
    """Return all services ordered by date descending."""
    cursor = db.conn.cursor()
    cursor.execute(
        """
        SELECT sv.*, COUNT(DISTINCT ss.song_id) AS song_count
        FROM services sv
        LEFT JOIN service_songs ss ON ss.service_id = sv.id
        GROUP BY sv.id
        ORDER BY sv.service_date DESC, sv.service_name
        """
    )
    return [dict(row) for row in cursor.fetchall()]


def _query_service_by_id(db: Database, service_id: int) -> Optional[dict]:
    """Return a single service row or None."""
    cursor = db.conn.cursor()
    cursor.execute("SELECT * FROM services WHERE id = ?", (service_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def _query_service_songs(db: Database, service_id: int) -> list[dict]:
    """Return songs for a service in setlist order, with full credits."""
    cursor = db.conn.cursor()
    cursor.execute(
        """
        SELECT ss.ordinal, ss.occurrences,
               s.id AS song_id, s.display_title, s.canonical_title,
               se.publisher, se.words_by, se.music_by, se.arranger, se.copyright_notice,
               GROUP_CONCAT(ce.reproduction_type, ', ') AS copy_types
        FROM service_songs ss
        JOIN songs s ON ss.song_id = s.id
        LEFT JOIN song_editions se ON ss.song_edition_id = se.id
        LEFT JOIN copy_events ce ON ce.service_id = ss.service_id
                                 AND ce.song_id = ss.song_id
                                 AND ce.reportable = 1
        WHERE ss.service_id = ?
        GROUP BY ss.id
        ORDER BY ss.ordinal
        """,
        (service_id,),
    )
    return [dict(row) for row in cursor.fetchall()]
