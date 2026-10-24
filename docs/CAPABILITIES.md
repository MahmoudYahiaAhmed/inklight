# Capability matrix: English, Arabic and mixed documents

Inklight is a general document tool for Arabic and English. This page says what works today, measured on
original files. Invoices are one use case among several.

**What this is.** A small, automated diagnostic of baseline 4 (`f4ebb5a`), run on 2026-10-25. It covers 25
original files, 1–2 per cell, with real OCR (Indra) and the local models (reader, embedder). ONNX Runtime
calls were counted independently: about 600 reader and embedder calls, and 1,400 (`auto`) to 2,200 (`ocr`) OCR model calls, per run. No person
reviewed anything. Questions, accepted answers and search queries come from dataset labels (CUAD, FUNSD,
CORU, INV-CDIP, Voxel51) or were written by an AI from reading each original file (UN documents, W-9).

**What this is not.** A benchmark. With 1–6 documents per cell, a number says "this worked or failed here",
not a rate. Scores are kept separate by language, document type, modality and task, and are never averaged
across them.

Reproduce:
```bash
python -I bench/capability_diag.py --corpus bench/capability_corpus.json --docs <files> --models <models> --out <dir>
python -I bench/summarize_capability.py <dir>/capability-diag.json
```

## Status definitions

| Status | Meaning |
|---|---|
| **Works (tested)** | Ran on original files in this diagnostic or an earlier measured benchmark, and gave correct results |
| **Partial (tested)** | Ran, correct on some documents, with failures shown below |
| **Fails (tested)** | Ran and gave wrong or unusable results |
| **Implemented, unmeasured** | Code exists, but no original file in this diagnostic exercised it, or there is no reference to score it against |
| **Unsupported** | The code does not do it |

## Matrix by language and modality

OCR mode `ocr` (OCR every page) unless the cell says `auto` (the default: the PDF text layer first, OCR where a
page has none). Counts are k/n.

| Capability | English digital | English scanned or photographed | Arabic digital | Arabic scanned | Mixed Arabic/English (photos) |
|---|---|---|---|---|---|
| **Text (OCR)** | **Works.** Word recall 0.99–1.00 against the PDF's own text layer (5 docs) | **Partial.** Printed forms: word recall 0.96 (FUNSD, 2). Indra ignores the old invisible OCR layers of archive scans and OCRs them itself; its own misreads remain ("O1 /31 /92" for 01/31/82, "191" for 019114) | **Fails in `auto`** (the default): the UN text layers decode to broken Arabic, so key strings are found 0/3 and 1/3. **Works in `ocr`**: key strings 3/3 and 3/3 | **Partial.** Typewritten 1974–1990 scans: key strings 1/3, 2/3, 1/3 | **Partial.** Key strings 11/12, but some Arabic words come out as Latin letters ("53gili sia Tedata") |
| **Search** (document ranked first, 25-doc library) | **Works** on these easy queries: 5/5 | **Works**: 11/11 (9 scans and photos, 2 synthetic) | **Partial**: 3/4 at rank 1, 4/4 in the top 3. Text with harakat is not found by the same word without them (probe: 0 hits) | **Partial**: 2/5 at rank 1, 4/5 in the top 3 | **Partial**: 3/5 at rank 1, 5/5 in the top 3 |
| **Question answering with sources** (answer line correct; source check separate) | **Partial**: 7/15 (contracts 3/6, letter 2/3, report 1/3, form 1/3) | **Partial**: synthetic invoices 6/6; scans and photos 5/27 (invoice scans 2/6, receipts 2/6, forms 1/6, letter, report and agreement scans 0/9) | **Fails**: 2/6 | **Fails**: 0/9 | **Partial**: 4/12 |
| **Summarisation** (extractive) | **Implemented, quality unmeasured.** Produced for 5/5, in English, quoting the document; no reference summaries | Same: produced 11/11 | **Fails**: "لخص هذه الوثيقة" is not recognised as a summary request (0/2); the answer is a fragment such as "23-01144" | **Fails**: 0/3 | Produced 4/4 with an English request, quoting Arabic lines |
| **Custom field extraction** (schema with labels) | **Partial**: 4/8. Labelled dates work; contract agreement date 1/2; governing law and court as text fields 0/2 | **Partial**: synthetic invoices 6/6; scans and photos 11/17 | **Partial**: 1/2, only where an English-format date exists. "رسالة مؤرخة 18 كانون الثاني/يناير 2023" is not read (Arabic month names unsupported) | **Partial**: 1/3, again only the English header date | **Partial**: 3/7. Totals wrong on 3 of 4 receipts (251, 51, 13.12) |
| **Document type** (classification) | **Partial**: 3/5 (letter and W-9 wrong) | **Partial**: 7/11. Letters and forms are "unknown" or "report"; a resolution scan was classed as a contract | **Fails**: 0/2 (unknown) | **Fails**: 0/3 | **Fails**: 1/4 |
| **Review (API)** | **Works**: a review opened with each document's custom fields, 25/25 | same | same; Arabic text typed into a review is stored unchanged | same | same |
| **Review (web UI)** | **Invoice-only**: the Review tab always opens the 8 invoice fields (`app.js:315` sends no `fields`) | same | Same, and no right-to-left layout (`index.html` has `lang="en"` and no `dir`) | same | same |
| **Export** | **Works**: the review CSV is a generic long format (one row per field); 43 rows, every custom field present | same | Arabic values exported unchanged in CSV and JSON (direct check) | same | same |

### By document type (both languages, OCR mode)

| Type | Docs (en / ar / mixed) | QA | Custom fields | Type recognised | Main failure |
|---|---|---|---|---|---|
| Invoices and receipts | 6 / 0 / 4 | 14/30 | 15/23 | 7/10 | Wrong number taken (card or phone number for the receipt number; tendered cash for the total) |
| Contracts and agreements | 3 / 1 / 0 | 3/12 | 3/6 | 3/4 | Questions about clauses are answered with a nearby phrase; the text fields "governing law" and "court" are not found by label |
| Letters | 2 / 2 / 0 | 3/12 | 2/4 | 0/4 | Requests are misrouted. "Which city…" became a vendor filter and "Which mission…" became an invoice extraction (see failures) |
| Reports | 2 / 2 / 0 | 2/12 | 2/4 | 1/4 | The answer comes from the wrong passage (resolution 3232 instead of 3314 on the same page) |
| Forms and certificates | 3 / 0 / 0 | 2/9 | 4/6 | 0/3 | Form labels next to values are not used as answers; "how many pages" became a count |

**Gaps (no data was available, so nothing is claimed):**
- an Arabic digital contract
- any Arabic or bilingual form or certificate
- an Arabic invoice other than the bilingual receipts
- a genuine English invoice as a digital PDF
- handwriting

The Humans in the Loop Arabic documents set is CC0 but needs a request form; it would fill most of these gaps.

## Representative failures

1. **Arabic digital PDFs are read as broken text by default.** The UN Arabic letter S/2023/50 has a text layer,
   so `auto` uses it. The layer decodes as "األمــم المتحـدة … رساا مؤ مةر ؤ 18 ك نون امث ني": lam-alef split and
   letters dropped. Key strings were found 0/3. Forcing OCR on the same file finds 3/3 and recovers QA from
   0/3 to 1/3. This is the cheapest large fix.
2. **Arabic requests are never understood.** The planner sends "لخص هذه الوثيقة", "استخرج التاريخ والمبلغ" and
   "كم عدد العقود؟" all to `ask` (probe). The rule-based word splitter keeps only `[a-z0-9]` (`answer.py:136`):
   `words("ما هو الإجمالي") == []`. Arabic questions therefore get the "closest passage" fallback, and the answers
   were "23-01144", "8" and "1983".
3. **Arabic search depends on exact spelling.** A document with "المُستحق" is not found by "المستحق" (0 hits).
   The query with the mark is split into "الم" OR "ستحق" (`store.py:70`). FTS5 uses `porter unicode61` with
   no diacritic removal. The embedder is English-only (`bge-small-en-v1.5`).
4. **English questions are routed to invoice tools.** On a 1983 letter, "Which city was hit by artillery fire
   on 8 September?" was planned as a filter `vendor contains "artillery fir…"`. "Which mission sent the
   letter?" became an extraction of invoice columns. On the W-9, "How many pages including the cover sheet?"
   became a count. All three returned PARTIAL instead of an answer.
5. **The reader picks the wrong entity.**
   - "Who are the parties?" → "their agents, employees, experts, and attorneys"
   - "When was the agreement signed?" → "one month"
   - "Who is the fax addressed to?" → "Attorney General"
6. **OCR misreads on old scans.** The invoice number came out as "191" for 019114 (unflagged) and the date as
   "O1 /31 /92". *Correction (2026-10-25):* an earlier version of this page blamed the archives' own OCR
   layers. Indra does not use those: it marks them "invisible text (OCR layer)" and OCRs the page. These are
   Indra's misreads. The archive layer's "44149" never reached Inklight, whose text has "44/49".
7. **Arabic month names are not dates.** "18 كانون الثاني/يناير 2023" and "22 أيلول/سبتمبر 1983" are not
   parsed (`values.py`: English month names only). Date fields on Arabic documents succeed only when an English
   header date is present.
8. **Totals on bilingual receipts.** The receipts gave 251 (should be 220), 51 (cash tendered, should be 46) and
   13.12 (the date read as money, should be 137.6).
9. **Arabic OCR on photos.** Arabic words on a payment receipt came out as Latin text ("O Sila / 53gili sia
   Tedata"), so every question on that receipt failed, including the one asked in Arabic.
10. **Classification is English keyword lists.** All 9 Arabic and mixed documents but one are "unknown".
    English letters and forms are "unknown" or "report"; there is no certificate type.

## Invoice-specific assumptions in shared code

Found by reading the code, and confirmed by execution where marked ✓.

| Area | Where | Assumption | Hard-wired? |
|---|---|---|---|
| Planner | `agent/planner.py:264-269` | Default fields for any type other than contract and receipt (report, letter, form, unknown) are `invoice_number, vendor, date, total` ✓ (failure 4) | yes |
| Planner | `planner.py:30, 126-132, 180-182` | Aggregation is money-only; set totals need "invoices/receipts/bills/orders" | yes |
| Planner | `planner.py:163-164`, `conditions.py:203-216, 553-566` | Nouns and vocabularies are English and billing-centred; no Arabic ✓ (failure 2) | yes |
| Conditions | `conditions.py:51-52, 83-92, 386, 408, 420, 427` | A bare threshold means `total`; "from X" means `vendor`; date conditions only on date, due_date and expiry_date ✓ (failure 4: "vendor contains") | yes |
| Tools | `agent/tools.py:20` | Field names `^[a-z0-9_]{1,40}$`, so no Arabic field names | yes |
| Extraction | `extract/fields.py:42-193` | CATALOG of 15 mostly invoice fields with English (and Indonesian) labels; aliases "amount" → total, "number" → invoice_number, "name" → customer | defaults; a schema can add labels |
| Extraction | `fields.py:345-349, 557-571, 648-674` | Every CATALOG label is always claimed; `total` implies subtotal and tax and the last candidate wins; subtotal + tax = total check | yes |
| Extraction | `extract/values.py:9, 20-32`; `amounts.py:34-46` | English month names; fixed currency list; Arabic separators ٫ ٬ and "ر.س" not parsed outside review input ✓ (failure 7) | yes |
| Classification | `extract/classify.py:7-74` | 7 types with English keywords; no certificate ✓ (failure 10) | yes |
| CLI | `cli.py:229-230` | `inklight extract` without fields extracts invoice fields | `--fields` / `--schema` override |
| Review API | `server/review_api.py:16, 22` | `INVOICE_FIELDS` is the default | the API accepts `fields` ✓ |
| Review UI | `static/app.js:315`; `index.html:2, 67, 97` | Never sends `fields`, so always invoice fields ✓; `lang="en"`, no `dir`; invoice placeholders and examples | yes |
| Review input | `entered.py:40, 86` | Error text says "as the invoice prints it"; money currency list | wording |
| Export | `review.py:361-381`; `analysis.py:409-459` | Generic: one row per field, or columns from the requested fields ✓ | no |

## Proposal: one general workflow, with invoice schemas as presets

Make the shared path "document → text → fields from a profile → review → export" independent of invoices.

1. **Profiles (presets).** A profile is data, not code: a field list with types, labels in English and Arabic,
   and optional checks. Ship `general` (title, date, reference, parties/sender, recipient, subject) as the
   default, plus `invoice`, `receipt`, `contract`, `letter`, `report` and `form`. Move today's CATALOG, aliases
   and the subtotal + tax = total check into the `invoice` and `receipt` profiles. Custom schemas stay as they
   are.
2. **Profile selection.** In order: an explicit choice, then the classified type, then `general`. The planner
   takes its default fields, money fields and nouns from the active profile instead of the hard-coded lists
   (`planner.py:264-269`, `conditions.py:51-52`). An answer-type question ("which city", "who signed") stays
   `ask` and never becomes a filter on `vendor`.
3. **Review UI.** A profile or schema picker; the field list is sent in `POST /api/reviews`; values shown with
   `dir="auto"`; validation from the field type. The API needs no change.
4. **Language layer.** One Arabic and English normalisation, used at indexing, querying, matching and scoring:
   - harakat, tatweel and alef variants
   - Unicode digits and Arabic separators
   - Arabic month names (Syriac and Gregorian), with Hijri dates flagged rather than converted silently
   - an Arabic request lexicon for the planner
5. **Models.** Keep the English models as the default for English. Add measured multilingual options for
   Arabic (an embedder and an extractive reader with ONNX exports), selected by the document's script. Do not
   claim Arabic QA until measured.

This keeps every existing invoice behaviour reachable as the `invoice` profile, so the earlier invoice results
remain a valid comparison reference.

## Prioritised plan

Each step ends with a re-run of this diagnostic plus the existing benchmarks, compared with this baseline.
None needs a human study.

| # | Change | Why first | Size | Measured by |
|---|---|---|---|---|
| P0 ✓ | **Check PDF text layers before trusting them.** Per page, detect broken text (Arabic presentation forms, split lam-alef, isolated letters, a high share of 1–2 letter tokens, or disagreement with a sampled OCR line), and OCR that page | Fixes failure 1, the default path for every Arabic digital PDF (Indra already OCRs invisible OCR layers) | S | Arabic digital key strings (0/3 → expected 3/3); English word recall unchanged |
| P0 ✓ | **Arabic text normalisation at index and query** (FTS5 `remove_diacritics 2`, alef and ya variants, tatweel), and fix the query splitting at harakat | Fixes failure 3 | S | Diacritic probe; Arabic search rows |
| P1 | **Arabic request handling in the planner**: lexicon for summarise, extract, count, find and compare; Unicode word splitting in rule QA (`answer.py:136`) | Fixes failure 2; Arabic summaries 0/5 today | S–M | Arabic summary intent and QA rows |
| P1 | **Stop routing questions into invoice tools** ("which/who/what" questions stay `ask`; default fields from the profile, not invoice fields) | Fixes failure 4 across all English non-invoice types | M | English letters, reports and forms QA rows |
| P1 | **Arabic dates and amounts in extraction**: Arabic month names, ٫ ٬ ر.س ج.م, reusing the strict review parsers where possible | Fixes failures 7 and 8 in part | S–M | Arabic date fields; mixed receipt totals |
| P2 | **Profiles and the review UI field picker** (the proposal above) | Makes the shared workflow general; removes invoice fields from letters and forms | M–L | Fields per type; review UI on a letter |
| P2 | **Classification**: Arabic keywords, a certificate type, letter and form cues | Failure 10; profile selection depends on it | S | Type-recognised column |
| P3 | **Multilingual embedder and reader options**, measured before any default change | Arabic QA 0/9 on scans needs more than rules | M | Arabic QA and search rows, with ONNX call counts |
| P3 | **Arabic OCR on photos and typewritten scans** (Indra script routing; report upstream with examples) | Failures 9 and the 1/3 key strings on typewritten Arabic | depends on Indra | Arabic scan key strings |
| — | **Data**: request the CC0 Humans in the Loop Arabic set; add Arabic contracts, forms and certificates | Fills the gaps listed above | — | — |

## P0 results (after baseline 4)

Both P0 items are done. The diagnostic was re-run on the same corpus plus one control, giving 26 documents.
The control is the Arabic Wikipedia article "مصر" (CC BY-SA), whose text layer is sound. Each build ran in
both modes with the same models, so the two columns compare like with like. Results:
`bench/results/capability-diag26-baseline4.json` and `capability-diag26-p0.json`.

**1. Broken Arabic text layers are OCR'd.** Indra rejects a broken font map or a layer in visual order, but
accepts the UN layers, whose codes are Arabic letters, just the wrong ones. `inklight.ocr.textcheck` checks
each text-layer page for two signatures:
- a split lam-alef ("األمم" for "الأمم")
- an alef run ("امرساااااا")

A page is read by OCR instead when at least 1.5% of its Arabic words show one, judged on 20 or more Arabic
words. The page and the document say so.

| Default mode `auto` | Baseline 4 | P0 |
|---|---|---|
| Arabic digital letter: key phrases found | 0/3 | 3/3 |
| Arabic digital report: key phrases found | 1/3 | 3/3 |
| QA on those two documents | 0/6 | 2/6 |
| Pages OCR'd again | – | 18 (3 + 15) |
| Ingest time for all 26 documents | 55.7 s | 60.2 s |
| Indra ONNX calls | 1,833 | 2,108 |
| Any English or mixed document changed | – | no (one more FUNSD date, from the date change) |

*False positives:* none on 124 pages of correct Arabic. That is 65 pages of OCR output, including noisy scans,
and 59 Wikipedia text-layer pages. The control itself could not exercise the new path, because Indra OCRs
it for visual-order text. So did a PDF printed by Edge, and one made by PyMuPDF. **Untested:** a trusted,
correctly encoded Arabic text layer going through the check inside the engine. No such PDF was found.

**2. Arabic search normalisation.** The index and every query use `textnorm.search_form`:
- harakat and tatweel removed
- أ إ آ ٱ → ا, ى → ي, ة → ه
- Unicode digits → ASCII

Queries are no longer split at a vowel mark. The library schema goes to version 2, and older libraries are
re-indexed when opened (tested).

| Arabic test queries (one document with harakat, shadda, ta marbuta, Arabic-Indic digits) | Baseline 4 | P0 |
|---|---|---|
| Document found | 4/10 | 10/10 |

In the 26-document diagnostic, Arabic search ranks moved both ways, with too few queries to call:
- the digital letter went from ranks 3 and 2 to 1 and 3
- two scans dropped one or two places

With keyword search alone the letter scan ranks first. The shuffling comes from fusing keyword ranks with
the English-only embedder, which is the P3 item.

**Still failing after P0**, unchanged:
- Arabic QA: 2/9 on digital documents (the control 0/3) and 0/9 on scans
- Arabic summaries: not recognised as requests
- Arabic month names
- classification

These are P1–P3.

## Separate improvement: dates such as JAN04/00 in extraction

Baseline 4 read month-name dates only with a 4-digit year and spaces ("14 Mar 2026"). Invoices also print
"JAN04/00", "04-JAN-00", "19Jun'22" and "Sept 30, 82". The change (`extract/values.py`) accepts a 2- or
4-digit year with spaces, hyphens, slashes, dots or an apostrophe. A year followed by ".5" or ":30" is not read
as a year, so "QTY 2 MAY 15.00" stays an amount. An issue date more than a year in the future is now flagged
(due, expiry and end dates are not). Baseline 4 stays the comparison reference.

Measured with `bench/compare_dates.py`: the same files through baseline 4 and the new code, with the same OCR
models and fresh libraries. Labels are parsed by the script's own date parser, independent of Inklight's.

| Set | Documents | Labelled dates | Correct (old → new) | Missing | Wrong | Values changed |
|---|---|---|---|---|---|---|
| INV-CDIP genuine invoices (test set) | 80 | 91 | 71 → 76 | 13 → 7 | 7 → 8 | 6 |
| Voxel51 synthetic invoices, dev | 60 | 60 | 60 → 60 | 0 → 0 | 0 → 0 | 0 |
| Voxel51 fresh + CORD receipts (no date labels) | 120 | – | – | – | – | 0 |
| This diagnostic's 25 documents | 25 | 31 date fields | +1 (FUNSD fax "Dec 10 '98") | | | 1 |

Of the 6 changed INV-CDIP values, 5 are now right: JAN04/00, JAN24/00, FEB12/03, FEB14/02 and MAR06/02, all
missing before. One is wrong: "08-OCT-85" was read as 2035-10-08, because Indra's OCR reads the scan as
"08-OCT-35". That value is now flagged ("more than a year in the future"), so it is a flagged error, not a
silent one. 2 labels could not be parsed by the script and are not scored. Earlier benchmark results are
unaffected: no Voxel51 or CORD value changed.

Regression tests (`tests/test_values_fields.py`):
- 9 accepted forms
- 6 inputs that must not become dates
- extraction of "INVOICE DATE JAN04/00"
- the future-date flag

Arabic month names are still unsupported (failure 7, plan P1).
