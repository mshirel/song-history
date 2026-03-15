"""Shared import pipeline — used by both CLI and web upload endpoints (#129).

Extracts songs from a PPTX file and persists them to the database.
CLI-specific output (Click echo, progress) stays in cli.py.
Web-specific logic (job status updates, inbox cleanup) stays in web/app.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from worship_catalog.db import Database

_log = logging.getLogger(__name__)


@dataclass
class ImportResult:
    """Summary of a completed import run."""

    service_date: str | None
    service_name: str | None
    songs_imported: int
    anomalies: list[dict[str, Any]] = field(default_factory=list)


def run_import(
    db: Database,
    pptx_path: Path | str,
    *,
    library_index: dict[str, Any] | None = None,
    ocr_budget: Any | None = None,
    use_ocr: bool = False,
) -> ImportResult:
    """Extract songs from *pptx_path* and persist them to *db*.

    This is the shared core used by both ``import_cmd`` (CLI) and
    ``_run_import_in_background`` (web upload), so that the two entry-points
    stay in sync (#129).

    CLI-specific logic (progress echo, Click output) and web-specific logic
    (job status updates, inbox file cleanup) are handled by the respective
    callers — this function is pure "extract + store".

    Args:
        db: An open, schema-initialised :class:`Database` instance.
        pptx_path: Path to the PPTX file to import.
        library_index: Optional pre-loaded library credits index dict.
        ocr_budget: Optional :class:`OcrBudget` instance (passed to extractor).
        use_ocr: Whether to enable OCR fallback for credit resolution.

    Returns:
        :class:`ImportResult` with summary counts.

    Raises:
        FileNotFoundError: If *pptx_path* does not exist.
        ValueError: If the file exceeds size/slide-count limits.
        TimeoutError: If extraction exceeds the per-file time limit.
    """
    from worship_catalog.extractor import extract_songs
    from worship_catalog.pptx_reader import compute_file_hash

    pptx_path = Path(pptx_path)

    result = extract_songs(
        pptx_path,
        use_ocr=use_ocr,
        ocr_budget=ocr_budget,
        library_index=library_index,
    )
    service_hash = compute_file_hash(pptx_path)

    with db.transaction():
        # Idempotent re-import: delete existing service data if present
        cursor = db.cursor()
        cursor.execute(
            """
            SELECT id FROM services
            WHERE service_date = ? AND service_name = ? AND source_hash = ?
            """,
            (
                result.service_date or "0000-00-00",
                result.service_name or "Unknown",
                service_hash,
            ),
        )
        existing = cursor.fetchone()
        if existing:
            db.delete_service_data(existing[0])

        service_id = db.insert_or_update_service(
            service_date=result.service_date or "0000-00-00",
            service_name=result.service_name or "Unknown",
            source_file=str(pptx_path),
            source_hash=service_hash,
            song_leader=result.song_leader,
            preacher=result.preacher,
            sermon_title=result.sermon_title,
        )

        for song in result.songs:
            song_id = db.insert_or_get_song(
                song.canonical_title,
                song.display_title,
            )

            edition_id = None
            if song.publisher or song.words_by or song.music_by or song.arranger:
                edition_id = db.insert_or_get_song_edition(
                    song_id=song_id,
                    publisher=song.publisher,
                    words_by=song.words_by,
                    music_by=song.music_by,
                    arranger=song.arranger,
                )

            db.insert_service_song(
                service_id=service_id,
                song_id=song_id,
                ordinal=song.ordinal,
                song_edition_id=edition_id,
                first_slide_index=song.first_slide_index,
                last_slide_index=song.last_slide_index,
                occurrences=1,
            )

            db.insert_or_get_copy_event(
                service_id=service_id,
                song_id=song_id,
                song_edition_id=edition_id,
                reproduction_type="projection",
                count=1,
                reportable=True,
            )

            db.insert_or_get_copy_event(
                service_id=service_id,
                song_id=song_id,
                song_edition_id=edition_id,
                reproduction_type="recording",
                count=1,
                reportable=True,
            )

    _log.info(
        "run_import complete",
        extra={
            "file": pptx_path.name,
            "songs": len(result.songs),
            "service_date": result.service_date,
        },
    )

    return ImportResult(
        service_date=result.service_date,
        service_name=result.service_name,
        songs_imported=len(result.songs),
        anomalies=result.anomalies,
    )
