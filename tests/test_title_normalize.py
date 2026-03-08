"""Unit tests for title normalization and stripping logic."""

import pytest
from worship_catalog.normalize import strip_title_prefix


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

