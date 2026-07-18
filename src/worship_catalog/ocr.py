"""Vision-based OCR for extracting song credits from slide images."""

import base64
import json
import logging
import os
import re
import time
from dataclasses import dataclass

import httpx

from worship_catalog.normalize import _SCRIPTURE_RE, _TITLE_MAX_LENGTH, is_non_song_title

# Provider/model defaults; both are overridable for benchmarking and fallback.
_OCR_PROVIDER_DEFAULT: str = "openrouter"
_OCR_MODEL_DEFAULT: str = "google/gemini-2.5-flash-lite"
_ANTHROPIC_MODEL_DEFAULT: str = "claude-haiku-4-5-20251001"
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_OPENROUTER_REFERER = "https://github.com/mshirel/song-history"
_MAX_OCR_TOKENS: int = 200  # Sufficient for a single credits line
_MAX_RETRIES: int = 3
_RETRY_BASE_DELAY: float = 1.0  # seconds; doubles on each retry


def _get_ocr_provider() -> str:
    """Return the configured provider, with legacy-key compatibility."""
    configured = os.environ.get("WORSHIP_OCR_PROVIDER")
    if configured:
        provider = configured.strip().lower()
        if provider not in {"openrouter", "anthropic"}:
            raise ValueError(
                "WORSHIP_OCR_PROVIDER must be 'openrouter' or 'anthropic'"
            )
        return provider
    # Existing CLI installations that only have the legacy key keep working;
    # new installs (and keyless error messages) use the OpenRouter default.
    if os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("OPENROUTER_API_KEY"):
        return "anthropic"
    return _OCR_PROVIDER_DEFAULT


def _get_ocr_model(provider: str | None = None) -> str:
    """Return the OCR model name, honouring the WORSHIP_OCR_MODEL env var."""
    configured = os.environ.get("WORSHIP_OCR_MODEL")
    if configured:
        return configured
    if provider == "anthropic":
        return _ANTHROPIC_MODEL_DEFAULT
    return _OCR_MODEL_DEFAULT

_log = logging.getLogger(__name__)

# Output validation (issue #42 — CWE-94 prompt injection hardening)
_CREDITS_RE = re.compile(
    r"\b(words|music|arr|arrangement|lyrics|composer)\b",
    re.IGNORECASE,
)
# Issue #61 — require at least one "First Last" name pattern so that hallucinated
# phrases like "Words by the congregation" are rejected.
_NAME_RE = re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+")
_MAX_OCR_OUTPUT_LENGTH = 300


@dataclass(frozen=True)
class ScoreHeader:
    """Structured classification and header text for one image-only slide."""

    is_score: bool
    title: str | None
    credits: str | None
    model: str


def _validate_ocr_output(text: str) -> str | None:
    """Return text if it looks like credits; None otherwise.

    Rejects output that:
    - Exceeds _MAX_OCR_OUTPUT_LENGTH characters (likely injected content)
    - Contains no recognizable credits keywords (not a credits line at all)
    - Contains credit keywords but no "First Last" name-like pattern (issue #61)
    """
    if len(text) > _MAX_OCR_OUTPUT_LENGTH:
        return None
    if not _CREDITS_RE.search(text):
        return None
    if not _NAME_RE.search(text):
        return None
    return text


def _iter_text_blocks(content: object) -> list[str]:
    """Return text payloads from Claude response blocks, tolerating absent/empty blocks."""
    if not isinstance(content, list):
        return []

    texts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        block_type = getattr(block, "type", None)
        if isinstance(text, str) and (block_type == "text" or not isinstance(block_type, str)):
            texts.append(text)
    return texts


def _retryable_ocr_errors(anthropic: object) -> tuple[type[BaseException], ...]:
    """Return only transient Anthropic exception classes."""
    retryable_names = ("RateLimitError", "InternalServerError", "APIConnectionError")
    retryable: list[type[BaseException]] = []
    for name in retryable_names:
        exc_type = getattr(anthropic, name, None)
        if isinstance(exc_type, type) and issubclass(exc_type, BaseException):
            retryable.append(exc_type)
    return tuple(retryable)


def _call_anthropic(image_bytes: bytes, prompt: str) -> str | None:
    """Send one vision request through the legacy Anthropic backend."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise OSError(
            "ANTHROPIC_API_KEY is not set. Export it before using the "
            "anthropic OCR provider."
        )

    try:
        import anthropic
    except ImportError as err:
        raise ImportError(
            "The 'anthropic' package is required for the anthropic OCR provider."
        ) from err

    client = anthropic.Anthropic(api_key=api_key)
    request_kwargs = {
        "model": _get_ocr_model("anthropic"),
        "max_tokens": _MAX_OCR_TOKENS,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": _detect_media_type(image_bytes),
                            "data": base64.standard_b64encode(image_bytes).decode("utf-8"),
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }

    retryable = _retryable_ocr_errors(anthropic)
    last_exc: BaseException | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            message = client.messages.create(**request_kwargs)
            texts = _iter_text_blocks(message.content)
            return texts[0].strip() if texts else None
        except retryable as exc:
            last_exc = exc
            if attempt >= _MAX_RETRIES - 1:
                raise
            delay = _RETRY_BASE_DELAY * (2**attempt)
            _log.warning(
                "OCR API transient error (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1,
                _MAX_RETRIES,
                delay,
                exc,
            )
            time.sleep(delay)
    raise last_exc  # type: ignore[misc]


def _call_openrouter(
    image_bytes: bytes,
    prompt: str,
    *,
    json_response: bool = False,
) -> str | None:
    """Send one OpenAI-shaped vision request through OpenRouter."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise OSError(
            "OPENROUTER_API_KEY is not set. Export it before using --ocr."
        )

    media_type = _detect_media_type(image_bytes)
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    payload: dict[str, object] = {
        "model": _get_ocr_model("openrouter"),
        "max_tokens": _MAX_OCR_TOKENS,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{image_b64}",
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }
    if json_response:
        payload["response_format"] = {"type": "json_object"}

    response = httpx.post(
        _OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": _OPENROUTER_REFERER,
            "X-Title": "song-history",
        },
        json=payload,
        timeout=30.0,
    )
    response.raise_for_status()
    response_payload = response.json()
    try:
        content = response_payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    return content.strip() if isinstance(content, str) else None


def _call_vision(
    image_bytes: bytes,
    prompt: str,
    *,
    json_response: bool = False,
) -> str | None:
    """Dispatch a vision request to the configured provider."""
    provider = _get_ocr_provider()
    if provider == "anthropic":
        return _call_anthropic(image_bytes, prompt)
    return _call_openrouter(image_bytes, prompt, json_response=json_response)


def _validate_ocr_title(title: str) -> str | None:
    """Return a safe song title or ``None`` for footer/prose/scripture text."""
    stripped = " ".join(title.split())
    if not stripped or len(stripped) > _TITLE_MAX_LENGTH:
        return None
    if _SCRIPTURE_RE.match(stripped) or is_non_song_title(stripped):
        return None
    lowered = stripped.lower()
    if lowered in {
        "announcements",
        "closing prayer",
        "giving",
        "offering",
        "opening prayer",
        "scripture reading",
        "the lord's supper",
        "welcome",
    }:
        return None
    if any(
        marker in lowered
        for marker in ("copyright", "all rights reserved", "used by permission")
    ):
        return None
    return stripped


def _validate_score_credits(credits: object) -> str | None:
    """Validate structured score credits without rejecting all-uppercase names."""
    if not isinstance(credits, str):
        return None
    stripped = " ".join(credits.split())
    if not stripped or len(stripped) > _MAX_OCR_OUTPUT_LENGTH:
        return None
    if not _CREDITS_RE.search(stripped):
        return None
    return stripped


def _parse_score_header(raw: str, model: str) -> ScoreHeader | None:
    """Parse defensive JSON, tolerating markdown fences around the object."""
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        payload = json.loads(raw[start : end + 1])
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("is_score"), bool):
        return None
    is_score = payload["is_score"]
    if not is_score:
        return ScoreHeader(False, None, None, model)
    raw_title = payload.get("title")
    title = _validate_ocr_title(raw_title) if isinstance(raw_title, str) else None
    credits = _validate_score_credits(payload.get("credits"))
    return ScoreHeader(True, title, credits, model)


def extract_score_header_via_vision(image_bytes: bytes) -> ScoreHeader | None:
    """Classify a slide and recover its printed score header as structured JSON."""
    prompt = (
        "Classify this worship slide image. A music-score page contains visible "
        "musical staff lines and notation; sermon art, logos, scripture, photos, "
        "and title cards are not score pages. Return ONLY JSON with exactly these "
        "fields: {\"is_score\": boolean, \"title\": string|null, "
        "\"credits\": string|null}. For a score, title is the printed song header "
        "when legible and credits is any Words/Music/Arranged-by line. For a "
        "non-score, both text fields must be null. Do not infer missing text."
    )
    raw = _call_vision(image_bytes, prompt, json_response=True)
    if not raw:
        return None
    return _parse_score_header(raw, _get_ocr_model(_get_ocr_provider()))


def extract_credits_via_vision(image_bytes: bytes) -> str | None:
    """
    Use the configured vision provider to extract a credits line.

    Targets the "Words: X / Music: Y" or "Words and Music by: X" line
    commonly found at the bottom of Taylor Publications / hymnal slides.

    Args:
        image_bytes: Raw image bytes (JPEG, PNG, etc.)

    Returns:
        The raw credits text if found, or None if no credits detected or
        if the selected provider's API key is not configured.
    """
    prompt = (
        "This is a worship song slide image. Find and return ONLY the song "
        "credits line — the line that starts with 'Words:', 'Music:', 'Words "
        "and Music:', 'Words & Music:', or similar. Return the exact text of "
        "that line only. If no credits line is visible, return the word 'none'."
    )
    raw = _call_vision(image_bytes, prompt)
    if raw is None:
        return None
    if raw.lower() == "none" or not raw:
        return None
    return _validate_ocr_output(raw)


def _detect_media_type(image_bytes: bytes) -> str:
    """Detect image media type from magic bytes."""
    if image_bytes[:2] == b"\xff\xd8":
        return "image/jpeg"
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:4] in (b"GIF8", b"GIF9"):
        return "image/gif"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    # Default to JPEG (most common for PPTX embedded images)
    return "image/jpeg"
