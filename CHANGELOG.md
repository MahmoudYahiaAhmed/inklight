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

### Layout-aware answers (`bcd4752`, `915be7b`)
Measured in [docs/EVALUATION.md](docs/EVALUATION.md#labels-and-values-on-the-page-915be7b).
- **Labels paired with values across OCR columns.** Visual rows group lines by bounding box, ordered by the
  script's direction (Arabic right to left).
  - *Extraction.* A money or date field whose label has no value in reading direction tries the other side
    of its row. Several values on one row are flagged.
  - *Answers.* Date, amount and count answers can be supported by a row as well as a sentence. Answers keep
    their page and box.
- **Questions that name a printed label** ("What is the product?", "ما هي الكثافة؟") are answered with the
  value beside or below that label, with page and box, and without a model call.
  - Titles, document-noun headings and prose are not labels.
  - Several candidate values, or several matching labels, are flagged.
  - A label left blank on a form is declined.
- **Every line of a reader answer is checked.** A multi-line span must sit in one sentence or one visual row.
  A continuation that adds its own date, amount or "Label:" is cut, and the sentence that holds the rest is
  cited.
- **Evaluation**:
  - Each answer is also scored for the same entity, allowing Arabic particles such as "لتركيا" for "تركيا";
    exact transcription is still reported.
  - Pairing accuracy, page and box are reported per field.
  - New splits fresh4 (12 documents) and fresh5 (10), each with expectations written before first access.
    - fresh4: no change.
    - fresh5: answerable questions correct 27 → 32 of 44, silent wrong 9 → 8, one incorrect decline.
- **README lead image**: real screenshots of the latest build, covering an English letter, an Arabic letter,
  an English form and a mixed receipt (labelled as a development example).

### Fixed: a label's qualifier and section
Three answers reproduced on `2a628c1`, each returned without a warning:
- the shipping address taken from "Billing Address:";
- the delivery date taken from "Invoice Date:";
- Alice's salary taken from the "Salary:" printed under Bob.

The fixes:
- **A label naming a different field is not used.** This holds when the label has a word the question lacks
  ("billing") and the question has one the label lacks ("shipping"). Such a value is declined, as is a bare
  label returned as an answer ("Invoice Date:"). A qualifying document word is kept, so "the invoice date" is
  not answered from "Due Date:".
- **Copies of a repeated label are told apart by the section above each.** A section runs from the label that
  opens it ("Employee: Bob Turner") or from the person's heading.
  - A question naming no one, or someone under none of the copies, gets each copy listed with its section. None
    is picked.
  - A single label outside the named section is flagged on a page divided into sections.
  - Any answer to a question naming something the document never prints is flagged.
- **The other answering paths are checked the same way.** This covers the field shortcut, the reader, the
  rules, and plain-text documents (laid out as one column for the check). Only the first cited source is checked.
- **What counts as a name.** A run of capitalised words is a name when the document prints any of it outside its
  labels ("Bob Turner", "Security Council"). Otherwise it is the field asked for ("What's the Shipping
  address?"). "The company's address" names no one; "globex’s invoice" names the vendor the document prints.
- **Development data only.** On the dev, reserved and fresh–fresh4 splits (473 questions, models on), no answer
  was lost.
  - Five changed for the better: two Aswan infobox answers and a receipt number became correct, a flagged total
    became unflagged, and an unanswerable bank-account question was declined.
  - In rules mode, two more silent errors became declines.
- **Not handled:**
  - "What is the date?" on a page with both an invoice and a delivery date gives the invoice date.
  - Arabic names are not detected, so Arabic copies of a label are listed, not chosen between.
  - In plain text, a value cited beside another field's label is flagged, not corrected.

### Added: document structure from Docling on Indra's OCR (optional)
- **`[structure] engine = "docling"`** (extra: `pip install "inklight[structure]"`) runs Docling's existing components
  on each document Indra has read: the Heron layout model, reading order and TableFormer, through Docling's
  supported OCR-engine extension point. The engine hands Docling Indra's stored lines; Docling does no OCR of its own
  (`OcrMode.FULL_PAGE`, and PDFs passed as page images). Details: [docs/STRUCTURE.md](docs/STRUCTURE.md).
  - Each document records cells delivered, foreign tokens (0) and orphan lines; lines no Docling item holds are
    kept as blocks.
  - The DoclingDocument is stored per document (new `structures` table, `blocks.ref`). It is exported by
    `inklight structure DOC --format md|json|html|meta` and `GET /api/documents/{id}/structure`.
  - Original OCR lines are unchanged. Tables are searched as rows of "header: value"; text inside pictures is
    kept and searchable.
- **Answers from table cells:**
  - the value under the heading that names the field, never the heading;
  - the row named by the question's other words; several rows with nothing to choose are listed;
  - "who" lookups, and field/value tables;
  - blank cells and unreadable dates are declined; cells OCR read with low confidence are flagged.
- **Measured on synthetic registration cards** (Arabic, English, mixed; fixed Indra OCR; rules mode), correct
  answers, `030dd41` → this build with Docling:
  - Arabic 0 → 10 of 18 (the 6 wrong are flagged Indra misreads);
  - English 2 → 18 of 18;
  - mixed 6 → 10 of 10;
  - silent wrong 17 → 0.

  Cost: 1.1 GB peak memory, 2–3 s per page, and a one-time model load of 5.5 s (CPU, torch 2.14.1).

### Fixed: headings and citations (with or without structure)
- An answer that only repeats the question's words, or equals a table heading, is declined. "اسم الشركة" was
  returned for "ما اسم الشركة؟", and "Company name" for "What is the company name?".
- **Citations are verified line by line.** A label-and-value citation of two separate lines was being dropped.
- **An answer whose every citation fails verification is marked "Unverified".** It is flagged and its confidence
  capped at 0.2; it is no longer presented as supported.
- **Choosing labels and values:**
  - Generic question words break ties between labels ("company type" vs "company name").
  - The value under a label is the line most squarely under it among value-like lines, not the neighbouring
    column's.
  - A label's value OCR read with confidence below 0.85 is flagged.
- **Search folds the Persian yeh and keheh (ی ک) into Arabic ي and ك.** OCR writes "مدیر" for "مدير". Schema
  version 4; existing libraries are re-indexed when opened, and the shown text is unchanged. After that, an
  older Inklight version can still read the library, but cannot add documents to it (blocks gained a `ref`
  column).
- **Classification:** commercial-register certificates and tax cards are certificates, not contracts, even when
  they cite the company's articles ("عقد التأسيس").
- On the 473 development questions, `030dd41` → this build (structure off): no correct answer lost, and silent
  errors became declined or flagged (3 silent errors with models on, 5 in rules mode).

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
- **The English-only models no longer touch Arabic.** Measured on identical documents and passages:
  - The reader turned correct Arabic passages into wrong spans (Arabic answers 17/36 → 3/36).
  - The embedder ranked the right Arabic document lower (top 3: 29/36 → 20/36).
  - Both still help English (answers 16/53 → 20/53, top 3: 37/53 → 42/53).

  Arabic queries now use keyword search, and the reader is not asked about Arabic. Each skip is stated in the
  result's `checks`. OCR is unaffected by the models: stored text was identical with them on or off. See
  [docs/EVALUATION.md](docs/EVALUATION.md).
- **Arabic requests are understood:** summarise, compare, count, extract and find. On the reserved split, Arabic
  summaries went from 0/9 recognised to 9/9, covering 17/27 key facts, every sentence quoted verbatim.
- **Arabic questions** are answered from the best-matching sentence: words, light stems, sentences and question
  types in Arabic. These answers are always flagged for review. On reserved: 11/23 right, 0 silently wrong (P0:
  1/23).
- **Answers must be connected to what was asked, not merely near it.** Sender, recipient and signer come from
  the letter's title, From/To lines or the signature line (English and Arabic, OCR damage tolerated). A date,
  amount or count must come from a sentence holding that value and the question's own words; a letter's heading
  date does not answer a question about an event; "Total (incl Tax)" is not the tax; otherwise the answer says no
  supporting evidence was found. On 11 new genuine documents, run once: correct 26 -> 30 of 44 answerable
  questions, silent wrong 7 -> 6, one answerable question declined; unanswerable questions about a mentioned
  subject answered silently 4 -> 1 of 8. One receipt answer regressed ("VAT-Inclusive" is not read as a
  qualifier).
- **Questions about something the documents never mention** ("What is the IBAN?" over a letter) are answered
  "I couldn't find supporting evidence for “IBAN” in the processed text of this document." instead of with the
  nearest sentence (it does not claim the fact is absent: OCR can miss words). On 15 new genuine
  documents, run once on the frozen build: 18 of 19 such questions declined (before: 0). Questions whose subject is
  mentioned but whose value is not are not covered: 6 of 11 are still answered silently. No answerable question
  was declined (0 of 42).
- **Evaluation runs keep complete answers and cited passages**, so they can be rescored exactly. The first-access
  source of the reserved and fresh runs is reconstructed; its re-run reproduces the stored results
  (`bench/results/usecases/provenance/`), which shows the same behaviour but is not a byte-exact recovery.
- **Requests Inklight cannot carry out** ("translate this", "email it", "sign it") are `unsupported` with the reason,
  instead of `succeeded`.
- **Questions about a document's content** stay questions: "Which city was hit…?" used to become an invoice filter.
  Letters, reports and forms no longer get invoice fields. "Compare the letter dates" compares dates. "Export the
  number, date and total of the invoices" is an export, not a sum.
- **Extraction:**
  - right-to-left label/value layouts
  - Arabic labels in the invoice preset
  - Arabic month names (Gregorian and Levantine)
  - Egyptian, Saudi and UAE currency forms
  - "Total Tendered" is not the total
  - parentheses restating a written amount are not negative
  - "Letter dated" dates a document only when it is a letter
- **Classification:** English and Arabic cues for letters, reports, receipts, invoices, contracts and forms, plus a
  certificate type (12 → 28 of 35 dev documents).
- **Search:** the index also strips the Arabic article ("بالنزاع" finds "النزاع"); library schema 3, re-indexed on
  open. A question about one or two documents with no keyword match reads their passages instead of answering
  "nothing found".
- **Review:** fields follow the document type unless given, the Review tab has a field box, and Arabic and mixed
  text lays out right to left in the workspace.
- **Evaluation:** `bench/usecases/` holds 75 documents in dev, reserved and fresh splits, expected results written
  before running, logged reserved access, a full pipeline per run, the model ablations and synthetic Arabic
  documents (labelled). Results are in `bench/results/usecases/`.
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
- **Arabic search no longer depends on optional marks or letter variants.** The full-text index and every
  query use `textnorm.search_form`:
  - harakat and tatweel removed
  - alef forms → ا, ى → ي, ة → ه
  - Unicode digits → ASCII

  "المستحق" now finds "المُستحق", "القاهره" finds "القاهرة", and "2023" finds "٢٠٢٣": 4/10 → 10/10 test
  queries. Queries are no longer split at a vowel mark. Excerpts still show the original text. Library
  schema version 2: a version 1 library is re-indexed when it is opened.
- **Extraction reads month-name dates as invoices print them**: "JAN04/00", "04-JAN-00", "19Jun'22",
  "Sept 30, 82". Before, only 4-digit years with spaces were read. On 80 INV-CDIP invoices and 60 Voxel51
  invoices with date labels, correct dates went from 131 to 136 of 151 and missing from 13 to 7. No value
  changed on any of the 180 Voxel51 and CORD documents, so earlier benchmark results stand. A year followed
  by ".5" or ":30" is not read as a year ("QTY 2 MAY 15.00"). Measured with `bench/compare_dates.py`.
- An issue date more than a year in the future is flagged ("check the year"); due, expiry and end dates are
  not. OCR had read "08-OCT-85" on a 1985 invoice scan as "08-OCT-35".
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
