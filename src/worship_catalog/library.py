"""TPH library lookup — read song credits from OLE metadata in .ppt files."""

import json
import re
import subprocess
from pathlib import Path
from typing import Optional

from worship_catalog.normalize import canonicalize_title

# Serialized index schema: {canonical_title: {words_by, music_by, arranger, display_title}}
LibraryIndex = dict[str, dict[str, Optional[str]]]

# Suffixes to strip when deriving a song title from a library filename.
# Order matters — strip longest/most specific first.
_FILENAME_SUFFIXES = [
    r"-PH-HD$",
    r"-PH20-HD$",
    r"-PH20$",
    r"-HD$",
    r"-PftL(?:_16x9)?$",
    r"_16[xX]9$",
    r"-SFP(?:_16x9)?$",
    r"-SotC(?:_16x9)?$",
    r"-Bulls(?:_16[xX]9)?$",
    r"-Zoe(?:_16x9)?$",
    r"-Young(?:_16x9)?$",
    r"-Paris(?:_16x9)?$",
    r"-[\w]+_16[xX]9$",   # generic "Name_16x9" arranger suffix
    r"\s*\([^)]*conflicted copy[^)]*\)$",  # Dropbox conflict copies
]


def scrape_library(library_path: Path) -> LibraryIndex:
    """
    Walk the library directory, read OLE metadata from each .ppt file,
    and return a fully-parsed credits index.

    Returns {canonical_title: {words_by, music_by, arranger, display_title}}.
    Prefers -PH-HD variants over -HD over plain _16x9.
    """
    # First pass: collect best file path per canonical title
    file_candidates: dict[str, list[tuple[int, Path]]] = {}

    for ppt_file in library_path.rglob("*.ppt"):
        if ppt_file.name.startswith("~"):
            continue
        stem = ppt_file.stem
        title = _stem_to_title(stem)
        if not title:
            continue
        canonical = canonicalize_title(title)
        if not canonical:
            continue
        priority = _file_priority(stem)
        if canonical not in file_candidates:
            file_candidates[canonical] = []
        file_candidates[canonical].append((priority, ppt_file, title))

    # Second pass: read OLE metadata from best file and parse credits
    index: LibraryIndex = {}
    for canonical, candidates in file_candidates.items():
        _, best_path, display_title = sorted(candidates, key=lambda x: x[0])[0]
        author = read_ppt_author(best_path)
        if not author:
            continue
        credits = parse_author_credits(author)
        if not any(credits.values()):
            continue
        index[canonical] = {
            "display_title": display_title,
            "words_by": credits.get("words_by"),
            "music_by": credits.get("music_by"),
            "arranger": credits.get("arranger"),
        }

    return index


def save_library_index(index: LibraryIndex, path: Path) -> None:
    """Write the library index to a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)


def load_library_index(path: Path) -> LibraryIndex:
    """Load a previously-scraped library index from a JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_library_index(library_path: Path) -> LibraryIndex:
    """Alias for scrape_library — builds index from a directory at runtime."""
    return scrape_library(library_path)


def _stem_to_title(stem: str) -> str:
    """Strip known suffixes from a filename stem to recover the song title."""
    title = stem
    for pattern in _FILENAME_SUFFIXES:
        title = re.sub(pattern, "", title, flags=re.IGNORECASE).strip()
    return title.strip()


def _file_priority(stem: str) -> int:
    """
    Lower number = higher priority (preferred).
    PH-HD is most representative of service deck format.
    """
    s = stem.lower()
    if "ph-hd" in s:
        return 0
    if "-hd" in s:
        return 1
    if "ph20" in s:
        return 2
    return 3


def read_ppt_author(ppt_path: Path) -> Optional[str]:
    """
    Extract the Author field from a .ppt file's OLE2 metadata using `file`.

    Returns the raw author string, or None if not found.
    """
    try:
        result = subprocess.run(
            ["file", str(ppt_path)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout
        # Pattern: "Author: <value>, <next_field>:"
        match = re.search(
            r"Author:\s*(.+?)(?:,\s*(?:Last Saved|Keywords|Revision|Name of Creating))",
            output,
        )
        if match:
            return match.group(1).strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def parse_author_credits(author: str) -> dict[str, Optional[str]]:
    """
    Parse the OLE Author field into words_by / music_by / arranger.

    Handles patterns like:
    - "Charles Brown"                              → words_by only
    - "Elizabeth Clephane/Frederick Maker"         → words_by / music_by
    - "Lynn DeShazo/Arr. R. Dan Dalzell"           → words_by / arranger
    - "Reuben Morgan, Ben Fielding, Arr. Ryan C."  → words_by / arranger
    - "Gilbert / Gilbert / F"                      → words_by / music_by (drop lone letter)
    """
    result: dict[str, Optional[str]] = {
        "words_by": None,
        "music_by": None,
        "arranger": None,
    }

    if not author or not author.strip():
        return result

    author = author.strip()

    # Split on "/" or ","
    # First check for arranger marker anywhere in the string
    arr_match = re.search(r"(?:,\s*|/\s*)Arr\.?\s+(.+)$", author, re.IGNORECASE)
    if arr_match:
        result["arranger"] = arr_match.group(1).strip()
        # Everything before the Arr. part is the composer(s)
        before_arr = author[: arr_match.start()].strip().rstrip(",/").strip()
        result["words_by"] = before_arr or None
        return result

    # No arranger — split on "/" into parts, drop lone single letters (key signatures)
    parts = [p.strip() for p in re.split(r"\s*/\s*", author)]
    parts = [p for p in parts if len(p) > 1 or p.isalpha() is False]
    # Filter out lone key letter like "F", "G", "A" (key signatures stored as Keywords)
    parts = [p for p in parts if not re.fullmatch(r"[A-G](?:\s*(?:Flat|Sharp|#|b))?", p, re.IGNORECASE)]

    if not parts:
        return result
    if len(parts) == 1:
        result["words_by"] = parts[0]
    elif len(parts) >= 2:
        result["words_by"] = parts[0]
        result["music_by"] = parts[1]

    return result


def lookup_song_credits(
    canonical_title: str,
    library_index: LibraryIndex,
) -> Optional[dict[str, Optional[str]]]:
    """
    Look up credits for a song by canonical title using the library index.

    Returns a credits dict (words_by, music_by, arranger), or None if not found.
    """
    entry = library_index.get(canonical_title)
    if not entry:
        return None
    return {
        "words_by": entry.get("words_by"),
        "music_by": entry.get("music_by"),
        "arranger": entry.get("arranger"),
    }
