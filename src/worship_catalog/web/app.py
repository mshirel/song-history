"""FastAPI + HTMX web UI for the worship catalog."""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from worship_catalog.db import Database

app = FastAPI(title="Worship Catalog")

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
        },
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
