#!/usr/bin/env bash
# Quick Reference - Common Commands

# Setup (first time only)
echo "=== SETUP (Run Once) ==="
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"

# Run demo
echo "=== RUN DEMO ==="
./demo.sh

# Run all tests
echo "=== RUN ALL TESTS ==="
pytest tests/ -v

# Run tests with coverage
echo "=== RUN TESTS WITH COVERAGE ==="
pytest tests/ --cov=src/worship_catalog --cov-report=term-missing

# Run a specific test
echo "=== RUN SPECIFIC TEST ==="
pytest tests/test_title_normalize.py::TestTitleNormalization::test_strip_numeric_prefix_with_dash -v

# Lint check
echo "=== LINT CHECK ==="
ruff check src/

# Type check
echo "=== TYPE CHECK ==="
mypy src/

# Interactive Python shell
echo "=== INTERACTIVE SHELL ==="
python3
# Then in Python:
# from worship_catalog.normalize import strip_title_prefix
# strip_title_prefix("1-1 Ancient Words")
