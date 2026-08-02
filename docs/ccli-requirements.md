# CCLI reporting requirements

What CCLI actually requires, and where this application's assumptions match or diverge from it.

Written because `spec.md` encodes a set of "default CCLI assumptions" that were never checked against
CCLI's published rules, and issue #86 proposes contract-testing the export against a column
specification that — as far as this research can establish — does not exist in the form assumed.

**Scope:** United States, congregational worship, Highland (`songs.highland-coc.com`). CCLI operates
country-specific licences and portals; UK/IE wording differs in places and is flagged where relied on.

**Status:** desk research from CCLI's published pages, August 2026. It is *not* a reading of
Highland's own licence certificate, which is the only authority on what Highland actually holds.
See [Open questions](#open-questions) — two of them can only be answered from the CCLI account.

---

## 1. The licence stack

CCLI sells permissions separately. Holding one does not imply the others.

| Licence | Covers | Highland |
|---|---|---|
| **Church Copyright License** | Reproducing lyrics to support congregational singing — projecting, typing out, copy & paste, printing songsheets/bulletins, and making custom arrangements (without altering melody, lyrics, or the song's fundamental character) | **Unknown** \* |
| **CCLI Streaming License** | Extends the above to online worship: live-streaming or uploading services containing songs performed live by your own musicians | **Unknown** \* |
| **CCLI Streaming Plus License** | Additionally covers master recordings — artist tracks, backing tracks, multitracks — from an authorised source during online services | Only needed if pre-recorded tracks are used |

\* **Not established by this research, and not stated by anyone.** Nothing in this repository
records which licences Highland holds, and no certificate was read. Left as Unknown deliberately:
guessing here would be a guess about a legal obligation. See [Open questions](#open-questions).

> **The Church Copyright License does not cover streaming** — that needs the separate Streaming
> License. This still matters even though Highland holds both, because the two are purchased and
> renewed independently: a lapse of the Streaming License alone would leave the livestream
> unlicensed while the copy report carried on looking perfect. `spec.md` records that services are
> livestreamed (Facebook today, YouTube planned). This application cannot detect, close, or warn
> about that gap — it is an account-level concern, not a software one.

Streaming Plus is also required for using master/backing tracks; neither streaming licence covers
choir anthems, and both carry limits on pre-recorded content outside the service stream.

---

## 2. What must be reported

Reporting exists so CCLI can distribute royalties to songwriters and publishers. It does **not**
affect the licence fee, so there is no incentive to under-report.

CCLI's four activity categories, quoted from **CCLI's own** *Online Reporting — a step-by-step
guide* (September 2017), which is the most explicit statement of the vocabulary I could find:

| CCLI's category | CCLI's wording | This app's term |
|---|---|---|
| **Print** | "When you have reproduced a song using a printed, copied or handwritten source (e.g. service sheets or OHP acetates) **or when you have made a custom musical arrangement** where no published version is available" | `print` |
| **Digital** | "When you project a song's lyrics onto a big screen using Powerpoint or projection software" | `projection` ⚠️ |
| **Record** | "When you have recorded (audio or video) a live performance of a song during a service/assembly" | `recording` ⚠️ |
| **Translation** | "When you make a translation of a song into a different language (where no existing translation is available)" | `translation` |

Two mappings here are not obvious and are easy to get wrong:

- **Projection is `Digital`, not "digital copies".** Our `projection` maps to it correctly, but the
  name differs, so anyone cross-checking the export against the portal is comparing two vocabularies.
- **There is no separate "custom arrangement" category — it folds into Print.** A future feature that
  invents one would be reporting into a bucket CCLI does not have.

The 2017 guide is also explicit about what a "1" means, which is the rule the app's data model
depends on:

> "Please report one (1) in the appropriate category for **each occasion on which a song was
> reproduced**, *not* how many copies of a song were made."

> "If you're reporting on a regular basis, the numbers you enter here will be **added to the total
> reproductions of that song in the current reporting period**."

So CCLI's ingestion model is a **per-song, per-category running total for the period**, built from
per-occasion increments.

### CCLI does not ask for a date

This is the single most surprising finding, and it changes how the export should be read. The
Church Copyright License report has **no date field**: you search for a song, enter a number 0–9 in
each of the four categories, and submit. The only temporal language in CCLI's instructions is
"since you last reported". The one place CCLI does ask for a date is the **CCS WorshipCast**
licence, which is a different licence with a different flow.

Our per-event rows carry `Date` and `Service`. That is *more* than CCLI ingests — which is a feature
for the human doing the typing (an auditable, correctable record of what happened when) and a cost
at the moment of transcription (they must tally by hand). See [§5.2](#52-the-exports-columns-and-what-a-test-can-honestly-assert).

Two rules that directly constrain this application:

1. **Streaming may be one credit per performance even across multiple platforms — UNCONFIRMED.**
   CCLI's US streaming page was re-read on 2026-08-02 and **does not address the question at all**.
   Treat this as an open question, not a rule: it decides whether adding YouTube alongside Facebook
   should double the streaming credits or leave them unchanged, and it is exactly the kind of thing
   to ask CCLI directly rather than infer. See [§5](#5-implications-for-this-application).
2. **Translation is additive.** A translated song is reported as a translation credit *in addition
   to* the credit for the original-language song, not instead of it.

### Public domain

No CCLI reporting is required for public-domain songs. A work enters the public domain 70 years
after the author's death, at which point no permission is needed to reproduce the words. The
application's configurable public-domain exclusion is therefore correct.

### "Nothing to report"

CCLI asks churches to report on a regular basis — ideally weekly — **even when there is nothing to
report**, because that positively confirms the record is current rather than merely absent. The
application's `ccli_nothing_to_report.csv` output matches this.

---

## 3. Reporting cadence

Two distinct rhythms, easily conflated:

- **Ongoing:** report weekly, or whenever songs are used or copies made. Can be manual through the
  CCLI reporting portal, or automatic from participating worship/presentation software.
- **Mandatory:** each organisation is assigned a **six-month copy-reporting period once every
  two and a half years**. CCLI notifies by mail and email beforehand.

`spec.md`'s "typically a 6-month period when assigned" is correct. The 2.5-year cycle is worth
recording explicitly, because it means the assigned window will usually arrive after a long enough
gap that nobody remembers the workflow — which is precisely the case this application exists to make
painless.

---

## 4. Identifying songs

The CCLI Song Number is the most accurate identifier, but how strictly it is required depends on the
submission path:

- **Online portal / auto-reporting:** CCLI states you must include the correct CCLI song numbers,
  found via SongSelect. Auto-reporting integrations rely on SongSelect to keep the mapping accurate.
- **Manual write-in sheet:** the song-number column is explicitly marked *"IF KNOWN"*, alongside
  free-text title, author(s) and copyright information.

`spec.md` places CCLI Song Number out of scope for v1, reporting on normalised title + date +
reproduction type instead. That is defensible for a write-in submission and insufficient for portal
submission. **Which path Highland uses decides whether the song-number mapping is a nice-to-have or
a blocker** — see [Open questions](#open-questions).

### Copyright notice on display

Separate from reporting, but a licence condition: each printed or projected song must display the
author/writer, copyright year, publisher, and **the church's CCLI licence number** (not the song's
CCLI ID — a common confusion). Since this application already parses the source PPTX decks, it is
positioned to *audit* whether decks carry a compliant notice. Not currently in scope; noted as a
possible future check.

---

## 5. Implications for this application

### 5.1 `recording` is misnamed, and the name hides a real bug risk

`config/reporting.yml` and `import_service.py` use `recording` for what CCLI calls
**video or audio streaming**. The naming is worth fixing on its own, but the reason to care is the
counting question behind it. The importer hardcodes `recording=1` per song per service. If CCLI
counts one credit per *performance*, that stays correct when YouTube joins Facebook and the
natural-seeming change — emit an event per platform — would silently **double** every streaming
credit in a compliance document. If CCLI counts per *platform*, the current behaviour is already
under-reporting once a second platform exists.

**Which of those is true is not established** — CCLI's US streaming page does not say (re-checked
2026-08-02). Ask CCLI before adding a second platform, then pin the answer with a regression test.
Do not write the test first: it would encode a guess as a compliance guarantee.

### 5.2 The export's columns, and what a test can honestly assert

Three column sets are in play:

| Source | Columns |
|---|---|
| **Emitted today** (`cli.py`, `web/app.py`) | `Date`, `Service`, `Title`, `CCLI#`, `Reproduction Type`, `Count` |
| **Asserted by issue #86** | `Song Title`, `Words By`, `Music By`, `Arranger`, `Publisher`, `Reproduction Type`, `Times Used` |
| **CCLI** | — no published file format exists |

**Issue #86's columns are wrong on the merits, not merely unsourced.** `Words By`, `Music By`,
`Arranger` and `Publisher` are song *credits*. CCLI already holds those in its own catalogue and
identifies songs by **CCLI song number**; it never asks a church to report them. They appear only as
write-in fallback when a song is not in CCLI's catalogue, and then only as title plus authors.
Meanwhile that column list **drops the CCLI song number** — the one identifier CCLI and every
auto-reporting integration actually key on, and the reason Planning Center silently excludes songs
without one. The proposal reads like a plausible-looking invention.

A contract test hard-coding those headers would fail immediately and, once "fixed", would cement an
invented specification: it would report confidence about legal compliance while proving only
self-consistency. That is worse than no test.

**What a test can legitimately assert** is this project's own contract, not conformance to an
external spec that does not exist:

- a stable header row and stable column order (already covered by `TestCsvHeaderContracts`);
- ISO dates, in the file and in the filename;
- `CCLI#` present or explicitly blank, never absent;
- `Reproduction Type` drawn from a **closed enum**, so a typo in `import_service.py` cannot reach a
  licensing document — and ideally an enum that maps onto CCLI's real four terms;
- the encoding the file is served with;
- display title, not canonical title.

### 5.2b Per-event log or per-song aggregate?

Both are defensible and they answer different questions. CCLI ingests a **per-song, per-category
total for the reporting period**, so an admin transcribing from our per-event log has to tally by
hand — every other tool surveyed (Planning Center's *CCLI Copy Activity*, SlideGen's worksheet)
emits the aggregate precisely because it maps 1:1 onto the portal's data entry.

But the per-event log is the faithful underlying record — CCLI's own instruction is to report one
per *occasion* — and it is what makes the data auditable and correctable, which matters here because
this app derives its events from OCR and slide classification that can be wrong.

**The useful answer is both, from the same data**: keep the per-event log as the record and the
audit trail, and add an aggregate view (song, CCLI#, count per category, over the range) as the
transcription aid. That is a feature, not a test, and it should be its own issue.

### 5.3 What `spec.md` got right

Recorded so it does not get re-litigated: the six-month assigned window, "Nothing to Report" weeks,
configurable public-domain exclusion, and the four-category shape are all consistent with CCLI's
published rules. The defaults `print=0` and `translation=0` are `spec.md`'s, and are configurable; whether they match Highland's actual practice is unrecorded anywhere and was not checked.

---

## Open questions

Neither can be answered from the code or from CCLI's public pages:

1. **Does Highland hold a CCLI Streaming License?** Open. `spec.md` records that services are
   livestreamed, and the Church Copyright License does not cover that on its own. Nothing in this
   repository says which licences Highland holds. If only the base licence is held, this application
   can emit a flawless copy report while the stream is unlicensed — a gap no amount of software can
   detect or close. Worth confirming once against the CCLI account and re-checking at renewal, since
   the two licences renew independently.
2. **Will Highland submit through the online portal or the write-in path?** This decides whether the
   CCLI Song Number mapping (currently out of scope for v1) is optional or required. Still open, and
   it is the question that most affects what this application needs to build next.

---

## Sources and confidence

**Verified from CCLI's own material** (re-checked 2026-08-02): the licence split and that streaming
needs its own licence; the four category names and their definitions; "report one (1) for each
occasion"; period totals accumulating per song; that no date is captured for the Church Copyright
License; the six-month-every-two-and-a-half-years manual rotation; "nothing to report"; and that
CCLI song numbers are required for portal submission.

**Firm negative finding:** *no published CCLI CSV or file specification exists for Church Copyright
License usage.* This is the result of searching ccli.com across the US, UK, global, IE, SE and AU
reporting pages, CCLI's support knowledge base (the full Online Reporting category — twelve
articles, none about file formats), CCLI's blog, and CCLI-hosted PDFs. No column list, no schema, no
sample file, no developer or partner API documentation. The single CCLI-sanctioned upload file found
anywhere is the **CCS WorshipCast** spreadsheet template, which is a different licence and sits
behind portal authentication.

**Not established:** whether streaming to multiple platforms counts once or once per platform;
whether `Record` is still a live counter in the current US portal UI (marketing copy says yes, the
2017 guide marked it UK-only); and the WorshipCast template's actual headers.

Primary:
- [CCLI Reporting (US)](https://ccli.com/us/en/reporting) · [(UK)](https://ccli.com/uk/en/reporting) · [(Global)](https://ccli.com/global/en/reporting)
- [CCLI — Online Reporting, a step-by-step guide (PDF, Sept 2017)](https://dq5pwpg1q8ru0.cloudfront.net/2020/10/31/03/47/57/8cb63e88-3f5a-4b84-94cc-7786d47d7c7f/online-reporting-guide.pdf) — the category definitions above
- [CCLI Auto Reporting](https://ccli.com/us/en/auto-reporting) · [Church Copyright License](https://ccli.com/us/en/copyright-license) · [Streaming Licenses](https://ccli.com/us/en/streaming) · [The 5 Questions We Hear The Most](https://ccli.com/us/en/5-questions)
- CCLI support: [How often do I need to report?](https://support-ccli-us.helpscoutdocs.com/article/411-how-often-do-i-need-to-report) · [How do we report?](https://support-ccli-us.helpscoutdocs.com/article/2089-how-do-we-report) · [OHP acetates → Print](https://support-ccli-us.helpscoutdocs.com/article/2090-we-use-ohp-acetates-which-category-should-we-report-these-under)

Secondary — what other tools emit, as indirect evidence of what churches work from:
- [Planning Center — CCLI reporting](https://help.planningcenter.com/en/139389-ccli-reporting.html) and [song reports](https://help.planningcenter.com/en/139390-create-song-reports.html): tracks the same four types; its **CCLI Copy Activity** report is a **per-song aggregate over a date range**. Auto-reporting counts a song **once per week regardless of how many campuses or service types used it**, and **excludes songs with no CCLI number**.
- [WorshipTools Song Usage Report](https://www.worshiptools.com/en-us/docs/77-pl-usage-report): **per-event** — song, CCLI number, date scheduled — and says outright that it cannot track *how* the song was used.
- [OpenLP Song Usage Tracking](https://manual.openlp.org/song_usage.html): one row per display event, with Displayed/Printed.
- [SlideGen CCLI Reporting](https://www.psoft.com.au/slidegen/help/doc/ccli_reporting.html): states plainly that "CCLI does not support or allow a 'file upload' facility for copyright reporting", and produces a per-song aggregate worksheet to type from.
