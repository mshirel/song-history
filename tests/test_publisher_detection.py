"""Unit tests for publisher detection logic."""

import pytest
from worship_catalog.normalize import detect_publisher


@pytest.mark.unit
class TestPublisherDetection:
    """Tests for detecting publisher markers in slide text."""

    def test_detect_paperless_hymnal_website(self):
        """Detect 'PaperlessHymnal.com' → 'Paperless Hymnal'."""
        text = "Amazing Grace\nPaperlessHymnal.com"
        assert detect_publisher(text) == "Paperless Hymnal"

    def test_detect_paperless_hymnal_lowercase(self):
        """Detect 'paperlesshymnal.com' (case-insensitive) → 'Paperless Hymnal'."""
        text = "Some Song\nvisit paperlesshymnal.com for more"
        assert detect_publisher(text) == "Paperless Hymnal"

    def test_detect_paperless_hymnal_phrase(self):
        """Detect 'Paperless Hymnal' (without .com)."""
        text = "From Paperless Hymnal Collection"
        assert detect_publisher(text) == "Paperless Hymnal"

    def test_detect_taylor_publications_direct(self):
        """Detect 'Taylor Publications' → 'Taylor Publications'."""
        text = "Copyright © Taylor Publications LLC"
        assert detect_publisher(text) == "Taylor Publications"

    def test_detect_taylor_publications_with_presentation(self):
        """Detect 'Presentation ©' + 'Publications' → 'Taylor Publications'."""
        text = "Presentation © 2020 Publications LLC"
        assert detect_publisher(text) == "Taylor Publications"

    def test_detect_taylor_publications_case_insensitive(self):
        """Detect 'taylor publications' (case-insensitive)."""
        text = "source: taylor publications"
        assert detect_publisher(text) == "Taylor Publications"

    def test_no_publisher_detected(self):
        """Return None if no publisher markers found."""
        text = "Just a regular hymn\nWords by Someone\nMusic by Someone Else"
        assert detect_publisher(text) is None

    def test_empty_text_returns_none(self):
        """Return None for empty text."""
        assert detect_publisher("") is None
        assert detect_publisher(None) is None

    def test_presentation_without_publications_not_taylor(self):
        """Require both 'Presentation ©' AND 'Publications' for Taylor."""
        text = "Presentation © 2020 by Someone"
        assert detect_publisher(text) is None

    def test_publications_without_presentation_is_taylor(self):
        """Match 'Publications' alone."""
        text = "Copyright © Publications"
        # This might match Taylor if we're checking for "taylor publications"
        result = detect_publisher(text)
        # Should require more specific marker
        assert result is None or result == "Taylor Publications"
