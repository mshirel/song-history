"""PPTX file reading and slide parsing."""

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pptx import Presentation

logger = logging.getLogger(__name__)

_HASH_CHUNK_SIZE: int = 4096
# python-pptx shape type integer for Picture shapes (MSO_SHAPE_TYPE.PICTURE == 13)
_PPTX_PICTURE_SHAPE_TYPE: int = 13


@dataclass
class SlideText:
    """Text extracted from a slide."""
    text_lines: list[str]
    """All text lines from text frames and table cells."""


@dataclass
class SlideImage:
    """Image/picture information."""
    shape_id: int
    """Unique identifier for the shape."""
    blob: bytes | None = None
    """Raw image bytes, if extracted."""


@dataclass
class Slide:
    """Parsed slide data."""
    index: int
    """0-based slide index in presentation."""
    hidden: bool
    """Whether slide is marked as hidden."""
    text: SlideText
    """Extracted text content."""
    images: list[SlideImage]
    """Picture/image shapes on slide."""


@dataclass
class ServiceMetadata:
    """Service metadata from presentation."""
    date: str | None
    """ISO format date (YYYY-MM-DD)."""
    service_name: str | None
    """Service name (e.g., 'Morning Worship')."""
    song_leader: str | None
    """Song leader name."""
    preacher: str | None
    """Preacher name."""
    sermon_title: str | None
    """Sermon title."""


def compute_file_hash(file_path: Path | str) -> str:
    """Compute SHA256 hash of file."""
    file_path = Path(file_path)
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(_HASH_CHUNK_SIZE), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def load_pptx(file_path: Path | str) -> Presentation:  # type: ignore[valid-type]
    """Load a PPTX file."""
    return Presentation(file_path)  # type: ignore[arg-type]


def extract_metadata_from_file(file_path: Path | str) -> dict[str, str]:
    """Extract core metadata from PPTX file path and structure."""
    file_path = Path(file_path)
    return {
        "filename": file_path.name,
        "file_hash": compute_file_hash(file_path),
    }


def is_slide_hidden(slide: Any) -> bool:
    """Check if slide has hidden attribute set."""
    try:
        # Access the slide's XML to check the show attribute
        slide_elem = slide.element
        return bool(slide_elem.get("show") == "0")
    except (AttributeError, KeyError):
        return False


def extract_text_from_slide(slide: Any) -> SlideText:
    """Extract all text from a slide's text frames and tables."""
    text_lines = []

    # Extract from text frames
    for shape in slide.shapes:
        if hasattr(shape, "text_frame"):
            for paragraph in shape.text_frame.paragraphs:
                text = paragraph.text.strip()
                if text:
                    text_lines.append(text)

        # Extract from tables
        if shape.has_table:
            table = shape.table
            for row in table.rows:
                for cell in row.cells:
                    cell_text = cell.text.strip()
                    if cell_text:
                        text_lines.append(cell_text)

    return SlideText(text_lines=text_lines)


def extract_images_from_slide(slide: Any) -> list[SlideImage]:
    """Extract image/picture shape information from slide, including raw bytes."""
    images = []

    for shape in slide.shapes:
        if shape.shape_type == _PPTX_PICTURE_SHAPE_TYPE:
            try:
                blob = shape.image.blob
            except Exception:
                logger.warning(
                    "Failed to extract blob from shape %s — returning blob=None",
                    shape.shape_id,
                    exc_info=True,
                )
                blob = None
            images.append(SlideImage(shape_id=shape.shape_id, blob=blob))

    return images


def parse_slide(slide: Any, index: int) -> Slide:
    """Parse a single slide into structured format."""
    return Slide(
        index=index,
        hidden=is_slide_hidden(slide),
        text=extract_text_from_slide(slide),
        images=extract_images_from_slide(slide),
    )


def parse_all_slides(prs: Presentation) -> list[Slide]:  # type: ignore[valid-type]
    """Parse all slides from presentation."""
    slides = []
    for i, slide in enumerate(prs.slides):  # type: ignore[attr-defined]
        slides.append(parse_slide(slide, i))
    return slides


def extract_metadata_from_table_slide(slide_text_lines: list[str]) -> ServiceMetadata:
    """
    Extract service metadata from a table slide.

    Expected format: alternating key-value pairs (may have header row like "Service Data").
    """
    result = ServiceMetadata(
        date=None,
        service_name=None,
        song_leader=None,
        preacher=None,
        sermon_title=None,
    )

    if not slide_text_lines:
        return result

    # Skip first line if it's a header
    start_idx = 0
    if slide_text_lines[0].lower() in ("service data", "metadata", "service info"):
        start_idx = 1

    # Convert to dict (assumes alternating key-value pairs)
    i = start_idx
    metadata_dict = {}
    while i < len(slide_text_lines) - 1:
        key = slide_text_lines[i].lower().strip()
        value = slide_text_lines[i + 1].strip()
        if value:  # Only store non-empty values
            metadata_dict[key] = value
        i += 2

    # Map to result
    if "date" in metadata_dict:
        result.date = metadata_dict["date"]
    if "service" in metadata_dict:
        result.service_name = metadata_dict["service"]
    if "song leader" in metadata_dict:
        result.song_leader = metadata_dict["song leader"]
    if "preacher" in metadata_dict:
        result.preacher = metadata_dict["preacher"]
    if "sermon title" in metadata_dict:
        result.sermon_title = metadata_dict["sermon title"]

    return result


def parse_filename_for_metadata(filename: str) -> ServiceMetadata:
    """
    Fallback: parse metadata from filename pattern like 'AM Worship 2026.02.15.pptx'.

    Expected pattern:
    - AM Worship YYYY.MM.DD.pptx → Morning Worship, date
    - PM Worship YYYY.MM.DD.pptx → Evening Worship, date
    """
    import re

    result = ServiceMetadata(
        date=None,
        service_name=None,
        song_leader=None,
        preacher=None,
        sermon_title=None,
    )

    # Pattern: (AM|PM) Worship YYYY.MM.DD — accepts underscores and job_id prefixes (#265)
    match = re.search(r"([AP]M)[\s_]+Worship[\s_]+(\d{4})\.(\d{2})\.(\d{2})", filename)
    if match:
        am_pm, year, month, day = match.groups()
        result.service_name = "Morning Worship" if am_pm == "AM" else "Evening Worship"
        result.date = f"{year}-{month}-{day}"

    return result


def extract_service_metadata(
    first_slide: Slide, filename: str
) -> ServiceMetadata:
    """
    Extract service metadata from presentation.

    Strategy:
    1. Try to parse structured metadata from first slide table
    2. Fallback to filename parsing
    3. Return result with None for missing fields
    """
    # Try table-based extraction first
    metadata = ServiceMetadata(
        date=None, service_name=None, song_leader=None, preacher=None, sermon_title=None,
    )
    if first_slide.text.text_lines:
        metadata = extract_metadata_from_table_slide(first_slide.text.text_lines)

    # Fill any None fields from filename fallback (#169)
    if metadata.date is None or metadata.service_name is None:
        fallback = parse_filename_for_metadata(filename)
        if metadata.date is None:
            metadata.date = fallback.date
        if metadata.service_name is None:
            metadata.service_name = fallback.service_name

    return metadata
