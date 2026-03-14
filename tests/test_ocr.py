"""Tests for worship_catalog.ocr — Vision API credit extraction."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from worship_catalog.extractor import OcrBudget
from worship_catalog.ocr import _detect_media_type, extract_credits_via_vision


class TestOcrBudget:
    """Tests for the OcrBudget call-cap class."""

    def test_unlimited_budget_always_allows(self):
        budget = OcrBudget(max_calls=None)
        for _ in range(1000):
            assert budget.consume() is True

    def test_zero_budget_never_allows(self):
        budget = OcrBudget(max_calls=0)
        assert budget.consume() is False

    def test_budget_allows_up_to_max(self):
        budget = OcrBudget(max_calls=3)
        assert budget.consume() is True
        assert budget.consume() is True
        assert budget.consume() is True
        assert budget.consume() is False

    def test_calls_made_increments_on_success(self):
        budget = OcrBudget(max_calls=5)
        budget.consume()
        budget.consume()
        assert budget.calls_made == 2

    def test_calls_made_does_not_increment_when_capped(self):
        budget = OcrBudget(max_calls=1)
        budget.consume()  # uses the 1 allowed call
        budget.consume()  # capped — should not increment
        assert budget.calls_made == 1

    def test_is_capped_false_when_unlimited(self):
        budget = OcrBudget(max_calls=None)
        budget.consume()
        assert budget.is_capped is False

    def test_is_capped_true_when_limit_reached(self):
        budget = OcrBudget(max_calls=2)
        budget.consume()
        assert budget.is_capped is False
        budget.consume()
        assert budget.is_capped is True

    def test_remaining_none_when_unlimited(self):
        budget = OcrBudget(max_calls=None)
        assert budget.remaining is None

    def test_remaining_decrements(self):
        budget = OcrBudget(max_calls=5)
        assert budget.remaining == 5
        budget.consume()
        assert budget.remaining == 4


class TestDetectMediaType:
    """Tests for magic-byte media type detection."""

    def test_jpeg_magic_bytes(self):
        assert _detect_media_type(b"\xff\xd8\x00\x00") == "image/jpeg"

    def test_png_magic_bytes(self):
        assert _detect_media_type(b"\x89PNG\r\n\x1a\n") == "image/png"

    def test_gif87_magic_bytes(self):
        assert _detect_media_type(b"GIF87a...") == "image/gif"

    def test_gif89_magic_bytes(self):
        assert _detect_media_type(b"GIF89a...") == "image/gif"

    def test_webp_magic_bytes(self):
        data = b"RIFF\x00\x00\x00\x00WEBP"
        assert _detect_media_type(data) == "image/webp"

    def test_unknown_defaults_to_jpeg(self):
        assert _detect_media_type(b"\x00\x00\x00\x00") == "image/jpeg"

    def test_empty_bytes_defaults_to_jpeg(self):
        assert _detect_media_type(b"") == "image/jpeg"


class TestExtractCreditsViaVision:
    """Tests for the Vision API extraction function."""

    def test_raises_os_error_when_api_key_missing(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(OSError, match="ANTHROPIC_API_KEY"):
            extract_credits_via_vision(b"\xff\xd8\x00\x00")

    def test_raises_import_error_when_anthropic_missing(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        with patch.dict(sys.modules, {"anthropic": None}):
            with pytest.raises(ImportError, match="anthropic"):
                extract_credits_via_vision(b"\xff\xd8\x00\x00")

    def test_returns_none_when_api_returns_none_string(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_client.messages.create.return_value.content = [MagicMock(text="none")]
        mock_anthropic.Anthropic.return_value = mock_client
        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            result = extract_credits_via_vision(b"\xff\xd8\x00\x00")
        assert result is None

    def test_returns_none_when_api_returns_empty_string(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_client.messages.create.return_value.content = [MagicMock(text="")]
        mock_anthropic.Anthropic.return_value = mock_client
        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            result = extract_credits_via_vision(b"\xff\xd8\x00\x00")
        assert result is None

    def test_returns_credits_text_when_found(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_client.messages.create.return_value.content = [
            MagicMock(text="Words: John Newton / Music: Traditional")
        ]
        mock_anthropic.Anthropic.return_value = mock_client
        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            result = extract_credits_via_vision(b"\xff\xd8\x00\x00")
        assert result == "Words: John Newton / Music: Traditional"

    def test_strips_whitespace_from_result(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
        mock_anthropic = MagicMock()
        mock_client = MagicMock()
        mock_client.messages.create.return_value.content = [
            MagicMock(text="  Words: John Newton  ")
        ]
        mock_anthropic.Anthropic.return_value = mock_client
        with patch.dict(sys.modules, {"anthropic": mock_anthropic}):
            result = extract_credits_via_vision(b"\xff\xd8\x00\x00")
        assert result == "Words: John Newton"
