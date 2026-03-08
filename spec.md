# Worship Slide Deck Song Catalog — Extraction + Catalog Pipeline (Spec)

## Goal

Build a repeatable pipeline that:

1. Extracts **service metadata** + **songs used** from worship PPTX slide decks.
2. Stores normalized data in a small **SQLite** DB (not just CSV).
3. Generates:
   - **CCLI Copy Report export for a date range**, suitable for entering into the CCLI reporting portal
   - Internal stats (song frequency, unique songs, leader trends, repetition over time)
4. Supports a low-friction weekly workflow so the required CCLI reporting window (typically a 6‑month period when assigned) is painless.

CCLI-focused constraints we must support:

- Reporting is by **date range** and requires logging each instance of reproduction (e.g., projection/print/recording/translation).
- Prefer capturing **CCLI Song Number** when possible (most accurate identifier).
- Support “Nothing to Report” weeks.
- Support excluding **public domain** songs from reports (configurable).

Non-goals (for v1):

- Automated submission into CCLI portal (we will export; you submit)
- Fully automated CCLI Song Number lookups unless you provide a mapping/source

---

## Inputs

### Primary input: PPTX slide decks

- Convention: a **hidden first slide** contains structured metadata (preferred).

### Metadata slide format (required)

- Slide 1 is hidden (`show="0"` in PPT XML) and contains a **table** with key/value pairs.
- Required keys:
  - `Date` (ISO `YYYY-MM-DD`)
  - `Service` (e.g., `Morning Worship`, `Evening Worship`)
  - `Song Leader`
- Optional keys:
  - `Preacher`
  - `Sermon Title`
  - `Series`
  - `Notes`
- If a key is missing, set it to NULL and keep processing.

---

## Outputs

### Database

SQLite file, e.g. `data/worship.db`

### Reports

- `ccli_copy_report.csv` (date, service, title, **ccli\_number**, reproduction\_types, counts)
- `ccli_nothing_to_report.csv` (weeks/services with no reportable songs)
- `stats_*.md` or `stats_*.html` (optional)
- Console output summary (songs found, anomalies)

---

## Data model (SQLite)

Keep it normalized, but pragmatic, and support multiple **versions/editions** of the same song (publisher + arranger/composer differences).

### Table: services

- id (PK)
- service\_date (TEXT, ISO date)
- service\_name (TEXT)              -- "Morning Worship" / "Evening Worship"
- song\_leader (TEXT, nullable)     -- may be NULL when metadata slide is absent
- preacher (TEXT, nullable)
- sermon\_title (TEXT, nullable)
- source\_file (TEXT)               -- original pptx filename
- source\_hash (TEXT)               -- sha256 of file bytes
- imported\_at (TEXT)               -- ISO datetime

Constraints:

- UNIQUE(service\_date, service\_name, source\_hash)

### Table: songs

Represents the **canonical song identity**.

- id (PK)
- canonical\_title (TEXT, UNIQUE)   -- normalized
- display\_title (TEXT)             -- first-seen casing
- ccli\_number (TEXT, nullable)     -- optional mapping later
- aliases\_json (TEXT, nullable)

### Table: song\_editions

Represents a specific **edition/version** of a song, based on publisher and credits.

- id (PK)
- song\_id (FK -> songs.id)
- publisher (TEXT, nullable)       -- e.g., "Paperless Hymnal", "Taylor Publications"
- words\_by (TEXT, nullable)        -- parsed credits
- music\_by (TEXT, nullable)
- arranger (TEXT, nullable)
- other\_credits (TEXT, nullable)   -- e.g., "Edited", "Arr. Copyright...", etc.
- copyright\_notice (TEXT, nullable)

Constraints:

- UNIQUE(song\_id, publisher, words\_by, music\_by, arranger)

### Table: service\_songs (join)

Links a service to the **song edition actually used**.

- id (PK)
- service\_id (FK -> services.id)
- song\_id (FK -> songs.id)
- song\_edition\_id (FK -> song\_editions.id, nullable)
- ordinal (INTEGER)                -- order in service
- occurrences (INTEGER)            -- number of slide groups seen (optional)
- first\_slide\_index (INTEGER, nullable)
- last\_slide\_index (INTEGER, nullable)

Constraints:

- UNIQUE(service\_id, ordinal)

### Table: copy\_events

Represents **what must be reported to CCLI**: each instance of reproduction per service.

- id (PK)
- service\_id (FK -> services.id)
- song\_id (FK -> songs.id)
- song\_edition\_id (FK -> song\_editions.id, nullable)
- reproduction\_type (TEXT)         -- enum: projection|print|recording|translation
- count (INTEGER)                  -- usually 1 per service, but configurable
- reportable (INTEGER)             -- 1/0 (exclude public domain or policy-based exclusions)

Constraints:

- UNIQUE(service\_id, song\_id, song\_edition\_id, reproduction\_type)

---

## Extraction logic

Implement in Python using `python-pptx`.

Implement in Python using `python-pptx`.

### Step 1: Load PPTX and extract metadata

Preferred path:

- Read slide[0] XML attribute `show`; if hidden, treat as metadata slide.
- Look for a **table shape**; parse rows as `key => value`.

Fallback path (your historical decks):

- If **no metadata slide** exists, derive metadata from the filename.
  - Expected filename patterns:
    - `AM Worship YYYY.MM.DD.pptx`
    - `PM Worship YYYY.MM.DD.pptx`
  - Parse:
    - `service_date` from `YYYY.MM.DD`
    - `service_name` from `AM`/`PM` → `Morning Worship` / `Evening Worship`
  - Set `song_leader` NULL (or optionally infer from folder structure later).

Validation:

- If neither metadata slide nor filename parse works → mark run as `needs_review`.

### Step 2: Identify “song slides”

We use **one unified ruleset** for both publishers, but we also **detect and store the publisher** per song edition so we can see which version we tend to use.

Publishers seen:

- **Paperless Hymnal** (marker: `PaperlessHymnal.com`)
- **Taylor Publications** (marker often includes `Taylor Publications` and/or `Presentation © ... Taylor Publications LLC`)

Publisher detection (per slide):

- If any text contains `PaperlessHymnal.com` → publisher=`Paperless Hymnal`
- Else if any text contains `Taylor Publications` OR (`Presentation ©` AND `Publications`) → publisher=`Taylor Publications`
- Else publisher=NULL

Song slide detection: A slide is treated as a song slide if ANY of:

1. publisher is detected (above)
2. slide contains a short “title-like” line near the top AND also contains at least one image/picture shape (musical score)

Non-song slides (sermon, announcements, etc.) should be skipped unless they match the above.

### Step 3: Extract candidate title from a slide

Collect all text:

- text frames (all paragraphs)
- table cells

Ignore lines that are clearly not titles:

- publisher/footer markers (Paperless Hymnal / Taylor Publications / copyright blocks)
- lines containing: `Copyright`, `All Rights Reserved`, `All Rights reserved`, `Used by permission`, `admin. by`, `c/o`
- long lyric paragraphs (> \~120 chars)

#### Title detection + normalization rules

We want **one canonical song title**, not a new song per verse/chorus/bridge/part labels.

**A) Candidate selection (pick best title line)** Choose the best title candidate using this priority:

1. A short line (2–80 chars) that appears to be a title and is not a credit/footer.
2. If a slide contains both a prefixed-title line (e.g., `1-1 Ancient Words`) and a plain title line (`Ancient Words`), prefer the plain line.

**B) Strip part/section indicators (MUST NOT create new songs)** Apply these normalizations in order to any candidate line:

1. Numeric / chorus prefix with dash:

- `^\s*([0-9]+|[cC])\s*[-–]\s*(.+)$` → keep group 2

2. Compound numbering at start (e.g., `1-1 Title`, `C-2 Title`, `V1a – Title`):

- `^\s*[A-Za-z]?\d+(?:[-–]\w+)*\s*[-–]?\s*(.+)$` → keep group 1

3. Named sections (Verse/Chorus/Bridge/etc.) including compact forms like `Bridge1 Title`:

- `^\s*(Verse|V|Chorus|C|Refrain|R|Bridge|B|Tag|Intro|Outro|Coda|CODA|DS)\s*\d*\w*\s*[-–:]?\s*(.+)$` → keep group 2

4. Lowercase `tag` (seen in some decks):

- `^\s*tag\s+(.+)$` → keep group 1

**C) Canonicalization**

- normalize whitespace
- trim punctuation at ends
- canonical key is lowercase

---

### Step 3b: Extract publisher + credits (composer/arranger)

For each song occurrence, attempt to parse credits from the slide text (often present on Paperless and sometimes on Taylor):

Recognize and capture these fields when present:

- `Words and Music by:` / `Words & Music:`
- `Words by:`
- `Music by:`
- `Arr.:` / `Arr:` / `Arrangement by:`
- other credit fragments (e.g., `Edited.`)

Examples we need to handle (observed in your decks):

- `Words and Music by: Twila Paris / Arr.: Ken Young` (Paperless)
- `Words & Music: Traditional / Arr.: Pam Stephenson` (Paperless)
- `Words from Psalm 25:1-7, Music by: Charles F. Monroe, Arrangement by Pam Stephenson` (Paperless)

Store:

- publisher (from Step 2)
- words\_by, music\_by, arranger
- keep any remaining credit text as `other_credits` and/or `copyright_notice`

If multiple slides in an occurrence contain credit lines, merge them (prefer the most complete).

---

## Regex cookbook (unified rules)

This section is the concrete mapping from common slide-text patterns to normalized fields.

### A) Title extraction

| Raw line                 | Regex / rule                        | Normalized title                    |                   |
| ------------------------ | ----------------------------------- | ----------------------------------- | ----------------- |
| `1 - We Will Glorify`    | strip \`^([0-9]+                    | c)\s\*[-–]\s\*\`                    | `We Will Glorify` |
| `C – We Bow Down`        | strip \`^([0-9]+                    | c)\s\*[-–]\s\*\` (case-insensitive) | `We Bow Down`     |
| `1-1 Ancient Words`      | strip leading compound token        | `Ancient Words`                     |                   |
| `C-2 Light The Fire`     | strip leading compound token        | `Light The Fire`                    |                   |
| `tag Ancient Words`      | strip leading `tag`                 | `Ancient Words`                     |                   |
| `Bridge1 Mighty To Save` | strip leading section name + digits | `Mighty To Save`                    |                   |
| `DS1 Mighty To Save`     | strip leading section name + digits | `Mighty To Save`                    |                   |
| `CODA – Create In Me`    | strip leading section name          | `Create In Me`                      |                   |
| `V1a – Create In Me`     | strip leading section token         | `Create In Me`                      |                   |

Candidate selection rule:

- If the slide has both a prefixed line (`1-1 Title`) AND a plain line (`Title`), always choose the plain line.

### B) Publisher detection

| Marker text found                                                       | Publisher             |
| ----------------------------------------------------------------------- | --------------------- |
| contains `PaperlessHymnal.com`                                          | `Paperless Hymnal`    |
| contains `Taylor Publications` OR (`Presentation ©` and `Publications`) | `Taylor Publications` |

### C) Credits parsing

Capture these fields when present:

- `Words and Music by:` / `Words & Music:` → `words_by` and `music_by` (same list)
- `Words by:` → `words_by`
- `Music by:` → `music_by`
- `Arr.:` / `Arr:` / `Arrangement by:` → `arranger`

Common credit line shapes to handle:

- `Words and Music by: Twila Paris / Arr.: Ken Young`
- `Words & Music: Traditional / Arr.: Pam Stephenson`
- `Words from Psalm 25:1-7, Music by: Charles F. Monroe, Arrangement by Pam Stephenson`

Normalization:

- Store names as a single string as seen (no attempt to split into first/last).
- Preserve separators like `/` as part of the stored string when multiple names exist.

---

## Version preference analysis

Because we store `publisher` + `arranger/composer` in `song_editions`, we can report:

- which publisher’s edition is most frequently used per canonical title
- whether certain arrangers correlate with certain leaders/services
- “same title, multiple editions” occurrences over time

### Step 4: Group slides into song occurrences

Iterate slides in order:

- When extracted canonical title changes from previous title → start a new song occurrence
- Track `first_slide_index`, `last_slide_index`, and `occurrences`

Handle “picture-only” slides (score images) that precede the first text slide:

- If a slide has no usable title but matches publisher markers/picture heuristic, and the next slide yields a title, assign it to that title.

### Step 5: De-dup and aliasing

Before writing to DB:

- If titles differ only by punctuation/casing, treat as the same song.
- Optional: maintain aliases (JSON array) to help later cleanup.

---

## CLI design

Create a small CLI in `src/worship_catalog/cli.py`.

Commands:

- `import <pptx_or_folder> [--recurse] [--db data/worship.db]`
  - Imports one or many PPTX files
  - Uses sha256 to avoid duplicate imports
  - Emits summary + anomalies
- `report ccli --from YYYY-MM-DD --to YYYY-MM-DD --out ccli_usage.csv`
- `report stats --from ... --to ... --out stats.md`
- `validate <pptx>` prints extracted metadata + detected song list (no DB write)

Exit codes:

- 0 success
- 2 needs\_review (missing required metadata OR low-confidence extraction)
- 1 failure

Logging:

- JSONL logs in `logs/import_YYYYMMDD.jsonl`
- Each anomaly includes: filename, slide index, reason, extracted candidates

---

## Workflow integration for CCLI reporting

We need an explicit workflow that turns “songs detected in a deck” into “copy activity to report”.

### Default CCLI assumptions (configurable)

Given your current practice:

- `projection` count = 1 per song per service (lyrics projected)
- `print` count = 0 (you do not print lyrics)
- `recording` count = 1 per song per service (services are livestreamed/recorded: Facebook today; YouTube soon)
- `translation` count = 0

These should be set in a config file (e.g., `config/reporting.yml`) and/or overridden per service. (e.g., `config/reporting.yml`) and/or overridden per service.

### Weekly “import” workflow (recommended)

1. Drop the final PPTX into a watched folder.
2. Importer runs:
   - extracts songs + editions
   - creates/updates `service_songs`
   - generates `copy_events` for that service using defaults
3. If no reportable songs found for the week/service → mark as “Nothing to Report”.

### Date-range reporting workflow

1. When CCLI requests a reporting window (e.g., 6 months), run:
   - `report ccli --from YYYY-MM-DD --to YYYY-MM-DD`
2. Output:
   - a detailed CSV for copy activity
   - a separate list of “Nothing to Report” weeks/services
3. Optional: generate a “review queue” CSV for any songs missing CCLI numbers.

### CCLI song number workflow (future enhancement)

For v1, **CCLI Song Number is out of scope**. Reports will be produced using normalized title + date + reproduction type.

Future enhancement:

- Maintain an **offline local catalog** mapping `canonical_title (+ optional credits)` → `ccli_number`.
- Populate via manual export/lookup from SongSelect or the CCLI reporting portal search.
- Provide utilities to import/update this mapping (CSV) and flag ambiguous title collisions.

### Public domain handling

- Add a per-song flag (or per-edition flag) to mark `public_domain=1`.
- Default behavior: public domain songs are **not reportable** and are excluded from `copy_events`.

---

## Review/correction workflow (MVP)

We will use **sidecar override JSON files** (auditable, n8n-friendly) instead of a web UI.

### Override file convention

For a deck named:

- `AM Worship 2025.11.02.pptx` Overrides live at:
- `AM Worship 2025.11.02.override.json`

### Override file schema (MVP)

```json
{
  "service_meta": {
    "service_date": "2025-11-02",
    "service_name": "Morning",
    "song_leader": "..."
  },
  "songs": [
    {
      "ordinal": 1,
      "title": "Mighty To Save",
      "publisher": "Paperless Hymnal",
      "raw_credits": "Words and Music by: ... / Arr.: ...",
      "credits": {"words_by": "...", "music_by": "...", "arranger": "..."}
    }
  ],
  "notes": "optional"
}
```

Overrides are **partial**: unspecified fields do not overwrite extracted values.

### Interactive mode (CLI prompts)

Default behavior may prompt for unresolved items and then **write/merge** the sidecar override JSON.

### Non-interactive mode (automation)

Add flags for n8n/unattended runs:

- `--non-interactive` / `--no-prompt`: never prompt; rely on extraction + override file only
- `--require-overrides`: fail if unresolved items exist and no override present
- `--write-overrides`: write a sidecar file with proposed values + unresolved items for later review

### Idempotency + re-run behavior

We must remain idempotent across re-runs and override edits.

Implementation:

- Compute `source_hash` (sha256 of PPTX bytes).
- Compute `override_hash` (sha256 of override JSON bytes, if present).
- A service import is uniquely identified by `(service_date, service_name, source_hash, override_hash)`.

Re-run rules:

1. Same PPTX, same override content → no-op.
2. Same PPTX, override changed → replace derived rows for that service deterministically:
   - delete/rebuild `service_songs` + `copy_events`
   - keep canonical `songs` / `song_editions` (dedupe by keys)
3. PPTX changed (new hash) → new import; optionally mark prior import as superseded.

---

## n8n automation (Dropbox/OneDrive)

Pattern:

1. Trigger: “New file in folder”
2. Filter: file ends with `.pptx` and matches naming scheme (optional)
3. Action: run Dockerized importer or local script via SSH
4. Action: post result somewhere useful (Slack/Teams/email)

Implementation notes:

- Make importer idempotent via `source_hash` uniqueness.
- Store SQLite DB on persistent storage (NAS/VM), not ephemeral containers.

---

## Repo structure (recommendation)

. ├── SPEC.md ├── pyproject.toml ├── src/ │   └── worship\_catalog/ │       ├── **init**.py │       ├── cli.py │       ├── pptx\_reader.py │       ├── extractor.py │       ├── normalize.py │       ├── db.py │       └── reports.py ├── tests/ │   ├── test\_metadata.py │   ├── test\_title\_patterns.py │   └── fixtures/ │       └── sample.pptx └── data/ └── worship.db   (gitignored)

---

## Test-driven development (TDD) approach

Testing is a first-class deliverable from day 1. Every new capability must land with automated tests that prove:

- correct extraction (titles, grouping, publisher, credits)
- correct metadata inference (hidden slide and filename fallback)
- stability against regressions when templates change

### Guiding rules

- **Red → Green → Refactor** for each feature.
- Keep extraction logic **pure and deterministic** wherever possible:
  - parsing functions accept `list[str]` / small structs, return plain dataclasses
  - avoid coupling tests to file I/O when a unit test can cover the same logic
- Use **fixture PPTX files** only for integration-style tests; most tests should be unit tests.
- Every bug becomes a regression test.

### Test layers

1. **Unit tests (majority)**

   - Title normalization (strip verse/chorus/bridge indicators)
   - Candidate selection (prefer plain title over prefixed forms)
   - Publisher detection (Paperless marker; Taylor marker when present)
   - Credits parsing (words\_by / music\_by / arranger)
   - Grouping logic (contiguous canonical titles become one occurrence)

2. **Integration tests (PPTX fixtures)**

   - End-to-end slide parsing on a small set of representative decks
   - Validate output: extracted titles in order + publisher + credits presence
   - Verify anomalies are produced when expected

3. **Contract tests (output stability)**

   - Golden-file testing for `validate` output as JSON (preferred) so diffs are clear

### Required test harness (day 1)

- Use `pytest` as the runner.
- Add `ruff` (lint) and `mypy` (type check) to prevent subtle parsing breakage.
- CI must run on every commit/PR.

Recommended additions to `pyproject.toml`:

- dev dependencies: `pytest`, `pytest-cov`, `ruff`, `mypy`
- optional: `python-Levenshtein` if later using fuzzy matching

### Make the CLI testable

To enable automated testing from day 1:

- Implement `validate` to support a **machine-readable output mode**:
  - `worship-catalog validate <pptx> --format json`
  - `--format human` remains default
- JSON schema (contract):
  - `service_meta`: {date, service\_name, song\_leader, source\_file}
  - `songs`: ordered list of {ordinal, title, canonical\_title, publisher, credits, slide\_range}
  - `anomalies`: list of {slide\_index, reason, sample\_lines}

Tests should assert JSON content, not console formatting.

### Initial fixture set (use your uploaded decks)

Create a fixtures folder:

- `tests/fixtures/AM Worship 2025.11.02.pptx`
- `tests/fixtures/AM Worship 2025.11.16.pptx`
- `tests/fixtures/PM Worship 2025.11.16.pptx`
- `tests/fixtures/AM Worship 2025.11.23.pptx`
- `tests/fixtures/AM Worship 2025.12.07.pptx`
- `tests/fixtures/PM Worship 2025.12.07.pptx`
- `tests/fixtures/AM Worship 2025.12.14.pptx`

For each fixture, maintain a small paired truth file:

- `tests/fixtures/<same-base>.expected.json` This is the “golden” expected extraction result.

### What to test first (day 1 backlog)

1. **Filename metadata parser**
   - parses `AM/PM` and `YYYY.MM.DD` correctly
   - rejects unknown formats (needs\_review)
2. **Title normalization**
   - strips: `1 - Title`, `1-1 Title`, `Bridge1 Title`, `DS1 Title`, `Coda1 Title`, `tag Title`
3. **Candidate selection**
   - if both `1-1 Title` and `Title` exist in same slide text set, choose `Title`
4. **Grouping**
   - contiguous slides with same canonical title become a single occurrence
5. **Credits parsing**
   - extract words/music/arranger from common line shapes

### CI pipeline (required)

- `pytest -q --cov=src`
- `ruff check .`
- `mypy src`

### Definition of done (DoD)

A feature is done only when:

- unit tests cover the parsing/normalization rules
- at least one integration test covers the feature end-to-end on a fixture deck
- CI passes

---

## Testing strategy

(See TDD section above; strategy is implemented as unit + integration + contract tests.)

---

## Edge cases / operational decisions

- If metadata slide missing:
  - fallback to parsing filename conventions (optional)
  - or require a prompt/manual override in CLI
- If extraction confidence is low:
  - flag `needs_review` and output `review.json` containing slide text snippets
- If you later want automatic CCLI #:
  - seed a catalog (CSV/JSON) mapping canonical\_title -> ccli\_number
  - match exact first, then fuzzy (rapidfuzz) with threshold + manual review queue

---

## Deliverables (implement in this order)

1. `validate` command working on the sample deck
2. `import` to SQLite (services + songs + join)
3. `report ccli` for date range
4. n8n trigger wiring

