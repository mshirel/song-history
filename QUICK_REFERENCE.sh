#!/usr/bin/env bash
# Quick Reference - Common Commands

# Setup (first time only)
echo "=== SETUP (Run Once) ==="
uv sync --frozen --extra dev --extra web --extra ocr

# Run demo
echo "=== RUN DEMO ==="
./demo.sh

# Run all tests
echo "=== RUN ALL TESTS ==="
uv run --frozen pytest tests/ -v

# Run tests with coverage
echo "=== RUN TESTS WITH COVERAGE ==="
uv run --frozen pytest tests/ --cov=src/worship_catalog --cov-report=term-missing

# Run a specific test
echo "=== RUN SPECIFIC TEST ==="
uv run --frozen pytest tests/test_title_normalize.py::TestTitleNormalization::test_strip_numeric_prefix_with_dash -v

# Lint check
echo "=== LINT CHECK ==="
uv run --frozen ruff check src/

# Type check
echo "=== TYPE CHECK ==="
uv run --frozen mypy src/

# Interactive Python shell
echo "=== INTERACTIVE SHELL ==="
uv run --frozen python
# Then in Python:
# from worship_catalog.normalize import strip_title_prefix
# strip_title_prefix("1-1 Ancient Words")
