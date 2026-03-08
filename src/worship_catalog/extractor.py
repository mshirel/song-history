"""Orchestrate song extraction from PPTX files."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from worship_catalog.normalize import (
    canonicalize_title,
    detect_publisher,
    parse_credits,
    select_best_title,
    strip_title_prefix,
)
from worship_catalog.pptx_reader import (
    Slide,
    extract_service_metadata,
    load_pptx,
    parse_all_slides,
)


@dataclass
class SongOccurrence:
    """A song occurrence within a service."""

    ordinal: int
    """Order in service (1-indexed)."""
    canonical_title: str
    """Normalized lowercase title."""
    display_title: str
    """Original casing as first seen."""
    publisher: Optional[str] = None
    """Publisher (Paperless Hymnal, Taylor Publications, etc.)."""
    words_by: Optional[str] = None
    """Composer(s) of lyrics."""
    music_by: Optional[str] = None
    """Composer(s) of music."""
    arranger: Optional[str] = None
    """Arranger name."""
    first_slide_index: Optional[int] = None
    """Index of first slide containing this song."""
    last_slide_index: Optional[int] = None
    """Index of last slide containing this song."""
    slide_count: int = 0
    """Number of slides containing this song."""


@dataclass
class ExtractionResult:
    """Result of extracting songs from a PPTX file."""

    filename: str
    file_hash: str
    service_date: Optional[str]
    service_name: Optional[str]
    song_leader: Optional[str]
    preacher: Optional[str]
    sermon_title: Optional[str]
    songs: list[SongOccurrence] = field(default_factory=list)
    anomalies: list[dict] = field(default_factory=list)
    """List of extraction anomalies and low-confidence items."""


def extract_songs(file_path: Path | str) -> ExtractionResult:
    """
    Extract songs from a PPTX file.

    Process:
    1. Load and parse all slides
    2. Extract service metadata
    3. Identify song slides
    4. Group by canonical title
    5. Extract credits
    6. Return normalized results
    """
    file_path = Path(file_path)

    # Step 1: Load presentation
    prs = load_pptx(file_path)
    slides = parse_all_slides(prs)

    # Step 2: Extract metadata
    if slides:
        metadata = extract_service_metadata(slides[0], file_path.name)
    else:
        metadata = None

    # Step 3: Identify and group song slides (skip first slide which is metadata)
    song_groups = _group_song_slides(slides[1:] if slides else [])

    # Step 4: Convert groups to song occurrences
    songs = []
    for ordinal, (canonical, group) in enumerate(song_groups, 1):
        song = _create_song_occurrence(ordinal, canonical, group)
        songs.append(song)

    # Create result
    result = ExtractionResult(
        filename=file_path.name,
        file_hash="",  # TODO: compute hash
        service_date=metadata.date if metadata else None,
        service_name=metadata.service_name if metadata else None,
        song_leader=metadata.song_leader if metadata else None,
        preacher=metadata.preacher if metadata else None,
        sermon_title=metadata.sermon_title if metadata else None,
        songs=songs,
    )

    return result


def _group_song_slides(slides: list[Slide]) -> list[tuple[str, list[Slide]]]:
    """
    Group consecutive slides by canonical song title.

    Returns list of (canonical_title, [slides]) tuples in order.
    Skips groups with empty canonical titles.

    Handles gap detection: if we encounter many consecutive slides with zero text
    (image-only slides), we assume the song has ended and close the group.
    """
    if not slides:
        return []

    groups = []
    current_canonical = None
    current_group = []
    no_text_streak = 0  # Track consecutive slides with no text

    for slide in slides:
        # Extract title candidates from slide
        title_candidates = _extract_title_candidates(slide)

        if not title_candidates:
            # Check if this slide has any text at all
            has_text = bool(slide.text.text_lines)

            if not has_text:
                # Increment no-text streak
                no_text_streak += 1

                # If we've seen 5+ slides with no text, close current group
                # (likely transitioned from song to sermon/presentation)
                if no_text_streak >= 5 and current_group and current_canonical:
                    groups.append((current_canonical, current_group))
                    current_canonical = None
                    current_group = []
                    continue
            else:
                # Reset streak if this slide has text (even if no title)
                no_text_streak = 0

            # Add to current group if exists (but only if not breaking from long text gap)
            if current_group and no_text_streak < 5:
                current_group.append(slide)
            continue

        # Reset streak when we find a title
        no_text_streak = 0

        # Get best candidate and canonicalize
        best_title = select_best_title(title_candidates)
        if not best_title:
            continue

        canonical = canonicalize_title(best_title)

        # Skip empty canonical titles
        if not canonical or not canonical.strip():
            continue

        # Skip giving/offering/communion content at canonical level
        canonical_lower = canonical.lower()
        if any(
            marker in canonical_lower
            for marker in [
                "give online",
                "text give",
                "giving",
                "offering",
                "communion",
                "tithe",
                "donation",
            ]
        ):
            continue

        stripped = strip_title_prefix(best_title)

        # Check if this starts a new song or continues current
        if canonical != current_canonical:
            # New song - save current group if exists and has valid title
            if current_group and current_canonical:
                groups.append((current_canonical, current_group))

            # Start new group
            current_canonical = canonical
            current_group = [slide]
        else:
            # Continue current song
            current_group.append(slide)

    # Save final group if valid
    if current_group and current_canonical:
        groups.append((current_canonical, current_group))

    return groups


def _extract_title_candidates(slide: Slide) -> list[str]:
    """
    Extract potential title lines from slide text.

    Strategy:
    - Collect all non-empty text lines
    - Filter out footer/copyright markers
    - Filter out very short lines (single char or just punctuation)
    - Return non-empty candidates
    """
    candidates = []

    for line in slide.text.text_lines:
        line = line.strip()
        if not line:
            continue

        # Skip single character or pure punctuation
        if len(line) <= 1 or all(c in ".,;:-'" for c in line):
            continue

        # Skip footer/copyright lines and non-song content
        lower = line.lower()
        if any(
            marker in lower
            for marker in [
                "copyright",
                "all rights",
                "permission",
                "paperlesshymnal",
                "taylor publications",
                "presentation ©",
                "admin",
                # Skip giving/offering/communion content
                "give online",
                "text give",
                "giving",
                "offering",
                "communion",
                "tithe",
                "donation",
                "giving online",
            ]
        ):
            continue

        # Skip very long lines (likely lyrics)
        if len(line) > 120:
            continue

        candidates.append(line)

    return candidates


def _create_song_occurrence(
    ordinal: int, canonical_title: str, slides: list[Slide]
) -> SongOccurrence:
    """
    Create a song occurrence from grouped slides.

    Extracts credits and metadata from all slides in group.
    """
    # Extract display title from first slide with text
    display_title = ""
    for slide in slides:
        candidates = _extract_title_candidates(slide)
        if candidates:
            best = select_best_title(candidates)
            if best:
                display_title = strip_title_prefix(best)
                break

    # Combine all text from group to extract credits
    all_text = "\n".join(
        "\n".join(slide.text.text_lines) for slide in slides
    )

    # Extract credits
    credits = parse_credits(all_text)

    # Detect publisher
    publisher = detect_publisher(all_text)

    # Get slide range
    first_index = slides[0].index if slides else None
    last_index = slides[-1].index if slides else None

    return SongOccurrence(
        ordinal=ordinal,
        canonical_title=canonical_title,
        display_title=display_title or canonical_title,
        publisher=publisher,
        words_by=credits.get("words_by"),
        music_by=credits.get("music_by"),
        arranger=credits.get("arranger"),
        first_slide_index=first_index,
        last_slide_index=last_index,
        slide_count=len(slides),
    )
