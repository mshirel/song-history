"""Unit tests for worship_catalog.extractor internal functions."""

import io
import zipfile
from pathlib import Path

from worship_catalog.extractor import (
    _create_song_occurrence,
    _extract_title_candidates,
    _group_song_slides,
    _is_song_title_slide,
    extract_songs,
)
from worship_catalog.pptx_reader import Slide, SlideImage, SlideText


def make_slide(
    index: int = 0,
    lines: list[str] | None = None,
    hidden: bool = False,
    image_blobs: list[bytes | None] | None = None,
) -> Slide:
    text = SlideText(text_lines=lines or [])
    images = [SlideImage(shape_id=i + 1, blob=b) for i, b in enumerate(image_blobs or [])]
    return Slide(index=index, hidden=hidden, text=text, images=images)


class TestExtractTitleCandidates:
    def test_empty_slide_returns_empty(self):
        slide = make_slide(lines=[])
        assert _extract_title_candidates(slide) == []

    def test_copyright_line_filtered(self):
        slide = make_slide(lines=["Copyright 2020 by Acme Publishing"])
        assert _extract_title_candidates(slide) == []

    def test_long_line_over_120_chars_filtered(self):
        slide = make_slide(lines=["A" * 121])
        assert _extract_title_candidates(slide) == []

    def test_single_char_filtered(self):
        slide = make_slide(lines=["A"])
        assert _extract_title_candidates(slide) == []

    def test_scripture_reference_filtered(self):
        slide = make_slide(lines=["John 3:16"])
        assert _extract_title_candidates(slide) == []

    def test_normal_title_returned(self):
        slide = make_slide(lines=["Amazing Grace"])
        assert "Amazing Grace" in _extract_title_candidates(slide)

    def test_offering_line_filtered(self):
        slide = make_slide(lines=["Giving Online"])
        assert _extract_title_candidates(slide) == []

    def test_multiple_lines_mixed(self):
        slide = make_slide(lines=["Amazing Grace", "Copyright 2020", "How Sweet the Sound"])
        candidates = _extract_title_candidates(slide)
        assert "Amazing Grace" in candidates
        assert "How Sweet the Sound" in candidates
        assert len([c for c in candidates if "copyright" in c.lower()]) == 0


class TestIsSongTitleSlide:
    def test_paperlesshymnal_marker_returns_true(self):
        slide = make_slide(lines=["Amazing Grace", "PaperlessHymnal.com"])
        assert _is_song_title_slide(slide) is True

    def test_taylor_publications_marker_returns_true(self):
        slide = make_slide(lines=["How Great Thou Art", "Taylor Publications"])
        assert _is_song_title_slide(slide) is True

    def test_verse_prefix_returns_true(self):
        slide = make_slide(lines=["1 – Amazing grace, how sweet the sound"])
        assert _is_song_title_slide(slide) is True

    def test_chorus_prefix_returns_true(self):
        slide = make_slide(lines=["Chorus – How great thou art"])
        assert _is_song_title_slide(slide) is True

    def test_plain_prose_returns_false(self):
        slide = make_slide(lines=["This is a sermon slide about faith and hope."])
        assert _is_song_title_slide(slide) is False

    def test_empty_slide_returns_false(self):
        slide = make_slide(lines=[])
        assert _is_song_title_slide(slide) is False


class TestGroupSongSlides:
    def test_empty_list_returns_empty(self):
        assert _group_song_slides([]) == []

    def test_single_titled_song_multiple_slides(self):
        """Multiple slides with same canonical title stay in one group."""
        slides = [
            make_slide(0, ["Amazing Grace", "PaperlessHymnal.com"]),
            make_slide(1, ["Amazing Grace"]),  # same canonical — continues group
            make_slide(2, ["Amazing Grace"]),
        ]
        groups = _group_song_slides(slides)
        assert len(groups) == 1
        assert groups[0][0] == "amazing grace"

    def test_two_songs_with_title_slides(self):
        slides = [
            make_slide(0, ["Amazing Grace", "PaperlessHymnal.com"]),
            make_slide(1, ["Amazing Grace"]),
            make_slide(2, ["How Great Thou Art", "PaperlessHymnal.com"]),
            make_slide(3, ["How Great Thou Art"]),
        ]
        groups = _group_song_slides(slides)
        assert len(groups) == 2
        canonicals = [c for c, _ in groups]
        assert "amazing grace" in canonicals
        assert "how great thou art" in canonicals

    def test_five_consecutive_empty_slides_closes_group(self):
        slides = [
            make_slide(0, ["Amazing Grace", "PaperlessHymnal.com"]),
            make_slide(1, []),  # image-only
            make_slide(2, []),
            make_slide(3, []),
            make_slide(4, []),
            make_slide(5, []),  # 5th empty — closes group
            make_slide(6, ["How Great Thou Art", "PaperlessHymnal.com"]),
        ]
        groups = _group_song_slides(slides)
        assert len(groups) == 2

    def test_skip_offering_slide(self):
        slides = [
            make_slide(0, ["Giving Online"]),
        ]
        groups = _group_song_slides(slides)
        assert groups == []


class TestCreateSongOccurrence:
    def test_returns_song_occurrence_with_correct_ordinal(self):
        slides = [make_slide(0, ["Amazing Grace", "PaperlessHymnal.com"])]
        result = _create_song_occurrence(1, "amazing grace", slides)
        assert result.ordinal == 1

    def test_display_title_extracted_from_slide(self):
        slides = [make_slide(0, ["Amazing Grace", "PaperlessHymnal.com"])]
        result = _create_song_occurrence(1, "amazing grace", slides)
        assert result.display_title == "Amazing Grace"

    def test_falls_back_to_canonical_when_no_text(self):
        slides = [make_slide(0, [])]
        result = _create_song_occurrence(1, "amazing grace", slides)
        assert result.display_title == "amazing grace"

    def test_slide_range_set_correctly(self):
        slides = [
            make_slide(3, ["1 – Amazing grace"]),
            make_slide(4, ["2 – That saved a wretch"]),
        ]
        result = _create_song_occurrence(1, "amazing grace", slides)
        assert result.first_slide_index == 3
        assert result.last_slide_index == 4

    def test_ocr_not_called_when_credits_found_in_text(self, monkeypatch):
        """If credits are in text, OCR should not be called."""
        called = []
        monkeypatch.setattr(
            "worship_catalog.extractor.extract_credits_via_vision",
            lambda blob: called.append(blob) or "Words: X",
        )
        slides = [
            make_slide(0, ["Amazing Grace", "Words: John Newton", "PaperlessHymnal.com"],
                       image_blobs=[b"\xff\xd8"])
        ]
        _create_song_occurrence(1, "amazing grace", slides, use_ocr=True)
        assert called == [], "OCR should not be called when credits found in text"

    def test_ocr_not_called_when_no_image(self, monkeypatch):
        """If slide has no image, OCR should not be called even when use_ocr=True."""
        called = []
        monkeypatch.setattr(
            "worship_catalog.extractor.extract_credits_via_vision",
            lambda blob: called.append(blob) or "Words: X",
        )
        slides = [make_slide(0, ["Amazing Grace"])]
        _create_song_occurrence(1, "amazing grace", slides, use_ocr=True)
        assert called == []


class TestExtractSongsFileHash:
    """Tests for ExtractionResult.file_hash — issue #15."""

    def _minimal_pptx(self) -> bytes:
        """Build a minimal valid PPTX (ZIP) with a single blank slide."""
        ns_pkg = "http://schemas.openxmlformats.org/package/2006"
        ns_doc = "http://schemas.openxmlformats.org/officeDocument/2006"
        ns_pml = "http://schemas.openxmlformats.org/presentationml/2006/main"
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<Types xmlns="{ns_pkg}/content-types">'
                '<Default Extension="rels" ContentType='
                f'"{ns_pkg}/relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/ppt/presentation.xml" ContentType='
                '"application/vnd.openxmlformats-officedocument'
                '.presentationml.presentation.main+xml"/>'
                "</Types>",
            )
            zf.writestr(
                "_rels/.rels",
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<Relationships xmlns="{ns_pkg}/relationships">'
                f'<Relationship Id="rId1" Type="{ns_doc}/relationships'
                '/officeDocument" Target="ppt/presentation.xml"/>'
                "</Relationships>",
            )
            zf.writestr(
                "ppt/presentation.xml",
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<p:presentation xmlns:p="{ns_pml}"'
                f' xmlns:r="{ns_doc}/relationships">'
                '<p:sldMasterIdLst/>'
                '<p:sldSz cx="9144000" cy="5143500"/>'
                '<p:notesSz cx="6858000" cy="9144000"/>'
                "</p:presentation>",
            )
            zf.writestr(
                "ppt/_rels/presentation.xml.rels",
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<Relationships xmlns="{ns_pkg}/relationships">'
                "</Relationships>",
            )
        return buf.getvalue()

    def test_file_hash_is_non_empty(self, tmp_path: Path) -> None:
        """ExtractionResult.file_hash must be a non-empty string."""
        pptx_path = tmp_path / "test.pptx"
        pptx_path.write_bytes(self._minimal_pptx())
        result = extract_songs(pptx_path)
        assert result.file_hash, "file_hash must not be empty"
        assert isinstance(result.file_hash, str)

    def test_file_hash_is_stable(self, tmp_path: Path) -> None:
        """Same file produces the same hash on repeated calls."""
        pptx_bytes = self._minimal_pptx()
        pptx_path = tmp_path / "test.pptx"
        pptx_path.write_bytes(pptx_bytes)
        result1 = extract_songs(pptx_path)
        result2 = extract_songs(pptx_path)
        assert result1.file_hash == result2.file_hash

    def test_different_files_produce_different_hashes(self, tmp_path: Path) -> None:
        """Different file content produces different hashes."""
        bytes_a = self._minimal_pptx()
        bytes_b = bytes_a + b"\x00"  # trivially different content
        path_a = tmp_path / "a.pptx"
        path_b = tmp_path / "b.pptx"
        path_a.write_bytes(bytes_a)
        path_b.write_bytes(bytes_b)
        result_a = extract_songs(path_a)
        result_b = extract_songs(path_b)
        assert result_a.file_hash != result_b.file_hash
