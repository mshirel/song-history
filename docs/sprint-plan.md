# Sprint Plan

Current sprint planning mirror for `mshirel/song-history`, synchronized on
2026-07-17.

- GitHub milestones are the sprint assignment source of truth.
- This document mirrors the current **non-deferred** open backlog only.
- Deferred issues are intentionally excluded, even when assigned to a milestone.

## Sprint 3 - Safety and image OCR

Due: 2026-07-31. Focus: restore operational safety and deliver image-only score
recognition after establishing a reproducible development and CI environment.

No non-deferred open items remain in this sprint.

Completed: #537, #542, #544, #545, #546, and #547.

## Sprint 4 - Data correctness and OCR rollout

Due: 2026-08-14. Focus: harden concurrent writes, make credits deterministic,
and roll the Sprint 3 OCR result into production data.

- #500 `data`: make multi-edition song credits and sorting deterministic
- #509 `data`: make same-service concurrent imports retry-safe
- #510 `arch`: align the fresh services schema with migration 3
- #538 `ops`: re-import the Goodness of God decks after #537 ships
- #540 `data`: fix the transaction snapshot race in `insert_or_get_song`

## Sprint 5 - Runtime and extraction reliability

Due: 2026-08-28. Focus: bound resource use and blocking work, then address the
remaining extraction false positive requiring domain review.

- #498 `dev`: enforce the `extract_songs` timeout without blocking shutdown
- #501 `arch`: move synchronous report/xlsx work off the event-loop thread
- #503 `security`: stream uploads instead of buffering up to 200 MB in memory
- #511 `data`: bound copy-events queries by SQLite's variable limit
- #527 `bug`: classify `What the Lord Has Done` without a phantom song

## Out of scope for this plan

Deferred backlog intentionally excluded from the sprint scopes above:

- #323 `deferred`: delete/correct-song UI
- #152 `deferred`: automatic container image updates via Watchtower
- #86 `deferred`: CCLI report contract-test against the external CSV spec
- #46 `deferred`: Helm chart for self-hosted RKE2 deployment
