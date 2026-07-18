# Getting Started with Worship Catalog

This guide gets you up and running quickly. For full command documentation,
see [README.md](README.md).

---

## Prerequisites

- **Python 3.10+** (3.12 recommended)
- **Docker** (optional, for containerized deployment)
- PowerPoint (`.pptx`) worship slide decks to import

---

## Quick Start (Local)

### 1. Install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

### 2. Validate a slide deck

Preview what will be extracted, without touching the database:

```bash
worship-catalog validate "data/AM Worship 2026.02.15.pptx"
```

### 3. Import to database

```bash
worship-catalog import "data/AM Worship 2026.02.15.pptx"
```

Import an entire folder recursively:

```bash
worship-catalog import data/ --recurse
```

### 4. Generate reports

```bash
# CCLI compliance CSV
worship-catalog report ccli --from 2026-01-01 --to 2026-12-31 --out ccli.csv

# Usage statistics (Markdown)
worship-catalog report stats --out stats.md
```

### 5. Repair missing credits

Some slide formats embed credits in images. Backfill them from the bundled
library index or Claude Vision OCR:

```bash
worship-catalog repair-credits              # library index only
worship-catalog repair-credits --ocr        # + Vision API fallback
worship-catalog repair-credits --dry-run    # preview without writing
```

---

## Quick Start (Docker)

Pre-built images are published to GitHub Container Registry:

```bash
docker pull ghcr.io/mshirel/song-history:latest
```

### Start the web UI and inbox watcher

```bash
docker compose up -d web watcher
```

### Run CLI commands in the container

```bash
docker compose run --rm cli report ccli --from 2026-01-01 --to 2026-12-31
docker compose run --rm cli report stats --all-songs
docker compose run --rm cli repair-credits
```

### Volume layout

| Host path   | Container path | Contents                          |
|-------------|---------------|-----------------------------------|
| `./data/`   | `/data`       | `worship.db` SQLite database      |
| `./inbox/`  | `/inbox`      | New PPTX files for auto-import    |
| `./config/` | `/config`     | Optional configuration            |

---

## Web UI

Start locally:

```bash
pip install -e ".[web]"
uvicorn worship_catalog.web.app:app --host 0.0.0.0 --port 8000
```

Or via Docker: `docker compose up -d web`

Open **http://localhost:8000** to access:

| Page             | URL               | Description                                       |
|------------------|-------------------|---------------------------------------------------|
| Songs            | `/songs`          | Searchable, sortable song browser                 |
| Song Detail      | `/songs/{id}`     | Service history for a single song                 |
| Services         | `/services`       | Filterable list of all imported services          |
| Service Detail   | `/services/{id}`  | Setlist and metadata for a service                |
| Leaders          | `/leaders`        | Song leader directory with top songs              |
| Reports          | `/reports`        | Generate stats, CCLI CSV, or missing-services reports |
| Upload           | `/upload`         | Browser upload flow for importing a PPTX deck     |
| About            | `/about`          | App overview plus version and build details       |
| Health           | `/health`         | `{"status": "ok"}` for Docker healthcheck         |

---

### Uploading In The Browser

The `/upload` page is the easiest way for a church volunteer to add a slide deck.

- When `UPLOAD_PASSWORD` is unset, browser upload is open by default.
- When `UPLOAD_PASSWORD` is set, `/upload` shows a `Log in to upload` button. Opening `/upload?login=1` triggers the browser's HTTP Basic-auth prompt.
- `UPLOAD_USERNAME` defaults to `highland` if you do not set it explicitly.
- The same credentials are required for `/jobs` and for editing exclusions in the Missing Services report.

---

## CLI Commands

| Command                 | Purpose                                       |
|-------------------------|-----------------------------------------------|
| `validate <pptx>`       | Preview extraction without importing          |
| `import <pptx\|dir>`    | Import slide decks to SQLite                  |
| `report ccli`           | Generate CCLI compliance CSV                  |
| `report stats`          | Generate usage statistics (Markdown)          |
| `repair-credits`        | Backfill missing credits from library or OCR  |
| `library index`         | Rebuild the TPH credits index from `.ppt` files |

See [README.md](README.md) for full flag reference and examples.

---

## Running Tests

The project has **741+ tests** with **93%+ coverage**.

```bash
# Install dev dependencies
uv sync --frozen --extra dev --extra web --extra ocr

# Run all tests
uv run --frozen pytest

# Run a specific test file
uv run --frozen pytest tests/test_cli.py -v

# Run with coverage report
uv run --frozen pytest --cov=worship_catalog

# Skip slow integration tests
uv run --frozen pytest -m "not integration"
```

### Key test files

| File                            | What it covers                    |
|---------------------------------|-----------------------------------|
| `tests/test_cli.py`            | CLI commands and flags            |
| `tests/test_web.py`            | Web UI routes and HTMX           |
| `tests/test_db_integration.py` | Database operations              |
| `tests/test_extractor_unit.py` | PPTX song extraction             |
| `tests/test_credits_parsing.py`| Credit parsing and normalization |
| `tests/test_pptx_reader_unit.py`| Low-level slide parsing         |
| `tests/test_ocr.py`            | Claude Vision API                |
| `tests/test_web_security.py`   | Security (CSRF, upload limits)   |

---

## Development Setup

```bash
uv sync --frozen --extra dev --extra web --extra ocr

# Install pre-commit hooks
uv tool install pre-commit
pre-commit install
```

### Code quality checks

```bash
uv run --frozen ruff check src/       # Lint
uv run --frozen mypy src/             # Type check (strict)
```

Both must pass with zero errors before any commit.

### Security checks

```bash
uv run --frozen bandit -r src/ -ll -c pyproject.toml   # Static analysis
uv run --frozen pip-audit --skip-editable              # Dependency CVE scan
```

### CI pipeline

Every push/PR runs these GitHub Actions jobs:

| Job        | Steps                                              |
|------------|-----------------------------------------------------|
| `test`     | ruff lint, mypy type check, pytest                  |
| `security` | gitleaks secrets scan, pip-audit, bandit             |
| `publish`  | Docker build + push to GHCR (main branch only)      |

---

## Troubleshooting

### ModuleNotFoundError: No module named 'worship_catalog'

Make sure you synchronized the frozen development environment:

```bash
uv sync --frozen --extra dev --extra web --extra ocr
```

### pytest: command not found

Install dev dependencies:

```bash
uv sync --frozen --extra dev --extra web --extra ocr
```

### Vision OCR not working

OCR requires the `ocr` extra and an API key:

```bash
pip install -e ".[ocr]"
export ANTHROPIC_API_KEY=sk-ant-...
```

### Docker healthcheck failing

Verify the web service is running and port 8000 is accessible:

```bash
docker compose logs web
curl http://localhost:8000/health
```

---

For full command documentation, database schema, and feature details, see
[README.md](README.md).
