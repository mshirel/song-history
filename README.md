# Worship Slide Deck Song Catalog

Extract song metadata from PowerPoint worship slide decks, store in SQLite, generate CCLI reports.

## Quick Start

### Installation

```bash
python -m venv venv
source venv/bin/activate
pip install -e .
```

For Claude Vision OCR support (optional):

```bash
pip install -e ".[ocr]"
export ANTHROPIC_API_KEY=sk-ant-...
```

### Basic Workflow

```
validate → import → report
```

---

## Commands

### `validate` — Preview a PPTX without importing

View extracted songs without touching the database:

```bash
worship-catalog validate "data/AM Worship 2026.02.15.pptx"
```

JSON output for scripting:

```bash
worship-catalog validate "data/AM Worship 2026.02.15.pptx" --format json
```

---

### `import` — Import PPTX file(s) to database

Import a single file:

```bash
worship-catalog import "data/AM Worship 2026.02.15.pptx"
```

Import all PPTX files in a folder:

```bash
worship-catalog import "data/" --recurse
```

Use a custom database path:

```bash
worship-catalog import "data/" --db "path/to/custom.db" --recurse
```

**Fill in missing credits from the library index** (see [library index](#library-index--build-a-portable-credits-index)):

```bash
worship-catalog import "data/" --library-index data/library_index.json
```

**Use Claude Vision API** as a further fallback for credits not in the library:

```bash
worship-catalog import "data/" --library-index data/library_index.json --ocr
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--db` | `data/worship.db` | SQLite database path |
| `--recurse` | off | Recurse into subdirectories |
| `--non-interactive` | off | Skip interactive prompts |
| `--library-index` | `data/library_index.json` | Pre-scraped credits index |
| `--ocr` | off | Fall back to Claude Vision API |

---

### `report ccli` — Generate CCLI compliance CSV

```bash
worship-catalog report ccli \
  --from 2026-02-01 \
  --to 2026-02-28 \
  --out ccli_report.csv
```

All data in the database:

```bash
worship-catalog report ccli --out ccli_report.csv
```

---

### `report stats` — Generate usage statistics (Markdown)

```bash
worship-catalog report stats \
  --from 2026-02-01 \
  --to 2026-02-28 \
  --out stats_report.md
```

All data in the database:

```bash
worship-catalog report stats --out stats_report.md
```

Show all songs (not just top 20):

```bash
worship-catalog report stats --all-songs --out stats_report.md
```

**Filter by song leader** (partial match, case-insensitive):

```bash
worship-catalog report stats --leader "Matt" --out stats_report.md
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--from` | all | Start date (YYYY-MM-DD) |
| `--to` | all | End date (YYYY-MM-DD) |
| `--db` | `data/worship.db` | SQLite database path |
| `--out` | `stats_report.md` | Output file |
| `--all-songs` | off | Show all songs instead of top 20 |
| `--leader` | none | Filter to a specific song leader |

---

### `repair-credits` — Fix missing credits for existing songs

After import, some songs (typically Taylor Publications / sheet-music format) may
have no credits because the credit text is embedded in an image. Use this command
to backfill credits from the library index or via Vision OCR.

**From library index (fast, no API key needed):**

```bash
worship-catalog repair-credits \
  --library-index data/library_index.json
```

**With Claude Vision OCR fallback for songs not in the library:**

```bash
worship-catalog repair-credits \
  --library-index data/library_index.json \
  --ocr
```

**Dry run — preview changes without writing:**

```bash
worship-catalog repair-credits \
  --library-index data/library_index.json \
  --dry-run
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--db` | `data/worship.db` | SQLite database path |
| `--library-index` | `data/library_index.json` | Pre-scraped credits index |
| `--ocr` | off | Fall back to Claude Vision API |
| `--dry-run` | off | Show what would change without writing |

---

### `library index` — Build a portable credits index

Scrape OLE metadata from `.ppt` files in the song library directory and write a
portable JSON index. After running this once, `import` and `repair-credits` will
use the JSON automatically without needing the library mounted.

```bash
worship-catalog library index \
  --path tph_libarary/ \
  --out data/library_index.json
```

The index is stored at `data/library_index.json` by default and is excluded from
version control (`.gitignore`).

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--path` | (required) | Path to TPH song library directory |
| `--out` | `data/library_index.json` | Output JSON file |

---

## Features

- **Song Extraction**: Parses PowerPoint slides to extract song titles, credits, and slide positions
- **Credit Sources**: Text-based parsing → library OLE index → Claude Vision OCR (cascading fallback)
- **Duplicate Handling**: Songs appearing multiple times in a service are counted once for reporting
- **CCLI Reporting**: CSV reports for CCLI license compliance (projection + recording)
- **Statistics**: Markdown reports with frequency tables, service summaries, and leader filtering
- **Idempotent Imports**: Re-importing the same file updates existing data instead of duplicating it
- **Portable Library Index**: Song credits scraped from `.ppt` OLE metadata, stored as JSON

---

## Database

Default location: `data/worship.db`

| Table | Contents |
|-------|----------|
| `services` | Date, name, song leader, preacher, source file |
| `songs` | Canonical titles with display variants |
| `song_editions` | Publisher, words/music/arranger credits |
| `service_songs` | Song order within each service |
| `copy_events` | Projection and recording use for CCLI reporting |

---

## Development

### Running Tests

```bash
pytest                          # Run all tests
pytest tests/test_cli.py -v    # CLI tests
pytest tests/test_library.py   # Library/credits parsing tests
pytest -k "missing_credits"    # Run tests matching keyword
```

### Test Coverage

The project maintains 84%+ test coverage including:
- CLI commands: validate, import, report ccli/stats, repair-credits, library index
- PPTX parsing and song extraction
- Database operations and querying
- Title normalization and canonicalization
- Credits parsing (text patterns + OLE Author field)
- Library index save/load round-trip
- Song leader filtering in stats reports
- Missing-credits repair with FK backfill

---

## Known Limitations

- PPTX files must have metadata in standard locations (title slide table or filename)
- Song credits are parsed from text patterns (Words by, Music by, Arranger, Publisher)
- Taylor Publications / sheet-music slides store credits in images — use `repair-credits` with `--library-index` or `--ocr` to fill these in
- Vision OCR requires `ANTHROPIC_API_KEY` and `pip install -e ".[ocr]"`
- Requires Python 3.12+
