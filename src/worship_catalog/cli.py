"""CLI interface for worship catalog."""

import importlib.resources
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import click


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

from worship_catalog.db import Database
from worship_catalog.extractor import extract_songs


@click.group()
@click.version_option()
def main():
    """Worship Slide Deck Song Catalog.

    Extract, organize, and track songs from worship presentation files.
    """
    pass


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
    help="Fall back to Claude Vision API for credits not found in library (requires ANTHROPIC_API_KEY)",
)
def import_cmd(
    pptx_or_folder: str,
    db: str,
    recurse: bool,
    non_interactive: bool,
    library_index: str,
    ocr: bool,
) -> None:
    """Import PPTX file(s) to database.

    Extracts song data and stores in SQLite database.
    If folder path provided, imports all PPTX files.
    """
    try:
        from worship_catalog.library import load_library_index, lookup_song_credits

        path = Path(pptx_or_folder)
        db_path = Path(db)
        database = Database(db_path)
        database.connect()
        database.init_schema()

        # Load library index from JSON if it exists (local override or bundled default)
        lib_index = {}
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

        total_songs = 0
        for pptx_file in pptx_files:
            click.echo(f"Processing {pptx_file.name}...", err=False)

            try:
                result = extract_songs(pptx_file, use_ocr=ocr)

                # Check for missing metadata
                needs_review = False
                if not result.service_date or not result.service_name:
                    if not non_interactive:
                        click.echo(
                            f"  ⚠️  Missing service metadata (date: {result.service_date}, "
                            f"name: {result.service_name})",
                            err=True,
                        )
                        needs_review = True
                    else:
                        click.echo(
                            f"  Skipping due to missing metadata",
                            err=True,
                        )
                        continue

                # Insert service
                from worship_catalog.pptx_reader import compute_file_hash

                service_hash = compute_file_hash(pptx_file)

                # Check if this service already exists (idempotency check)
                cursor = database.conn.cursor()
                cursor.execute(
                    """
                    SELECT id FROM services
                    WHERE service_date = ? AND service_name = ? AND source_hash = ?
                    """,
                    (result.service_date or "0000-00-00",
                     result.service_name or "Unknown",
                     service_hash),
                )
                existing_service = cursor.fetchone()

                # If it exists, delete old data for clean re-import (idempotent re-import)
                if existing_service:
                    existing_id = existing_service[0]
                    database.delete_service_data(existing_id)

                service_id = database.insert_or_update_service(
                    service_date=result.service_date or "0000-00-00",
                    service_name=result.service_name or "Unknown",
                    source_file=str(pptx_file),
                    source_hash=service_hash,
                    song_leader=result.song_leader,
                    preacher=result.preacher,
                    sermon_title=result.sermon_title,
                )

                # Insert songs and service songs
                for song in result.songs:
                    song_id = database.insert_or_get_song(
                        song.canonical_title,
                        song.display_title,
                    )

                    # Fill missing credits from library if available
                    words_by = song.words_by
                    music_by = song.music_by
                    arranger = song.arranger
                    if lib_index and not any([words_by, music_by, arranger]):
                        lib_credits = lookup_song_credits(song.canonical_title, lib_index)
                        if lib_credits:
                            words_by = lib_credits.get("words_by")
                            music_by = lib_credits.get("music_by")
                            arranger = lib_credits.get("arranger")

                    edition_id = None
                    if song.publisher or words_by or music_by or arranger:
                        edition_id = database.insert_or_get_song_edition(
                            song_id=song_id,
                            publisher=song.publisher,
                            words_by=words_by,
                            music_by=music_by,
                            arranger=arranger,
                        )

                    database.insert_service_song(
                        service_id=service_id,
                        song_id=song_id,
                        ordinal=song.ordinal,
                        song_edition_id=edition_id,
                        first_slide_index=song.first_slide_index,
                        last_slide_index=song.last_slide_index,
                        occurrences=1,
                    )

                    # Create copy events (default: projection and recording)
                    # Use insert_or_get to handle songs that appear multiple times in same service
                    database.insert_or_get_copy_event(
                        service_id=service_id,
                        song_id=song_id,
                        song_edition_id=edition_id,
                        reproduction_type="projection",
                        count=1,
                        reportable=True,
                    )

                    database.insert_or_get_copy_event(
                        service_id=service_id,
                        song_id=song_id,
                        song_edition_id=edition_id,
                        reproduction_type="recording",
                        count=1,
                        reportable=True,
                    )

                total_songs += len(result.songs)
                click.echo(
                    f"  ✓ Imported {len(result.songs)} songs"
                    + (" (review metadata)" if needs_review else ""),
                    err=False,
                )

            except Exception as e:
                click.echo(f"  ✗ Error: {e}", err=True)
                continue

        database.close()
        click.echo(f"\nTotal: {total_songs} songs imported", err=False)
        sys.exit(0)

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@main.group()
def report():
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
        database = Database(db_path)
        database.connect()

        # Use broad date range if not specified
        if not start_date:
            start_date = "0000-01-01"
        if not end_date:
            end_date = "9999-12-31"

        # Query copy events
        events = database.query_copy_events(start_date, end_date)

        if not events:
            click.echo(f"No events found for {start_date} to {end_date}")
            sys.exit(0)

        # Write CSV
        output_path = Path(out)
        with open(output_path, "w") as f:
            # Header
            f.write(
                "Date,Service,Title,CCLI#,Reproduction Type,Count\n"
            )

            # Group events for cleaner output
            current_date = None
            for event in events:
                if event["service_date"] != current_date:
                    current_date = event["service_date"]
                    f.write(f"\n# {event['service_date']} - {event['service_name']}\n")

                f.write(
                    f"{event['service_date']},"
                    f"{event['service_name']},"
                    f"{event['display_title']},"
                    f"{event.get('ccli_number', '')},"
                    f"{event['reproduction_type']},"
                    f"{event['count']}\n"
                )

        database.close()
        click.echo(f"Report written to {output_path}")
        sys.exit(0)

    except Exception as e:
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
def stats(start_date: str, end_date: str, out: str, db: str, all_songs: bool, leader: Optional[str]) -> None:
    """Generate statistics report for date range.

    Output markdown with frequency tables and trends.
    If no date range specified, includes all data in database.
    """
    try:
        db_path = Path(db)
        database = Database(db_path)
        database.connect()

        # Use broad date range if not specified
        if not start_date:
            start_date = "0000-01-01"
        if not end_date:
            end_date = "9999-12-31"

        # Query services (with optional leader filter) then scope events to those services
        services = database.query_services(start_date, end_date, song_leader=leader)
        service_ids = [s["id"] for s in services] if leader else None
        events = database.query_copy_events(start_date, end_date, service_ids=service_ids)

        # Use actual DB min/max dates for the report header instead of wildcards
        if services:
            report_start = services[0]["service_date"]
            report_end = services[-1]["service_date"]
        else:
            report_start = start_date
            report_end = end_date

        # Build statistics: count distinct services per song (not copy events,
        # which are doubled by projection + recording). Also collect credits.
        song_services: dict[str, set] = {}
        song_credits: dict[str, str] = {}
        for event in events:
            title = event["display_title"]
            if title not in song_services:
                song_services[title] = set()
            song_services[title].add(event["service_id"])
            # Collect credits (first non-null value seen wins)
            if title not in song_credits:
                parts = []
                if event.get("words_by"):
                    parts.append(f"Words: {event['words_by']}")
                if event.get("music_by") and event.get("music_by") != event.get("words_by"):
                    parts.append(f"Music: {event['music_by']}")
                if event.get("arranger"):
                    parts.append(f"Arr: {event['arranger']}")
                if parts:
                    song_credits[title] = ", ".join(parts)
        song_counts = {title: len(s) for title, s in song_services.items()}

        # Build per-leader breakdown (only when not already filtered to one leader)
        leader_breakdown: dict[str, list[tuple[str, int]]] = {}
        if not leader:
            service_leader_map = {s["id"]: (s.get("song_leader") or "Unknown") for s in services}
            ldr_song_services: dict[str, dict[str, set]] = {}
            for event in events:
                ldr = service_leader_map.get(event["service_id"], "Unknown")
                title = event["display_title"]
                ldr_song_services.setdefault(ldr, {}).setdefault(title, set()).add(
                    event["service_id"]
                )
            # Sort each leader's songs by count desc, then alpha; leaders by service count desc
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

        # Sort by count descending, then alphabetically by title
        sorted_songs = sorted(song_counts.items(), key=lambda x: (-x[1], x[0].lower()))

        # Write markdown
        output_path = Path(out)
        with open(output_path, "w") as f:
            f.write(f"# Song Statistics Report\n\n")
            f.write(f"**Period:** {report_start} to {report_end}\n\n")
            if leader:
                f.write(f"**Song Leader:** {leader}\n\n")

            f.write(f"## Summary\n\n")
            f.write(f"- Services: {len(services)}\n")
            f.write(f"- Unique Songs: {len(sorted_songs)}\n")
            f.write(f"- Total Song Performances: {sum(song_counts.values())}\n")
            f.write(f"- Total Copy Events: {len(events)}\n\n")

            heading = "All Songs" if all_songs else "Most Frequent Songs"
            songs_to_show = sorted_songs if all_songs else sorted_songs[:20]
            f.write(f"## {heading}\n\n")
            f.write(f"| Song | Credits | Count |\n")
            f.write(f"|------|---------|-------|\n")
            for song, count in songs_to_show:
                credits = song_credits.get(song, "")
                f.write(f"| {song} | {credits} | {count} |\n")

            if leader_breakdown:
                f.write(f"\n## By Song Leader\n\n")
                for ldr_name, ldr_songs in leader_breakdown.items():
                    service_count = sum(1 for s in services if (s.get("song_leader") or "Unknown") == ldr_name)
                    f.write(f"### {ldr_name} ({service_count} service{'s' if service_count != 1 else ''})\n\n")
                    f.write(f"| Song | Count |\n")
                    f.write(f"|------|-------|\n")
                    for song_title, count in ldr_songs:
                        f.write(f"| {song_title} | {count} |\n")
                    f.write(f"\n")

            f.write(f"\n## Services\n\n")
            f.write(f"| Date | Service | Song Leader | Songs |\n")
            f.write(f"|------|---------|-------------|-------|\n")
            for service in services:
                service_songs = [e for e in events if e["service_id"] == service["id"]]
                unique_songs = len(set(e["song_id"] for e in service_songs))
                svc_leader = service.get("song_leader") or ""
                f.write(
                    f"| {service['service_date']} | "
                    f"{service['service_name']} | {svc_leader} | {unique_songs} |\n"
                )

        database.close()
        click.echo(f"Report written to {output_path}")
        sys.exit(0)

    except Exception as e:
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
    help="Fall back to Claude Vision API for any songs not in the library index (requires ANTHROPIC_API_KEY)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show which songs would be updated without writing to DB",
)
def repair_credits(db: str, library_index: str, ocr: bool, dry_run: bool) -> None:
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
            click.echo("No songs with missing credits found.")
            database.close()
            sys.exit(0)

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
                    click.echo(f"    [library] found")
                else:
                    credits = None
                    click.echo(f"    [library] not found", err=True)

            # Strategy 2: Vision OCR fallback
            if credits is None and ocr:
                source_file = row.get("source_file")
                if source_file and Path(source_file).exists():
                    try:
                        prs = load_pptx(source_file)
                        all_slides = parse_all_slides(prs)
                        song_slides = [
                            s for s in all_slides[1:]
                            if any(canonical in line.lower() for line in s.text.text_lines)
                        ]
                        ocr_text = _try_ocr_credits(song_slides) if song_slides else None
                        if ocr_text:
                            raw = parse_credits(ocr_text)
                            if any(raw.values()):
                                credits = raw
                                click.echo(f"    [ocr] found")
                            else:
                                click.echo(f"    [ocr] no parseable credits: {ocr_text!r}", err=True)
                        else:
                            click.echo(f"    [ocr] no text returned", err=True)
                    except Exception as e:
                        click.echo(f"    [ocr] error: {e}", err=True)
                else:
                    click.echo(f"    [ocr] source file not found", err=True)

            if credits is None or not any(credits.values()):
                click.echo(f"    ✗ No credits found — skipping", err=True)
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

        if dry_run:
            click.echo(f"\nDry run: would update {updated} of {len(missing)} song(s).")
        else:
            click.echo(f"\nUpdated credits for {updated} song(s).")
        sys.exit(0)

    except Exception as e:
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
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
