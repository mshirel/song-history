"""Tests for TPH library OLE metadata lookup."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import pytest

from worship_catalog.library import (
    _file_priority,
    _stem_to_title,
    load_library_index,
    lookup_song_credits,
    parse_author_credits,
    read_ppt_author,
    save_library_index,
)


class TestParseAuthorCredits:
    """Tests for parse_author_credits()."""

    def test_single_name_becomes_words_by(self):
        result = parse_author_credits("Charles Brown")
        assert result["words_by"] == "Charles Brown"
        assert result["music_by"] is None
        assert result["arranger"] is None

    def test_slash_split_gives_words_and_music(self):
        result = parse_author_credits("Elizabeth Clephane/Frederick Maker")
        assert result["words_by"] == "Elizabeth Clephane"
        assert result["music_by"] == "Frederick Maker"
        assert result["arranger"] is None

    def test_arr_prefix_gives_arranger(self):
        result = parse_author_credits("Lynn DeShazo/Arr. R. Dan Dalzell")
        assert result["words_by"] == "Lynn DeShazo"
        assert result["arranger"] == "R. Dan Dalzell"
        assert result["music_by"] is None

    def test_arr_after_comma(self):
        result = parse_author_credits("Reuben Morgan, Ben Fielding, Arr. Ryan C.")
        assert result["words_by"] == "Reuben Morgan, Ben Fielding"
        assert result["arranger"] == "Ryan C."
        assert result["music_by"] is None

    def test_lone_key_letter_filtered(self):
        # "Gilbert / Gilbert / F" — F is a key signature
        result = parse_author_credits("Gilbert / Gilbert / F")
        assert result["words_by"] == "Gilbert"
        assert result["music_by"] == "Gilbert"
        assert result["arranger"] is None

    def test_key_sharp_filtered(self):
        result = parse_author_credits("John Smith / G#")
        assert result["words_by"] == "John Smith"
        assert result["music_by"] is None

    def test_empty_string_returns_nones(self):
        result = parse_author_credits("")
        assert result["words_by"] is None
        assert result["music_by"] is None
        assert result["arranger"] is None

    def test_whitespace_only_returns_nones(self):
        result = parse_author_credits("   ")
        assert result["words_by"] is None

    def test_single_slash_no_arr(self):
        result = parse_author_credits("Robert Taylor")
        assert result["words_by"] == "Robert Taylor"
        assert result["music_by"] is None

    def test_arr_case_insensitive(self):
        result = parse_author_credits("John Doe / arr. Jane Smith")
        assert result["words_by"] == "John Doe"
        assert result["arranger"] == "Jane Smith"


class TestStemToTitle:
    """Tests for _stem_to_title()."""

    def test_strips_ph_hd_suffix(self):
        assert _stem_to_title("Amazing Grace-PH-HD") == "Amazing Grace"

    def test_strips_hd_suffix(self):
        assert _stem_to_title("Amazing Grace-HD") == "Amazing Grace"

    def test_strips_16x9_suffix(self):
        assert _stem_to_title("Amazing Grace_16x9") == "Amazing Grace"

    def test_strips_ph20_hd_suffix(self):
        assert _stem_to_title("Amazing Grace-PH20-HD") == "Amazing Grace"

    def test_no_suffix_unchanged(self):
        assert _stem_to_title("Amazing Grace") == "Amazing Grace"

    def test_strips_dropbox_conflict(self):
        title = _stem_to_title("Amazing Grace (Matt's conflicted copy 2024-01-01)")
        assert title == "Amazing Grace"


class TestFilePriority:
    """Tests for _file_priority()."""

    def test_ph_hd_is_highest_priority(self):
        assert _file_priority("Song-PH-HD") == 0

    def test_hd_is_second(self):
        assert _file_priority("Song-HD") == 1

    def test_ph20_is_third(self):
        assert _file_priority("Song-PH20") == 2

    def test_plain_is_lowest(self):
        assert _file_priority("Song_16x9") == 3


class TestLookupSongCredits:
    """Tests for lookup_song_credits()."""

    def test_found_returns_credits(self):
        index = {
            "amazing grace": {
                "display_title": "Amazing Grace",
                "words_by": "John Newton",
                "music_by": None,
                "arranger": None,
            }
        }
        result = lookup_song_credits("amazing grace", index)
        assert result is not None
        assert result["words_by"] == "John Newton"
        assert result["music_by"] is None

    def test_not_found_returns_none(self):
        index = {}
        result = lookup_song_credits("missing song", index)
        assert result is None

    def test_returns_all_credit_fields(self):
        index = {
            "holy holy holy": {
                "display_title": "Holy Holy Holy",
                "words_by": "Reginald Heber",
                "music_by": "John Dykes",
                "arranger": "R. Dan Dalzell",
            }
        }
        result = lookup_song_credits("holy holy holy", index)
        assert result["words_by"] == "Reginald Heber"
        assert result["music_by"] == "John Dykes"
        assert result["arranger"] == "R. Dan Dalzell"


class TestSaveLoadLibraryIndex:
    """Tests for save_library_index() and load_library_index()."""

    def test_round_trip(self):
        index = {
            "amazing grace": {
                "display_title": "Amazing Grace",
                "words_by": "John Newton",
                "music_by": None,
                "arranger": None,
            },
            "holy holy holy": {
                "display_title": "Holy Holy Holy",
                "words_by": "Reginald Heber",
                "music_by": "John Dykes",
                "arranger": None,
            },
        }

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "index.json"
            save_library_index(index, path)
            assert path.exists()

            loaded = load_library_index(path)
            assert loaded == index

    def test_saves_valid_json(self):
        index = {"test song": {"display_title": "Test Song", "words_by": "Author", "music_by": None, "arranger": None}}

        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "index.json"
            save_library_index(index, path)

            # Verify it's valid JSON
            with open(path) as f:
                data = json.load(f)
            assert "test song" in data

    def test_creates_parent_directory(self):
        index = {}
        with TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "subdir" / "deep" / "index.json"
            save_library_index(index, path)
            assert path.exists()


class TestReadPptAuthor:
    """Tests for read_ppt_author() — olefile-based OLE metadata reading (#24)."""

    def test_returns_author_from_ole_metadata(self, tmp_path):
        """Returns the Author field from OLE SummaryInformation via olefile."""
        dummy_ppt = tmp_path / "Amazing Grace-PH-HD.ppt"
        dummy_ppt.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")  # OLE magic

        mock_meta = MagicMock()
        mock_meta.author = b"John Newton/William Walker"
        mock_ole = MagicMock()
        mock_ole.get_metadata.return_value = mock_meta

        with patch("worship_catalog.library.olefile") as mock_olefile_mod:
            mock_olefile_mod.OleFileIO.return_value.__enter__ = lambda s: mock_ole
            mock_olefile_mod.OleFileIO.return_value.__exit__ = MagicMock(return_value=False)
            result = read_ppt_author(dummy_ppt)

        assert result == "John Newton/William Walker"

    def test_returns_none_when_author_is_none(self, tmp_path):
        """Returns None when the Author field is absent."""
        dummy_ppt = tmp_path / "song.ppt"
        dummy_ppt.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")

        mock_meta = MagicMock()
        mock_meta.author = None
        mock_ole = MagicMock()
        mock_ole.get_metadata.return_value = mock_meta

        with patch("worship_catalog.library.olefile") as mock_olefile_mod:
            mock_olefile_mod.OleFileIO.return_value.__enter__ = lambda s: mock_ole
            mock_olefile_mod.OleFileIO.return_value.__exit__ = MagicMock(return_value=False)
            result = read_ppt_author(dummy_ppt)

        assert result is None

    def test_returns_none_on_invalid_file(self, tmp_path):
        """Returns None when olefile raises an exception (not a valid OLE file)."""
        dummy_ppt = tmp_path / "not_an_ole.ppt"
        dummy_ppt.write_bytes(b"not ole content")

        with patch("worship_catalog.library.olefile") as mock_olefile_mod:
            mock_olefile_mod.OleFileIO.side_effect = OSError("not a valid OLE file")
            result = read_ppt_author(dummy_ppt)

        assert result is None

    def test_does_not_call_subprocess(self, tmp_path):
        """The olefile implementation must not fall back to subprocess.run."""
        import subprocess
        dummy_ppt = tmp_path / "song.ppt"
        dummy_ppt.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")

        mock_meta = MagicMock()
        mock_meta.author = b"Test Author"
        mock_ole = MagicMock()
        mock_ole.get_metadata.return_value = mock_meta

        with patch("worship_catalog.library.olefile") as mock_olefile_mod:
            mock_olefile_mod.OleFileIO.return_value.__enter__ = lambda s: mock_ole
            mock_olefile_mod.OleFileIO.return_value.__exit__ = MagicMock(return_value=False)
            with patch.object(subprocess, "run") as mock_subprocess:
                read_ppt_author(dummy_ppt)

        mock_subprocess.assert_not_called()
