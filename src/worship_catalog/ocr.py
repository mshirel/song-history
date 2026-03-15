"""Vision-based OCR for extracting song credits from slide images."""

import base64
import os
import re

# Output validation (issue #42 — CWE-94 prompt injection hardening)
_CREDITS_RE = re.compile(
    r"\b(words|music|arr|arrangement|lyrics|composer)\b",
    re.IGNORECASE,
)
_MAX_OCR_OUTPUT_LENGTH = 300


def _validate_ocr_output(text: str) -> str | None:
    """Return text if it looks like credits; None otherwise.

    Rejects output that:
    - Exceeds _MAX_OCR_OUTPUT_LENGTH characters (likely injected content)
    - Contains no recognizable credits keywords (not a credits line at all)
    """
    if len(text) > _MAX_OCR_OUTPUT_LENGTH:
        return None
    if not _CREDITS_RE.search(text):
        return None
    return text


def extract_credits_via_vision(image_bytes: bytes) -> str | None:
    """
    Use Claude Vision API to extract the credits line from a slide image.

    Targets the "Words: X / Music: Y" or "Words and Music by: X" line
    commonly found at the bottom of Taylor Publications / hymnal slides.

    Args:
        image_bytes: Raw image bytes (JPEG, PNG, etc.)

    Returns:
        The raw credits text if found, or None if no credits detected or
        if the API key is not configured.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise OSError(
            "ANTHROPIC_API_KEY is not set. "
            "Export it before using --ocr: export ANTHROPIC_API_KEY=sk-ant-..."
        )

    try:
        import anthropic
    except ImportError as err:
        raise ImportError(
            "The 'anthropic' package is required for OCR. "
            "Install it with: pip install anthropic"
        ) from err

    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    # Detect media type from magic bytes
    media_type = _detect_media_type(image_bytes)

    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "This is a worship song slide image. "
                            "Find and return ONLY the song credits line — "
                            "the line that starts with 'Words:', 'Music:', "
                            "'Words and Music:', 'Words & Music:', or similar. "
                            "Return the exact text of that line only. "
                            "If no credits line is visible, return the word 'none'."
                        ),
                    },
                ],
            }
        ],
    )

    raw = message.content[0].text.strip()
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
