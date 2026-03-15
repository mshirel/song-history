# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.1.0] — 2026-03-15

### Added
- PPTX slide deck import with song extraction and service metadata
- SQLite database with full schema (services, songs, song_editions, copy_events, service_songs)
- Schema versioning with `PRAGMA user_version` — detects schema drift on connect
- CCLI compliance report (CSV export)
- Stats report (Markdown, CSV, Excel) with leader breakdown
- `repair-credits` command — backfills missing credits from library index or OCR
- TPH library index builder (`library index --path`)
- Claude Vision API OCR fallback for image-embedded credits
- FastAPI + HTMX web UI (songs, services, reports, leaders)
- Docker Compose stack with watcher, backup, and optional watchtower services
- `scripts/backup.sh` with `gzip -t` integrity check and `.last_success` sentinel
- Backup service healthcheck in compose.yml (fails if last success > 25 h)
- Trivy container image CVE scanning in CI (CRITICAL/HIGH, ignore-unfixed)
- SBOM and provenance manifests attached to GHCR images via build-push-action
- Service layer (`worship_catalog.services.report_service`) separating computation from I/O
- Streaming `iter_copy_events()` generator — avoids loading full result sets into memory
- Named constants replacing all magic numbers (`_REPORT_DATE_MIN/MAX`, `_STATS_TOP_SONGS`, etc.)
- OCR model name overridable via `WORSHIP_OCR_MODEL` environment variable
- Exponential backoff retry on Vision API transient errors
- Non-root Docker user (UID 1001) for runtime security
- All GitHub Actions and base images pinned to exact commit SHAs

[Unreleased]: https://github.com/mshirel/song-history/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mshirel/song-history/releases/tag/v0.1.0
