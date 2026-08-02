"""Worship Slide Deck Song Catalog - Extract songs from PowerPoint presentations."""

from __future__ import annotations

import importlib.metadata

try:
    __version__ = importlib.metadata.version("worship-catalog")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0+unknown"
