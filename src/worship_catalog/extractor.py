"""Orchestrate song extraction from PPTX files."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from worship_catalog.normalize import (
    _SCRIPTURE_RE,
    canonicalize_title,
    detect_publisher,
    parse_credits,
    select_best_title,
    strip_title_prefix,
)
from worship_catalog.ocr import extract_credits_via_vision
from worship_catalog.pptx_reader import (
    Slide,
    compute_file_hash,
    extract_service_metadata,
    load_pptx,
    parse_all_slides,
)


@dataclass
class OcrBudget:
    """Call cap for the Claude Vision API during a single extraction run.

    Pass an instance to :func:`extract_songs` so that the number of
    Vision API calls is bounded.  ``max_calls=None`` means unlimited.
    """

    max_calls: int | None
    calls_made: int = 0

    def consume(self) -> bool:
        """Attempt to use one OCR call.

        Returns True if the call is allowed (and increments the counter),
        False if the budget is already exhausted.
        """
        if self.max_calls is not None and self.calls_made >= self.max_calls:
            return False
        self.calls_made += 1
        return True

    def refund(self) -> None:
        """Undo one consume() call (used when OCR returns nothing useful)."""
        if self.calls_made > 0:
            self.calls_made -= 1

    @property
    def is_capped(self) -> bool:
        """True if the budget has been exhausted."""
        return self.max_calls is not None and self.calls_made >= self.max_calls

    @property
    def remaining(self) -> int | None:
        """Remaining calls allowed, or None if unlimited."""
        if self.max_calls is None:
            return None
        return max(0, self.max_calls - self.calls_made)


@dataclass
class SongOccurrence:
    """A song occurrence within a service."""

    ordinal: int
    """Order in service (1-indexed)."""
    canonical_title: str
    """Normalized lowercase title."""
    display_title: str
    """Original casing as first seen."""
    publisher: str | None = None
    """Publisher (Paperless Hymnal, Taylor Publications, etc.)."""
    words_by: str | None = None
    """Composer(s) of lyrics."""
    music_by: str | None = None
    """Composer(s) of music."""
    arranger: str | None = None
    """Arranger name."""
    first_slide_index: int | None = None
    """Index of first slide containing this song."""
    last_slide_index: int | None = None
    """Index of last slide containing this song."""
    slide_count: int = 0
    """Number of slides containing this song."""


@dataclass
class ExtractionResult:
    """Result of extracting songs from a PPTX file."""

    filename: str
    file_hash: str
    service_date: str | None
    service_name: str | None
    song_leader: str | None
    preacher: str | None
    sermon_title: str | None
    songs: list[SongOccurrence] = field(default_factory=list)
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    """List of extraction anomalies and low-confidence items."""


def extract_songs(
    file_path: Path | str,
    use_ocr: bool = False,
    ocr_budget: OcrBudget | None = None,
) -> ExtractionResult:
    """
    Extract songs from a PPTX file.

    Process:
    1. Load and parse all slides
    2. Extract service metadata
    3. Identify song slides
    4. Group by canonical title
    5. Extract credits (with optional Vision OCR fallback)
    6. Return normalized results

    Args:
        file_path: Path to the PPTX file
        use_ocr: If True, use Claude Vision API to extract credits from image-only slides
        ocr_budget: Optional call cap; if None and use_ocr is True, calls are unlimited
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
        song = _create_song_occurrence(
            ordinal, canonical, group, use_ocr=use_ocr, ocr_budget=ocr_budget
        )
        songs.append(song)

    # Create result
    result = ExtractionResult(
        filename=file_path.name,
        file_hash=compute_file_hash(file_path),
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
    current_canonical: str | None = None
    current_group: list[Slide] = []
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
                "lesson",
                "scripture reading",
                "announcements",
            ]
        ):
            continue

        # Check if this starts a new song or continues current
        if canonical != current_canonical:
            if _is_song_title_slide(slide):
                # New song - save current group if exists and has valid title
                if current_group and current_canonical:
                    groups.append((current_canonical, current_group))
                # Start new group
                current_canonical = canonical
                current_group = [slide]
            else:
                # Slide has text but no publisher/section-prefix marker - not a song title slide.
                # Add to current group (if any) to avoid creating spurious song entries.
                if current_group:
                    current_group.append(slide)
        else:
            # Continue current song
            current_group.append(slide)

    # Save final group if valid
    if current_group and current_canonical:
        groups.append((current_canonical, current_group))

    return groups


def _is_song_title_slide(slide: Slide) -> bool:
    """
    Return True if this slide is allowed to start a new song group.

    A slide qualifies if it has:
    - A publisher marker (PaperlessHymnal.com, Taylor Publications), OR
    - A line with a recognizable section prefix (c–, 1–, Verse, Chorus, etc.)

    This prevents devotional/sermon prose slides from being mistaken for song starts.
    """
    combined = " ".join(slide.text.text_lines).lower()
    if any(
        marker in combined
        for marker in ["paperlesshymnal", "taylor publications", "presentation ©"]
    ):
        return True
    for line in slide.text.text_lines:
        stripped = strip_title_prefix(line)
        if stripped != line.strip() and stripped:
            return True
    return False


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
                "lesson",
                "scripture reading",
                "announcements",
            ]
        ):
            continue

        # Skip very long lines (likely lyrics)
        if len(line) > 120:
            continue

        # Skip scripture references (e.g., "John 3:16", "1 Peter 1:3-4")
        if _SCRIPTURE_RE.match(line):
            continue

        candidates.append(line)

    return candidates


def _create_song_occurrence(
    ordinal: int,
    canonical_title: str,
    slides: list[Slide],
    use_ocr: bool = False,
    ocr_budget: OcrBudget | None = None,
) -> SongOccurrence:
    """
    Create a song occurrence from grouped slides.

    Extracts credits and metadata from all slides in group.
    If use_ocr is True and no credits are found via text, falls back to
    Claude Vision API on the first slide's image, subject to ocr_budget.
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

    # Extract credits from text
    credits = parse_credits(all_text)

    # OCR fallback: if no credits found and first slide has an image, try Vision API.
    # Budget is consumed only when the call returns useful text; it is refunded on
    # failure so that transient errors or image-less slides don't waste quota.
    if use_ocr and not any([
        credits.get("words_by"), credits.get("music_by"), credits.get("arranger"),
    ]):
        if ocr_budget is None or ocr_budget.consume():
            ocr_text = _try_ocr_credits(slides)
            if ocr_text:
                credits = parse_credits(ocr_text)
            elif ocr_budget is not None:
                ocr_budget.refund()

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


def _try_ocr_credits(slides: list[Slide]) -> str | None:
    """
    Attempt to extract credits text from the first image on the first slide
    using Claude Vision API.

    Returns raw credits text string, or None if OCR fails or yields nothing.
    """
    if not slides:
        return None

    # Use the first slide's first image blob
    first_slide = slides[0]
    if not first_slide.images:
        return None

    blob = first_slide.images[0].blob
    if not blob:
        return None

    try:
        return extract_credits_via_vision(blob)
    except Exception:
        return None
