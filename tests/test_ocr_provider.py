"""Provider and structured score-header OCR tests for issue #537."""

from unittest.mock import MagicMock

import pytest

import worship_catalog.ocr as ocr


@pytest.fixture(autouse=True)
def _openrouter_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WORSHIP_OCR_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test-key")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def _response(content: str) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {
        "choices": [{"message": {"content": content}}],
    }
    response.raise_for_status.return_value = None
    return response


class TestOpenRouterVisionProvider:
    def test_uses_openai_image_shape_and_attribution_headers(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        post = MagicMock(
            return_value=_response(
                '{"is_score":true,"title":"Goodness Of God","credits":null}'
            )
        )
        monkeypatch.setattr(ocr.httpx, "post", post)

        result = ocr.extract_score_header_via_vision(b"\xff\xd8image")

        assert result is not None
        assert result.is_score is True
        assert result.title == "Goodness Of God"
        _, kwargs = post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer or-test-key"
        assert kwargs["headers"]["HTTP-Referer"]
        assert kwargs["headers"]["X-Title"] == "song-history"
        payload = kwargs["json"]
        assert payload["model"] == "google/gemini-2.5-flash-lite"
        assert payload["response_format"] == {"type": "json_object"}
        image_part = payload["messages"][0]["content"][0]
        assert image_part["type"] == "image_url"
        assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")

    def test_model_slug_passes_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WORSHIP_OCR_MODEL", "openai/gpt-5-nano")
        post = MagicMock(
            return_value=_response(
                '{"is_score":false,"title":null,"credits":null}'
            )
        )
        monkeypatch.setattr(ocr.httpx, "post", post)

        ocr.extract_score_header_via_vision(b"\xff\xd8image")

        assert post.call_args.kwargs["json"]["model"] == "openai/gpt-5-nano"

    def test_plain_credit_extraction_does_not_force_json_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        post = MagicMock(
            return_value=_response("Words and Music by: Jenn Johnson and Ed Cash")
        )
        monkeypatch.setattr(ocr.httpx, "post", post)

        result = ocr.extract_credits_via_vision(b"\xff\xd8image")

        assert result == "Words and Music by: Jenn Johnson and Ed Cash"
        assert "response_format" not in post.call_args.kwargs["json"]

    def test_missing_key_is_actionable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY")

        with pytest.raises(OSError, match="OPENROUTER_API_KEY"):
            ocr.extract_score_header_via_vision(b"\xff\xd8image")

    def test_explicit_anthropic_provider_uses_legacy_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("WORSHIP_OCR_PROVIDER", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        anthropic_call = MagicMock(
            return_value='{"is_score":true,"title":"Amazing Grace","credits":null}'
        )
        openrouter_call = MagicMock()
        monkeypatch.setattr(ocr, "_call_anthropic", anthropic_call)
        monkeypatch.setattr(ocr, "_call_openrouter", openrouter_call)

        result = ocr.extract_score_header_via_vision(b"\xff\xd8image")

        assert result is not None and result.title == "Amazing Grace"
        anthropic_call.assert_called_once()
        openrouter_call.assert_not_called()


class TestStructuredScoreHeader:
    @pytest.mark.parametrize(
        ("content", "expected"),
        [
            ('{"is_score":false,"title":null,"credits":null}', (False, None)),
            ('{"is_score":true,"title":null,"credits":null}', (True, None)),
        ],
    )
    def test_preserves_score_tri_state(
        self,
        monkeypatch: pytest.MonkeyPatch,
        content: str,
        expected: tuple[bool, str | None],
    ) -> None:
        monkeypatch.setattr(ocr.httpx, "post", MagicMock(return_value=_response(content)))

        result = ocr.extract_score_header_via_vision(b"\xff\xd8image")

        assert result is not None
        assert (result.is_score, result.title) == expected

    def test_returns_validated_title_and_credits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        content = (
            '```json\n{"is_score":true,"title":"Goodness Of God",'
            '"credits":"Words and Music by JENN JOHNSON and ED CASH"}\n```'
        )
        monkeypatch.setattr(ocr.httpx, "post", MagicMock(return_value=_response(content)))

        result = ocr.extract_score_header_via_vision(b"\xff\xd8image")

        assert result is not None
        assert result.title == "Goodness Of God"
        assert result.credits == "Words and Music by JENN JOHNSON and ED CASH"

    def test_malformed_json_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            ocr.httpx,
            "post",
            MagicMock(return_value=_response("this is not JSON")),
        )

        assert ocr.extract_score_header_via_vision(b"\xff\xd8image") is None

    @pytest.mark.parametrize(
        "title",
        ["A" * 121, "John 3:16", "Closing Prayer", "Copyright 2018 Alletrop"],
    )
    def test_title_validation_rejects_non_song_text(self, title: str) -> None:
        assert ocr._validate_ocr_title(title) is None
