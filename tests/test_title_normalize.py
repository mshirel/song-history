"""Unit tests for title normalization and stripping logic."""

import pytest
from worship_catalog.normalize import _is_invalid_line, strip_title_prefix


@pytest.mark.unit
class TestTitleNormalization:
    """Tests for stripping verse/chorus/section prefixes from titles."""

    def test_strip_numeric_prefix_with_dash(self):
        """Strip '1 - Title' → 'Title'."""
        assert strip_title_prefix("1 - We Will Glorify") == "We Will Glorify"
        assert strip_title_prefix("5 - Ancient Words") == "Ancient Words"

    def test_strip_numeric_prefix_with_endash(self):
        """Strip '1 – Title' (with en-dash) → 'Title'."""
        assert strip_title_prefix("1 – We Bow Down") == "We Bow Down"

    def test_strip_lowercase_c_prefix(self):
        """Strip 'c - Title' (chorus indicator) → 'Title'."""
        assert strip_title_prefix("c - Amazing Grace") == "Amazing Grace"

    def test_strip_uppercase_c_prefix(self):
        """Strip 'C - Title' (chorus indicator) → 'Title'."""
        assert strip_title_prefix("C – We Bow Down") == "We Bow Down"

    def test_strip_compound_numbering(self):
        """Strip '1-1 Ancient Words' → 'Ancient Words'."""
        assert strip_title_prefix("1-1 Ancient Words") == "Ancient Words"
        assert strip_title_prefix("C-2 Light The Fire") == "Light The Fire"
        assert strip_title_prefix("V1a – Create In Me") == "Create In Me"

    def test_strip_named_section_bridge(self):
        """Strip 'Bridge1 Title' → 'Title'."""
        assert strip_title_prefix("Bridge1 Mighty To Save") == "Mighty To Save"
        assert strip_title_prefix("Bridge Mighty To Save") == "Mighty To Save"
        assert strip_title_prefix("Bridge – Mighty To Save") == "Mighty To Save"

    def test_strip_named_section_verse(self):
        """Strip 'Verse1 Title' → 'Title'."""
        assert strip_title_prefix("Verse1 Holy Ground") == "Holy Ground"
        assert strip_title_prefix("V – Holy Ground") == "Holy Ground"
        assert strip_title_prefix("V1 Holy Ground") == "Holy Ground"

    def test_strip_named_section_chorus(self):
        """Strip 'Chorus Title' → 'Title'."""
        assert strip_title_prefix("Chorus Ancient Words") == "Ancient Words"
        assert strip_title_prefix("C1 – Ancient Words") == "Ancient Words"

    def test_strip_named_section_refrain(self):
        """Strip 'Refrain Title' → 'Title'."""
        assert strip_title_prefix("Refrain – Create In Me") == "Create In Me"
        assert strip_title_prefix("R1 Create In Me") == "Create In Me"

    def test_strip_named_section_tag(self):
        """Strip 'Tag Title' → 'Title'."""
        assert strip_title_prefix("Tag Mighty To Save") == "Mighty To Save"

    def test_strip_named_section_intro(self):
        """Strip 'Intro Title' → 'Title'."""
        assert strip_title_prefix("Intro Ancient Words") == "Ancient Words"

    def test_strip_named_section_outro(self):
        """Strip 'Outro Title' → 'Title'."""
        assert strip_title_prefix("Outro Mighty To Save") == "Mighty To Save"

    def test_strip_named_section_coda(self):
        """Strip 'Coda Title' (case variations) → 'Title'."""
        assert strip_title_prefix("Coda – Create In Me") == "Create In Me"
        assert strip_title_prefix("CODA Create In Me") == "Create In Me"

    def test_strip_named_section_ds(self):
        """Strip 'DS Title' (Dal Segno) → 'Title'."""
        assert strip_title_prefix("DS1 Mighty To Save") == "Mighty To Save"

    def test_strip_lowercase_tag(self):
        """Strip 'tag Title' (lowercase) → 'Title'."""
        assert strip_title_prefix("tag Ancient Words") == "Ancient Words"

    def test_whitespace_normalization(self):
        """Normalize whitespace in title."""
        assert strip_title_prefix("1  -  We  Will  Glorify") == "We Will Glorify"
        assert strip_title_prefix("  Bridge1   Mighty To Save  ") == "Mighty To Save"

    def test_no_prefix_already_clean(self):
        """Return title unchanged if no prefix detected."""
        assert strip_title_prefix("We Will Glorify") == "We Will Glorify"
        assert strip_title_prefix("Ancient Words") == "Ancient Words"

    def test_leading_trailing_whitespace_stripped(self):
        """Strip leading/trailing whitespace."""
        assert strip_title_prefix("  Amazing Grace  ") == "Amazing Grace"


@pytest.mark.unit
class TestCandidateSelection:
    """Tests for selecting best title candidate from multiple lines."""

    def test_prefer_plain_title_over_prefixed(self):
        """If both '1-1 Title' and 'Title' exist, choose 'Title'."""
        from worship_catalog.normalize import select_best_title

        candidates = ["1-1 Ancient Words", "Ancient Words"]
        assert select_best_title(candidates) == "Ancient Words"

    def test_prefer_plain_over_chorus_prefix(self):
        """If both 'C – Title' and 'Title' exist, choose 'Title'."""
        from worship_catalog.normalize import select_best_title

        candidates = ["C – Amazing Grace", "Amazing Grace"]
        assert select_best_title(candidates) == "Amazing Grace"

    def test_select_shortest_valid(self):
        """Select shortest valid title if multiple non-prefixed candidates."""
        from worship_catalog.normalize import select_best_title

        candidates = ["We Will Glorify God", "We Will Glorify"]
        # Both are valid, prefer shorter
        result = select_best_title(candidates)
        assert len(result) <= len(max(candidates))

    def test_ignore_copyright_lines(self):
        """Ignore lines containing copyright markers."""
        from worship_catalog.normalize import select_best_title

        candidates = [
            "Copyright © 2020",
            "All Rights Reserved",
            "We Will Glorify"
        ]
        assert select_best_title(candidates) == "We Will Glorify"

    def test_ignore_footer_lines(self):
        """Ignore lines containing footer markers."""
        from worship_catalog.normalize import select_best_title

        candidates = [
            "PaperlessHymnal.com",
            "Used by permission",
            "Ancient Words"
        ]
        assert select_best_title(candidates) == "Ancient Words"

    def test_single_candidate(self):
        """Return single candidate if valid."""
        from worship_catalog.normalize import select_best_title

        assert select_best_title(["Amazing Grace"]) == "Amazing Grace"

    def test_empty_list_returns_none(self):
        """Return None if no valid candidates."""
        from worship_catalog.normalize import select_best_title

        assert select_best_title([]) is None

    def test_all_invalid_candidates_returns_none(self):
        """Return None if all candidates are invalid."""
        from worship_catalog.normalize import select_best_title

        candidates = ["Copyright © 2020", "All Rights Reserved"]
        assert select_best_title(candidates) is None


@pytest.mark.unit
class TestCanonicalizeTitle:
    """Tests for canonicalizing titles (lowercase key)."""

    def test_lowercase_conversion(self):
        """Convert title to lowercase for canonical key."""
        from worship_catalog.normalize import canonicalize_title

        assert canonicalize_title("We Will Glorify") == "we will glorify"
        assert canonicalize_title("ANCIENT WORDS") == "ancient words"

    def test_punctuation_trim(self):
        """Trim punctuation from ends."""
        from worship_catalog.normalize import canonicalize_title

        assert canonicalize_title("We Will Glorify!") == "we will glorify"
        assert canonicalize_title("'Amazing Grace'") == "amazing grace"

    def test_whitespace_normalization_canonical(self):
        """Normalize interior whitespace."""
        from worship_catalog.normalize import canonicalize_title

        assert canonicalize_title("We  Will   Glorify") == "we will glorify"


@pytest.mark.unit
class TestHymnNumberFiltering:
    """Tests for filtering out hymn numbers and reference markers."""

    def test_select_best_title_skips_hymn_numbers(self):
        """Hymn numbers like '#480' should be filtered out."""
        from worship_catalog.normalize import select_best_title

        # When both a hymn number and a real title are present, prefer the title
        candidates = [
            "1 – Blessed Assurance",
            "#480",
        ]
        assert select_best_title(candidates) == "Blessed Assurance"

    def test_select_best_title_skips_bare_numbers(self):
        """Bare hymn numbers like '480' should be filtered out."""
        from worship_catalog.normalize import select_best_title

        candidates = [
            "c – My Great Redeemer",
            "480",
        ]
        assert select_best_title(candidates) == "My Great Redeemer"

    def test_select_best_title_prefers_real_title_over_number(self):
        """Real titles should always win over hymn reference numbers."""
        from worship_catalog.normalize import select_best_title

        candidates = [
            "#480",  # Just a number
            "Blessed Assurance",  # Real title
        ]
        assert select_best_title(candidates) == "Blessed Assurance"

    def test_blessed_assurance_extraction(self):
        """Test extraction from Blessed Assurance slides."""
        from worship_catalog.normalize import select_best_title

        # Typical candidates on a Blessed Assurance slide
        candidates = [
            "1 – Blessed Assurance",
            "PaperlessHymnal.com",
            "#480",
        ]
        best = select_best_title(candidates)
        assert best == "Blessed Assurance"


@pytest.mark.unit
class TestScriptureGuard:
    """Tests that scripture references are flagged as invalid lines."""

    def test_single_chapter_verse(self):
        assert _is_invalid_line("John 3:16") is True

    def test_verse_range(self):
        assert _is_invalid_line("1 Peter 1:3-4") is True

    def test_two_word_book(self):
        assert _is_invalid_line("2 Corinthians 4:7") is True

    def test_psalm(self):
        assert _is_invalid_line("Psalm 23:1-3") is True

    def test_multi_verse_range(self):
        assert _is_invalid_line("Romans 8:28") is True

    def test_with_leading_whitespace(self):
        assert _is_invalid_line("  John 3:16  ") is True

    def test_song_title_not_flagged(self):
        assert _is_invalid_line("Amazing Grace") is False

    def test_song_title_with_number_not_flagged(self):
        assert _is_invalid_line("10,000 Reasons") is False

    def test_partial_reference_not_flagged(self):
        # No chapter:verse pattern → not a scripture ref
        assert _is_invalid_line("John") is False

    def test_scripture_with_en_dash(self):
        """Scripture with en-dash verse range should be flagged (#313)."""
        assert _is_invalid_line("MICAH 6:6 – 8") is True

    def test_scripture_with_em_dash(self):
        """Scripture with em-dash verse range should be flagged (#313)."""
        assert _is_invalid_line("Psalm 23:1—6") is True

    def test_scripture_with_spaced_range(self):
        """Scripture with spaces around hyphen should be flagged (#313)."""
        assert _is_invalid_line("Romans 8:28 - 30") is True


@pytest.mark.unit
class TestNonSongTitleFilter:
    """is_non_song_title() drops sermon points, scripture quotes, verse/stanza
    markers, and lyric fragments that the grouping step mistakenly split out.

    Applied to the FINAL chosen title (post-extraction) so it does not perturb
    slide grouping. These are the real false positives observed in production.
    """

    # Titles that must be rejected (NOT real songs).
    NON_TITLES = [
        ":7",  # bare verse fragment
        "And when he has found it, he lays it on his shoulders, rejoicing.",  # scripture prose
        "(6) Humble yourselves, therefore, under the mighty hand of God "
        "so that at the proper time he may exalt you",  # leading (N) + prose
        "St. 2 The Lord as Host (vv. 5–6)",  # stanza + verse markers
        'The Simplest Promise: “You are with me”',  # sermon point w/ quote
        "The Simplest Truth: The Lord is My Deliverer",  # sermon point (colon)
        'Many of them said, “He has a demon, and is insane; '
        'why listen to him?”',  # scripture quote ending ?"
        "“Ah, shepherds of Israel who have been feeding yourselves! "
        "Should not shepherds feed the sheep?”",  # quote-wrapped
        ". SALVATION IS COMPLETELY THE WORK OF GOD, THE MOST HIGH.",  # leading . + caps
        "MICAH 6:6 – 8",  # scripture reference
        "us Christ, the King of Glory,",  # lyric: lowercase start + trailing comma
        "sick and sorrowworn,",  # lyric: lowercase start + trailing comma
        "they comfort me.",  # lyric: lowercase start
        "SFP 373",  # Paperless Hymnal catalog number
        "SFP 878",
        "",  # empty
        "   ",  # whitespace only
    ]

    # Real titles from production that must NOT be rejected.
    REAL_TITLES = [
        "Amazing Grace",
        "Are You Washed in the Blood?",
        "Does Jesus Care?",
        "Praise Him! Praise Him!",
        "Lovest Thou Me More Than These?",
        "He arose! He arose!",
        "Where Could I Go?",
        "Alleluia, Alleluia! Hearts to Heaven",
        "‘Tis So Sweet to Trust in Jesus",
        "The Lord's My Shepherd",
        "Praise to the Lord, the Almighty, the King of Creation",
        "Come, We That Love the Lord",
        "Stand Up, Stand Up for Jesus",
        "I Love You, Lord",
        "God’s Family",
        "How Deep the Father’s Love",
        "10,000 Reasons",
        "We Saw Thee Not",
    ]

    @pytest.mark.parametrize("title", NON_TITLES)
    def test_non_titles_are_dropped(self, title):
        from worship_catalog.normalize import is_non_song_title

        assert is_non_song_title(title) is True

    @pytest.mark.parametrize("title", REAL_TITLES)
    def test_real_titles_are_kept(self, title):
        from worship_catalog.normalize import is_non_song_title

        assert is_non_song_title(title) is False


@pytest.mark.unit
class TestSermonOutlineNotStripped:
    """Sermon outline numbered points should not be stripped (#314)."""

    def test_numbered_period_not_stripped(self):
        """'1. SALVATION' should NOT have '1.' stripped."""
        result = strip_title_prefix("1. SALVATION THEN SANCTIFICATION")
        assert "SALVATION" in result
        # Should not strip the number — it's a sermon outline, not a verse prefix
        assert result.startswith("1.")

    def test_regular_verse_prefix_still_stripped(self):
        """'1 - Amazing Grace' should still be stripped normally."""
        assert strip_title_prefix("1 - Amazing Grace") == "Amazing Grace"

    def test_numbered_period_short(self):
        """'2. Grace' — even short entries with period should not strip."""
        result = strip_title_prefix("2. Grace")
        assert result.startswith("2.")


@pytest.mark.unit
class TestInvalidLineMarkers:
    """_is_invalid_line marker lists must not contain duplicates (#416)."""

    def test_copyright_marker_list_has_no_duplicates(self):
        import inspect
        import re

        src = inspect.getsource(_is_invalid_line)
        # Only standalone quoted list items (one per line), e.g. `    "copyright",`.
        # Avoids matching the docstring or inline regex/code.
        markers = re.findall(r'^\s*"([^"]+)",?\s*$', src, re.MULTILINE)
        dupes = sorted({m for m in markers if markers.count(m) > 1})
        assert not dupes, f"Duplicate markers in _is_invalid_line: {dupes}"

    def test_all_rights_reserved_still_filtered(self):
        assert _is_invalid_line("All Rights Reserved") is True
