# Sprint Plan

Current sprint planning mirror for `highland/song-history`.

- GitHub milestones are the sprint assignment source of truth.
- This document mirrors the current **non-deferred** open backlog only.
- Deferred issues are intentionally excluded from the sprint scopes below, even
  if they still sit on a milestone in GitHub.

## Sprint 2 - Deploy & supply-chain hardening

Focus: finish the remaining public-host hardening item on `pi-songs`.

- #452 `sec`: pi-songs SSH allows password auth with no fail2ban

## Sprint 3 - Data layer & reliability

Focus: core data-path correctness, import concurrency, report correctness, and
runtime reliability in the web/import stack.

- #498 `dev`: `extract_songs` 120s timeout defeated by `ThreadPoolExecutor` blocking shutdown
- #500 `data`: song-list credits/sort nondeterministic for multi-edition songs
- #501 `arch`: heavy synchronous report/xlsx work blocks the event-loop thread
- #503 `devops`: `/upload` buffers the entire file (up to 200MB) in memory before writing
- #509 `data`: `insert_or_update_service` not retry-safe against a concurrent same-service import
- #510 `arch`: services schema defined in two disagreeing places
- #511 `data`: copy-events `IN` clause unbounded by SQLite variable limit
- #529 `dev`: leader-filtered stats report returns unrelated events when no services match

## Sprint 4 - Test strategy & OCR

Focus: test-suite sliceability, stronger regression coverage, and OCR failure handling.

- #499 `dev`: OCR retries permanent 4xx errors 3x with backoff
- #505 `qa/uat`: extend Playwright E2E to cover interactive HTMX report and upload flows
- #506 `qa`: expand mutation-testing scope to `db.py` and `import_service.py`
- #507 `qa`: pytest markers aspirational; fast-slice and guard tests need cleanup
- #508 `dev`: OCR response parsing assumes a text block at `content[0]`
- #530 `qa`: make e2e modules safe to collect during `pytest -m "not e2e"`

## Sprint 5 - UX, a11y & docs

Focus: browser usability, accessibility polish, and user-facing docs for the public web UI.

- #470 `enhancement`: report-page song-leader filter dropdown
- #504 `pm`: document browser Upload, Missing-Services report, and `UPLOAD_PASSWORD` auth gate
- #516 `a11y`: WCAG 2.1 AA polish for table semantics, contrast, and nav state
- #517 `uat`: HTMX live-search should push URL state so Back preserves filters

## Sprint 6 - Extraction edge cases

Focus: remaining extraction false positives that need domain-reviewed heuristics
rather than mechanical parser cleanup.

- #527 `bug`: `What the Lord Has Done` extracted as a phantom song; needs a
  non-refrain/domain-specific mechanism

## Out of scope for this plan

Deferred backlog intentionally excluded from the sprint scopes above:

- #323 `deferred`: delete/correct-song UI
- #152 `deferred`: automatic container image updates via Watchtower
- #86 `deferred`: CCLI report contract-test against the external CSV spec
- #46 `deferred`: Helm chart for self-hosted RKE2 deployment
