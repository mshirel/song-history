# Code Review History

Full multi-perspective reviews conducted by ten senior engineering personas
(Architect, Developer, DevOps, Security, DevSecOps, QA, Product Manager,
UAT Analyst, Accessibility Specialist, Database/Data Engineer).
Each review produces GitHub issues for every significant finding.

---

## Review 12 — 2026-07-02

**Branch:** `agent/claude/code-review`
**Reviewer:** Claude Code (full-code-review skill)
**Focus:** Full ten-persona sweep, code **and** live pi-songs host. Verified the Review-11 host-posture fixes held (no drift): `.env` 600, port 8000 firewall-gated to Prometheus only, `TRUSTED_PROXY=1`, `/metrics` proxy-header-denied + firewalled, `/jobs` 401, reports rate-limited, third-party images digest-pinned. `#452` (fail2ban) remains the only still-open Review-11 item — password auth is now disabled, fail2ban still inactive.
**Issues created:** #496–#517

### Findings

| Issue | Persona | Title | Severity |
|-------|---------|-------|----------|
| #496 | UAT | HTMX date-validation errors (422) silently swallowed — Stats & CCLI Preview appear to do nothing | HIGH |
| #497 | QA | Extraction has no golden-file regression test that runs in CI (fixture has no committed input deck; assertion is weak) | HIGH |
| #498 | Developer | `extract_songs` 120s timeout defeated by `ThreadPoolExecutor` blocking shutdown | MED |
| #499 | Developer | OCR retries permanent 4xx errors (bad key / bad request) 3× with backoff | MED |
| #500 | Database | Song-list credits/sort nondeterministic for multi-edition songs | MED |
| #501 | Architect | Heavy synchronous report/xlsx work blocks the event-loop thread | MED |
| #502 | DevSecOps | Dependabot `docker-compose` ecosystem invalid — deploy/pi images get no update PRs | MED |
| #503 | DevOps | `/upload` buffers the entire file (up to 200MB) in memory before writing | MED |
| #504 | Product | Browser Upload, Missing-Services report, and `UPLOAD_PASSWORD` auth gate absent from user docs | MED |
| #505 | UAT/QA | Extend Playwright E2E to cover interactive HTMX report & upload flows | MED |
| #506 | QA | Expand mutation-testing scope to `db.py` + `import_service.py` | MED |
| #507 | QA | Pytest markers aspirational — most tests unmarked, fast-slice broken, guard tests tautological | MED |
| #508 | Developer | OCR response parsing assumes a text block at `content[0]` | LOW |
| #509 | Database | `insert_or_update_service` not retry-safe against a concurrent same-service import | LOW |
| #510 | Architect | `services` schema defined in two disagreeing places (init_schema vs migration 3) | LOW |
| #511 | Database | copy-events IN-clause unbounded by SQLite variable limit (latent) | LOW |
| #512 | DevOps | App image deployed via mutable `:latest` tag on pi-songs | LOW |
| #513 | Security | Traefik API dashboard runs with `insecure: true` (container-internal only today) | LOW |
| #514 | DevOps | promtail container runs as root; prod watcher healthcheck disabled | LOW |
| #515 | QA | Docker image smoke test only pings `/health`, exercises no real route | LOW |
| #516 | Accessibility | WCAG 2.1 AA polish — table header semantics, muted-text contrast, nav `aria-expanded` | LOW |
| #517 | UAT | HTMX live-search doesn't push URL state — Back button loses search/filters | LOW |

### Grades

| Persona | Grade | Notes |
|---------|-------|-------|
| Senior Architect | A- | Clean layering; only smells are the event-loop-blocking report path (#501) and the dual `services` schema definition (#510) |
| Senior Developer | B+ | Solid logic; a few real edge-case bugs — timeout shutdown blocks (#498), OCR retries permanent 4xx (#499), unguarded `content[0]` (#508) |
| Senior DevOps | B | Review-11 host fixes verified holding; new gaps — invalid Dependabot ecosystem (#502), app `:latest` (#512), in-memory upload buffer (#503), promtail root (#514) |
| Senior Security Architect | A- | Parameterized SQL, thorough upload validation (MIME+ext+magic+size), CSRF/CSP/HSTS, auth gates, host fixes held; only defense-in-depth items left (#513, #503) |
| Senior DevSecOps | B+ | CI supply chain strong (SHA-pinned actions, Trivy-before-push, digest-pinned base); the Dependabot deploy/pi gap leaves the public proxy/tunnel images unpatched (#502) |
| Senior QA Engineer | B | Large green suite (1275 passing) but the one golden extraction test never runs in CI (#497), mutation scope narrow (#506), markers aspirational + tautological guards (#507, #515) |
| Product Manager | B+ | Features solid; docs understate the product and omit the only write surface's auth model (#504) |
| UAT Analyst | B | Strong `/songs` browser coverage, but reports/upload/missing-services HTMX flows untested in a real browser (#505) and a real 422-swallow bug (#496) |
| Accessibility Specialist | A- | Prior work (skip-nav, live regions, `aria-sort`, table markup) solid and intact; only minor AA stragglers remain (#516) |
| Database / Data Engineer | B+ | WAL, indexes, read-snapshot pagination, retry-safe inserts largely done; multi-edition nondeterminism (#500) and one non-retry-safe insert path (#509) remain |

**Overall: B+** — a mature, well-tested, and (post-Review-11) well-hardened codebase. This review's findings are mostly refinements, plus one genuine user-facing bug (#496 swallowed date errors) and one real CI blind spot (#497 the golden extraction test never runs).

---

## Review 11 — 2026-05-26

**Branch:** `agent/claude/review-11-history`
**Reviewer:** Claude Code (full-code-review skill)
**Focus:** Heavy security emphasis — code **and** the pi-songs host — after `songs.highland-coc.com` was exposed publicly via a cloudflared tunnel.
**Issues created:** #446–#455

### Findings

| Issue | Persona | Title | Severity |
|-------|---------|-------|----------|
| #446 | Security | pi-songs `.env` world-readable (644) — exposes CF API/tunnel tokens, CSRF & upload secrets | HIGH |
| #447 | Security | App port 8000 (incl. `/metrics`) bound to 0.0.0.0, no host firewall — bypasses Cloudflare/Traefik | HIGH |
| #448 | Security | `TRUSTED_PROXY` unset → CF-Connecting-IP unused → upload rate limiter buckets all tunnel traffic as one client | MED |
| #449 | Security | `/metrics` unauthenticated & reachable through the public tunnel — leaks routes/traffic/latency | MED |
| #450 | Security | Public report endpoints unrate-limited — unauthenticated CPU/memory DoS (esp. `/reports/stats/xlsx`) | MED |
| #451 | Security | `/jobs` & `/jobs/{id}` public & unauthenticated — leak uploaded filenames + raw error messages | MED |
| #452 | Security | pi-songs SSH allows password auth, no fail2ban | MED |
| #453 | DevSecOps | cloudflared & promtail pinned to `:latest` on the public-facing host | MED |
| #454 | DevOps | pi-deploy runbook still says "LAN-only, no public internet exposure" — now false | MED |
| #455 | Product | Public exposure publishes leader/preacher names, sermon titles & full history — confirm intended audience (re-triage #2) | MED |

### Grades

| Persona | Grade | Notes |
|---------|-------|-------|
| Senior Architect | A- | Code structure clean (Review 10 fixes landed); only smell is the dual public-tunnel vs Traefik path |
| Senior Developer | A- | No new code-logic bugs; findings are deployment/exposure, not application logic |
| Senior DevOps | C | Public host has no firewall, app port on 0.0.0.0, unpinned tunnel image, and a runbook that contradicts reality |
| Senior Security Architect | C | Strong code-level controls (CSP/CSRF/HSTS/param queries), but weak posture for a public service: world-readable secrets, app+metrics reachable off-Cloudflare, defeated rate limiting, public /jobs & /metrics |
| Senior DevSecOps | B- | CI supply chain solid; the two most-privileged runtime containers are unpinned and secret-at-rest perms are wrong |
| Senior QA Engineer | A- | Large healthy suite + e2e/contract coverage; gap was no tests asserting deploy security posture (now embedded in issues) |
| Product Manager | B | Features solid; the live question is the privacy/audience decision for now-public congregant data |
| UAT Analyst | A- | Strong Playwright coverage incl. the new upload→songs pipeline; no new gaps |
| Accessibility Specialist | B+ | Songs concise live region + polite upload landed; #431 (services) still open |
| Database / Data Engineer | A- | WAL, indexes, read-snapshot pagination (#415), retry-safe inserts (#400) landed; #420 still tracked |

**Overall: C+** — the codebase is in good shape, but the production security posture for the newly public deployment has several real, fixable gaps (the focus of this review).

---

## Review 10 — 2026-05-25

**Branch:** `agent/claude/import-summary-output`
**Reviewer:** Claude Code (full-code-review skill)
**Issues created:** #399–#416

### Findings

| Issue | Persona | Title | Severity |
|-------|---------|-------|----------|
| #399 | Architect | `Database.normalize_service_dates()` imports from `pptx_reader` — cross-layer coupling | MED |
| #400 | Developer | `insert_or_get_song/edition/copy_event` have TOCTOU race under concurrent background imports | HIGH |
| #401 | Developer | `upload.js` injects `job.error_message` into `innerHTML` without HTML escaping | MED |
| #402 | DevOps | Dockerfile has no `HEALTHCHECK` instruction | MED |
| #403 | DevOps | Dockerfile base image is Python 3.14 (pre-release) | HIGH |
| #404 | Security | `X-Forwarded-For` leftmost-IP trust is bypassable — rate limiter can be evaded | MED |
| #405 | Security | Missing `Strict-Transport-Security` response header | MED |
| #406 | Security | `CSRF_SECRET` env var not enforced — process restart invalidates all live tokens | MED |
| #408 | DevSecOps | `pip-audit` CVE skip for CVE-2026-3219 has no expiry mechanism | LOW |
| #409 | QA | CI test-count floor (700) is stale — actual suite is 1010+ tests | HIGH |
| #410 | QA | No snapshot test for CCLI CSV column headers | MED |
| #411 | PM | CCLI report has no inline preview before downloading CSV | LOW |
| #412 | UAT | No E2E Playwright test verifying songs appear in /songs after successful upload | MED |
| #413 | Accessibility | `aria-live` on song table announces full table content on every HTMX search swap | MED |
| #414 | Accessibility | Upload result div uses `role=alert`/`aria-live=assertive` on initially empty element | LOW |
| #415 | Database | Pagination queries (COUNT + SELECT) run without a shared read snapshot | LOW |
| #416 | Developer | `_is_invalid_line()` has duplicate "all rights reserved" string — dead code | LOW |

### Grades

| Persona | Grade | Notes |
|---------|-------|-------|
| Senior Architect | A- | Clean separation of concerns; cross-layer import in db→pptx_reader is the main structural debt |
| Senior Developer | B+ | Strong typing and error handling; TOCTOU race in concurrent inserts is a real data-integrity bug; innerHTML XSS risk |
| Senior DevOps | B+ | Excellent CI pipeline; Python 3.14 pre-release image and missing Dockerfile HEALTHCHECK are operational risks |
| Senior Security Architect | B+ | CSP, CSRF, parameterized queries, rate limiting all solid; X-Forwarded-For bypass and missing HSTS are gaps |
| Senior DevSecOps | A- | SHA-pinned actions, Trivy, SBOM, gitleaks all present; CVE skip without expiry is process debt |
| Senior QA Engineer | B+ | 1010+ tests with strong coverage; CI floor stale, no CCLI header snapshot, mutation testing non-blocking |
| Product Manager | B+ | Full feature set for the use case; CCLI preview would reduce admin friction |
| UAT Analyst | B+ | Strong Playwright coverage for CRUD and forms; missing full upload-to-songs pipeline verification |
| Accessibility Specialist | B+ | Good foundations (skip-nav, aria-sort, labels); aria-live verbosity and assertive role misuse are UX issues |
| Database / Data Engineer | A- | WAL, indexes, migrations, whitelist-validated ORDER BY all correct; pagination read consistency is minor |

**Overall: B+**

---

## Review 9 — 2026-03-21

**Branch:** `main`
**Reviewer:** Claude Code (full-code-review skill)
**Issues created:** #335–#344

### Findings

| Issue | Persona | Title | Severity |
|-------|---------|-------|----------|
| #335 | Accessibility | Report form checkbox and date inputs missing accessible error feedback | MED |
| #336 | Accessibility | Services table empty action header and missing captions on detail tables | MED |
| #337 | Accessibility | stat-box label and badge-missing colors have marginal WCAG AA contrast | MED |
| #338 | Developer | purge_old_import_jobs accepts negative days parameter without validation | LOW |
| #339 | QA | No dedicated test file for ocr.py Vision API module | MED |
| #340 | QA | test_report_service.py has minimal assertions — leader filter and date boundaries untested | MED |
| #341 | Developer | _UploadRateLimiter reopens SQLite connection on every rate-limit check | LOW |
| #342 | Accessibility | Pagination links missing aria-label for screen reader context | LOW |
| #343 | Database | query_services uses SELECT * pulling all columns including source_file path | LOW |
| #344 | DevOps | CSRF_SECRET generated randomly on startup — breaks multi-process deployments | MED |

### Grades

| Persona | Grade | Notes |
|---------|-------|-------|
| Senior Architect | A | Excellent module separation; CreditResolver, import_service, report_service abstractions are clean and well-bounded |
| Senior Developer | A- | Clean code, strong typing, good error handling; minor purge validation and rate limiter efficiency gaps |
| Senior DevOps | A | Comprehensive CI with E2E, smoke test, lockfile verification, Trivy scanning; CSRF_SECRET startup logging needed |
| Senior Security Architect | A | CSP, CSRF, parameterized queries, ZIP magic bytes, LIKE escaping all solid; no injection vectors found |
| Senior DevSecOps | A | SHA-pinned actions, Trivy scan-before-push, SBOM baseline, gitleaks, pip-audit; lockfile used in all jobs |
| Senior QA Engineer | A- | 1,007 tests with strong markers and fixtures; OCR module and report service need deeper test coverage |
| Product Manager | A- | Functional features, good reporting, upload progress feedback; only deferred items remain |
| UAT Analyst | A- | 38+ Playwright tests cover upload, download, CSRF, navigation; good scenario coverage |
| Accessibility Specialist | B+ | Skip-nav, aria-sort, aria-live, labels, captions present; contrast and form feedback gaps remain |
| Database / Data Engineer | A- | WAL mode, indexes, migrations, parameterized queries; SELECT * in web queries and rate limiter connection churn are minor |

**Overall: A-**

---

## Review 8 — 2026-03-21

**Branch:** `fix/qa-sweep`
**Reviewer:** Claude Code (full-code-review skill)
**Issues created:** #315–#328

### Findings

| Issue | Persona | Title | Severity |
|-------|---------|-------|----------|
| #315 | Architect | repair-credits uses manual connect/close instead of context manager | LOW |
| #316 | Developer | sort_dir parameter not validated to safe values in DB query methods | HIGH |
| #317 | Developer | deprecated insert_copy_event still callable — no runtime guard | LOW |
| #318 | DevOps | Dockerfile uses python:3.14-slim — Python 3.14 is pre-release | MED |
| #319 | Security | LIKE pattern injection in query_services and query_leader methods | MED |
| #320 | Security | upload endpoint accepts file based solely on Content-Type header | MED |
| #321 | DevSecOps | CI security job installs extras not in lockfile | MED |
| #322 | QA | no mutation testing in CI — mutmut configured but never run | MED |
| #323 | Product Manager | no way to delete or correct misidentified songs from web UI | MED |
| #324 | UAT Analyst | no Playwright test for upload → poll → completion flow | HIGH |
| #325 | Accessibility | data tables missing caption, scope, and proper thead/th semantics | MED |
| #326 | Accessibility | services page filter inputs lack programmatic label association | MED |
| #327 | Database | query_songs_paginated count query does not match data query | MED |
| #328 | Database | delete_service_data does not remove orphaned songs or editions | LOW |

### Grades

| Persona | Grade | Notes |
|---------|-------|-------|
| Senior Architect | A | Clean separation of concerns; shared import pipeline; well-defined DB boundary. Minor lifecycle issue in one CLI command. |
| Senior Developer | B+ | 990 tests, 94% coverage, strong type checking. sort_dir validation gap is the main gap. |
| Senior DevOps | B+ | Excellent CI pipeline with CVE scan, smoke test, SBOM. Python version mismatch between Docker and CI is notable. |
| Senior Security Architect | B | CSP, CSRF, parameterized queries, non-root Docker user all good. LIKE injection and content-type-only upload validation are gaps. |
| Senior DevSecOps | B+ | SHA-pinned actions, gitleaks, pip-audit, lockfile verification. Security job dependency installation inconsistency. |
| Senior QA Engineer | B | Strong test suite with good coverage. Mutation testing configured but unused is a missed opportunity. |
| Product Manager | B | Functional product with clear user workflows. Lack of data correction UI is a significant gap for non-technical users. |
| UAT Analyst | B | E2E tests exist and run in CI. Upload flow — the most critical user journey — has no browser-level test. |
| Accessibility Specialist | B- | Skip nav, sr-only class, aria-sort, aria-live all present. Table semantics and label association need work. |
| Database / Data Engineer | B+ | WAL mode, indexes, migration framework, parameterized queries. Count/data query inconsistency and orphan cleanup gaps. |

**Overall: B+**

---

## Review 7 — 2026-03-21

**Branch:** `fix/extractor-size-limit`
**Reviewer:** Claude Code (full-code-review skill)
**Issues created:** #290–#309

### Findings

| Issue | Persona | Title | Severity |
|-------|---------|-------|----------|
| #290 | Architect | Database class not usable as context manager | MED |
| #291 | Architect | CreditResolver instantiated per-song instead of per-run | LOW |
| #293 | Developer | repair-credits OCR path reloads PPTX per song | MED |
| #294 | DevOps | Dockerfile pip install extras misleading with --no-deps | LOW |
| #295 | DevOps | No SIGTERM handler — ThreadPoolExecutor jobs may be orphaned | MED |
| #296 | Security | _get_db() schema_ready flag not set atomically | MED |
| #297 | Security | Upload reads entire file body into memory before size check | HIGH |
| #298 | DevSecOps | CI test job does not verify minimum test count | MED |
| #299 | QA | No contract test for stats XLSX output schema | MED |
| #300 | QA | No test for upload rate limiter SQLite persistence | MED |
| #301 | Product Manager | No user feedback when PPTX has zero recognizable songs | MED |
| #302 | Product Manager | Services date filters have no clear/reset button | LOW |
| #303 | UAT | No Playwright test for CCLI CSV download end-to-end | HIGH |
| #304 | UAT | No Playwright test for upload workflow end-to-end | HIGH |
| #305 | Accessibility | Sortable table headers missing aria-sort attribute | MED |
| #306 | Accessibility | HTMX dynamic content updates lack aria-live regions | HIGH |
| #307 | Accessibility | Error pages use low-contrast gray text | LOW |
| #308 | Database | No indexes on song_id columns for join performance | MED |
| #309 | Database | Database._in_transaction flag not thread-safe | LOW |

### Grades

| Persona | Grade | Notes |
|---------|-------|-------|
| Senior Architect | B+ | Good module separation and dataclass design; Database lifecycle still manual, CreditResolver instantiation pattern suboptimal |
| Senior Developer | B+ | Clean code with strong typing; repair-credits PPTX reload is a performance gap |
| Senior DevOps | A- | Excellent CI with E2E, smoke test, lockfile verify; minor Dockerfile clarity and SIGTERM gaps |
| Senior Security Architect | B | CSP, CSRF, parameterized SQL solid; upload memory consumption and schema_ready atomicity are real risks |
| Senior DevSecOps | B+ | SHA-pinned actions, Trivy scan, SBOM baseline; CI needs minimum test count guard |
| Senior QA Engineer | B | 950+ tests, good markers; XLSX contract and rate limiter persistence untested |
| Product Manager | B | Functional features; zero-song feedback and filter reset are UX gaps |
| UAT Analyst | B- | Playwright tests exist but miss critical download and upload workflows |
| Accessibility Specialist | C+ | Skip-nav, labels, semantic HTML present; aria-sort, aria-live, and contrast gaps remain |
| Database / Data Engineer | B | WAL mode, parameterized queries, migrations; missing indexes and thread-safety documentation |

**Overall: B**

---

## Review 6 — 2026-03-21

**Branch:** `fix/extractor-size-limit`
**Reviewer:** Claude Code (full-code-review skill)
**Issues created:** #274–#289

### Findings

| Issue | Persona | Title | Severity |
|-------|---------|-------|----------|
| #274 | Architect | CLI commands leak database connections on error paths | HIGH |
| #275 | Developer | OcrBudget.consume() return value not checked in repair-credits | HIGH |
| #276 | Product Manager | Upload page provides no feedback on import progress | HIGH |
| #277 | Architect | _schema_ready flag race condition between threads | MED |
| #278 | Developer | Double file hash computation during import | MED |
| #279 | Developer | Duplicated copy-event SQL across query/iter methods | MED |
| #280 | Architect | Non-song content marker lists duplicated in extractor | MED |
| #281 | Developer | O(n*m) service-song counting in CLI stats report | MED |
| #282 | Security | Missing X-Content-Type-Options, Referrer-Policy headers | MED |
| #283 | Security | Rate limiter collapses behind reverse proxy | MED |
| #284 | DevSecOps | Containers missing cap_drop ALL and no-new-privileges | MED |
| #285 | DevSecOps | CI test/e2e jobs install unlocked deps, not lockfile | MED |
| #286 | QA | CSV header contract tests assert partial columns only | MED |
| #287 | QA | HTMX songs search does not update pagination controls | MED |
| #288 | Product Manager | Stats download forms in HTMX partial may not bind CSRF | MED |
| #289 | DevOps | Web service in compose.yml missing init:true | MED |

### Grades

| Persona | Grade | Notes |
|---------|-------|-------|
| Senior Architect | B+ | Good separation (import_service, report_service), but DB connection lifecycle and thread-safety gaps |
| Senior Developer | B | Clean code, good types; double-hash and quadratic scan are performance risks |
| Senior DevOps | A- | Excellent pipeline with E2E job, smoke test, lockfile verification; minor compose.yml gap |
| Senior Security Architect | B | CSP, CSRF, parameterized queries all solid; missing standard headers and proxy-aware rate limiting |
| Senior DevSecOps | B+ | SHA-pinned actions, Trivy scan-before-push, SBOM baseline; CI dep install doesn't use lockfile |
| Senior QA Engineer | B | 916 tests at 94% coverage, E2E now in CI; CSV contract tests need tightening |
| Product Manager | B- | Functional features, good reporting; upload progress feedback is the biggest UX gap |
| UAT Analyst | B | 33 Playwright tests cover nav/search/sort/CSRF; missing upload workflow and download validation E2E |
| Accessibility Specialist | C+ | Skip-nav exists, basic ARIA; services filters lack labels, no ARIA live regions for HTMX updates |
| Database / Data Engineer | B | WAL mode, parameterized queries, migration tracking; schema_ready race and no indexes on hot paths |

**Overall: B**

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
