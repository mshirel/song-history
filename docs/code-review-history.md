# Code Review History

Full multi-perspective reviews conducted by seven senior engineering personas
(Architect, Developer, DevOps, Security, DevSecOps, QA, Product Manager).
Each review produces GitHub issues for every significant finding.

---

## Review 5 — 2026-03-21

**Branch:** `main`
**Reviewer:** Claude Code (full-code-review skill)
**Issues created:** #234–#248

### Critical Finding: CSRF + CSP Cluster

Issues #235, #237, #238, #239, #243, #247 form a cluster where most POST-based
web features are broken in real browsers: CSP blocks inline JS in upload form,
download forms lack CSRF tokens, CSRF_SECRET resets on restart. Invisible in
test suite because CsrfAwareClient injects tokens automatically.

### Findings

| Issue | Persona | Title | Severity |
|-------|---------|-------|----------|
| #234 | Developer | dev: duplicate static file mount in web app startup | LOW |
| #235 | Security | sec: PowerShell upload script bypasses CSRF protection | HIGH |
| #236 | Architect | arch: web routes use manual DB lifecycle instead of FastAPI DI | MED |
| #237 | DevOps | devops: compose.yml web service missing CSRF_SECRET | HIGH |
| #238 | QA | qa: stats report CSV/XLSX download forms missing CSRF tokens | HIGH |
| #239 | Security | sec: CSRF cookie name mismatch between middleware and JS | MED |
| #240 | Product Manager | pm: songs empty state card links to Reports instead of Upload | LOW |
| #241 | DevSecOps | devsecops: in-memory upload rate limiter resets on restart | MED |
| #242 | UAT | uat: browser upload form end-to-end acceptance test | HIGH |
| #243 | UAT | uat: report form submissions -- CSRF and download acceptance tests | HIGH |
| #244 | UAT | uat: navigation and page-load acceptance tests for all routes | MED |
| #245 | UAT | uat: HTMX search and filter interactions acceptance tests | MED |
| #246 | UAT | uat: leader CSV download and leader navigation acceptance tests | MED |
| #247 | DevOps/Security | devops: CSP script-src 'self' blocks inline JavaScript in upload.html | HIGH |
| #248 | QA | qa: CLI import command duplicates import pipeline logic from import_service.py | MED |

### Grades

| Persona | Grade | Notes |
|---------|-------|-------|
| Senior Architect | B | Good service layer, but web routes bypass FastAPI DI |
| Senior Developer | A- | Clean code, good types, minor duplicate static mount |
| Senior DevOps | B+ | Excellent CI pipeline, CSRF_SECRET gap in compose.yml |
| Senior Security Architect | C+ | Good fundamentals, but CSP incompatible with inline scripts, CSRF integration gaps |
| Senior DevSecOps | B | Comprehensive supply chain security, ephemeral rate limiter |
| Senior QA Engineer | B+ | 839+ tests at 94% coverage, CsrfAwareClient masks browser CSRF issues |
| Product Manager | A- | Clear features, good empty states, minor misdirected link |

**Overall: B**

---

## Review 4 — 2026-03-19

**Branch:** `feat/pushover-notify`
**Reviewer:** Claude Code (full-code-review skill)
**Issues created:** #191–#202

### Findings

| Issue | Persona | Title | Severity |
|-------|---------|-------|----------|
| #191 | Architect | `_get_db()` runs `init_schema()` on every request — unnecessary PRAGMA write | MED |
| #192 | Developer | CCLI CSV report injects non-CSV comment lines between data rows | HIGH |
| #193 | Developer | `_run_import_in_background` notify variables could be unbound | MED |
| #194 | DevOps | Pi deploy compose missing PUSHOVER env vars for import notifications | MED |
| #195 | DevOps | Dockerfile uses editable install (`-e`) in production image | MED |
| #196 | Security | Self-host htmx.js instead of loading from unpkg CDN | HIGH |
| #197 | Security | No Content-Security-Policy header on web responses | MED |
| #198 | DevSecOps | Trivy action pinned to stale v0.35.0 | MED |
| #199 | QA | No Playwright E2E tests for HTMX live-search and sort interactions | HIGH |
| #200 | QA | CI integration test step has no minimum test count assertion | MED |
| #201 | PM | CCLI CSV report not available in web UI reports page | MED |
| #202 | PM | No web upload form — PPTX upload is API-only with no browser UI | MED |

### Grades

| Persona | Grade | Notes |
|---------|-------|-------|
| Senior Architect | B | Good separation with import_service.py and report_service.py; per-request init_schema and import duplication (#165) remain |
| Senior Developer | B | Clean code with consistent patterns; CCLI CSV comment injection is a format bug; unbound notify vars are latent crash risk |
| Senior DevOps | B+ | Strong CI with SHA-pinned actions, digest-pinned Docker base, non-root container, smoke tests; editable install and missing env vars are easy fixes |
| Senior Security Architect | B | CSRF, parameterized SQL, SRI, safe filename sanitization all present; CDN dependency and missing CSP are standard hardening gaps |
| Senior DevSecOps | A- | SHA-pinned actions, gitleaks, pip-audit, Trivy SARIF, bandit, Dependabot for 4 ecosystems; only stale Trivy pin found |
| Senior QA Engineer | B | 751 tests at 93% coverage is strong; missing E2E browser tests for HTMX interactions and CI integration count guard |
| Product Manager | B- | Core workflows work well; CCLI report and PPTX upload missing from web UI hurt non-technical user accessibility |

**Overall: B+**

---

## Review 3 — 2026-03-17

**Branch:** `fix/sprint9-security-qa`
**Reviewer:** Claude Code (full-code-review skill)
**Issues created:** #165–#179

### Findings

| Issue | Persona | Title | Severity |
|-------|---------|-------|----------|
| #165 | Architect | Extract shared import service layer — CLI and web duplicate import pipeline | HIGH |
| #166 | Architect | Move SQL query helpers into db.py — business logic leaking into web layer | MEDIUM |
| #167 | Developer | cli.py stats command reimplements report_service.compute_stats_data | MEDIUM |
| #168 | Developer | repair-credits wastes OCR budget on empty results — no refund unlike CreditResolver | MEDIUM |
| #169 | Developer | extract_service_metadata returns partial table data without filename fallback | MEDIUM |
| #170 | Developer | Deduplicate _CsrfAwareClient from test_web.py and test_web_security.py | LOW |
| #171 | DevOps | Web background importer never cleans up inbox files — unbounded disk growth | HIGH |
| #172 | DevOps | Backup sidecar uses raw file copy — corrupt under concurrent writes; restore docs wrong | MEDIUM |
| #173 | Security | No rate limiting on /upload — four concurrent uploads exhaust import pool | MEDIUM |
| #174 | DevSecOps | No Python dependency lockfile — Docker builds are non-reproducible | MEDIUM |
| #175 | QA | No contract test for stats report Markdown output format | MEDIUM |
| #176 | QA | Web background import has no dedicated test coverage | MEDIUM |
| #177 | PM | GETTING_STARTED.md is severely outdated — references 53 tests, no Docker or web UI | HIGH |
| #178 | PM | `report ccli` command is hidden — primary CCLI report is undiscoverable via --help | MEDIUM |
| #179 | PM | No empty-state guidance in web UI for new installations | MEDIUM |

### Grades

| Persona | Grade | Notes |
|---------|-------|-------|
| Senior Architect | B | Import pipeline duplication and SQL in web layer are significant gaps; domain models are clean |
| Senior Developer | B | Code is readable and well-named; OCR budget refund inconsistency and metadata fallback gap are real bugs |
| Senior DevOps | B | CI and Dockerfile are hardened; inbox accumulation and backup integrity are operational risks |
| Senior Security Architect | B+ | CSRF, SRI, parameterized queries, file size limits all present; rate limiting on /upload is the key gap |
| Senior DevSecOps | A- | All actions SHA-pinned, Dependabot configured for all ecosystems; missing lockfile is the only meaningful gap |
| Senior QA Engineer | B | 349 tests, 88% coverage, mutation testing, E2E tests; web import path and stats format lack contract tests |
| Product Manager | C+ | Core functionality works; hidden CCLI command, outdated onboarding doc, blank empty-state hurt discoverability |

**Overall: B**

---

## Review 2 — 2026-03-15

**Branch:** `fix/sprint9-security-qa`
**Reviewer:** Claude Code (full-code-review skill)
**Issues created:** #128–#147

### Findings

| Issue | Persona | Title | Severity |
|-------|---------|-------|----------|
| #128 | Architect | `CreditResolver` ignores `library_index` — web upload never applies library credits | HIGH |
| #129 | Architect | Import logic duplicated between `cli.py` and `web/app.py` — divergence risk | HIGH |
| #130 | Architect | No schema migration path — `SchemaVersionError` is a dead end for existing DBs | MED |
| #131 | Developer | `repair-credits --ocr` ignores `consume()` return value; refund path never reached | MED |
| #132 | Developer | `_query_songs()` builds `ORDER BY` via f-string with no internal whitelist guard | HIGH |
| #133 | Developer | `Database.close()` does not null `self.conn` — use-after-close gives obscure errors | LOW |
| #134 | Developer | CCLI CSV uses manual f-strings — commas in song titles corrupt CSV rows | HIGH |
| #135 | DevOps | `uvicorn` has no graceful timeout; `ThreadPoolExecutor` not shut down on lifespan exit | MED |
| #136 | DevOps | Backup sleep loop has no failure alerting — silent failures for up to 25 hours | MED |
| #137 | DevOps | E2E (`@pytest.mark.e2e`) tests not excluded from `addopts` — will cause CI flaps | MED |
| #138 | Security | Uploaded PPTX files never deleted from inbox — unbounded disk growth + data retention | HIGH |
| #139 | Security | `CSRF_SECRET` falls back to per-process random — tokens invalidated on every restart | MED |
| #140 | Security | Stats CSV/XLSX `Content-Disposition` filename not sanitized | LOW |
| #141 | DevSecOps | Dockerfile comment says `python:3.12-slim`, `FROM` uses `python:3.14-slim` — contradiction | LOW |
| #142 | DevSecOps | Pre-commit hooks missing `bandit`, `gitleaks`, `pip-audit` (see also #50) | MED |
| #143 | QA | `purge_old_import_jobs()` has zero tests — retention boundary undefined | MED |
| #144 | QA | `SchemaVersionError` guard has zero test coverage | MED |
| #145 | QA | `/upload` MIME type rejection and 50 MB size limit have zero tests | HIGH |
| #146 | QA | `OcrBudget` boundary conditions (`consume` at cap, `refund` below zero) untested | MED |
| #147 | QA | `parse_filename_for_metadata()` has zero tests — fallback metadata path untested | LOW |

### Grades

| Persona | Grade | Notes |
|---------|-------|-------|
| Senior Architect | B+ | Good abstractions (`CreditResolver`, `ReportService`, `OcrBudget`), but `CreditResolver` silently skips library lookup in web upload (#128) and import logic is duplicated between CLI and web (#129) |
| Senior Developer | B | Error handling generally good; real correctness bugs in CSV escaping (#134) and OCR budget logic (#131) |
| Senior DevOps | B+ | Strong: WAL mode, tini, healthchecks, non-root container, resource limits; gaps in ThreadPoolExecutor drain (#135) and backup alerting (#136) |
| Senior Security Architect | A- | Excellent hardening (CSRF, SRI, path traversal, MIME validation, job ID tokens); inbox file retention (#138) and CSRF secret fallback (#139) remain |
| Senior DevSecOps | A- | All actions SHA-pinned, Dependabot active, SBOM baseline, trivy scan; pre-commit/CI alignment still pending (#50/#142) |
| Senior QA Engineer | B+ | 479 tests, 91% coverage, mutation testing, Playwright E2E, accessibility tests; upload validation paths completely untested (#145) |

**Overall: B+**

---

## Review 1 — 2026-03-15

**Branch:** `main` (post-sprint-8)
**Reviewer:** Claude Code (full-code-review skill)
**Issues created:** #51–#75

### Grades

| Persona | Grade | Notes |
|---------|-------|-------|
| Senior Architect | B | Solid layering; credit resolution cascade well-designed; coupling between CLI and extractor acceptable |
| Senior Developer | B+ | Good error handling; test suite present; some magic strings and long functions flagged |
| Senior DevOps | B | CI pipeline functional; Docker image reasonable; observability gaps noted |
| Senior Security Architect | C+ | Multiple web security gaps found: CSRF missing, no size limits on upload, header injection possible |
| Senior DevSecOps | B- | Actions not fully SHA-pinned; no SBOM; gitleaks missing from pipeline |
| Senior QA Engineer | B- | Unit tests solid; integration and E2E coverage thin; mutation testing absent |

**Overall: B-**

> Note: Most findings from Review 1 were resolved in PR #82 and subsequent sprint-9 work. See issues #51–#75 for individual resolution status.
