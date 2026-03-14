"""Unit tests for worship_catalog.pptx_reader internal functions."""

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from worship_catalog.pptx_reader import (
    ServiceMetadata,
    SlideText,
    compute_file_hash,
    extract_metadata_from_table_slide,
    is_slide_hidden,
    parse_filename_for_metadata,
)


class TestIsSlideHidden:
    def test_show_zero_returns_true(self):
        mock_slide = MagicMock()
        mock_slide.element.get.return_value = "0"
        assert is_slide_hidden(mock_slide) is True

    def test_show_one_returns_false(self):
        mock_slide = MagicMock()
        mock_slide.element.get.return_value = "1"
        assert is_slide_hidden(mock_slide) is False

    def test_show_none_returns_false(self):
        mock_slide = MagicMock()
        mock_slide.element.get.return_value = None
        assert is_slide_hidden(mock_slide) is False

    def test_attribute_error_returns_false(self):
        mock_slide = MagicMock()
        mock_slide.element.get.side_effect = AttributeError
        assert is_slide_hidden(mock_slide) is False


class TestComputeFileHash:
    def test_known_content_hash(self, tmp_path):
        test_file = tmp_path / "test.bin"
        content = b"hello world"
        test_file.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert compute_file_hash(test_file) == expected

    def test_different_files_different_hashes(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"file one")
        f2.write_bytes(b"file two")
        assert compute_file_hash(f1) != compute_file_hash(f2)

    def test_same_content_same_hash(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"same content")
        f2.write_bytes(b"same content")
        assert compute_file_hash(f1) == compute_file_hash(f2)


class TestParseFilenameForMetadata:
    def test_am_worship_filename(self):
        result = parse_filename_for_metadata("AM Worship 2026.02.15.pptx")
        assert result.service_name == "Morning Worship"
        assert result.date == "2026-02-15"

    def test_pm_worship_filename(self):
        result = parse_filename_for_metadata("PM Worship 2025.11.01.pptx")
        assert result.service_name == "Evening Worship"
        assert result.date == "2025-11-01"

    def test_non_matching_filename(self):
        result = parse_filename_for_metadata("random_file.pptx")
        assert result.service_name is None
        assert result.date is None

    def test_other_fields_are_none(self):
        result = parse_filename_for_metadata("AM Worship 2026.02.15.pptx")
        assert result.song_leader is None
        assert result.preacher is None
        assert result.sermon_title is None


class TestExtractMetadataFromTableSlide:
    def test_empty_list_returns_all_none(self):
        result = extract_metadata_from_table_slide([])
        assert result.date is None
        assert result.service_name is None

    def test_header_row_skipped(self):
        lines = ["Service Data", "Date", "2026-02-15", "Service", "Morning Worship"]
        result = extract_metadata_from_table_slide(lines)
        assert result.date == "2026-02-15"
        assert result.service_name == "Morning Worship"

    def test_key_value_pairs_extracted(self):
        lines = [
            "Date", "2026-02-15",
            "Service", "Morning Worship",
            "Song Leader", "Matt",
            "Preacher", "David",
            "Sermon Title", "Grace Abounds",
        ]
        result = extract_metadata_from_table_slide(lines)
        assert result.date == "2026-02-15"
        assert result.service_name == "Morning Worship"
        assert result.song_leader == "Matt"
        assert result.preacher == "David"
        assert result.sermon_title == "Grace Abounds"

    def test_partial_data_returns_what_exists(self):
        lines = ["Date", "2026-03-01"]
        result = extract_metadata_from_table_slide(lines)
        assert result.date == "2026-03-01"
        assert result.service_name is None
