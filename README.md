# Worship Slide Deck Song Catalog

Extract song metadata from PowerPoint worship slide decks, store in SQLite, generate CCLI reports.

## Quick Start

### Installation

```bash
python -m venv venv
source venv/bin/activate
pip install -e .
```

### Basic Usage

#### 1. Validate a PPTX file before importing

View extracted songs without modifying the database:

```bash
python -m worship_catalog.cli validate "data/AM Worship 2026.02.15.pptx"
```

Get JSON output for scripting:

```bash
python -m worship_catalog.cli validate "data/AM Worship 2026.02.15.pptx" --format json
```

#### 2. Import PPTX file(s) to database

Import a single file:

```bash
python -m worship_catalog.cli import "data/AM Worship 2026.02.15.pptx"
```

Import all PPTX files in a folder:

```bash
python -m worship_catalog.cli import "data/" --recurse
```

Use custom database path:

```bash
python -m worship_catalog.cli import "data/" --db "path/to/custom.db" --recurse
```

#### 3. Generate CCLI Report

Generate report for specific date range:

```bash
python -m worship_catalog.cli report ccli \
  --from 2026-02-01 \
  --to 2026-02-28 \
  --out ccli_report.csv
```

Generate report for all data in database:

```bash
python -m worship_catalog.cli report ccli --out ccli_report.csv
```

#### 4. Generate Statistics Report

Generate report for specific date range:

```bash
python -m worship_catalog.cli report stats \
  --from 2026-02-01 \
  --to 2026-02-28 \
  --out stats_report.md
```

Generate report for all data in database:

```bash
python -m worship_catalog.cli report stats --out stats_report.md
```

## Features

- **Song Extraction**: Automatically parses PowerPoint slides to extract song titles, credits, and slide positions
- **Duplicate Handling**: When a song appears multiple times in the same service, it's counted once for reporting
- **CCLI Reporting**: Generates CSV reports for CCLI license compliance (projection + recording)
- **Statistics**: Generates markdown reports with frequency analysis and service summaries
- **Idempotent Imports**: Re-importing the same file updates existing data instead of creating duplicates

## Database

Default database location: `data/worship.db`

The database tracks:
- **Services**: Date, name, source file, metadata
- **Songs**: Canonical titles with display variants
- **Song Editions**: Publisher, credits (words, music, arrangement)
- **Copy Events**: Projection and recording use for CCLI reporting

## Development

### Running Tests

```bash
pytest                          # Run all tests
pytest tests/test_cli.py -v    # Run CLI tests only
pytest -k "duplicate"          # Run tests matching keyword
```

### Test Coverage

The project maintains 90%+ test coverage including:
- CLI command validation
- PPTX parsing and extraction
- Database operations
- Title normalization
- Report generation
- Duplicate song handling

## Known Limitations

- PPTX files must have metadata in standard locations (title slide, slide notes)
- Song credits are parsed from text patterns (words by, music by, arranger, publisher)
- Requires Python 3.12+

