"""Title normalization, candidate selection, and credit parsing."""

import re
from typing import Optional


def strip_title_prefix(line: str) -> str:
    """
    Strip verse/chorus/section indicators from the start of a title.

    Applies normalizations in order per spec:
    1. Numeric / chorus prefix with dash: ^\\s*([0-9]+|c)\\s*[-–]\\s*(.+)$
    2. Compound numbering: ^\\s*[A-Za-z]?\\d+(?:[-–]\\w+)*\\s*[-–]?\\s*(.+)$
    3. Named sections: ^\\s*(Verse|V|Chorus|...)\\s*\\d*\\w*\\s*[-–:]?\\s*(.+)$
    4. Lowercase tag: ^\\s*tag\\s+(.+)$

    Args:
        line: Raw text line potentially containing a prefix

    Returns:
        Normalized title with prefix stripped and whitespace normalized
    """
    stripped = line.strip()

    # 1. Strip numeric / chorus prefix with dash (e.g., "1 - Title", "c – Title")
    # Must have: number or 'c' + whitespace + dash + whitespace + title
    # (vs compound numbering which has NO spaces: "1-1" or "C-2")
    match = re.match(r'^\s*([0-9]+|c)\s+[-–]\s+(.+)$', stripped, re.IGNORECASE)
    if match:
        stripped = match.group(2).strip()
        return _normalize_whitespace(stripped)

    # 2. Strip compound numbering (e.g., "1-1 Title", "C-2 Title", "V1a – Title")
    # Restriction: prefix must be SHORT (2-4 chars) OR contain a dash
    # This avoids matching regular title words like "Amazing Grace"
    # Pattern: alphanumeric (1-4 chars, with optional dashes in middle)
    match = re.match(r'^\s*[\dA-Za-z][\dA-Za-z-]{0,3}\s*[-–]?\s*(.+)$', stripped)
    if match:
        # Additional validation: must either be digits or have a dash or be letter-digit pattern
        prefix_match = re.match(r'^\s*([\dA-Za-z][\dA-Za-z-]{0,3})', stripped)
        if prefix_match:
            prefix = prefix_match.group(1)
            # Accept if: has dash, starts with digit, or is letter+digits (like V1, C2, V1a)
            if '-' in prefix or prefix[0].isdigit() or re.match(r'^[A-Za-z]\d', prefix):
                stripped = match.group(1).strip()
                return _normalize_whitespace(stripped)

    # 3. Strip named sections (e.g., "Bridge1 Title", "Verse Title")
    # Only matches if FOLLOWED by whitespace + title (not if it's part of compound number)
    match = re.match(
        r'^\s*(Verse|V|Chorus|C|Refrain|R|Bridge|B|Tag|Intro|Outro|Coda|CODA|DS)\s*\d*\s*[-–:]?\s+(.+)$',
        stripped,
        re.IGNORECASE
    )
    if match:
        stripped = match.group(2).strip()
        return _normalize_whitespace(stripped)

    # 4. Strip lowercase tag (e.g., "tag Title")
    match = re.match(r'^\s*tag\s+(.+)$', stripped, re.IGNORECASE)
    if match:
        stripped = match.group(1).strip()
        return _normalize_whitespace(stripped)

    # No prefix detected, just normalize whitespace
    return _normalize_whitespace(stripped)


def _normalize_whitespace(text: str) -> str:
    """Normalize interior whitespace, trim ends."""
    return ' '.join(text.split()).strip()


def select_best_title(candidates: list[str]) -> Optional[str]:
    """
    Select the best title candidate from a list of lines.

    Strategy:
    1. Filter out invalid candidates (copyright, footer markers)
    2. Strip prefixes from each candidate
    3. If both prefixed and plain forms exist, prefer plain
    4. Select shortest valid title
    5. Return None if no valid candidates

    Args:
        candidates: List of text lines to evaluate

    Returns:
        Best title candidate, or None if no valid candidates found
    """
    if not candidates:
        return None

    # Filter out invalid candidates (copyright, footer, empty)
    valid = []
    for line in candidates:
        line = line.strip()
        if not line:
            continue
        if _is_invalid_line(line):
            continue
        valid.append(line)

    if not valid:
        return None

    # Normalize all candidates
    normalized = set()
    for candidate in valid:
        norm = strip_title_prefix(candidate)
        if norm:
            normalized.add(norm)

    if not normalized:
        return None

    # Prefer shorter titles
    return min(normalized, key=len)


def _is_invalid_line(line: str) -> bool:
    """Check if a line is a footer/copyright/invalid marker."""
    lower = line.lower()

    # Copyright markers
    if any(marker in lower for marker in [
        "copyright",
        "all rights reserved",
        "all rights reserved",
        "used by permission",
        "admin. by",
        "c/o",
    ]):
        return True

    # Publisher markers (treated as headers, not titles)
    if any(marker in lower for marker in [
        "paperlesshymnal.com",
        "taylor publications",
        "presentation ©",
    ]):
        return True

    # Very long lines are likely lyrics, not titles
    if len(line) > 120:
        return True

    return False


def canonicalize_title(title: str) -> str:
    """
    Canonicalize a title for deduplication.

    - Lowercase
    - Trim punctuation at ends
    - Normalize whitespace

    Args:
        title: Display title

    Returns:
        Canonical lowercase key
    """
    # Strip punctuation from ends
    title = title.strip()
    title = title.strip('\'"!?;:.,')

    # Lowercase
    title = title.lower()

    # Normalize whitespace
    title = _normalize_whitespace(title)

    return title


def parse_credits(text: str) -> dict[str, Optional[str]]:
    """
    Parse credit fields (Words/Music/Arranger) from slide text.

    Recognizes patterns like:
    - "Words and Music by: Twila Paris / Arr.: Ken Young"
    - "Words & Music: Traditional / Arr.: Pam Stephenson"
    - "Words by: ..., Music by: ..., Arrangement by: ..."

    Args:
        text: Raw text containing potential credit lines

    Returns:
        Dict with keys: words_by, music_by, arranger, other_credits
    """
    result: dict[str, Optional[str]] = {
        "words_by": None,
        "music_by": None,
        "arranger": None,
        "other_credits": None,
    }

    if not text:
        return result

    # Handle "Words and Music by:" / "Words & Music:"
    for pattern in [
        r'Words\s+(?:and|&)\s+Music\s*(?:by)?:\s*([^/\n]+?)(?:/|[\n]|$)',
        r'Words\s+and\s+Music\s*(?:by)?:\s*([^/\n]+?)(?:/|[\n]|$)',
        r'Words\s+&\s+Music\s*(?:by)?:\s*([^/\n]+?)(?:/|[\n]|$)',
    ]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            combined = match.group(1).strip()
            # Try to split if contains "/"
            if '/' in combined:
                parts = combined.split('/')
                result['words_by'] = parts[0].strip()
                result['music_by'] = parts[1].strip() if len(parts) > 1 else None
            else:
                # Assume same for both
                result['words_by'] = combined
                result['music_by'] = combined
            break

    # Handle standalone "Words by:"
    if not result['words_by']:
        match = re.search(r'Words\s+by:\s*([^/\n,]+)', text, re.IGNORECASE)
        if match:
            result['words_by'] = match.group(1).strip()

    # Handle standalone "Music by:"
    if not result['music_by']:
        match = re.search(r'Music\s+by:\s*([^/\n,]+)', text, re.IGNORECASE)
        if match:
            result['music_by'] = match.group(1).strip()

    # Handle "Arrangement by:" / "Arr:" / "Arr."
    for pattern in [
        r'Arrangement\s+by:\s*([^/\n]+?)(?:/|$)',
        r'Arr\.?:\s*([^/\n]+?)(?:/|$)',
    ]:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            result['arranger'] = match.group(1).strip()
            break

    # Capture remaining credit text
    remaining = text
    for key in ['words_by', 'music_by', 'arranger']:
        if result[key]:
            # Remove this credit from remaining text
            value = re.escape(result[key])
            pattern = (
                r'(?i)(words\s+(?:and|&)\s+music|words\s+by|music\s+by|'
                r'arr(?:angement)?\s+by).*?' + value
            )
            remaining = re.sub(pattern, '', remaining)

    remaining = remaining.strip()
    if remaining and len(remaining) > 5:
        result['other_credits'] = remaining

    return result


def detect_publisher(text: str) -> Optional[str]:
    """
    Detect publisher from slide text.

    - "PaperlessHymnal.com" → "Paperless Hymnal"
    - "Taylor Publications" or ("Presentation ©" and "Publications") → "Taylor Publications"
    - Otherwise None

    Args:
        text: Raw slide text

    Returns:
        Publisher name or None
    """
    if not text:
        return None

    lower = text.lower()

    # Check for PaperlessHymnal
    if "paperlesshymnal.com" in lower or "paperless hymnal" in lower:
        return "Paperless Hymnal"

    # Check for Taylor Publications
    if "taylor publications" in lower:
        return "Taylor Publications"

    # Check for "Presentation ©" + "Publications"
    if "presentation ©" in lower and "publications" in lower:
        return "Taylor Publications"

    return None
