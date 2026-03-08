"""Integration tests for PPTX extraction."""

import json
from pathlib import Path

import pytest

from worship_catalog.extractor import extract_songs
from worship_catalog.pptx_reader import (
    extract_service_metadata,
    is_slide_hidden,
    load_pptx,
    parse_all_slides,
)


@pytest.mark.integration
class TestPPTXReading:
    """Tests for basic PPTX reading and parsing."""

    @pytest.fixture
    def pptx_file(self):
        """Path to a test PPTX file from data directory."""
        # Path(__file__) = tests/test_extraction_integration.py
        # .parent = tests/ directory
        # .parent = project root directory
        project_root = Path(__file__).parent.parent
        return project_root / "data" / "AM Worship 2026.02.15.pptx"

    def test_load_pptx(self, pptx_file):
        """Load a PPTX file successfully."""
        if not pptx_file.exists():
            pytest.skip(f"Test PPTX not found: {pptx_file}")

        prs = load_pptx(pptx_file)
        assert prs is not None
        assert len(prs.slides) > 0

    def test_parse_all_slides(self, pptx_file):
        """Parse all slides from PPTX."""
        if not pptx_file.exists():
            pytest.skip(f"Test PPTX not found: {pptx_file}")

        prs = load_pptx(pptx_file)
        slides = parse_all_slides(prs)

        assert len(slides) > 0
        # Each slide should have basic structure
        for slide in slides:
            assert slide.index >= 0
            assert hasattr(slide, "hidden")
            assert hasattr(slide, "text")
            assert hasattr(slide, "images")

    def test_extract_metadata_from_first_slide(self, pptx_file):
        """Extract service metadata from first slide."""
        if not pptx_file.exists():
            pytest.skip(f"Test PPTX not found: {pptx_file}")

        prs = load_pptx(pptx_file)
        slides = parse_all_slides(prs)
        first_slide = slides[0]

        metadata = extract_service_metadata(first_slide, pptx_file.name)

        # Metadata should have been extracted
        assert metadata is not None
        # At least date or service should be present
        assert metadata.date or metadata.service_name


@pytest.mark.integration
class TestSongExtraction:
    """Tests for song extraction logic."""

    @pytest.fixture
    def pptx_file(self):
        """Path to a test PPTX file."""
        project_root = Path(__file__).parent.parent
        return project_root / "data" / "AM Worship 2026.02.15.pptx"

    def test_extract_songs_basic(self, pptx_file):
        """Extract songs from PPTX file."""
        if not pptx_file.exists():
            pytest.skip(f"Test PPTX not found: {pptx_file}")

        result = extract_songs(pptx_file)

        assert result is not None
        assert result.filename == pptx_file.name
        # Should have extracted some metadata
        assert result.service_date or result.service_name
        # Should have found some songs
        assert len(result.songs) > 0

    def test_extraction_result_structure(self, pptx_file):
        """Verify extraction result has expected structure."""
        if not pptx_file.exists():
            pytest.skip(f"Test PPTX not found: {pptx_file}")

        result = extract_songs(pptx_file)

        # Check metadata fields
        assert hasattr(result, "filename")
        assert hasattr(result, "service_date")
        assert hasattr(result, "service_name")
        assert hasattr(result, "song_leader")
        assert hasattr(result, "preacher")
        assert hasattr(result, "sermon_title")
        assert hasattr(result, "songs")
        assert hasattr(result, "anomalies")

    def test_song_occurrence_structure(self, pptx_file):
        """Verify each song occurrence has expected fields."""
        if not pptx_file.exists():
            pytest.skip(f"Test PPTX not found: {pptx_file}")

        result = extract_songs(pptx_file)
        assert len(result.songs) > 0

        for song in result.songs:
            # Core fields
            assert song.ordinal >= 1
            assert song.canonical_title
            assert song.display_title
            # Optional fields (may be None)
            assert hasattr(song, "publisher")
            assert hasattr(song, "words_by")
            assert hasattr(song, "music_by")
            assert hasattr(song, "arranger")
            assert hasattr(song, "first_slide_index")
            assert hasattr(song, "slide_count")

    def test_extraction_produces_json_serializable(self, pptx_file):
        """Verify extraction result can be serialized to JSON."""
        if not pptx_file.exists():
            pytest.skip(f"Test PPTX not found: {pptx_file}")

        result = extract_songs(pptx_file)

        # Convert to dict and serialize
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
                    "slide_count": song.slide_count,
                }
                for song in result.songs
            ],
        }

        # Should be JSON serializable
        json_str = json.dumps(result_dict, indent=2)
        assert json_str is not None
        assert len(json_str) > 0


@pytest.mark.integration
class TestExtractionAccuracy:
    """Tests to verify extraction accuracy on known files."""

    @pytest.fixture
    def pptx_file(self):
        """Path to a test PPTX file."""
        project_root = Path(__file__).parent.parent
        return project_root / "data" / "AM Worship 2026.02.15.pptx"

    @pytest.fixture
    def expected_results(self):
        """Load expected extraction results."""
        expected_file = (
            Path(__file__).parent / "fixtures" / "AM_Worship_2026.02.15.expected.json"
        )
        if expected_file.exists():
            with open(expected_file) as f:
                return json.load(f)
        return None

    def test_extraction_matches_expected(self, pptx_file, expected_results):
        """Verify extraction matches expected results."""
        if not pptx_file.exists():
            pytest.skip(f"Test PPTX not found: {pptx_file}")

        if expected_results is None:
            pytest.skip("Expected results fixture not found")

        result = extract_songs(pptx_file)

        # Check filename
        assert result.filename == expected_results["filename"]

        # Check service metadata
        assert result.service_date == expected_results["service_date"]
        assert result.service_name == expected_results["service_name"]
        assert result.song_leader == expected_results["song_leader"]
        assert result.preacher == expected_results["preacher"]
        assert result.sermon_title == expected_results["sermon_title"]

        # Check song count
        assert len(result.songs) >= len(expected_results["songs"])

        # Check first song
        if expected_results["songs"]:
            expected_song = expected_results["songs"][0]
            actual_song = result.songs[0]

            assert actual_song.ordinal == expected_song["ordinal"]
            assert actual_song.canonical_title == expected_song["canonical_title"]
            assert actual_song.display_title == expected_song["display_title"]
            assert actual_song.publisher == expected_song.get("publisher")

    def test_extracted_songs_are_unique(self, pptx_file):
        """Verify each extracted song has a unique canonical title."""
        if not pptx_file.exists():
            pytest.skip(f"Test PPTX not found: {pptx_file}")

        result = extract_songs(pptx_file)

        canonical_titles = [song.canonical_title for song in result.songs]
        # All should be unique (no duplicates)
        assert len(canonical_titles) == len(set(canonical_titles))

    def test_songs_have_correct_ordinal(self, pptx_file):
        """Verify songs have correct ordinal numbering."""
        if not pptx_file.exists():
            pytest.skip(f"Test PPTX not found: {pptx_file}")

        result = extract_songs(pptx_file)

        for i, song in enumerate(result.songs, 1):
            assert song.ordinal == i
