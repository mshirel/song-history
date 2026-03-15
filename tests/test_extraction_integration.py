"""Integration tests for PPTX extraction."""

import json
from pathlib import Path

import pytest

from worship_catalog.extractor import extract_songs
from worship_catalog.pptx_reader import (
    extract_service_metadata,
    load_pptx,
    parse_all_slides,
)

# Path to the real worship PPTX (optional — present on developer machines, absent in CI).
# All structural tests use the synthetic_pptx fixture from conftest.py instead (#85).
_REAL_PPTX = Path(__file__).parent.parent / "data" / "AM Worship 2026.02.15.pptx"


@pytest.mark.integration
class TestPPTXReading:
    """Tests for basic PPTX reading and parsing (use synthetic fixture, always run in CI)."""

    def test_load_pptx(self, synthetic_pptx):
        """Load a PPTX file successfully."""
        prs = load_pptx(synthetic_pptx)
        assert prs is not None
        assert len(prs.slides) > 0

    def test_parse_all_slides(self, synthetic_pptx):
        """Parse all slides from PPTX."""
        prs = load_pptx(synthetic_pptx)
        slides = parse_all_slides(prs)

        assert len(slides) > 0
        for slide in slides:
            assert slide.index >= 0
            assert hasattr(slide, "hidden")
            assert hasattr(slide, "text")
            assert hasattr(slide, "images")

    def test_extract_metadata_from_first_slide(self, synthetic_pptx):
        """Extract service metadata from first slide."""
        prs = load_pptx(synthetic_pptx)
        slides = parse_all_slides(prs)
        first_slide = slides[0]

        metadata = extract_service_metadata(first_slide, synthetic_pptx.name)

        assert metadata is not None
        assert metadata.date or metadata.service_name


@pytest.mark.integration
class TestSongExtraction:
    """Tests for song extraction logic (use synthetic fixture, always run in CI)."""

    def test_extract_songs_basic(self, synthetic_pptx):
        """Extract songs from PPTX file."""
        result = extract_songs(synthetic_pptx)

        assert result is not None
        assert result.filename == synthetic_pptx.name
        assert result.service_date or result.service_name
        assert len(result.songs) > 0

    def test_extraction_result_structure(self, synthetic_pptx):
        """Verify extraction result has expected structure."""
        result = extract_songs(synthetic_pptx)

        assert hasattr(result, "filename")
        assert hasattr(result, "service_date")
        assert hasattr(result, "service_name")
        assert hasattr(result, "song_leader")
        assert hasattr(result, "preacher")
        assert hasattr(result, "sermon_title")
        assert hasattr(result, "songs")
        assert hasattr(result, "anomalies")

    def test_song_occurrence_structure(self, synthetic_pptx):
        """Verify each song occurrence has expected fields."""
        result = extract_songs(synthetic_pptx)
        assert len(result.songs) > 0

        for song in result.songs:
            assert song.ordinal >= 1
            assert song.canonical_title
            assert song.display_title
            assert hasattr(song, "publisher")
            assert hasattr(song, "words_by")
            assert hasattr(song, "music_by")
            assert hasattr(song, "arranger")
            assert hasattr(song, "first_slide_index")
            assert hasattr(song, "slide_count")

    def test_extraction_produces_json_serializable(self, synthetic_pptx):
        """Verify extraction result can be serialized to JSON."""
        result = extract_songs(synthetic_pptx)

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

        json_str = json.dumps(result_dict, indent=2)
        assert json_str is not None
        assert len(json_str) > 0

    def test_extracted_songs_are_unique(self, synthetic_pptx):
        """Verify each extracted song has a unique canonical title."""
        result = extract_songs(synthetic_pptx)

        canonical_titles = [song.canonical_title for song in result.songs]
        assert len(canonical_titles) == len(set(canonical_titles))

    def test_songs_have_correct_ordinal(self, synthetic_pptx):
        """Verify songs have correct ordinal numbering."""
        result = extract_songs(synthetic_pptx)

        for i, song in enumerate(result.songs, 1):
            assert song.ordinal == i


@pytest.mark.integration
@pytest.mark.slow
class TestExtractionAccuracy:
    """Golden-file accuracy tests — require the real worship PPTX (skip in CI if absent).

    Marked ``slow`` because the test loads and parses a real multi-slide PPTX
    via python-pptx, which takes ~180 ms on a developer laptop.
    """

    @pytest.fixture
    def expected_results(self):
        """Load expected extraction results from the golden fixture file."""
        expected_file = (
            Path(__file__).parent / "fixtures" / "AM_Worship_2026.02.15.expected.json"
        )
        if expected_file.exists():
            with open(expected_file) as f:
                return json.load(f)
        return None

    def test_extraction_matches_expected(self, expected_results):
        """Verify extraction against golden file — skips in CI when real PPTX is absent."""
        if not _REAL_PPTX.exists():
            pytest.skip(f"Real worship PPTX not found: {_REAL_PPTX}")
        if expected_results is None:
            pytest.skip("Golden fixture not found")

        result = extract_songs(_REAL_PPTX)

        assert result.filename == expected_results["filename"]
        assert result.service_date == expected_results["service_date"]
        assert result.service_name == expected_results["service_name"]
        assert result.song_leader == expected_results["song_leader"]
        assert result.preacher == expected_results["preacher"]
        assert result.sermon_title == expected_results["sermon_title"]
        assert len(result.songs) >= len(expected_results["songs"])

        if expected_results["songs"]:
            expected_song = expected_results["songs"][0]
            actual_song = result.songs[0]
            assert actual_song.ordinal == expected_song["ordinal"]
            assert actual_song.canonical_title == expected_song["canonical_title"]
            assert actual_song.display_title == expected_song["display_title"]
            assert actual_song.publisher == expected_song.get("publisher")
