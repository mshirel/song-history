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


_SONGS_SORT_COLS = {"display_title", "words_by", "music_by", "arranger", "performance_count"}


@app.get("/songs", response_class=HTMLResponse)
async def songs(
    request: Request,
    q: Optional[str] = Query(default=None),
    sort: str = Query(default="performance_count"),
    sort_dir: str = Query(default="desc"),
):
    sort = sort if sort in _SONGS_SORT_COLS else "performance_count"
    sort_dir = "asc" if sort_dir == "asc" else "desc"
    db = _get_db()
    rows = _query_songs(db, q, sort=sort, sort_dir=sort_dir)
    db.close()

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request, "songs_rows.html", {"songs": rows}
        )
    return templates.TemplateResponse(
        request, "songs.html", {"songs": rows, "q": q or "", "sort": sort, "sort_dir": sort_dir}
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


@app.get("/songs/{song_id}", response_class=HTMLResponse)
async def song_detail(request: Request, song_id: int):
    db = _get_db()
    song = _query_song_by_id(db, song_id)
    if not song:
        db.close()
        _log.warning("Song not found", extra={"song_id": song_id})
        raise HTTPException(status_code=404, detail="Song not found")
    editions = _query_song_editions(db, song_id)
    service_history = _query_song_services(db, song_id)
    db.close()
    return templates.TemplateResponse(
        request,
        "song_detail.html",
        {"song": song, "editions": editions, "service_history": service_history},
    )


_SERVICES_SORT_COLS = {"service_date", "service_name", "song_leader", "preacher", "song_count"}


@app.get("/services", response_class=HTMLResponse)
async def services_list(
    request: Request,
    sort: str = Query(default="service_date"),
    sort_dir: str = Query(default="desc"),
    q_service: str = Query(default=""),
    q_leader: str = Query(default=""),
    q_preacher: str = Query(default=""),
    q_sermon: str = Query(default=""),
    start_date: str = Query(default=""),
    end_date: str = Query(default=""),
):
    sort = sort if sort in _SERVICES_SORT_COLS else "service_date"
    sort_dir = "asc" if sort_dir == "asc" else "desc"
    db = _get_db()
    services = _query_all_services(
        db, sort=sort, sort_dir=sort_dir,
        q_service=q_service, q_leader=q_leader, q_preacher=q_preacher,
        q_sermon=q_sermon, start_date=start_date, end_date=end_date,
    )
    db.close()
    ctx = {
        "services": services, "sort": sort, "sort_dir": sort_dir,
        "q_service": q_service, "q_leader": q_leader, "q_preacher": q_preacher,
        "q_sermon": q_sermon, "start_date": start_date, "end_date": end_date,
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "services_rows.html", ctx)
    return templates.TemplateResponse(request, "services.html", ctx)


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

def _query_songs(
    db: Database,
    search: Optional[str] = None,
    sort: str = "performance_count",
    sort_dir: str = "desc",
) -> list[dict]:
    """Return all songs with performance count, optionally filtered and sorted."""
    order = f"{sort} {sort_dir.upper()}, s.display_title"
    cursor = db.conn.cursor()
    base = """
        SELECT s.id, s.display_title, s.canonical_title,
               se.words_by, se.music_by, se.arranger,
               COUNT(DISTINCT ss.service_id) AS performance_count
        FROM songs s
        LEFT JOIN song_editions se ON se.song_id = s.id
        LEFT JOIN service_songs ss ON ss.song_id = s.id
    """
    if search:
        like = f"%{search}%"
        cursor.execute(
            base + """
            WHERE LOWER(s.display_title) LIKE LOWER(?)
               OR LOWER(COALESCE(se.words_by, '')) LIKE LOWER(?)
               OR LOWER(COALESCE(se.music_by, '')) LIKE LOWER(?)
            GROUP BY s.id
            ORDER BY """ + order,
            (like, like, like),
        )
    else:
        cursor.execute(base + "GROUP BY s.id ORDER BY " + order)
    return [dict(row) for row in cursor.fetchall()]


def _query_song_by_id(db: Database, song_id: int) -> Optional[dict]:
    cursor = db.conn.cursor()
    cursor.execute("SELECT * FROM songs WHERE id = ?", (song_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def _query_song_editions(db: Database, song_id: int) -> list[dict]:
    cursor = db.conn.cursor()
    cursor.execute(
        "SELECT * FROM song_editions WHERE song_id = ? ORDER BY id",
        (song_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def _query_song_services(db: Database, song_id: int) -> list[dict]:
    """Return all services where a song was performed, with position and copy types."""
    cursor = db.conn.cursor()
    cursor.execute(
        """
        SELECT sv.id AS service_id, sv.service_date, sv.service_name, sv.song_leader,
               ss.ordinal,
               GROUP_CONCAT(DISTINCT ce.reproduction_type) AS copy_types
        FROM services sv
        JOIN service_songs ss ON ss.service_id = sv.id
        LEFT JOIN copy_events ce ON ce.service_id = sv.id
                                 AND ce.song_id = ss.song_id
                                 AND ce.reportable = 1
        WHERE ss.song_id = ?
        GROUP BY sv.id
        ORDER BY sv.service_date DESC
        """,
        (song_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def _query_all_services(
    db: Database,
    sort: str = "service_date",
    sort_dir: str = "desc",
    q_service: str = "",
    q_leader: str = "",
    q_preacher: str = "",
    q_sermon: str = "",
    start_date: str = "",
    end_date: str = "",
) -> list[dict]:
    """Return services with optional filtering and sorting."""
    where_clauses = []
    params: list = []
    if q_service:
        where_clauses.append("LOWER(sv.service_name) LIKE LOWER(?)")
        params.append(f"%{q_service}%")
    if q_leader:
        where_clauses.append("LOWER(COALESCE(sv.song_leader,'')) LIKE LOWER(?)")
        params.append(f"%{q_leader}%")
    if q_preacher:
        where_clauses.append("LOWER(COALESCE(sv.preacher,'')) LIKE LOWER(?)")
        params.append(f"%{q_preacher}%")
    if q_sermon:
        where_clauses.append("LOWER(COALESCE(sv.sermon_title,'')) LIKE LOWER(?)")
        params.append(f"%{q_sermon}%")
    if start_date:
        where_clauses.append("sv.service_date >= ?")
        params.append(start_date)
    if end_date:
        where_clauses.append("sv.service_date <= ?")
        params.append(end_date)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    order = f"{sort} {sort_dir.upper()}, sv.service_name"
    cursor = db.conn.cursor()
    cursor.execute(
        f"""
        SELECT sv.*, COUNT(DISTINCT ss.song_id) AS song_count
        FROM services sv
        LEFT JOIN service_songs ss ON ss.service_id = sv.id
        {where_sql}
        GROUP BY sv.id
        ORDER BY {order}
        """,
        params,
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
