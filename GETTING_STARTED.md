# Getting Started with Worship Catalog

## Quick Start (5 minutes)

### 1. Clone/Setup Repository

```bash
cd /home/matt/projects/highland/song-history

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install project in development mode
pip install -e ".[dev]"
```

### 2. Run the Demo

```bash
# Make the demo executable
chmod +x demo.sh

# Run it!
./demo.sh
```

This will:
- ✅ Show title normalization in action
- ✅ Demonstrate candidate selection logic
- ✅ Show credit parsing
- ✅ Demonstrate publisher detection
- ✅ Run all 53 unit tests with coverage report

### 3. Explore the Code

**Core Module:**
```bash
# View the main normalization module
cat src/worship_catalog/normalize.py
```

**Test Files:**
```bash
# View the test suites
cat tests/test_title_normalize.py        # 29 tests
cat tests/test_publisher_detection.py   # 11 tests
cat tests/test_credits_parsing.py       # 13 tests
```

---

## Manual Testing (if you prefer)

Instead of the demo script, you can test functions directly:

### Test 1: Title Stripping

```bash
source venv/bin/activate
python3 << 'EOF'
from worship_catalog.normalize import strip_title_prefix

# Test examples
test_cases = [
    ("1 - We Will Glorify", "We Will Glorify"),
    ("1-1 Ancient Words", "Ancient Words"),
    ("Bridge Mighty To Save", "Mighty To Save"),
    ("C – Amazing Grace", "Amazing Grace"),
]

for input_title, expected in test_cases:
    result = strip_title_prefix(input_title)
    status = "✅" if result == expected else "❌"
    print(f"{status} {input_title:30} → {result:20} (expected: {expected})")
EOF
```

### Test 2: Publisher Detection

```bash
source venv/bin/activate
python3 << 'EOF'
from worship_catalog.normalize import detect_publisher

test_cases = [
    ("PaperlessHymnal.com", "Paperless Hymnal"),
    ("Copyright © Taylor Publications LLC", "Taylor Publications"),
    ("Regular hymn with no markers", None),
]

for text, expected in test_cases:
    result = detect_publisher(text)
    status = "✅" if result == expected else "❌"
    print(f"{status} Publisher: {result} (expected: {expected})")
EOF
```

### Test 3: Run All Tests

```bash
source venv/bin/activate

# Run all tests with verbose output
python -m pytest tests/ -v

# Run with coverage report
python -m pytest tests/ --cov=src/worship_catalog --cov-report=term-missing

# Run just one test file
python -m pytest tests/test_title_normalize.py -v

# Run a specific test
python -m pytest tests/test_title_normalize.py::TestTitleNormalization::test_strip_numeric_prefix_with_dash -v
```

---

## What's Implemented (Phase 1)

### Functions Available

1. **`strip_title_prefix(line: str) -> str`**
   - Strips verse/chorus/section indicators from titles
   - Handles: numeric prefixes (1 -), compound numbering (1-1), named sections (Bridge), lowercase tag
   - Example: `"1-1 Ancient Words"` → `"Ancient Words"`

2. **`select_best_title(candidates: list[str]) -> Optional[str]`**
   - Chooses best title from multiple lines
   - Prefers plain titles over prefixed forms
   - Ignores copyright/footer lines
   - Example: `["1-1 Title", "Title"]` → `"Title"`

3. **`canonicalize_title(title: str) -> str`**
   - Creates lowercase deduplication key
   - Removes punctuation, normalizes whitespace
   - Example: `"We Will Glorify!"` → `"we will glorify"`

4. **`parse_credits(text: str) -> dict`**
   - Extracts composer/arranger information
   - Returns: `{words_by, music_by, arranger, other_credits}`
   - Handles: "Words and Music by:", "Arr.:", "Arrangement by:"

5. **`detect_publisher(text: str) -> Optional[str]`**
   - Identifies publisher from slide text
   - Returns: `"Paperless Hymnal"` or `"Taylor Publications"` or `None`

---

## Test Results

```
Phase 1 Summary:
✅ 53/53 tests passing (100% pass rate)
✅ 93% code coverage (exceeds 85% target)
✅ All parsing functions validated

Breakdown:
- Title normalization:    29 tests ✅
- Publisher detection:    11 tests ✅
- Credits parsing:        13 tests ✅
```

---

## Project Structure

```
.
├── src/worship_catalog/
│   ├── __init__.py              # Package marker
│   └── normalize.py             # Core parsing functions (295 lines)
│
├── tests/
│   ├── test_title_normalize.py       # 29 tests
│   ├── test_publisher_detection.py   # 11 tests
│   └── test_credits_parsing.py       # 13 tests
│
├── data/                        # Input PPTX files (your worship decks)
│   ├── AM Worship 2025.11.23.pptx
│   ├── AM Worship 2026.02.15.pptx
│   ├── ... (8 total files)
│
├── pyproject.toml               # Project metadata & dependencies
├── demo.sh                      # Demo script
└── README.md                    # This file
```

---

## Next Steps (Phase 2 & Beyond)

Phase 2 will add:
- PPTX slide parsing with `python-pptx`
- Metadata extraction (date, service, leader)
- Song slide detection and grouping
- Integration tests on real PPTX files

Phases 3-7:
- SQLite database storage
- CLI commands (validate, import, report)
- CCLI report generation
- Testing & CI/CD
- Documentation

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'worship_catalog'"

Make sure you're in the virtual environment and installed in dev mode:
```bash
source venv/bin/activate
pip install -e ".[dev]"
```

### "pytest: command not found"

Install dev dependencies:
```bash
source venv/bin/activate
pip install -e ".[dev]"
```

### Tests fail with import errors

Verify the package structure:
```bash
ls -la src/worship_catalog/
# Should show: __init__.py, normalize.py
```

---

## Questions?

Refer to the specification in `spec.md` for complete requirements and architecture details.
