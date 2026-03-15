"""FastAPI + HTMX web UI for the worship catalog."""

from __future__ import annotations

import csv
import io
import logging
import math
import os
import re
import secrets
from collections.abc import Generator
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette_csrf import CSRFMiddleware  # type: ignore[attr-defined]

from worship_catalog.db import Database
from worship_catalog.log_config import RequestLoggingMiddleware
from worship_catalog.log_config import setup as _setup_logging

_setup_logging()
_log = logging.getLogger("worship_catalog.web")

app = FastAPI(title="Worship Catalog")

# CSRF protection — must be added BEFORE RequestLoggingMiddleware so that 403
# responses are logged correctly. Secret is read from env; a random value is
# generated on first start (sufficient for a single-process deployment).
_CSRF_SECRET = os.environ.get("CSRF_SECRET") or secrets.token_hex(32)
app.add_middleware(
    CSRFMiddleware,
    secret=_CSRF_SECRET,
    exempt_urls=[re.compile(r"^/health$")],
)
app.add_middleware(RequestLoggingMiddleware)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> HTMLResponse:
    if exc.status_code == 404:
        return templates.TemplateResponse(
            request, "404.html", {"detail": str(exc.detail)}, status_code=404
        )
    return templates.TemplateResponse(
        request, "500.html", {"detail": str(exc.detail)}, status_code=exc.status_code
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> HTMLResponse:
    _log.exception("Unhandled exception", extra={"path": str(request.url)})
    return templates.TemplateResponse(
        request, "500.html", {"detail": "An unexpected error occurred."}, status_code=500
    )


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date_range(start_date: str, end_date: str) -> None:
    """Raise HTTPException 422 if dates are not valid ISO-8601 or range is inverted."""
    for label, val in (("start_date", start_date), ("end_date", end_date)):
        if not _DATE_RE.match(val):
            raise HTTPException(
                status_code=422,
                detail=f"Invalid {label}: '{val}' — expected YYYY-MM-DD",
            )
        try:
            date.fromisoformat(val)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid {label}: '{val}' — not a real calendar date",
            ) from exc
    if start_date > end_date:
        raise HTTPException(
            status_code=422,
            detail=f"start_date ({start_date}) must not be after end_date ({end_date})",
        )


def _get_db() -> Database:
    db_path = Path(os.environ.get("DB_PATH", "data/worship.db"))
    db = Database(db_path)
    db.connect()
    db.init_schema()
    return db


def get_db() -> Generator[Database, None, None]:
    """FastAPI dependency that always closes the DB connection (issue #21)."""
    db = _get_db()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
async def health(response: Response) -> dict[str, str]:
    """Return 200 if DB is reachable; 503 otherwise (issue #31)."""
    try:
        db = _get_db()
        db.cursor().execute("SELECT 1")
        db.close()
        return {"status": "ok", "db": "connected"}
    except Exception as exc:
        _log.warning("Health check DB failure", extra={"error": str(exc)})
        response.status_code = 503
        return {"status": "error", "db": "unavailable"}


@app.get("/", response_class=RedirectResponse)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/songs")


_SONGS_SORT_COLS = {"display_title", "words_by", "music_by", "arranger", "performance_count"}


@app.get("/songs", response_class=HTMLResponse)
async def songs(
    request: Request,
    q: str | None = Query(default=None),
    sort: str = Query(default="performance_count"),
    sort_dir: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=10, le=500),
) -> HTMLResponse:
    sort = sort if sort in _SONGS_SORT_COLS else "performance_count"
    sort_dir = "asc" if sort_dir == "asc" else "desc"
    db = _get_db()
    rows, total = _query_songs(db, q, sort=sort, sort_dir=sort_dir, page=page, per_page=per_page)
    db.close()

    total_pages = math.ceil(total / per_page) if total > 0 else 1

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request, "songs_rows.html", {"songs": rows}
        )
    return templates.TemplateResponse(
        request, "songs.html", {
            "songs": rows, "q": q or "", "sort": sort, "sort_dir": sort_dir,
            "page": page, "per_page": per_page, "total_pages": total_pages, "total": total,
        }
    )


@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "reports.html")


@app.post("/reports/ccli")
async def reports_ccli(
    start_date: str = Form(...),
    end_date: str = Form(...),
) -> StreamingResponse:
    _validate_date_range(start_date, end_date)
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

    _log.info(
        "CCLI report generated",
        extra={"start_date": start_date, "end_date": end_date, "rows": len(events)},
    )
    output.seek(0)
    filename = f"ccli_report_{start_date}_{end_date}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _compute_stats(
    db: Database,
    start_date: str,
    end_date: str,
    leader: str,
    all_songs: bool,
) -> dict[str, Any]:
    """Compute stats report data, shared by HTML, CSV, and Excel routes."""
    services = db.query_services(start_date, end_date, song_leader=leader or None)
    service_ids = [s["id"] for s in services]
    events = db.query_copy_events(start_date, end_date, service_ids=service_ids or None)

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


@app.post("/reports/stats", response_class=HTMLResponse)
async def reports_stats(
    request: Request,
    start_date: str = Form(...),
    end_date: str = Form(...),
    leader: str = Form(default=""),
    all_songs: bool = Form(default=False),
) -> HTMLResponse:
    _validate_date_range(start_date, end_date)
    db = _get_db()
    data = _compute_stats(db, start_date, end_date, leader, all_songs)
    db.close()

    _log.info(
        "Stats report generated",
        extra={"start_date": start_date, "end_date": end_date, "leader": leader or None,
               "services": len(data["services"]), "unique_songs": len(data["sorted_songs"])},
    )
    return templates.TemplateResponse(
        request,
        "stats_result.html",
        {
            "start_date": start_date,
            "end_date": end_date,
            "leader": leader,
            "all_songs": all_songs,
            **data,
        },
    )


@app.post("/reports/stats/csv")
async def reports_stats_csv(
    start_date: str = Form(...),
    end_date: str = Form(...),
    leader: str = Form(default=""),
    all_songs: bool = Form(default=False),
) -> StreamingResponse:
    _validate_date_range(start_date, end_date)
    db = _get_db()
    data = _compute_stats(db, start_date, end_date, leader, all_songs)
    db.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Rank", "Title", "Credits", "Count"])
    for rank, (title, count) in enumerate(data["sorted_songs"], 1):
        writer.writerow([rank, title, data["song_credits"].get(title, ""), count])

    output.seek(0)
    filename = f"stats_{start_date}_{end_date}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/reports/stats/xlsx")
async def reports_stats_xlsx(
    start_date: str = Form(...),
    end_date: str = Form(...),
    leader: str = Form(default=""),
    all_songs: bool = Form(default=False),
) -> StreamingResponse:
    _validate_date_range(start_date, end_date)
    try:
        import openpyxl
        from openpyxl.styles import Font
    except ImportError as exc:
        raise HTTPException(
            status_code=501,
            detail="Excel export requires openpyxl. Install with: pip install openpyxl",
        ) from exc

    db = _get_db()
    data = _compute_stats(db, start_date, end_date, leader, all_songs)
    db.close()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Top Songs"
    header = ["Rank", "Title", "Credits", "Count"]
    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for rank, (title, count) in enumerate(data["sorted_songs"], 1):
        ws.append([rank, title, data["song_credits"].get(title, ""), count])

    if data["leader_breakdown"]:
        ws2 = wb.create_sheet("By Leader")
        ws2.append(["Leader", "Song", "Count"])
        for cell in ws2[1]:
            cell.font = Font(bold=True)
        for ldr, songs in data["leader_breakdown"].items():
            for title, count in songs:
                ws2.append([ldr, title, count])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"stats_{start_date}_{end_date}.xlsx"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/songs/{song_id}", response_class=HTMLResponse)
async def song_detail(request: Request, song_id: int) -> HTMLResponse:
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
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=10, le=500),
) -> HTMLResponse:
    sort = sort if sort in _SERVICES_SORT_COLS else "service_date"
    sort_dir = "asc" if sort_dir == "asc" else "desc"
    db = _get_db()
    services, total = _query_all_services(
        db, sort=sort, sort_dir=sort_dir,
        q_service=q_service, q_leader=q_leader, q_preacher=q_preacher,
        q_sermon=q_sermon, start_date=start_date, end_date=end_date,
        page=page, per_page=per_page,
    )
    db.close()
    total_pages = math.ceil(total / per_page) if total > 0 else 1
    ctx = {
        "services": services, "sort": sort, "sort_dir": sort_dir,
        "q_service": q_service, "q_leader": q_leader, "q_preacher": q_preacher,
        "q_sermon": q_sermon, "start_date": start_date, "end_date": end_date,
        "page": page, "per_page": per_page, "total_pages": total_pages, "total": total,
    }
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "services_rows.html", ctx)
    return templates.TemplateResponse(request, "services.html", ctx)


@app.get("/services/{service_id}", response_class=HTMLResponse)
async def service_detail(request: Request, service_id: int) -> HTMLResponse:
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


_LEADER_MIN_SONG_COUNT = 2
_MIN_SERVICES_FOR_MEANINGFUL_TRENDS = 5


@app.get("/leaders", response_class=HTMLResponse)
async def leaders_index(request: Request) -> HTMLResponse:
    db = _get_db()
    leaders = db.query_all_leaders()
    db.close()
    return templates.TemplateResponse(request, "leaders.html", {"leaders": leaders})


@app.get("/leaders/{leader_name}/top-songs", response_class=HTMLResponse)
async def leader_top_songs(request: Request, leader_name: str) -> HTMLResponse:
    db = _get_db()
    top_songs = db.query_leader_top_songs(leader_name, min_count=_LEADER_MIN_SONG_COUNT)
    service_count = db.query_leader_service_count(leader_name)
    db.close()
    warning_few_services = service_count < _MIN_SERVICES_FOR_MEANINGFUL_TRENDS
    return templates.TemplateResponse(
        request,
        "leader_top_songs.html",
        {
            "leader": leader_name,
            "top_songs": top_songs,
            "service_count": service_count,
            "warning_few_services": warning_few_services,
            "min_count": _LEADER_MIN_SONG_COUNT,
        },
    )


@app.get("/leaders/{leader_name}/top-songs/csv")
async def leader_top_songs_csv(leader_name: str) -> StreamingResponse:
    db = _get_db()
    top_songs = db.query_leader_top_songs(leader_name, min_count=_LEADER_MIN_SONG_COUNT)
    db.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Rank", "Title", "Credits", "Count"])
    for rank, song in enumerate(top_songs, 1):
        parts = [song.get("words_by") or "", song.get("music_by") or ""]
        credits = " / ".join(p for p in parts if p)
        writer.writerow([rank, song["display_title"], credits, song["performance_count"]])

    output.seek(0)
    filename = f"leader_songs_{leader_name}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _query_songs(
    db: Database,
    search: str | None = None,
    sort: str = "performance_count",
    sort_dir: str = "desc",
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """Return songs with performance count, optionally filtered and sorted, with pagination."""
    order = f"{sort} {sort_dir.upper()}, s.display_title"
    cursor = db.cursor()
    base = """
        SELECT s.id, s.display_title, s.canonical_title,
               se.words_by, se.music_by, se.arranger,
               COUNT(DISTINCT ss.service_id) AS performance_count
        FROM songs s
        LEFT JOIN song_editions se ON se.song_id = s.id
        LEFT JOIN service_songs ss ON ss.song_id = s.id
    """
    count_base = """
        SELECT COUNT(DISTINCT s.id)
        FROM songs s
        LEFT JOIN song_editions se ON se.song_id = s.id
        LEFT JOIN service_songs ss ON ss.song_id = s.id
    """
    offset = (page - 1) * per_page
    if search:
        like = f"%{search}%"
        where = """
            WHERE LOWER(s.display_title) LIKE LOWER(?)
               OR LOWER(COALESCE(se.words_by, '')) LIKE LOWER(?)
               OR LOWER(COALESCE(se.music_by, '')) LIKE LOWER(?)
        """
        cursor.execute(count_base + where, (like, like, like))
        total = cursor.fetchone()[0]
        cursor.execute(
            base + where + "GROUP BY s.id ORDER BY " + order + " LIMIT ? OFFSET ?",
            (like, like, like, per_page, offset),
        )
    else:
        cursor.execute(count_base)
        total = cursor.fetchone()[0]
        cursor.execute(base + "GROUP BY s.id ORDER BY " + order + " LIMIT ? OFFSET ?",
                       (per_page, offset))
    return [dict(row) for row in cursor.fetchall()], total


def _query_song_by_id(db: Database, song_id: int) -> dict[str, Any] | None:
    cursor = db.cursor()
    cursor.execute("SELECT * FROM songs WHERE id = ?", (song_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def _query_song_editions(db: Database, song_id: int) -> list[dict[str, Any]]:
    cursor = db.cursor()
    cursor.execute(
        "SELECT * FROM song_editions WHERE song_id = ? ORDER BY id",
        (song_id,),
    )
    return [dict(row) for row in cursor.fetchall()]


def _query_song_services(db: Database, song_id: int) -> list[dict[str, Any]]:
    """Return all services where a song was performed, with position and copy types."""
    cursor = db.cursor()
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
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    """Return services with optional filtering, sorting, and pagination."""
    where_clauses = []
    params: list[Any] = []
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
    offset = (page - 1) * per_page
    cursor = db.cursor()
    # Count query
    cursor.execute(
        f"SELECT COUNT(DISTINCT sv.id) FROM services sv {where_sql}",
        params,
    )
    total = cursor.fetchone()[0]
    cursor.execute(
        f"""
        SELECT sv.*, COUNT(DISTINCT ss.song_id) AS song_count
        FROM services sv
        LEFT JOIN service_songs ss ON ss.service_id = sv.id
        {where_sql}
        GROUP BY sv.id
        ORDER BY {order}
        LIMIT ? OFFSET ?
        """,
        params + [per_page, offset],
    )
    return [dict(row) for row in cursor.fetchall()], total


def _query_service_by_id(db: Database, service_id: int) -> dict[str, Any] | None:
    """Return a single service row or None."""
    cursor = db.cursor()
    cursor.execute("SELECT * FROM services WHERE id = ?", (service_id,))
    row = cursor.fetchone()
    return dict(row) if row else None


def _query_service_songs(db: Database, service_id: int) -> list[dict[str, Any]]:
    """Return songs for a service in setlist order, with full credits."""
    cursor = db.cursor()
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
