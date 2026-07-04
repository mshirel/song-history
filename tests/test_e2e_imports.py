"""Collection-safety checks for Playwright modules."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def test_e2e_module_imports_cleanly_for_non_e2e_collection() -> None:
    """Non-e2e pytest collection should not depend on a tests.* package import."""
    tests_dir = Path(__file__).parent
    module_path = tests_dir / "test_e2e_htmx.py"

    sys.path.insert(0, str(tests_dir))
    try:
        spec = importlib.util.spec_from_file_location("test_e2e_htmx_import_smoke", module_path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
