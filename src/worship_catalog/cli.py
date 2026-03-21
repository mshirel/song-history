"""CLI interface for worship catalog."""

import csv
import importlib.resources
import json
import logging
import sys
from pathlib import Path
from typing import Any

import click

from worship_catalog.db import Database
from worship_catalog.extractor import extract_songs
from worship_catalog.import_service import run_import
from worship_catalog.log_config import setup as _setup_logging
from worship_catalog.services.report_service import _STATS_TOP_SONGS as _STATS_TOP_SONGS
from worship_catalog.services.report_service import compute_stats_data

_log = logging.getLogger("worship_catalog.cli")

_DEFAULT_MAX_OCR_CALLS: int = 25
_REPORT_DATE_MIN: str = "0000-01-01"  # open-ended start sentinel for date range queries
_REPORT_DATE_MAX: str = "9999-12-31"  # open-ended end sentinel for date range queries


def _resolve_library_index(path_arg: str) -> Path:
    """Return the best available library index path.

    Priority:
    1. Explicit user-supplied path (if it exists)
    2. Bundled package data (src/worship_catalog/data/library_index.json)
    """
    p = Path(path_arg)
    if p.exists():
        return p
    # Fall back to bundled package data
    pkg_data = importlib.resources.files("worship_catalog") / "data" / "library_index.json"
    bundled = Path(str(pkg_data))
    if bundled.exists():
        return bundled
    return p  # return original (callers check .exists())


@click.group()
@click.version_option()
def main() -> None:
    """Worship Slide Deck Song Catalog.

    Extract, organize, and track songs from worship presentation files.
    """
    _setup_logging()


@main.command()
@click.argument("pptx", type=click.Path(exists=True))
@click.option(
    "--format",
    type=click.Choice(["json", "human"]),
    default="human",
    help="Output format",
)
def validate(pptx: str, format: str) -> None:
    """Validate a PPTX file without writing to database.

    Extracts songs and metadata, reporting any issues or low-confidence items.
    """
    try:
        pptx_path = Path(pptx)
        result = extract_songs(pptx_path)

        if format == "json":
            # Convert to JSON-serializable dict
            result_dict = {
                "filename": result.filename,
                "service_date": result.service_date,
                "service_name": result.service_name,
                "song_leader": result.song_leader,
                "preacher": result.preacher,
                "sermon_title": result.sermon_title,
                "songs": [
                    {
                        "ordinal": song.ordinal,
                        "canonical_title": song.canonical_title,
                        "display_title": song.display_title,
                        "publisher": song.publisher,
                        "words_by": song.words_by,
                        "music_by": song.music_by,
                        "arranger": song.arranger,
                        "first_slide_index": song.first_slide_index,
                        "last_slide_index": song.last_slide_index,
                        "slide_count": song.slide_count,
                    }
                    for song in result.songs
                ],
                "anomalies": result.anomalies,
            }
            click.echo(json.dumps(result_dict, indent=2))
        else:
            # Human-readable format
            click.echo(f"File: {result.filename}")
            click.echo(f"Date: {result.service_date}", err=False)
            click.echo(f"Service: {result.service_name}", err=False)
            if result.song_leader:
                click.echo(f"Song Leader: {result.song_leader}")
            if result.preacher:
                click.echo(f"Preacher: {result.preacher}")
            if result.sermon_title:
                click.echo(f"Sermon: {result.sermon_title}")

            click.echo(f"\nFound {len(result.songs)} songs:", err=False)
            for song in result.songs:
                click.echo(f"  {song.ordinal}. {song.display_title}", err=False)
                if song.publisher:
                    click.echo(f"     Publisher: {song.publisher}", err=False)
                if song.words_by or song.music_by or song.arranger:
                    credits = []
                    if song.words_by:
                        credits.append(f"Words: {song.words_by}")
                    if song.music_by:
                        credits.append(f"Music: {song.music_by}")
                    if song.arranger:
                        credits.append(f"Arr: {song.arranger}")
                    click.echo(f"     {', '.join(credits)}", err=False)

            if result.anomalies:
                click.echo(f"\n⚠️  Found {len(result.anomalies)} anomalies:", err=True)
                for anomaly in result.anomalies:
                    click.echo(f"  - {anomaly}", err=True)

        sys.exit(0)

    except Exception as e:
        _log.exception("validate error", extra={"error": str(e)})
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command(name="import")
@click.argument("pptx_or_folder", type=click.Path(exists=True))
@click.option(
    "--db",
    type=click.Path(),
    default="data/worship.db",
    help="Path to SQLite database",
)
@click.option(
    "--recurse",
    is_flag=True,
    help="Recursively process all PPTX files in folder",
)
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Skip interactive prompts",
)
@click.option(
    "--library-index",
    type=click.Path(),
    default="data/library_index.json",
    show_default=True,
    help="Path to scraped library index JSON (see: worship-catalog library index)",
)
@click.option(
    "--ocr",
    is_flag=True,
    help=(
        "Fall back to Claude Vision API for credits not found in library"
        " (requires ANTHROPIC_API_KEY)"
    ),
)
@click.option(
    "--max-ocr-calls",
    type=int,
    default=_DEFAULT_MAX_OCR_CALLS,
    show_default=True,
    help="Maximum Vision API calls across this run (ignored without --ocr)",
)
@click.option(
    "--unlimited-ocr",
    is_flag=True,
    help="Remove the OCR call cap (overrides --max-ocr-calls)",
)
def import_cmd(
    pptx_or_folder: str,
    db: str,
    recurse: bool,
    non_interactive: bool,
    library_index: str,
    ocr: bool,
    max_ocr_calls: int,
    unlimited_ocr: bool,
) -> None:
    """Import PPTX file(s) to database.

    Extracts song data and stores in SQLite database.
    If folder path provided, imports all PPTX files.
    """
    try:
        from worship_catalog.library import load_library_index

        path = Path(pptx_or_folder)
        db_path = Path(db)

        with Database(db_path) as database:
            database.init_schema()

            # Load library index from JSON if it exists (local override or bundled default)
            lib_index: dict[str, dict[str, str | None]] = {}
            lib_index_path = _resolve_library_index(library_index)
            if lib_index_path.exists():
                lib_index = load_library_index(lib_index_path)

            # Determine which files to process
            if path.is_file():
                pptx_files = [path]
            else:
                if recurse:
                    pptx_files = list(path.glob("**/*.pptx"))
                else:
                    pptx_files = list(path.glob("*.pptx"))

            if not pptx_files:
                click.echo("No PPTX files found", err=True)
                sys.exit(1)

            # Build shared OCR budget (shared across all files in this run)
            if ocr:
                from worship_catalog.extractor import OcrBudget
                ocr_budget: OcrBudget | None = OcrBudget(
                    max_calls=None if unlimited_ocr else max_ocr_calls
                )
            else:
                ocr_budget = None

            _log.info("Starting import", extra={"path": str(path), "files": len(pptx_files)})
            total_songs = 0
            failed_files = 0
            for pptx_file in pptx_files:
                click.echo(f"Processing {pptx_file.name}...", err=False)

                try:
                    import_result = run_import(
                        database,
                        pptx_file,
                        library_index=lib_index or None,
                        ocr_budget=ocr_budget,
                        use_ocr=ocr,
                    )

                    total_songs += import_result.songs_imported
                    _log.info(
                        "File imported",
                        extra={
                            "file": pptx_file.name,
                            "songs": import_result.songs_imported,
                            "service_date": import_result.service_date,
                            "service_name": import_result.service_name,
                        },
                    )
                    click.echo(
                        f"  ✓ Imported {import_result.songs_imported} songs",
                        err=False,
                    )

                except Exception as e:
                    _log.error(
                        "File import failed",
                        extra={"file": pptx_file.name, "error": str(e)},
                    )
                    click.echo(f"  ✗ Error: {e}", err=True)
                    failed_files += 1
                    continue

        succeeded = len(pptx_files) - failed_files
        _log.info(
            "Import complete",
            extra={
                "total_songs": total_songs,
                "files": len(pptx_files),
                "failed": failed_files,
            },
        )
        if failed_files:
            click.echo(
                f"\nTotal: {total_songs} songs imported "
                f"({succeeded} succeeded, {failed_files} failed)",
                err=False,
            )
            sys.exit(1)
        else:
            click.echo(f"\nTotal: {total_songs} songs imported", err=False)
            sys.exit(0)

    except Exception as e:
        _log.exception("import error", extra={"error": str(e)})
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.group()
def report() -> None:
    """Generate reports from database."""
    pass


@report.command()
@click.option(
    "--from",
    "start_date",
    type=str,
    default=None,
    help="Start date (YYYY-MM-DD), defaults to showing all data",
)
@click.option(
    "--to",
    "end_date",
    type=str,
    default=None,
    help="End date (YYYY-MM-DD), defaults to showing all data",
)
@click.option(
    "--out",
    type=click.Path(),
    default="ccli_report.csv",
    help="Output CSV file",
)
@click.option(
    "--db",
    type=click.Path(),
    default="data/worship.db",
    help="Path to SQLite database",
)
def ccli(start_date: str, end_date: str, out: str, db: str) -> None:
    """Generate CCLI report for date range.

    Output CSV with song performances and reproduction types.
    If no date range specified, includes all data in database.
    """
    try:
        db_path = Path(db)

        # Use broad date range if not specified
        if not start_date:
            start_date = _REPORT_DATE_MIN
        if not end_date:
            end_date = _REPORT_DATE_MAX

        with Database(db_path) as database:
            # Query copy events
            events = database.query_copy_events(start_date, end_date)

        if not events:
            click.echo(f"No events found for {start_date} to {end_date}")
            sys.exit(0)

        # Write CSV
        output_path = Path(out)
        with open(output_path, "w", newline="") as f:
            writer = csv.writer(f)
            # Header
            writer.writerow(["Date", "Service", "Title", "CCLI#", "Reproduction Type", "Count"])

            for event in events:
                writer.writerow([
                    event["service_date"],
                    event["service_name"],
                    event["display_title"],
                    event.get("ccli_number", ""),
                    event["reproduction_type"],
                    event["count"],
                ])

        click.echo(f"Report written to {output_path}")
        sys.exit(0)

    except Exception as e:
        _log.exception("ccli report error", extra={"error": str(e)})
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@report.command()
@click.option(
    "--from",
    "start_date",
    type=str,
    default=None,
    help="Start date (YYYY-MM-DD), defaults to showing all data",
)
@click.option(
    "--to",
    "end_date",
    type=str,
    default=None,
    help="End date (YYYY-MM-DD), defaults to showing all data",
)
@click.option(
    "--out",
    type=click.Path(),
    default="stats_report.md",
    help="Output markdown file",
)
@click.option(
    "--db",
    type=click.Path(),
    default="data/worship.db",
    help="Path to SQLite database",
)
@click.option(
    "--all-songs",
    is_flag=True,
    help="Export all songs instead of only the top 20 most frequent",
)
@click.option(
    "--leader",
    type=str,
    default=None,
    help="Filter to services led by this song leader (partial match, case-insensitive)",
)
def stats(
    start_date: str, end_date: str, out: str, db: str, all_songs: bool, leader: str | None
) -> None:
    """Generate statistics report for date range.

    Output markdown with frequency tables and trends.
    If no date range specified, includes all data in database.
    """
    try:
        db_path = Path(db)

        # Use broad date range if not specified
        if not start_date:
            start_date = _REPORT_DATE_MIN
        if not end_date:
            end_date = _REPORT_DATE_MAX

        with Database(db_path) as database:
            # Delegate data computation to shared service (#167)
            data = compute_stats_data(database, start_date, end_date, leader, all_songs)

        services = data["services"]
        events: list[dict[str, object]] = data["events"]
        sorted_songs: list[tuple[str, int]] = data["sorted_songs"]
        song_credits: dict[str, str] = data["song_credits"]
        leader_breakdown: dict[str, list[tuple[str, int]]] = data["leader_breakdown"]
        leader_service_counts: dict[str, int] = data["leader_service_counts"]

        # Use actual DB min/max dates for the report header instead of wildcards
        if services:
            report_start = services[0]["service_date"]
            report_end = services[-1]["service_date"]
        else:
            report_start = start_date
            report_end = end_date

        # Write markdown
        output_path = Path(out)
        with open(output_path, "w") as f:
            f.write("# Song Statistics Report\n\n")
            f.write(f"**Period:** {report_start} to {report_end}\n\n")
            if leader:
                f.write(f"**Song Leader:** {leader}\n\n")

            f.write("## Summary\n\n")
            f.write(f"- Services: {len(services)}\n")
            f.write(f"- Unique Songs: {len(sorted_songs)}\n")
            f.write(f"- Total Song Performances: {data['total_performances']}\n")
            f.write(f"- Total Copy Events: {data['total_events']}\n\n")

            heading = "All Songs" if all_songs else "Most Frequent Songs"
            f.write(f"## {heading}\n\n")
            f.write("| Song | Credits | Count |\n")
            f.write("|------|---------|-------|\n")
            for song, count in sorted_songs:
                credits = song_credits.get(song, "")
                f.write(f"| {song} | {credits} | {count} |\n")

            if leader_breakdown:
                f.write("\n## By Song Leader\n\n")
                for ldr_name, ldr_songs in leader_breakdown.items():
                    service_count = leader_service_counts.get(ldr_name, 0)
                    plural = "s" if service_count != 1 else ""
                    f.write(f"### {ldr_name} ({service_count} service{plural})\n\n")
                    f.write("| Song | Count |\n")
                    f.write("|------|-------|\n")
                    for song_title, count in ldr_songs:
                        f.write(f"| {song_title} | {count} |\n")
                    f.write("\n")

            f.write("\n## Services\n\n")
            f.write("| Date | Service | Song Leader | Songs |\n")
            f.write("|------|---------|-------------|-------|\n")
            # Pre-index events by service_id to avoid O(n*m) scan (#281)
            songs_by_service: dict[object, set[object]] = {}
            for e in events:
                songs_by_service.setdefault(e["service_id"], set()).add(e["song_id"])
            for service in services:
                unique_songs = len(songs_by_service.get(service["id"], set()))
                svc_leader = service.get("song_leader") or ""
                f.write(
                    f"| {service['service_date']} | "
                    f"{service['service_name']} | {svc_leader} | {unique_songs} |\n"
                )

        click.echo(f"Report written to {output_path}")
        sys.exit(0)

    except Exception as e:
        _log.exception("stats report error", extra={"error": str(e)})
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.command(name="repair-credits")
@click.option(
    "--db",
    type=click.Path(),
    default="data/worship.db",
    help="Path to SQLite database",
)
@click.option(
    "--library-index",
    type=click.Path(),
    default="data/library_index.json",
    show_default=True,
    help="Path to scraped library index JSON (see: worship-catalog library index)",
)
@click.option(
    "--ocr",
    is_flag=True,
    help=(
        "Fall back to Claude Vision API for any songs not in the library index"
        " (requires ANTHROPIC_API_KEY)"
    ),
)
@click.option(
    "--max-ocr-calls",
    type=int,
    default=_DEFAULT_MAX_OCR_CALLS,
    show_default=True,
    help="Maximum Vision API calls for this run (ignored without --ocr)",
)
@click.option(
    "--unlimited-ocr",
    is_flag=True,
    help="Remove the OCR call cap (overrides --max-ocr-calls)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show which songs would be updated without writing to DB",
)
def repair_credits(
    db: str,
    library_index: str,
    ocr: bool,
    max_ocr_calls: int,
    unlimited_ocr: bool,
    dry_run: bool,
) -> None:
    """Repair missing credits for songs in the database.

    Uses the pre-scraped library index JSON by default. Two strategies:

    \b
    1. Library index (default): fast JSON lookup, no library mount needed.
    2. --ocr: Claude Vision API fallback for songs not in the index.

    To build or refresh the library index, run:
      worship-catalog library index --path tph_libarary/
    """
    try:
        from worship_catalog.extractor import _try_ocr_credits
        from worship_catalog.library import load_library_index, lookup_song_credits
        from worship_catalog.normalize import parse_credits
        from worship_catalog.pptx_reader import load_pptx, parse_all_slides

        db_path = Path(db)
        database = Database(db_path)
        database.connect()

        missing = database.query_songs_missing_credits()

        if not missing:
            _log.info("repair-credits: no songs with missing credits")
            click.echo("No songs with missing credits found.")
            database.close()
            sys.exit(0)
        # Note: repair-credits keeps manual connect/close because the loop
        # interleaves user output with DB writes over a long-running session.

        _log.info("repair-credits started", extra={"missing": len(missing), "dry_run": dry_run})
        click.echo(f"Found {len(missing)} song(s) with missing credits.")

        # Load library index from JSON (local override or bundled default)
        lib_index = {}
        lib_index_path = _resolve_library_index(library_index)
        if lib_index_path.exists():
            lib_index = load_library_index(lib_index_path)
        elif not ocr:
            click.echo(
                f"Library index not found at {library_index}. "
                f"Run: worship-catalog library index --path <library-dir>",
                err=True,
            )

        # Pre-flight: count songs that will need OCR (not found in library)
        ocr_budget = None
        if ocr:
            from worship_catalog.extractor import OcrBudget

            def _has_library_credits(canonical: str) -> bool:
                result = lookup_song_credits(canonical, lib_index) if lib_index else None
                return bool(result and any(result.values()))

            ocr_needed = sum(
                0 if _has_library_credits(row["canonical_title"]) else 1
                for row in missing
            )
            cap = "unlimited" if unlimited_ocr else str(max_ocr_calls)
            click.echo(
                f"{ocr_needed} song(s) will need OCR (~$0.003 each est.). "
                f"Processing up to {cap}."
            )
            ocr_budget = OcrBudget(max_calls=None if unlimited_ocr else max_ocr_calls)

        # Cache parsed slides per source file to avoid reloading the same PPTX (#293)
        _slide_cache: dict[str, list[Any]] = {}

        updated = 0
        for row in missing:
            title = row["display_title"]
            canonical = row["canonical_title"]
            click.echo(f"  {title}")

            credits = None

            # Strategy 1: Library index lookup
            if lib_index:
                credits = lookup_song_credits(canonical, lib_index)
                if credits and any(credits.values()):
                    click.echo("    [library] found")
                else:
                    credits = None
                    click.echo("    [library] not found", err=True)

            # Strategy 2: Vision OCR fallback
            if credits is None and ocr:
                if ocr_budget is not None and ocr_budget.is_capped:
                    click.echo(
                        f"    [ocr] skipped — call limit reached ({ocr_budget.max_calls})",
                        err=True,
                    )
                else:
                    source_file = row.get("source_file")
                    if source_file and Path(source_file).exists():
                        try:
                            if ocr_budget is not None and not ocr_budget.consume():
                                click.echo(
                                    "    [ocr] skipped — budget exhausted",
                                    err=True,
                                )
                                continue
                            # Reuse cached slides for the same source file (#293)
                            if source_file not in _slide_cache:
                                prs = load_pptx(source_file)
                                _slide_cache[source_file] = parse_all_slides(prs)
                            all_slides = _slide_cache[source_file]
                            song_slides = [
                                s for s in all_slides[1:]
                                if any(canonical in line.lower() for line in s.text.text_lines)
                            ]
                            ocr_text = _try_ocr_credits(song_slides) if song_slides else None
                            if ocr_text:
                                raw = parse_credits(ocr_text)
                                if any(raw.values()):
                                    credits = raw
                                    click.echo("    [ocr] found")
                                else:
                                    click.echo(
                                        f"    [ocr] no parseable credits: {ocr_text!r}",
                                        err=True,
                                    )
                                    if ocr_budget is not None:
                                        ocr_budget.refund()
                            else:
                                click.echo("    [ocr] no text returned", err=True)
                                if ocr_budget is not None:
                                    ocr_budget.refund()
                        except Exception as e:
                            click.echo(f"    [ocr] error: {e}", err=True)
                            if ocr_budget is not None:
                                ocr_budget.refund()
                    else:
                        click.echo("    [ocr] source file not found", err=True)

            if credits is None or not any(credits.values()):
                click.echo("    ✗ No credits found — skipping", err=True)
                continue

            words_by = credits.get("words_by")
            music_by = credits.get("music_by")
            arranger = credits.get("arranger")

            parts = []
            if words_by:
                parts.append(f"Words: {words_by}")
            if music_by and music_by != words_by:
                parts.append(f"Music: {music_by}")
            if arranger:
                parts.append(f"Arr: {arranger}")
            click.echo(f"    ✓ {', '.join(parts)}")

            if not dry_run:
                database.update_song_edition_credits(
                    song_id=row["song_id"],
                    words_by=words_by,
                    music_by=music_by,
                    arranger=arranger,
                )
                updated += 1
            else:
                updated += 1

        database.close()

        _log.info(
            "repair-credits complete",
            extra={"updated": updated, "missing": len(missing), "dry_run": dry_run},
        )
        if dry_run:
            click.echo(f"\nDry run: would update {updated} of {len(missing)} song(s).")
        else:
            click.echo(f"\nUpdated credits for {updated} song(s).")
        sys.exit(0)

    except Exception as e:
        _log.exception("repair-credits error", extra={"error": str(e)})
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.group()
def library() -> None:
    """Manage the TPH song library index."""
    pass


@library.command(name="index")
@click.option(
    "--path",
    type=click.Path(exists=True),
    required=True,
    help="Path to TPH song library directory",
)
@click.option(
    "--out",
    type=click.Path(),
    default="data/library_index.json",
    show_default=True,
    help="Output JSON file path",
)
def library_index_cmd(path: str, out: str) -> None:
    """Scrape the TPH library and save a portable credits index.

    Reads OLE metadata from all .ppt files in the library directory
    and writes a JSON index to disk. After running this once, import
    and repair-credits will use the JSON automatically without needing
    the library mounted.

    Example:
      worship-catalog library index --path tph_libarary/
    """
    try:
        from worship_catalog.library import save_library_index, scrape_library

        library_path = Path(path)
        out_path = Path(out)

        click.echo(f"Scanning {library_path} ...")
        index = scrape_library(library_path)
        click.echo(f"  {len(index)} songs with credits found.")

        save_library_index(index, out_path)
        click.echo(f"Index saved to {out_path}")
        sys.exit(0)

    except Exception as e:
        _log.exception("library index error", extra={"error": str(e)})
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.group()
def cleanup() -> None:
    """Data cleanup commands.

    Find and remove bad imports, orphaned songs, and duplicate services.
    """
    pass


@cleanup.command(name="delete-service")
@click.option(
    "--id",
    "service_id",
    type=int,
    default=None,
    help="Delete service by ID",
)
@click.option(
    "--date",
    "service_date",
    type=str,
    default=None,
    help="Delete services matching this date (YYYY-MM-DD)",
)
@click.option(
    "--name",
    "name_pattern",
    type=str,
    default=None,
    help="Filter by service name pattern (used with --date)",
)
@click.option(
    "--db",
    type=click.Path(),
    default="data/worship.db",
    help="Path to SQLite database",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be deleted without modifying the database",
)
@click.option(
    "--yes",
    is_flag=True,
    help="Skip confirmation prompt",
)
def delete_service(
    service_id: int | None,
    service_date: str | None,
    name_pattern: str | None,
    db: str,
    dry_run: bool,
    yes: bool,
) -> None:
    """Delete service(s) and all related data.

    Use --id to delete a specific service, or --date to delete all services
    matching a date (optionally filtered by --name pattern).
    """
    if service_id is None and service_date is None:
        click.echo("Error: must provide --id or --date", err=True)
        sys.exit(1)

    try:
        db_path = Path(db)

        with Database(db_path) as database:
            services_to_delete: list[dict[str, Any]] = []

            if service_id is not None:
                svc = database.query_service_by_id(service_id)
                if svc is None:
                    click.echo(f"Error: service {service_id} not found", err=True)
                    sys.exit(1)
                services_to_delete = [svc]
            else:
                assert service_date is not None  # guaranteed by the check above
                services_to_delete = database.query_services_by_date(
                    service_date, name_pattern=name_pattern
                )
                if not services_to_delete:
                    click.echo(
                        f"Error: no services found for date {service_date}"
                        + (f" with name matching '{name_pattern}'" if name_pattern else ""),
                        err=True,
                    )
                    sys.exit(1)

            # Show what will be deleted
            click.echo(f"{'Would delete' if dry_run else 'Deleting'} "
                        f"{len(services_to_delete)} service(s):")
            for svc in services_to_delete:
                click.echo(
                    f"  ID={svc['id']}  {svc['service_date']}  "
                    f"{svc['service_name']}  hash={svc['source_hash']}"
                )

            if dry_run:
                click.echo("\nDry run — no changes made.")
                sys.exit(0)

            if not yes:
                click.confirm("Proceed?", abort=True)

            for svc in services_to_delete:
                database.delete_service_data(int(svc["id"]))
                _log.info(
                    "Deleted service",
                    extra={"service_id": svc["id"], "date": svc["service_date"]},
                )

        click.echo(f"Deleted {len(services_to_delete)} service(s).")
        sys.exit(0)

    except click.Abort:
        click.echo("\nAborted.")
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        _log.exception("cleanup delete-service error", extra={"error": str(e)})
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cleanup.command(name="orphaned-songs")
@click.option(
    "--db",
    type=click.Path(),
    default="data/worship.db",
    help="Path to SQLite database",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be deleted without modifying the database",
)
@click.option(
    "--yes",
    is_flag=True,
    help="Skip confirmation prompt",
)
def orphaned_songs(db: str, dry_run: bool, yes: bool) -> None:
    """Find and remove songs with 0 performances.

    Identifies songs that have no service_songs rows (orphaned after service
    deletion) and removes them along with their editions and copy_events.
    """
    try:
        db_path = Path(db)

        with Database(db_path) as database:
            orphans = database.query_orphaned_songs()

            if not orphans:
                click.echo("No orphaned songs found.")
                sys.exit(0)

            click.echo(f"Found {len(orphans)} orphaned song(s):")
            for song in orphans:
                click.echo(f"  ID={song['song_id']}  {song['display_title']}")

            if dry_run:
                click.echo(f"\nDry run — would remove {len(orphans)} song(s).")
                sys.exit(0)

            if not yes:
                click.confirm("Proceed?", abort=True)

            for song in orphans:
                database.delete_song(int(song["song_id"]))
                _log.info(
                    "Deleted orphaned song",
                    extra={"song_id": song["song_id"], "title": song["display_title"]},
                )

        click.echo(f"Removed {len(orphans)} orphaned song(s).")
        sys.exit(0)

    except click.Abort:
        click.echo("\nAborted.")
        sys.exit(1)
    except SystemExit:
        raise
    except Exception as e:
        _log.exception("cleanup orphaned-songs error", extra={"error": str(e)})
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cleanup.command(name="find-duplicates")
@click.option(
    "--db",
    type=click.Path(),
    default="data/worship.db",
    help="Path to SQLite database",
)
def find_duplicates(db: str) -> None:
    """List services with same date+name but different source hash.

    Helps identify duplicate imports caused by modified files being
    re-imported (different hash creates a second service row).
    """
    try:
        db_path = Path(db)

        with Database(db_path) as database:
            dupes = database.query_duplicate_services()

        if not dupes:
            click.echo("No duplicate services found.")
            sys.exit(0)

        # Group by (date, name)
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for svc in dupes:
            key = (str(svc["service_date"]), str(svc["service_name"]))
            groups.setdefault(key, []).append(svc)

        click.echo(f"Found {len(groups)} group(s) of duplicate services:\n")
        for (date, name), svcs in groups.items():
            click.echo(f"  {date}  {name}  ({len(svcs)} copies)")
            for svc in svcs:
                click.echo(f"    ID={svc['id']}  hash={svc['source_hash']}")

        sys.exit(0)

    except SystemExit:
        raise
    except Exception as e:
        _log.exception("cleanup find-duplicates error", extra={"error": str(e)})
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
