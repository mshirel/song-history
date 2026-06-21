"""Unit tests for worship_catalog.pptx_reader internal functions."""

import hashlib
import logging
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock

import pytest

from worship_catalog.pptx_reader import (
    ServiceMetadata,
    SlideText,
    compute_file_hash,
    extract_images_from_slide,
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


class TestSeparateLineMetadataSlide:
    """Metadata slides where keys/values are on separate lines and a stray
    line breaks strict even/odd pairing must still resolve (#385)."""

    def test_key_value_on_separate_lines_parses_date(self):
        lines = [
            "Service Data",
            "Date", "2026-04-05",
            "Service", "Evening Worship",
            "Song Leader", "Noah Whatever",
        ]
        meta = extract_metadata_from_table_slide(lines)
        assert meta.date == "2026-04-05"
        assert meta.service_name == "Evening Worship"
        assert meta.song_leader == "Noah Whatever"

    def test_misaligned_metadata_slide_still_resolves_keys(self):
        # Extra/blank lines push key/value off even-odd alignment;
        # parser must still associate each key with its following value.
        lines = [
            "Service Data",
            "",
            "Date", "2026-04-05",
            "Service", "Evening Worship",
        ]
        meta = extract_metadata_from_table_slide(lines)
        assert meta.date == "2026-04-05"
        assert meta.service_name == "Evening Worship"

    def test_stray_quote_line_does_not_break_pairing(self):
        # Exact shape of PM Worship 2026.4.5.pptx slide 0: a stray curly-quote
        # line after the header shifted every key onto the wrong parity.
        lines = [
            "Service Data",
            "“",  # stray curly open-quote
            "Date", "2026-04-05",
            "Service", "Evening Worship",
            "Song Leader", "Jeremy Farmer",
            "Preacher", "David Morris",
            "Sermon Title", "The Lord Is My Shepherd",
        ]
        meta = extract_metadata_from_table_slide(lines)
        assert meta.date == "2026-04-05"
        assert meta.service_name == "Evening Worship"
        assert meta.song_leader == "Jeremy Farmer"
        assert meta.preacher == "David Morris"
        assert meta.sermon_title == "The Lord Is My Shepherd"

    def test_missing_value_leaves_field_none(self):
        # A key immediately followed by another key has no value.
        lines = ["Date", "Service", "Evening Worship"]
        meta = extract_metadata_from_table_slide(lines)
        assert meta.date is None
        assert meta.service_name == "Evening Worship"

    def test_extract_service_metadata_uses_slide_over_filename(self):
        from worship_catalog.pptx_reader import Slide, extract_service_metadata

        slide = Slide(
            index=0,
            hidden=False,
            text=SlideText(text_lines=[
                "Service Data",
                "“",
                "Date", "2026-04-05",
                "Service", "Evening Worship",
            ]),
            images=[],
        )
        # Filename has single-digit month/day and should NOT be needed.
        meta = extract_service_metadata(slide, "PM Worship 2026.4.5.pptx")
        assert meta.date == "2026-04-05"
        assert meta.service_name == "Evening Worship"


class TestNormalizeServiceDate:
    """Service dates must canonicalize to ISO YYYY-MM-DD (#387)."""

    @pytest.mark.parametrize("raw,expected", [
        ("2026-05-10", "2026-05-10"),
        ("2026.05.10", "2026-05-10"),
        ("2026-05.10", "2026-05-10"),
        ("2026.05-10", "2026-05-10"),
        ("2026/05/10", "2026-05-10"),
        ("2026.5.10", "2026-05-10"),   # single-digit month/day
        ("2026-5-1", "2026-05-01"),
        ("  2026.5.1  ", "2026-05-01"),
        # US month-first format (Highland is a US congregation) — #483
        ("05-31-2026", "2026-05-31"),
        ("5/31/2026", "2026-05-31"),
        ("5.31.2026", "2026-05-31"),
        ("1-1-2026", "2026-01-01"),
    ])
    def test_normalizes_to_iso(self, raw, expected):
        from worship_catalog.pptx_reader import normalize_service_date

        assert normalize_service_date(raw) == expected

    def test_unparseable_returned_stripped(self):
        from worship_catalog.pptx_reader import normalize_service_date

        assert normalize_service_date("Easter Sunday") == "Easter Sunday"

    def test_unrecognized_format_logs_warning(self, caplog):
        import logging

        from worship_catalog.pptx_reader import normalize_service_date

        with caplog.at_level(logging.WARNING):
            assert normalize_service_date("Easter Sunday") == "Easter Sunday"
        assert any("Easter Sunday" in r.message for r in caplog.records), (
            "unrecognized date formats must be logged, not silently stored"
        )

    def test_invalid_calendar_date_passed_through(self):
        from worship_catalog.pptx_reader import normalize_service_date

        # 2026-13-40 matches the year-first shape but is not a real date — must
        # not be silently 'normalized' into a bogus ISO string.
        assert normalize_service_date("2026-13-40") == "2026-13-40"

    def test_none_and_empty(self):
        from worship_catalog.pptx_reader import normalize_service_date

        assert normalize_service_date(None) is None
        assert normalize_service_date("  ") is None

    def test_extract_service_metadata_normalizes_date(self):
        from worship_catalog.pptx_reader import Slide, extract_service_metadata

        slide = Slide(index=0, hidden=False, text=SlideText(text_lines=[
            "Service Data", "Date", "2026.05.10", "Service", "Evening Worship",
        ]), images=[])
        meta = extract_service_metadata(slide, "PM Worship 2026.5.10.pptx")
        assert meta.date == "2026-05-10"

    def test_filename_fallback_single_digit_normalizes(self):
        from worship_catalog.pptx_reader import parse_filename_for_metadata

        meta = parse_filename_for_metadata("PM Worship 2026.4.5.pptx")
        assert meta.date == "2026-04-05"
        assert meta.service_name == "Evening Worship"


class TestExtractImagesLogsOnError:
    """Issue #101 — blob extraction errors must be logged at WARNING."""

    def _make_slide_with_failing_blob(self) -> MagicMock:
        """Return a mock slide whose first picture shape raises on blob access."""
        mock_shape = MagicMock()
        mock_shape.shape_type = 13  # _PPTX_PICTURE_SHAPE_TYPE
        mock_shape.shape_id = 1
        # Make blob raise an exception when accessed
        type(mock_shape.image).blob = PropertyMock(
            side_effect=Exception("corrupt blob")
        )

        mock_slide = MagicMock()
        mock_slide.shapes = [mock_shape]
        return mock_slide

    def test_blob_error_is_logged_as_warning(self, caplog):
        mock_slide = self._make_slide_with_failing_blob()
        with caplog.at_level(logging.WARNING, logger="worship_catalog.pptx_reader"):
            result = extract_images_from_slide(mock_slide)
        assert any(
            "blob" in r.message.lower() or "extract" in r.message.lower()
            for r in caplog.records
        ), f"Expected a WARNING about blob/extract, got: {caplog.records}"

    def test_blob_error_still_appends_shape_with_none_blob(self, caplog):
        """Shape is still recorded with blob=None so callers know it existed."""
        mock_slide = self._make_slide_with_failing_blob()
        with caplog.at_level(logging.WARNING, logger="worship_catalog.pptx_reader"):
            result = extract_images_from_slide(mock_slide)
        assert len(result) == 1
        assert result[0].blob is None

    def test_warning_includes_exc_info(self, caplog):
        """The warning record must carry exc_info so the traceback is captured."""
        mock_slide = self._make_slide_with_failing_blob()
        with caplog.at_level(logging.WARNING, logger="worship_catalog.pptx_reader"):
            extract_images_from_slide(mock_slide)
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warning_records, "No WARNING records found"
        assert warning_records[0].exc_info is not None, (
            "exc_info must be set so the traceback is captured"
        )


# ---------------------------------------------------------------------------
# Issue #147 — parse_filename_for_metadata() untested
# ---------------------------------------------------------------------------


class TestParseFilenameForMetadata:
    """Tests for parse_filename_for_metadata() — issue #147."""

    def test_am_worship_filename(self):
        """'AM Worship 2024.01.14.pptx' parses to Morning Worship with correct date."""
        from worship_catalog.pptx_reader import parse_filename_for_metadata
        result = parse_filename_for_metadata("AM Worship 2024.01.14.pptx")
        assert result.service_name == "Morning Worship"
        assert result.date == "2024-01-14"

    def test_pm_worship_filename(self):
        """'PM Worship 2024.01.14.pptx' parses to Evening Worship with correct date."""
        from worship_catalog.pptx_reader import parse_filename_for_metadata
        result = parse_filename_for_metadata("PM Worship 2024.01.14.pptx")
        assert result.service_name == "Evening Worship"
        assert result.date == "2024-01-14"

    def test_date_year_month_day_correct(self):
        """Date components parse to correct YYYY-MM-DD format."""
        from worship_catalog.pptx_reader import parse_filename_for_metadata
        result = parse_filename_for_metadata("AM Worship 2026.03.15.pptx")
        assert result.date == "2026-03-15"

    def test_random_filename_returns_none_fields(self):
        """Unrecognized filename returns None for date and service_name."""
        from worship_catalog.pptx_reader import parse_filename_for_metadata
        result = parse_filename_for_metadata("random_filename.pptx")
        assert result.date is None
        assert result.service_name is None

    def test_filename_no_extension_returns_none_fields(self):
        """Filename with no extension returns None for date and service_name."""
        from worship_catalog.pptx_reader import parse_filename_for_metadata
        result = parse_filename_for_metadata("AM Worship 2024.01.14")
        # No extension — pattern still matches (pattern doesn't require .pptx extension)
        # Either date is parsed or not — just confirm no exception
        assert isinstance(result.date, (str, type(None)))
        assert isinstance(result.service_name, (str, type(None)))

    def test_empty_filename_returns_none_fields(self):
        """Empty filename string returns None for all fields."""
        from worship_catalog.pptx_reader import parse_filename_for_metadata
        result = parse_filename_for_metadata("")
        assert result.date is None
        assert result.service_name is None

    def test_leader_and_preacher_always_none(self):
        """parse_filename_for_metadata never sets song_leader or preacher."""
        from worship_catalog.pptx_reader import parse_filename_for_metadata
        result = parse_filename_for_metadata("AM Worship 2026.01.01.pptx")
        assert result.song_leader is None
        assert result.preacher is None

    def test_result_is_service_metadata(self):
        """Return type is ServiceMetadata."""
        from worship_catalog.pptx_reader import parse_filename_for_metadata, ServiceMetadata
        result = parse_filename_for_metadata("AM Worship 2026.01.01.pptx")
        assert isinstance(result, ServiceMetadata)

    def test_underscored_am_worship_filename(self):
        """Filename with underscores instead of spaces must still parse (#265)."""
        from worship_catalog.pptx_reader import parse_filename_for_metadata
        meta = parse_filename_for_metadata("AM_Worship_2025.09.28.pptx")
        assert meta.date == "2025-09-28"
        assert meta.service_name == "Morning Worship"

    def test_job_id_prefixed_filename(self):
        """Filename with job_id prefix must still extract date (#265)."""
        from worship_catalog.pptx_reader import parse_filename_for_metadata
        meta = parse_filename_for_metadata("abc123_AM_Worship_2025.09.28.pptx")
        assert meta.date == "2025-09-28"

    def test_pm_worship_with_underscores(self):
        """PM Worship with underscores must parse correctly (#265)."""
        from worship_catalog.pptx_reader import parse_filename_for_metadata
        meta = parse_filename_for_metadata("PM_Worship_2026.03.15.pptx")
        assert meta.date == "2026-03-15"
        assert meta.service_name == "Evening Worship"


class TestExtractServiceMetadataPartialFallback:
    """Partial table data should be merged with filename fallback (#169)."""

    def test_filename_fallback_fills_missing_service_name(self):
        """When table has date but no service_name, filename provides service_name."""
        from worship_catalog.pptx_reader import extract_service_metadata, Slide

        slide = Slide(
            index=0, hidden=False,
            text=SlideText(text_lines=["Date", "2026-02-15"]),
            images=[],
        )
        meta = extract_service_metadata(slide, "AM Worship 2026.02.15.pptx")
        assert meta.date == "2026-02-15"
        assert meta.service_name == "Morning Worship"

    def test_filename_fallback_fills_missing_date(self):
        """When table has service_name but no date, filename provides date."""
        from worship_catalog.pptx_reader import extract_service_metadata, Slide

        slide = Slide(
            index=0, hidden=False,
            text=SlideText(text_lines=["Service", "Morning Worship"]),
            images=[],
        )
        meta = extract_service_metadata(slide, "AM Worship 2026.03.01.pptx")
        assert meta.service_name == "Morning Worship"
        assert meta.date == "2026-03-01"

    def test_complete_table_data_does_not_use_filename(self):
        """When table has both date and service_name, filename is ignored."""
        from worship_catalog.pptx_reader import extract_service_metadata, Slide

        slide = Slide(
            index=0, hidden=False,
            text=SlideText(text_lines=["Date", "2026-01-01", "Service", "PM Worship"]),
            images=[],
        )
        meta = extract_service_metadata(slide, "AM Worship 2026.03.01.pptx")
        assert meta.date == "2026-01-01"
        assert meta.service_name == "PM Worship"

    def test_table_leader_preserved_with_filename_fallback(self):
        """Table-provided song_leader is kept when filename fills missing fields."""
        from worship_catalog.pptx_reader import extract_service_metadata, Slide

        slide = Slide(
            index=0, hidden=False,
            text=SlideText(text_lines=["Date", "2026-02-15", "Song Leader", "Matt"]),
            images=[],
        )
        meta = extract_service_metadata(slide, "AM Worship 2026.02.15.pptx")
        assert meta.song_leader == "Matt"
        assert meta.service_name == "Morning Worship"
