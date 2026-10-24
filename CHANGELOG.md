# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [SemVer](https://semver.org/).

## [0.1.1] — Unreleased

Fixes from a second external review of `914d321`. **0.1.0 (already on PyPI) is affected by the three
defects below.** Upgrade once 0.1.1 is published.

### Fixed
- **Conditions on extraction were not applied.** "Extract totals from Acme" showed the Acme condition under
  "Understood as" but returned every document: the extraction plan had no filter step. Conditions are now
  enforced first for every workflow (extract, filter, count, aggregate, inconsistencies, summarize,
  compare, find, ask, export). The document scope narrows to the matches before the operation runs.
- **Boolean grouping was flattened.** "between $100 and $6,000 or above $10,000" became
  `>=100 OR <=6000 OR >10000`. Conditions are now a typed expression (`Cond | All[...] | Any[...]`).
  Ranges, years and months are grouped operands, and `or` between alternatives on the same field forms one
  group. The same expression is executed and rendered in "Understood as", so the two cannot drift apart.
- **Coordinated names were dropped.** "from Acme or Globex" silently lost Globex. Vendor lists
  ("Acme or Globex", "Acme, Globex and Initech") are one group, and a shared amount condition applies to the
  whole group. "not from Acme or Globex" excludes both.
- **Dropped fragments are reported.** A connector left after a condition ("… above $5,000 or Globex"), an
  unconsumed proper noun ("List Acme's invoices"), a month without a year, a time span such as
  "under 30 days", and an amount with an unknown unit ("over 5 bucks") make the result `partial` and are
  listed under Not applied.
- **Partial selections are never exported.** `write_output` refuses while any part of the request is not
  applied. Partial previews are labelled "PARTIAL RESULT, not the complete answer to your request".
- **Ambiguous `and`/`or` mixes are not guessed.** For example "from Acme or above $10,000 in 2026". Nothing
  runs, and the result state is the new `unsupported`.
- **Filtering failures cannot leak unfiltered rows.** If the filter step fails, or `max_steps` would cut it
  off, no records are returned and the state is `failed`.
- A filter that could not evaluate some documents (missing value, incompatible currency) is now `partial`,
  not `succeeded`.
- Added "N grand" (×1000) and month-year ranges ("in March 2026").

### Changed
- `validate_plan()` refuses any plan whose steps do not filter with exactly the stated expression, after
  extracting every field it reads, and before any step that uses records or the document scope.
- Requested output columns are kept separate from fields read only to evaluate conditions. Records,
  tables, CSV and JSON exports show only the requested columns.
- The optional 135M writer can no longer replace an answer. Its wording is appended under an explicit
  "not verified" label. `grounded()` is documented as a surface check (entity order and negation count),
  not semantic verification.
- Results carry `checks`, which keeps provenance, interpretation and evidence separate. The confidence fields
  are documented as heuristics, not calibrated probabilities.
- The `TaskState` enum gained `unsupported`.

### Fixed after evaluating on external documents (third review)
Found by running real OCR on Voxel51 invoices and CORD receipts (dev splits; see
[docs/BENCHMARKS.md](docs/BENCHMARKS.md#external-datasets)). Holdout field accuracy, 0.1.0 → this release:
synthetic invoices 41.7% → 99.7% (silent errors 30.8% → 0.3%), genuine receipts 3.2% → 68.5%.
- **Two-column layouts took the wrong value.** In a "Seller: / Client:" block, the line after a label in
  reading order belongs to the other column, so an IBAN or the seller's name was returned as the customer.
  When lines have boxes, a lone label now takes the value to its right on the same row, or else the value
  below it in the same column.
- **Summary rows** ("Total  $ 2 205,34  $ 220,53  $ 2 425,87") are resolved by their column titles (Net worth →
  subtotal, VAT → tax, Gross worth → total). A row without titles is flagged, not guessed.
- **Amounts**: `$ 2 425,87` (spaces after a currency symbol), `16,363` / `7.000` / `Rp. 28.636`
  (thousands-grouped amounts without cents, IDR), an amount OCR split into `177` `870`, and a label followed
  by a rate ("Tax 10%"). A money cell must account for every digit in it.
- Cash tendered and change are never the inferred total.
- **Amounts OCR may have misread are flagged, on agreeing evidence only.**
  - *When:* an amount is flagged only when independent signals agree. The signals are: the document's
    number format (no cents, or a zero-decimal currency) against an amount with cents; an
    order-of-magnitude break against other non-payment amounts; low OCR confidence; and a second OCR
    reading of the enlarged image region that disagrees.
  - *What a flag does:* the value and its OCR text are kept. The warning gives the reasons, the second
    reading and the source box. Confidence is halved, and the value is no longer marked verified.
  - *Result:* on a fresh, de-duplicated split, silent receipt errors went from 6 to 4 of 127, with 0 correct
    values flagged out of 887 across dev and fresh.
  - *What it replaces:* an interim rule (`e61a8d6`) that flagged any total under half its subtotal, which a
    discount or deposit trips.
- **"The total of invoices above $X" computes a sum.** It used to return the matching invoices, report
  success and compute no total. `AgentResult.calculation` now exposes the sum: op, result, unit, values used
  and values left out.
- Rupiah amounts in requests ("above Rp 50.000", "50,000 IDR").
- **Human review** (Review tab, `/api/reviews`, `inklight review list|export`):
  - Each prediction is frozen when the review opens, and the database refuses any change to it.
  - Reviewers accept, correct, enter or mark each field absent, then approve.
  - The history is append-only, and manual-entry mode hides the predictions for timing.
  - Export includes approved reviews only.
- **Pilot tooling** in `pilot/`: permission-checked intake with a vendor-grouped reserved split, a frozen
  baseline with `verify`, evaluation with confidence intervals and a logged reserved group, latency with and
  without the second reading, and a dry run. No genuine invoices have been collected yet.
- Model revisions can be pinned (`models.*_revision`), and `extraction.second_reading` can be switched off.
- **Strict parsing of typed amounts** (`inklight.entered`). "100 + 20", "1e3", "12abc 34" and irregular groups
  are refused with the reason; they are no longer turned into numbers by deleting characters. Accounting
  parentheses keep their sign. The reviewer's exact input is stored and exported next to the parsed value.
- **Typed dates follow the same rule** (`parse_entered_date`). A date can be typed the way the invoice prints
  it ("JAN04/00", "04-JAN-00", "Jan. 4, 2000"), which the review form used to refuse. Input with extra words
  ("01/31/82 approx") or two dates is now refused, where the first date used to be taken.
- **Names in every script are compared correctly** (`inklight.textnorm`): different Arabic names were equal
  in the inconsistency check, because every non-ASCII letter was deleted.
- Pilot evaluation:
  - The cohort and split are selected before any reprediction, and reserved access is logged first.
  - `--predictions frozen|cached|full` separates re-extraction from stored OCR from a full pipeline run in an
    isolated library, and records the provenance of each.
  - `check_rehearsal.py` and `REHEARSAL.md` cover the 5–10 invoice human rehearsal, which has not run yet.
- **Broken Arabic PDF text layers are OCR'd instead of indexed.** The UN's Arabic PDFs carry a text layer in
  Arabic letters, but the wrong ones ("األمم" for "الأمم", "امرساااااا" for "المرسلة"). Indra's own checks
  accept it, so the broken text was indexed, searched and quoted.
  - *How it is detected:* `inklight.ocr.textcheck`. A page whose Arabic words show a split lam-alef or an
    alef run in at least 1.5% of words, judged on 20 or more Arabic words, is read by OCR instead, and the
    page and document say so.
  - *Diagnostic, default `auto` mode:* key phrases on the two Arabic digital documents went 0/3 → 3/3 and
    1/3 → 3/3, and QA 0/6 → 2/6. 18 pages were OCR'd again; ingest time for the 26 documents went 56 → 60 s.
  - *False positives:* none on 124 pages of correct Arabic (65 OCR'd pages, 59 Wikipedia text-layer pages).
  - If OCR of such a page fails or reads nothing, the layer is kept and the page says so. One page never
    ends the document.
  - Mode `text` still uses the layer as it is.
- **Extraction reads month-name dates as invoices print them**: "JAN04/00", "04-JAN-00", "19Jun'22",
  "Sept 30, 82". Before, only 4-digit years with spaces were read. On 80 INV-CDIP invoices and 60 Voxel51
  invoices with date labels, correct dates went from 131 to 136 of 151 and missing from 13 to 7. No value
  changed on any of the 180 Voxel51 and CORD documents, so earlier benchmark results stand. A year followed
  by ".5" or ":30" is not read as a year ("QTY 2 MAY 15.00"). Measured with `bench/compare_dates.py`.
- An issue date more than a year in the future is flagged ("check the year"); due, expiry and end dates are
  not. Archive OCR had read "08-OCT-85" as "08-OCT-35".
- The document viewer can be closed on narrow screens; below 1100 px it used to cover the tabs.
- **A sum or average that leaves documents out is `partial`, not `succeeded`.** Documents without a value
  were left out with only a warning. The answer now also says how many were left out.
- Indonesian tax labels (`pajak`, `ppn`, `pb1`, `p.rest`), plus `net worth` and `gross worth`.
- **Possessive requests**: "Show acme's invoices", curly apostrophes, the name first ("Acme's invoices above
  $5,000"), and coordinated owners. A possessive owner stops at a preposition ("terms on Acme's" → Acme) unless
  the preposition joins capitalised words ("Bank of America's").
- **Questions that name their document** ("What are the payment terms on the Acme invoice?") are answered
  only from documents matching that name. Before, the answer could come from another vendor's invoice.
  Such a question is no longer turned into a list of records.
- "from March" (a month without a year, after from/for/since/before/after/until) is reported as not
  applied. Before, it returned every document as a success.
- Words a request contains but no condition used are reported (a closed vocabulary), not ignored.

### Changed (third review)
- **Explicit, idempotent cleanup.** `DocumentAgent`, `Library` and `Store` have `close()` and are context
  managers. Each closes only what it created. `close()` cancels running tasks and waits for them, and using
  a closed store raises `StoreClosed`. The CLI closes its agents when a command ends. The server closes the
  agents it owns at shutdown, but not one passed in. Tests open and close resources with no
  `ResourceWarning`, and no warnings are filtered globally.
- `Brain.usage()` reports, per component, whether its model loaded, its inference calls and any fallback reason.
- New `bench/prepare_external.py`, `bench/external.py` and `bench/summarize_external.py`: external
  evaluation with provenance (commit, wheel hash, `inklight.__file__`), ONNX call counts per model, and
  four-way scoring (correct / abstained / wrong flagged / wrong silent).
- Documentation states measured results instead of general reliability claims.

## [0.1.0] — 2026-10-23

First public release candidate.

### Added
- Document library: incremental ingest (unchanged files skipped, identical content reuses OCR), SQLite +
  FTS5 index, layout-aware chunks, classification, prompt-injection scan, re-index and delete.
- Indra OCR backend (PDF text layer first, OCR where needed; PNG/JPEG/TIFF/BMP/WebP), plain-text and
  Markdown reader, pluggable engine registry.
- Typed field extraction with page/box provenance, confidence, warnings and `subtotal + tax = total`
  checks; schema files in three formats.
- Bounded agent: rule planner, 11 allow-listed tools, step limits, time budgets, cancellation, retries, trace.
- Small local models on ONNX Runtime: 66M extractive reader, 33M embedder (hybrid search), optional
  135M writer with grounding checks. Optional OpenAI-compatible remote model with quote verification.
- CLI (`process, ask, extract, search, docs, show, remove, reindex, history, watch, serve, tools, doctor, models`).
- Local web workspace: upload, library, page preview with evidence highlighting, agent, extraction, search, history, settings.
- Folder watcher automation.
- Benchmarks (`bench/`), 128 tests, CI and release workflows, Dockerfile.

### Fixed before release (external review of 478fc3d)
- Vendor and customer constraints ("invoices from Acme above $5,000") were silently dropped. They are now
  conditions (`vendor contains "Acme"`), including negation ("not from", "except").
- `or` between conditions was applied as AND. It now means any. A mix of `and`/`or` is reported instead of guessed.
- Added `between X and Y` and year conditions ("in 2026").
- Amounts in different currencies were summed into one number. Money values now carry a `unit`, sums are
  reported per currency, and filters never compare € amounts with a $ threshold.
- Requests with words no tool can apply ("paid late", "last month", "top 3", a stray amount) used to return
  `succeeded`. They now return `partial` and list the words under **Not applied**.
- Counting with conditions ("how many invoices above $8,000") ignored the conditions.
- Ambiguous numeric dates (`03/04/2026`) were read silently. They are now flagged, and `[extraction] day_first`
  sets the order.
- The currency is read from a label ("TOTAL DUE (USD)") when the amount has no symbol. Added EGP / E£.
- `grounded()` accepted "Acme owes Bob" against "Bob owes Acme". It now also requires the evidence's order of
  names and numbers, and is documented as a necessary check, not proof of correctness.
- Reader answers whose surroundings share no word with the question are penalised.

### Changed
- Results report confidence twice: `interpretation_confidence` (was the request understood) and
  `evidence_confidence` (do the documents support it). `confidence` is the lower of the two. Results also
  carry `interpretation` and `not_understood`, shown in the CLI and the web workspace.
- Docs: "verified" now explicitly means provenance (the text exists where cited), not semantic correctness.
- Benchmarks: three invoice layouts instead of one, plus a request-handling score.

### Configuration
- Config schema version `1`. Configs declaring a newer version are rejected with a clear message.
  Future migrations will run oldest-first in `config._migrate`.
- Library database schema version `1` (`meta.schema_version`).
