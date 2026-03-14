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

For the web UI (optional):

```bash
pip install -e ".[web]"
uvicorn worship_catalog.web.app:app --reload
# Open http://localhost:8000
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

**Fill in missing credits from the library index** (bundled by default — no flag needed):

```bash
worship-catalog import "data/AM Worship 2026.02.15.pptx"
```

**Override with a custom library index:**

```bash
worship-catalog import "data/" --library-index /path/to/my_index.json
```

**Use Claude Vision API** as a further fallback for credits not in the library:

```bash
worship-catalog import "data/" --ocr
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--db` | `data/worship.db` | SQLite database path |
| `--recurse` | off | Recurse into subdirectories |
| `--non-interactive` | off | Skip interactive prompts |
| `--library-index` | bundled | Pre-scraped credits index (overrides bundled default) |
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
worship-catalog repair-credits
```

**With Claude Vision OCR fallback for songs not in the library:**

```bash
worship-catalog repair-credits --ocr
```

**Dry run — preview changes without writing:**

```bash
worship-catalog repair-credits --dry-run
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--db` | `data/worship.db` | SQLite database path |
| `--library-index` | bundled | Pre-scraped credits index (overrides bundled default) |
| `--ocr` | off | Fall back to Claude Vision API |
| `--dry-run` | off | Show what would change without writing |

---

### `library index` — Rebuild the credits index from the TPH library

The package ships with a bundled credits index covering ~3,800 songs. You only
need this command if the library has been updated and you want to refresh the index.

```bash
worship-catalog library index \
  --path tph_libarary/ \
  --out data/library_index.json
```

Pass the new file with `--library-index` on subsequent import/repair-credits runs,
or replace the bundled file at `src/worship_catalog/data/library_index.json`.

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--path` | (required) | Path to TPH song library directory |
| `--out` | `data/library_index.json` | Output JSON file |

---

## Automated Inbox Ingestion

Drop new PPTX files into an `inbox/` folder and run the import script to process them
automatically. Successfully imported files are moved to `inbox/archive/`; files that
fail three times are quarantined to `inbox/quarantine/`.

```bash
./scripts/import-new.sh
```

Configure via environment variables:

```bash
INBOX_DIR=/data/inbox \
DB_PATH=/data/worship.db \
MAX_FAILURES=3 \
LOG_FILE=/var/log/worship-import.log \
./scripts/import-new.sh
```

Add to cron (example: every 5 minutes):

```cron
*/5 * * * * INBOX_DIR=/data/inbox DB_PATH=/data/worship.db /app/scripts/import-new.sh
```

---

## Docker / Podman

The app ships with a `Dockerfile` and `compose.yml` for portable deployment.
The bundled library index is baked into the image — no separate volume needed.

### Build

```bash
docker build -t worship-catalog .
# or: podman build -t worship-catalog .
```

### Ad-hoc CLI commands

```bash
docker compose run --rm cli report ccli --from 2026-01-01 --to 2026-12-31
docker compose run --rm cli report stats --all-songs
docker compose run --rm cli repair-credits
```

### Persistent services

```bash
# Start the inbox watcher (polls every 5 minutes) and web UI
docker compose up -d watcher web

# View logs
docker compose logs -f watcher
```

### Volume layout

| Host path | Container path | Contents |
|-----------|---------------|----------|
| `./data/` | `/data` | `worship.db` database |
| `./inbox/` | `/inbox` | New PPTX files to import |
| `./config/` | `/config` | `reporting.yml` (optional) |

---

## Web UI

Start the web server:

```bash
uvicorn worship_catalog.web.app:app --host 0.0.0.0 --port 8000
# or via Docker: docker compose up -d web
```

Open `http://localhost:8000`.

### Pages

| Page | URL | Description |
|------|-----|-------------|
| Songs | `/songs` | Searchable, sortable song browser with performance counts and credits |
| Song Detail | `/songs/{id}` | Full service history for a single song |
| Services | `/services` | Filterable, sortable list of all imported services |
| Service Detail | `/services/{id}` | Complete setlist and metadata for a single service |
| Reports | `/reports` | Generate CCLI CSV download or view stats report in browser |
| Health | `/health` | Returns `{"status": "ok"}` — used by Docker healthcheck |

**Songs page:** search filters live as you type; click any column header to sort.
**Services page:** filter by date range, service name, song leader, preacher, or sermon title; click headers to sort.
**Reports:** stats report supports date range, song leader filter (partial match), and top-20 vs all-songs toggle.

---

## Features

- **Song Extraction**: Parses PowerPoint slides to extract song titles, credits, and slide positions
- **Credit Sources**: Text-based parsing → bundled library index → Claude Vision OCR (cascading fallback)
- **Bundled Library Index**: ~3,800 song credits shipped with the package; no setup required
- **Duplicate Handling**: Songs appearing multiple times in a service are counted once for reporting
- **CCLI Reporting**: CSV reports for CCLI license compliance (projection + recording)
- **Statistics**: Markdown reports with frequency tables, service summaries, and leader filtering
- **Idempotent Imports**: Re-importing the same file updates existing data instead of duplicating it
- **Inbox Automation**: Shell script watches a folder, archives successes, quarantines repeat failures
- **Container Ready**: Dockerfile + compose.yml for local use or server deployment
- **Web UI**: FastAPI + HTMX browser interface — sortable/filterable song and service tables, song history detail, report generation
- **Scripture Guard**: Slide content matching Bible reference patterns (e.g. `John 3:16`, `1 Peter 1:3-4`) is automatically excluded from song title extraction

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

### Setup

Install all development dependencies (includes web, OCR, linting, type checking, and security tools):

```bash
python -m venv venv
source venv/bin/activate
pip install -e ".[dev,web,ocr]"
```

Install pre-commit hooks to enforce linting on every commit:

```bash
pip install pre-commit
pre-commit install
```

### Running Tests

```bash
pytest                           # Run all tests with coverage
pytest tests/test_cli.py -v     # CLI tests
pytest tests/test_web.py -v     # Web UI tests
pytest tests/test_library.py    # Library/credits parsing tests
pytest -k "missing_credits"     # Run tests matching keyword
```

### Test Coverage

The project maintains 85%+ test coverage including:
- CLI commands: validate, import, report ccli/stats, repair-credits, library index
- Bundled library index resolution (`_resolve_library_index`)
- PPTX parsing and song extraction
- Database operations and querying
- Title normalization and canonicalization
- Credits parsing (text patterns + OLE Author field)
- Library index save/load round-trip
- Song leader filtering in stats reports
- Missing-credits repair with FK backfill
- Web UI: songs browser, HTMX search, CCLI CSV download, stats report

### Code Quality

```bash
python -m ruff check src/        # Lint
python -m mypy src/              # Type check
```

### Security Checks

Run all security checks locally before pushing:

```bash
# Static security analysis (medium+ severity only)
python -m bandit -r src/ -ll -c pyproject.toml

# Dependency vulnerability audit
python -m pip_audit --skip-editable
```

### CI/CD

Every push and pull request to `main` runs two parallel jobs via GitHub Actions:

| Job | Steps |
|-----|-------|
| `test` | ruff lint → mypy type check → pytest |
| `security` | gitleaks secrets scan → pip-audit dependency audit → bandit static analysis |

The security job scans the full git history for accidentally committed secrets (API keys, tokens, passwords), checks all dependencies against the OSV/PyPI advisory database for known CVEs, and runs Bandit at medium+ severity for insecure Python patterns.

---

## Known Limitations

- PPTX files must have metadata in standard locations (title slide table or filename)
- Song credits are parsed from text patterns (Words by, Music by, Arranger, Publisher)
- Taylor Publications / sheet-music slides store credits in images — use `repair-credits` with `--library-index` or `--ocr` to fill these in
- Vision OCR requires `ANTHROPIC_API_KEY` and `pip install -e ".[ocr]"`
- Requires Python 3.10+
