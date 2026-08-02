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
| **Church Copyright License** | Reproducing lyrics to support congregational singing — projecting, typing out, copy & paste, printing songsheets/bulletins, and making custom arrangements (without altering melody, lyrics, or the song's fundamental character) | Held \* |
| **CCLI Streaming License** | Extends the above to online worship: live-streaming or uploading services containing songs performed live by your own musicians | Held \* |
| **CCLI Streaming Plus License** | Additionally covers master recordings — artist tracks, backing tracks, multitracks — from an authorised source during online services | Only needed if pre-recorded tracks are used |

\* Reported by Matt on 2026-08-01 as his understanding, **not verified against the licence
certificate**. Recorded as stated rather than promoted to established fact — see
[Open questions](#open-questions).

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

Four activity categories:

| Category | CCLI's definition | This app's term |
|---|---|---|
| **Digital copies** | How many digital copies of the song were shown — this is projection | `projection` |
| **Print copies** | Printed reproductions — bulletins, songsheets | `print` |
| **Video or audio streaming** | The service or event is available to view on the internet | `recording` ⚠️ |
| **Translation** | A translation of a copyrighted song was made | `translation` |

Two rules that directly constrain this application:

1. **Streaming is one credit per performance, even when streamed to multiple platforms.**
   When YouTube is added alongside Facebook, that remains **one** streaming credit per song per
   service, not two. See [§5](#5-implications-for-this-application).
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
**video or audio streaming**. The rename matters beyond vocabulary: CCLI's rule is *one credit per
performance regardless of how many platforms carry it*. The current importer hardcodes
`recording=1` per song per service, which is correct **today** because there is exactly one
platform. The moment YouTube is added alongside Facebook, the natural-seeming change — emit an event
per platform — silently doubles every streaming credit in a legal compliance document.

This deserves a regression test asserting that N streaming platforms still yield one streaming
credit per song per service.

### 5.2 The export's columns are unverified — and issue #86 would freeze that

Three different column sets are in play:

| Source | Columns |
|---|---|
| **Emitted today** (`cli.py`, `web/app.py`) | `Date`, `Service`, `Title`, `CCLI#`, `Reproduction Type`, `Count` |
| **Asserted by issue #86** | `Song Title`, `Words By`, `Music By`, `Arranger`, `Publisher`, `Reproduction Type`, `Times Used` |
| **CCLI write-in sheet** | `Song Title and/or First Line`, `Author(s)`, `Copyright Information`, `CCLI Song Number (if known)`, `Uses` |

None of the three agree. Issue #86's headers match neither the implementation nor anything CCLI
publishes, so a contract test hard-coding them would fail immediately and, once "fixed", would lock
in a specification that appears to be invented. A test that enforces an unverified contract is worse
than no test: it reports confidence about compliance while proving only self-consistency.

**No public CCLI CSV column specification was found.** CCLI's supported paths are the online portal
and auto-reporting integrations — not a published CSV schema for third-party tools. The export is
best understood as *an aid to a human filling in the portal*, and should be tested against that
purpose (stable, complete, unambiguous, correctly aggregated) rather than against invented headers.
See the comment on #86.

### 5.3 What `spec.md` got right

Recorded so it does not get re-litigated: the six-month assigned window, "Nothing to Report" weeks,
configurable public-domain exclusion, and the four-category shape are all consistent with CCLI's
published rules. The defaults `print=0` and `translation=0` match Highland's stated practice.

---

## Open questions

Neither can be answered from the code or from CCLI's public pages:

1. ~~**Does Highland hold a CCLI Streaming License?**~~ **Answered 2026-08-01:** Matt's
   understanding is that Highland holds both the Church Copyright License and the Streaming License.
   Recorded as reported, not verified — nobody has read the certificate as part of this work. Worth
   confirming once against the CCLI account, and worth re-checking at renewal, since the two licences
   renew independently and only the streaming one gates the livestream.
2. **Will Highland submit through the online portal or the write-in path?** This decides whether the
   CCLI Song Number mapping (currently out of scope for v1) is optional or required. Still open, and
   it is the question that most affects what this application needs to build next.

---

## Sources and confidence

Verified directly from CCLI's own US pages: the licence split, that streaming needs a separate
licence, the 2.5-year / six-month reporting cycle, "nothing to report" guidance, and the song-number
guidance for portal submission.

Relied on with lower confidence: the four category names and their definitions, and the public-domain
exclusion, which come from CCLI's UK/IE reporting material and a third-party summary of it. US portal
wording may differ in detail, though the underlying obligations are the same.

Checked and set aside: CCLI's downloadable write-in copy report turned out to be the **UK/IE Event
licence** variant, so its column layout is indicative of CCLI's data model but is not the US church
report and should not be treated as the target format.

- [CCLI Reporting (US)](https://ccli.com/us/en/reporting)
- [CCLI Streaming and Streaming Plus Licenses (US)](https://ccli.com/us/en/streaming)
- [CCLI — The 5 Questions We Hear The Most (US)](https://ccli.com/us/en/5-questions)
- [CCLI FAQ](https://ccli.com/de/en/what-we-provide/faq/?lang=en)
- [CCLI Church Copyright Licence (Event) Copy Report — PDF](https://ccli.com/pdfs/CCL_Event_Write_In_Sheet_e121d3e1e2.pdf)
- [CCLI report and song credits — third-party guide](https://brightmorningstar.org/ccli-report-and-song-credits/)
- [GCFA — Church Copyright Licensing Options](https://www.gcfa.org/resource/church-copyright-licensing-options)
