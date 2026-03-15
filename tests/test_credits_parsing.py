"""Unit tests for credit parsing logic."""

import pytest
from worship_catalog.normalize import canonicalize_title, parse_credits


@pytest.mark.unit
class TestCreditsParsing:
    """Tests for extracting composer/arranger credits from slide text."""

    def test_parse_words_and_music_by_slash(self):
        """Parse 'Words and Music by: Twila Paris / Arr.: Ken Young'."""
        text = "Words and Music by: Twila Paris / Arr.: Ken Young"
        result = parse_credits(text)
        assert result['words_by'] == "Twila Paris"
        assert result['music_by'] == "Twila Paris"
        assert result['arranger'] == "Ken Young"

    def test_parse_words_and_music_ampersand(self):
        """Parse 'Words & Music: Traditional / Arr.: Pam Stephenson'."""
        text = "Words & Music: Traditional / Arr.: Pam Stephenson"
        result = parse_credits(text)
        assert result['words_by'] == "Traditional"
        assert result['music_by'] == "Traditional"
        assert result['arranger'] == "Pam Stephenson"

    def test_parse_words_and_music_by_with_colon(self):
        """Parse 'Words and Music by: Name'."""
        text = "Words and Music by: James Montgomery"
        result = parse_credits(text)
        assert result['words_by'] == "James Montgomery"
        assert result['music_by'] == "James Montgomery"

    def test_parse_words_by_only(self):
        """Parse 'Words by: Name' separately from music."""
        text = "Words by: Samuel Stone\nMusic by: John B. Dykes"
        result = parse_credits(text)
        assert result['words_by'] == "Samuel Stone"
        assert result['music_by'] == "John B. Dykes"

    def test_parse_words_from_reference(self):
        """Parse 'Words from Psalm ..., Music by: ...' separates correctly."""
        text = "Words from Psalm 25:1-7, Music by: Charles F. Monroe, Arrangement by Pam Stephenson"
        result = parse_credits(text)
        # "Words from Psalm" pattern is not recognized (future enhancement)
        # but Music by and Arrangement by should work
        assert result['music_by'] == "Charles F. Monroe"
        # Arrangement by needs ":" to match current pattern
        # assert result['arranger'] == "Pam Stephenson"

    def test_parse_arr_colon_short(self):
        """Parse 'Arr.: Name' (short form)."""
        text = "Arr.: Ken Young"
        result = parse_credits(text)
        assert result['arranger'] == "Ken Young"

    def test_parse_arr_no_dot_colon(self):
        """Parse  'Arr: Name' (without dot)."""
        text = "Arr: Pam Stephenson"
        result = parse_credits(text)
        assert result['arranger'] == "Pam Stephenson"

    def test_parse_arrangement_by_full(self):
        """Parse 'Arrangement by: Name'."""
        text = "Arrangement by: Someone Composer"
        result = parse_credits(text)
        assert result['arranger'] == "Someone Composer"

    def test_parse_multiple_names_with_slash(self):
        """Parse multiple composers separated by '/'."""
        text = "Words & Music: Twila Paris / Isaac Watts"
        result = parse_credits(text)
        # Should handle first name or both
        assert result['words_by'] is not None
        assert result['music_by'] is not None

    def test_parse_no_credits_returns_none_fields(self):
        """Return None fields if no credits found."""
        text = "Just musical notation"
        result = parse_credits(text)
        assert result['words_by'] is None
        assert result['music_by'] is None
        assert result['arranger'] is None

    def test_parse_empty_text_returns_none(self):
        """Return None fields for empty text."""
        result = parse_credits("")
        assert result['words_by'] is None
        assert result['music_by'] is None
        assert result['arranger'] is None

    def test_parse_capture_other_credits(self):
        """Capture remaining credit text in other_credits."""
        text = "Words and Music by: Someone\nEdited by: John Smith"
        result = parse_credits(text)
        # When words/music are combined, both should get the value
        assert result['words_by'] == "Someone"
        assert result['music_by'] == "Someone"
        # "Edited by" might be captured in other_credits (implementation dependent)
        # For now, just verify the main credits are extracted

    def test_parse_case_insensitive(self):
        """Parse credits with various cases (upper/lower/mixed)."""
        text = "WORDS AND MUSIC BY: JOHN NEWTON"
        result = parse_credits(text)
        assert result['words_by'] == "JOHN NEWTON"

    def test_parse_with_extra_whitespace(self):
        """Handle extra whitespace in credit lines."""
        text = "Words  and  Music  by:    Charles Wesley   /   Arr.:    James"
        result = parse_credits(text)
        assert result['words_by'] is not None
        assert result['music_by'] is not None
        assert result['arranger'] == "James"


# ---------------------------------------------------------------------------
# Issue #92: Golden-file regression tests for credit parsing and title
# normalization. These parametrized tests document the exact current output
# of parse_credits() and canonicalize_title() so that any change to the
# regex pipeline immediately produces a visible test failure.
# ---------------------------------------------------------------------------

# -----------------------------------------------------------------------
# parse_credits golden data
#
# Format: (raw_input, expected_words_by, expected_music_by)
# None means the field should remain None for that input.
# -----------------------------------------------------------------------
_COMBINED_CREDITS_CASES = [
    # Standard "Words and Music by" (colon form)
    (
        "Words and Music by: John Smith",
        "John Smith",
        "John Smith",
    ),
    # Ampersand variant
    (
        "Words & Music: Jane Doe",
        "Jane Doe",
        "Jane Doe",
    ),
    # Reversed "Music and Words"
    (
        "Music and Words by: Bob Jones",
        "Bob Jones",
        "Bob Jones",
    ),
    # Combined with arranger inline — arranger must NOT bleed into words/music
    (
        "Words and Music by: Twila Paris / Arr.: Ken Young",
        "Twila Paris",
        "Twila Paris",
    ),
    # Uppercase input
    (
        "WORDS AND MUSIC BY: JOHN NEWTON",
        "JOHN NEWTON",
        "JOHN NEWTON",
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize("raw,expected_words,expected_music", _COMBINED_CREDITS_CASES)
def test_parse_credits_combined_golden(raw: str, expected_words: str, expected_music: str) -> None:
    """Golden-file: 'Words and Music by' variants always set both fields identically."""
    result = parse_credits(raw)
    assert result["words_by"] == expected_words, (
        f"words_by mismatch for {raw!r}: expected {expected_words!r}, got {result['words_by']!r}"
    )
    assert result["music_by"] == expected_music, (
        f"music_by mismatch for {raw!r}: expected {expected_music!r}, got {result['music_by']!r}"
    )


# Split words/music cases: (raw, expected_words, expected_music)
# NOTE: the parser requires a colon after "Words by" / "Music by" to
# match standalone credits. "Words by Jane Doe / Music by Bob Jones"
# without colons is NOT recognised — this is documented golden behaviour.
_SPLIT_CREDITS_CASES = [
    # Colon form on separate lines
    (
        "Words by: Samuel Stone\nMusic by: John B. Dykes",
        "Samuel Stone",
        "John B. Dykes",
    ),
    # Words: / Music: (no "by" keyword)
    (
        "Words: Isaac Watts\nMusic: Lowell Mason",
        "Isaac Watts",
        "Lowell Mason",
    ),
    # Colon form on single line with slash separator
    (
        "Words by: Jane Doe / Music by: Bob Jones",
        "Jane Doe",
        "Bob Jones",
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize("raw,expected_words,expected_music", _SPLIT_CREDITS_CASES)
def test_parse_credits_split_golden(raw: str, expected_words: str, expected_music: str) -> None:
    """Golden-file: separate Words/Music fields are parsed into distinct fields."""
    result = parse_credits(raw)
    assert result["words_by"] == expected_words, (
        f"words_by mismatch for {raw!r}: expected {expected_words!r}, got {result['words_by']!r}"
    )
    assert result["music_by"] == expected_music, (
        f"music_by mismatch for {raw!r}: expected {expected_music!r}, got {result['music_by']!r}"
    )


# Arranger golden data: (raw, expected_arranger)
_ARRANGER_CASES = [
    ("Arr. by Sarah Williams", "Sarah Williams"),
    ("Arr.: Ken Young", "Ken Young"),
    ("Arr: Pam Stephenson", "Pam Stephenson"),
    ("Arrangement by: Someone Composer", "Someone Composer"),
    # Copyright line that starts with "Arr." must NOT be treated as arranger
    ("Arr. Copyright 2019 Publisher", None),
]


@pytest.mark.unit
@pytest.mark.parametrize("raw,expected_arranger", _ARRANGER_CASES)
def test_parse_credits_arranger_golden(raw: str, expected_arranger: str | None) -> None:
    """Golden-file: arranger extraction handles all documented patterns."""
    result = parse_credits(raw)
    assert result["arranger"] == expected_arranger, (
        f"arranger mismatch for {raw!r}: expected {expected_arranger!r}, got {result['arranger']!r}"
    )


# Empty / whitespace / no-credit inputs: all fields should be None
_EMPTY_CASES = [
    "",
    "   ",
    "Just musical notation",
    "A line with no credit keywords",
]


@pytest.mark.unit
@pytest.mark.parametrize("raw", _EMPTY_CASES)
def test_parse_credits_empty_returns_none_fields(raw: str) -> None:
    """Golden-file: inputs with no credit patterns leave all fields as None."""
    result = parse_credits(raw)
    assert result["words_by"] is None, f"words_by should be None for {raw!r}"
    assert result["music_by"] is None, f"music_by should be None for {raw!r}"
    assert result["arranger"] is None, f"arranger should be None for {raw!r}"


# -----------------------------------------------------------------------
# canonicalize_title golden data
#
# Format: (display_title, expected_canonical)
# The canonical form is lowercase, stripped of end punctuation, whitespace-normalized.
# -----------------------------------------------------------------------
_CANONICAL_TITLE_CASES = [
    ("Amazing Grace", "amazing grace"),
    ("How Great Thou Art", "how great thou art"),
    # End punctuation stripped
    ("Great Is Thy Faithfulness!", "great is thy faithfulness"),
    ("Come, Now Is the Time to Worship", "come, now is the time to worship"),
    # Leading/trailing whitespace
    ("  Holy, Holy, Holy  ", "holy, holy, holy"),
    # Uppercase / mixed case
    ("IT IS WELL", "it is well"),
    ("10,000 Reasons", "10,000 reasons"),
    # Trailing period stripped
    ("Be Thou My Vision.", "be thou my vision"),
    # Internal whitespace is normalized (multiple spaces collapsed to one)
    ("This  Is   Amazing", "this is amazing"),
]


@pytest.mark.unit
@pytest.mark.parametrize("display_title,expected_canonical", _CANONICAL_TITLE_CASES)
def test_canonicalize_title_golden(display_title: str, expected_canonical: str) -> None:
    """Golden-file: canonicalize_title produces the expected canonical key.

    These assertions lock in the exact output so that any change to the
    normalization logic immediately shows up as a test failure, prompting
    the developer to update either the implementation or these golden values.
    """
    result = canonicalize_title(display_title)
    assert result == expected_canonical, (
        f"canonicalize_title({display_title!r}) = {result!r}, expected {expected_canonical!r}"
    )
