#!/usr/bin/env python3
"""Rasterise the brand icon assets from the SVG masters (#586).

Run from the repo root:

    uv run --frozen python scripts/generate-icons.py

The masters in ``assets/brand/`` are the source of truth; everything under
``src/worship_catalog/web/static/`` is generated.  Regenerate rather than
hand-editing, so the assets always match the spec in ``docs/brand-icon.md``.

Two things here are load-bearing and easy to get wrong:

* **The 16px frame comes from a different master.**  Scaled straight down, the
  note's stem falls under two device pixels and greys out.  ``icon-16.svg``
  redraws it for the pixel grid with a fatter stem, which is why the ``.ico``
  is assembled from two masters rather than one.

* **Pillow's multi-resolution ``.ico`` writer.**  ``.save()`` must be called on
  the **largest** frame with the smaller ones passed via ``append_images``.
  Saving from the 16px render silently produces a single-frame ``.ico`` and
  reports success.  ``tests/test_favicon.py`` asserts the frame count rather
  than trusting the write.
"""

from __future__ import annotations

import io
from pathlib import Path

import cairosvg
from PIL import Image

_REPO_ROOT = Path(__file__).resolve().parent.parent
_MASTERS = _REPO_ROOT / "assets" / "brand"
_STATIC = _REPO_ROOT / "src" / "worship_catalog" / "web" / "static"

# The .ico carries three frames.  16 is hinted from its own master; 32 and 48
# come from the standard one.
_ICO_FRAMES: tuple[tuple[int, str], ...] = (
    (48, "icon.svg"),
    (32, "icon.svg"),
    (16, "icon-16.svg"),
)

# Standalone PNGs: (filename, size, master, flatten)
#
# `flatten` composites the render onto the tile navy, dropping the alpha
# channel.  iOS ignores transparency on an apple-touch-icon and composites it
# onto black, so the rounded corners of the tile would come out as black
# wedges around a navy square.  Flattening makes the corners navy instead,
# which is what the platform's own rounding then masks.
_PNGS: tuple[tuple[str, int, str, bool], ...] = (
    ("icon-192.png", 192, "icon.svg", False),
    ("icon-512.png", 512, "icon.svg", False),
    ("icon-maskable-512.png", 512, "icon-maskable.svg", False),
    ("apple-touch-icon.png", 180, "icon.svg", True),
)

_THEME_COLOR = "#1a1a2e"


def _render(master: str, size: int) -> Image.Image:
    """Rasterise one SVG master at an exact pixel size."""
    png = cairosvg.svg2png(
        url=str(_MASTERS / master), output_width=size, output_height=size
    )
    return Image.open(io.BytesIO(png)).convert("RGBA")


def _write_ico(destination: Path) -> None:
    frames = [_render(master, size) for size, master in _ICO_FRAMES]
    largest, *rest = frames  # _ICO_FRAMES is ordered largest-first — see module docstring
    largest.save(
        destination,
        format="ICO",
        sizes=[(size, size) for size, _ in _ICO_FRAMES],
        append_images=rest,
    )


def _write_manifest(destination: Path) -> None:
    destination.write_text(
        "\n".join(
            [
                "{",
                '  "name": "Song History",',
                '  "short_name": "Song History",',
                '  "icons": [',
                '    { "src": "/static/icon-192.png", "sizes": "192x192", '
                '"type": "image/png" },',
                '    { "src": "/static/icon-512.png", "sizes": "512x512", '
                '"type": "image/png" },',
                '    { "src": "/static/icon-maskable-512.png", "sizes": "512x512", '
                '"type": "image/png", "purpose": "maskable" }',
                "  ],",
                f'  "theme_color": "{_THEME_COLOR}",',
                f'  "background_color": "{_THEME_COLOR}",',
                '  "display": "standalone",',
                '  "start_url": "/"',
                "}",
                "",
            ]
        )
    )


def main() -> None:
    _STATIC.mkdir(parents=True, exist_ok=True)

    _write_ico(_STATIC / "favicon.ico")
    print(f"favicon.ico  frames={[size for size, _ in _ICO_FRAMES]}")

    for name, size, master, flatten in _PNGS:
        image = _render(master, size)
        if flatten:
            background = Image.new("RGBA", image.size, _THEME_COLOR)
            image = Image.alpha_composite(background, image).convert("RGB")
        image.save(_STATIC / name, format="PNG")
        print(f"{name}  {size}x{size}  from {master}{'  (flattened)' if flatten else ''}")

    _write_manifest(_STATIC / "site.webmanifest")
    print("site.webmanifest")


if __name__ == "__main__":
    main()
