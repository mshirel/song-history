"""Per-slide scanned score grouping tests for issue #537."""

from unittest.mock import MagicMock

import pytest

import worship_catalog.extractor as extractor
from worship_catalog.extractor import OcrBudget
from worship_catalog.ocr import ScoreHeader
from worship_catalog.pptx_reader import Slide, SlideImage, SlideText


def _slide(index: int, lines: list[str] | None = None, blob: bytes | None = None) -> Slide:
    images = [SlideImage(shape_id=1, blob=blob)] if blob is not None else []
    return Slide(
        index=index,
        hidden=False,
        text=SlideText(text_lines=lines or []),
        images=images,
    )


def _header(
    title: str | None = "Goodness Of God",
    *,
    is_score: bool = True,
    credits: str | None = None,
) -> ScoreHeader:
    return ScoreHeader(
        is_score=is_score,
        title=title,
        credits=credits,
        model="google/gemini-2.5-flash-lite",
    )


class TestScoreImageSlidePattern:
    def test_image_only_score_run_groups_as_one_song(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        slides = [_slide(i, blob=f"score-{i}".encode()) for i in range(4)]
        vision = MagicMock(side_effect=[_header(), _header(None), _header(None), _header()])
        monkeypatch.setattr(extractor, "extract_score_header_via_vision", vision)

        result = extractor._group_song_slides_with_score_ocr(
            slides, OcrBudget(max_calls=10)
        )

        assert [(title, len(group)) for title, group in result.groups] == [
            ("goodness of god", 4)
        ]
        assert vision.call_count == 4
        info = result.score_groups[slides[0].index]
        assert info.display_title == "Goodness Of God"
        assert info.model == "google/gemini-2.5-flash-lite"

    def test_photo_background_slide_is_not_a_song(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vision = MagicMock(return_value=_header(None, is_score=False))
        monkeypatch.setattr(extractor, "extract_score_header_via_vision", vision)

        result = extractor._group_song_slides_with_score_ocr(
            [_slide(37, blob=b"giving-photo")], OcrBudget(max_calls=5)
        )

        assert result.groups == []
        vision.assert_called_once_with(b"giving-photo")

    def test_score_run_between_text_songs_is_not_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        slides = [
            _slide(0, ["Amazing Grace", "PaperlessHymnal.com"]),
            *[_slide(i, blob=f"score-{i}".encode()) for i in range(1, 5)],
            _slide(5, ["How Great Thou Art", "PaperlessHymnal.com"]),
        ]
        monkeypatch.setattr(
            extractor,
            "extract_score_header_via_vision",
            MagicMock(side_effect=[_header(), _header(None), _header(None), _header(None)]),
        )

        result = extractor._group_song_slides_with_score_ocr(
            slides, OcrBudget(max_calls=10)
        )

        assert [title for title, _ in result.groups] == [
            "amazing grace",
            "goodness of god",
            "how great thou art",
        ]
        assert len(result.groups[0][1]) == 1
        assert len(result.groups[1][1]) == 4

    def test_title_change_splits_contiguous_image_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        slides = [_slide(i, blob=str(i).encode()) for i in range(4)]
        monkeypatch.setattr(
            extractor,
            "extract_score_header_via_vision",
            MagicMock(
                side_effect=[
                    _header("Song A"),
                    _header(None),
                    _header("Song B"),
                    _header(None),
                ]
            ),
        )

        result = extractor._group_song_slides_with_score_ocr(
            slides, OcrBudget(max_calls=10)
        )

        assert [(title, len(group)) for title, group in result.groups] == [
            ("song a", 2),
            ("song b", 2),
        ]

    def test_nonscore_boundaries_are_excluded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        slides = [_slide(i, blob=str(i).encode()) for i in range(4)]
        monkeypatch.setattr(
            extractor,
            "extract_score_header_via_vision",
            MagicMock(
                side_effect=[
                    _header(None, is_score=False),
                    _header("Goodness Of God"),
                    _header(None),
                    _header(None, is_score=False),
                ]
            ),
        )

        result = extractor._group_song_slides_with_score_ocr(
            slides, OcrBudget(max_calls=10)
        )

        assert len(result.groups) == 1
        assert [slide.index for slide in result.groups[0][1]] == [1, 2]

    def test_no_score_pages_yields_no_song(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            extractor,
            "extract_score_header_via_vision",
            MagicMock(return_value=_header(None, is_score=False)),
        )
        budget = OcrBudget(max_calls=3)

        result = extractor._group_song_slides_with_score_ocr(
            [_slide(i, blob=str(i).encode()) for i in range(8)], budget
        )

        assert result.groups == []
        assert budget.calls_made == 3

    def test_budget_exhaustion_keeps_confirmed_score_tail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        vision = MagicMock(side_effect=[_header(), _header(None)])
        monkeypatch.setattr(extractor, "extract_score_header_via_vision", vision)
        budget = OcrBudget(max_calls=2)

        result = extractor._group_song_slides_with_score_ocr(
            [_slide(i, blob=str(i).encode()) for i in range(5)], budget
        )

        assert [(title, len(group)) for title, group in result.groups] == [
            ("goodness of god", 5)
        ]
        assert vision.call_count == 2

    def test_ocr_failure_does_not_fabricate_song(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            extractor, "extract_score_header_via_vision", MagicMock(return_value=None)
        )

        result = extractor._group_song_slides_with_score_ocr(
            [_slide(1, blob=b"unreadable")], OcrBudget(max_calls=5)
        )

        assert result.groups == []


class TestScoreOccurrenceMetadata:
    def test_recovered_title_credits_and_anomaly_flow_to_occurrence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        slide = _slide(39, blob=b"score")
        header = _header(
            "Goodness Of God",
            credits=(
                "Words and Music by JENN JOHNSON, ED CASH, JASON INGRAM, "
                "BEN FIELDING, and BRIAN JOHNSON / Arranged by Shane Coffman "
                "and Mark Simmons"
            ),
        )
        monkeypatch.setattr(
            extractor, "extract_score_header_via_vision", MagicMock(return_value=header)
        )
        grouped = extractor._group_song_slides_with_score_ocr(
            [slide], OcrBudget(max_calls=5)
        )
        info = grouped.score_groups[39]

        occurrence = extractor._create_song_occurrence(
            1,
            "goodness of god",
            [slide],
            display_title_override=info.display_title,
            credits_text_override=info.credits,
        )

        assert occurrence.display_title == "Goodness Of God"
        assert occurrence.words_by == (
            "JENN JOHNSON, ED CASH, JASON INGRAM, BEN FIELDING, and BRIAN JOHNSON"
        )
        assert occurrence.music_by == occurrence.words_by
        assert occurrence.arranger == "Shane Coffman and Mark Simmons"
        assert grouped.anomalies == [
            {
                "type": "score_image_ocr",
                "message": "title recovered from score image via OCR",
                "title": "Goodness Of God",
                "first_slide_index": 39,
                "model": "google/gemini-2.5-flash-lite",
            }
        ]
