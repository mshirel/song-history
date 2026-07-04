# Sprint Plan

Current sprint planning mirror for `highland/song-history`.

- GitHub milestones are the sprint assignment source of truth.
- This document mirrors the current **non-deferred** open backlog only.
- Deferred issues are intentionally excluded from the sprint scopes below, even
  if they still sit on a milestone in GitHub.
- Sprint 2, Sprint 4, and Sprint 5 backlog items were closed overnight on
  2026-07-03/2026-07-04 and are intentionally absent from the active plan.

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
