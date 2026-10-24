# Benchmarks

Two kinds of measurement live here, and they answer different questions:

1. **External datasets** (`bench/external.py`): real OCR on the original image files of two public datasets
   Inklight was not written against, scored against the datasets' own annotations. There are three splits:
   a development split used for fixing; a holdout, run several times and read after the fixes (see
   [Execution history](#execution-history)); and a fresh split that guided no development. This is the
   closest thing to field performance we have.
2. **Generated documents** (`bench/run.py`, `bench/memory.py`): synthetic invoices written by the same author
   as the code. They are regression checks and speed/memory measurements, not evidence of accuracy on real
   documents.

**Machine:** Windows 11, AMD64 (AMD Zen 4 laptop part), 16 logical cores, CPU only. External runs: Python
3.12.10 in fresh virtual environments. Generated-document runs: Python 3.13.9. **Date:** 2026-10-24.

## Scoring: five outcomes, and what counts as useful

Every extracted value is exactly one of five outcomes (`bench/scoring.py`). *Flagged* means the value asks
for review: it carries a warning, or its confidence is below 0.7.

| Outcome | Meaning |
|---|---|
| **correct, unflagged** | matches the annotation and asks for no review: the only outcome that saves work |
| correct, flagged | matches, but asks for review |
| **wrong, unflagged** | does not match and asks for no review: a **silent error** |
| wrong, flagged | does not match, and asks for review |
| missing | no value returned |

The metrics below use these definitions:

- **Value accuracy** = (correct, unflagged + correct, flagged) ÷ all values. This is the number of values
  that match, whether or not they are flagged.
- **Coverage without review** = correct, unflagged ÷ all values. This is the useful coverage.
- **Precision, unflagged** = correct, unflagged ÷ (correct, unflagged + wrong, unflagged). It answers how far
  an unflagged value can be trusted.
- **Silent error rate** = wrong, unflagged ÷ all values.
- **Review rate** = (correct, flagged + wrong, flagged) ÷ all values.

> **Correction (2026-10-24).** Until `e2563b6` this page counted a matching value as "correct" whether or
> not it was flagged. "Useful coverage" therefore included values that ask for review, and "precision when
> unflagged" was computed over flagged values too. For example, CORD holdout was reported as 68.5% useful
> coverage and 97.7% precision. Under the definitions above it is 50.8% coverage without review and 96.9%
> precision, unflagged (63 of 65). Every table below was recomputed from the saved predictions by
> `bench/rescore.py`. The original result files are unchanged, and the rescored ones are in
> `bench/results/external/rescored/`.

Requests are scored by result, not only by the documents returned (`bench/tasks.py`):

- **Counts** are checked as a number.
- **Sums and averages** are checked as a number, with currency, values left out, and state.
- **Exports** are checked for exactly the expected rows. Every exported amount must equal the annotation, or
  be flagged in the file itself.
- **Refusals** count as useful only when the run finished, the state is `partial` or `unsupported`, and the
  result names the unsupported phrase. A crash, a timeout or an unexplained failure is not a refusal.

The task outcomes are:

| Outcome | Meaning |
|---|---|
| correct | right result, reported as complete |
| flagged | wrong or incomplete, and the result says so |
| silent wrong | wrong, reported as complete |
| unnecessary flag | right, but reported as partial |
| useful abstention | an unsupported request, refused with the unsupported phrase named |

## External datasets

| Dataset | What it is | Splits | Fields scored |
|---|---|---|---|
| [Voxel51/high-quality-invoice-images-for-ocr](https://huggingface.co/datasets/Voxel51/high-quality-invoice-images-for-ocr) (ODbL) | **synthetic** invoices: rendered images, English, USD with `2 425,87` notation, two-column Seller/Client blocks, Net/VAT/Gross summary tables | dev 60, holdout 60, fresh 60 | vendor, customer, invoice_number, date, tax, total |
| [naver-clova-ix/cord-v2](https://huggingface.co/datasets/naver-clova-ix/cord-v2) (CC-BY-4.0) | **genuine** photographed restaurant receipts: Indonesia, IDR without cents (`16,363`, `7.000`), slanted and creased photos | dev 60 (validation), holdout 60 (test), fresh 60 (train) | total, subtotal, tax (where annotated) |

**Receipts are reported separately from invoices, and genuine-invoice validation is incomplete.** Voxel51
invoices are synthetic. CORD documents are genuine, but they are receipts. We found no openly licensed set
of *genuine* invoices with field annotations, so **performance on real-world invoices is not measured.**

How the splits were built:
- Splits are deterministic, using the `sha1` of the source id (`bench/prepare_external.py`,
  `bench/prepare_fresh.py`).
- The **fresh** split was built after all the development below. It was checked for duplicates against dev
  and holdout by exact bytes, by a 4096-bit pixel difference hash calibrated on known-distinct documents,
  and by annotation.
- Voxel51: no candidate was rejected.
- CORD: 4 of the first 64 train receipts were rejected. Two carry the same annotation as receipts in CORD's
  test split, one is a near copy of a validation receipt (distance 10/4096), and one is a byte copy within
  train. CORD's own validation split also contains two receipts twice (`cord_dev_016`/`038` and
  `027`/`044`, distances 5 and 2), so CORD dev counts two receipts double.
- Dev and holdout share no duplicate in either dataset.

Dataset images are not redistributed. The result files reference them by file name and contain derived
annotation values (licences in `bench/results/external/README.md`).

### Annotation problems found

**Preparation bugs in our own code, corrected:**
- CORD sometimes gives a field as a list (`['55,834', '55,800']`), and the preparation script concatenated
  the list into one number.
- One Voxel51 tax was annotated as a rate (`'10%'`) and was read as the amount 10.00.

The three affected values, all on the fresh split, are removed from scoring through
`bench/results/external/truth_corrections.json`. The dev and holdout samples contain no such values.

**Disagreements with the dataset, kept:** three Voxel51 invoices annotate the *net* amount as the total:
- dev `batch1-0487`
- holdout `batch1-0217`
- fresh `batch1-0167`

In each, net × 1.10 VAT equals the gross total that Inklight returns. We believe the annotation is wrong, but
these are still scored as Inklight errors. They are the only silent field errors on Voxel51 in the final
builds, and they also make the "total of all invoices" sum check fail by exactly that difference.

### Which code ran (provenance)

Each build ran from its own wheel in its own virtual environment, and each run had its own empty
`INKLIGHT_HOME`. Every result file records:
- the interpreter, `inklight.__file__` and the install method
- the wheel's sha256 and the git commit
- the commit of the evaluation harness

| Build | Commit | Wheel sha256 | What it adds |
|---|---|---|---|
| A: PyPI 0.1.0 | release from `914d321` | `4922dc132df4743e…` | the published baseline |
| B: before fixes | `d0fac3d` | `cd8494905e32673b…` | 0.1.1 request handling |
| F | `05206d7` | `1a751494d703cd01…` | layout-aware extraction, receipt amounts, scoped questions |
| G | `e61a8d6` | `518a87190224076…` | digit-loss check v1 (flags any total under half its subtotal) |
| H | `3788bf9` | `b02ccba3b4511e3f…` | amount-consistency check v2, set-total sums, Rp in requests, `AgentResult.calculation` |

Runs made in the final round record harness commits `54355d7` and `a7ee6fa`. The fresh Voxel51 runs record
"bench/ modified": `bench/summarize_external.py`, which the runs do not use, was being edited at the time.

### Proof that the models ran

The harness wraps `onnxruntime.InferenceSession.run`, independently of Inklight's own counters, and counts
every call per model file.

| Run | OCR model calls | Reader (66M) | Embedder (33M) | Writer (135M) |
|---|---|---|---|---|
| Voxel51 holdout, F, rules / auto | 1,248 / 1,248 | 0 / **0** | 0 / 15 | not loaded |
| CORD holdout, F, rules / auto | 818 / 818 | 0 / 116 | 0 / 6 | not loaded |

`Brain.usage()` reports the same loads and calls (0.1.0 has no `Brain.usage()`).

**The small models contribute little to field extraction here.** The auto brain's reader is never
consulted on Voxel51, because labelled values are found first. On CORD it changes one value out of 124, and
on fresh CORD it changes none that count as coverage. The gains come from layout handling in
deterministic code.

### Field results

Rules brain. With the auto brain, the 66M reader fills in some values the rules leave missing. In the
final builds that is 1–3 values per split, and every one is wrong and flagged, except one correct, flagged
value on CORD holdout. Coverage without review is unchanged. In 0.1.0 the reader filled 29–39 invoice
values per split, all wrong and flagged. All runs are in `rescored/tables.md`.

| Split | Build | Values | Value accuracy | **Coverage without review** | **Precision, unflagged** | Silent errors | Review rate | Missing |
|---|---|---|---|---|---|---|---|---|
| Voxel51 dev | A (0.1.0) | 360 | 45.3% | 36.1% | 54.9% | 29.7% (107) | 9.4% | 24.7% |
| Voxel51 dev | F | 360 | 99.4% | **93.1%** | **99.7%** | 0.3% (1) | 6.7% | 0.0% |
| Voxel51 holdout | A (0.1.0) | 360 | 41.7% | 31.9% | 50.9% | 30.8% (111) | 9.7% | 27.5% |
| Voxel51 holdout | F | 360 | 99.7% | **91.4%** | **99.7%** | 0.3% (1) | 8.3% | 0.0% |
| Voxel51 fresh | A (0.1.0) | 359 | 47.9% | 39.8% | 59.3% | 27.3% (98) | 8.4% | 24.5% |
| Voxel51 fresh | H | 359 | 99.4% | **91.6%** | **99.7%** | 0.3% (1) | 8.1% | 0.0% |
| CORD dev | A (0.1.0) | 120 | 2.5% | 1.7% | 100% (2 of 2) | 0.0% | 4.2% | 94.2% |
| CORD dev | F | 120 | 78.3% | **65.0%** | **100%** | 0.0% (0) | 20.0% | 15.0% |
| CORD holdout | A (0.1.0) | 124 | 3.2% | 2.4% | 50.0% | 2.4% (3) | 5.6% | 89.5% |
| CORD holdout | F | 124 | 68.5% | **50.8%** | **96.9%** | 1.6% (2) | 28.2% | 19.4% |
| CORD fresh | A (0.1.0) | 127 | 2.4% | 0.0% | – | 0.0% | 7.9% | 92.1% |
| CORD fresh | F | 127 | 61.4% | **47.2%** | **90.9%** | 4.7% (6) | 22.8% | 25.2% |
| CORD fresh | H | 127 | 61.4% | **47.2%** | **93.8%** | 3.1% (4) | 24.4% | 25.2% |

How to read this:
- **Invoices (synthetic):** about 91–93% of values need no review, and about 1 in 300 unflagged values is
  wrong. That one is the annotation disagreement above.
- **Receipts (genuine):** fewer than half of the values need no review. 1 in 11 to 1 in 16 unflagged values
  was wrong on fresh, before and after the new check.
- About a quarter of receipt values are flagged, and another quarter are missing.

### Task results

The final-round harness, rules brain. Dev ran builds A, F and H; fresh ran A, F, G and H, and G matches F
except where noted.

| Split | Dataset | Build | Document sets (11 / 3) | Count | Sums and averages | Export | Refusals (4) |
|---|---|---|---|---|---|---|---|
| dev | Voxel51 | A | 1 correct, 10 silent | silent (0 records reported as success) | 3 silent (stated average 152.06 vs 14,799.12) | silent (empty file) | 3, 1 silent ("from March") |
| dev | Voxel51 | F | 11 correct | correct (29) | 1 correct, **2 silent** | correct (29 rows, all values) | 4 |
| dev | Voxel51 | H | 11 correct | correct | 2 correct, 1 silent † | correct | 4 |
| fresh | Voxel51 | A | 1 correct, 10 silent | silent (5 vs 29) | 3 silent | silent (5 of 29 rows, unflagged) | 3, 1 silent |
| fresh | Voxel51 | F | 11 correct | correct | 1 correct, **2 silent** | correct | 4 |
| fresh | Voxel51 | H | 11 correct | correct (29) | 2 correct (449,102.48; 27,386.50), 1 silent † | correct | 4 |
| dev | CORD | A | 3 silent | silent | 2 silent | silent (58 rows for 28) | 3, 1 silent |
| dev | CORD | F, H | 3 flagged | flagged | 2 flagged | flagged | 4 |
| fresh | CORD | A | 3 silent | silent (0 vs 28) | 2 silent | silent | 3, 1 silent |
| fresh | CORD | F, G | 3 flagged ‡ | flagged ‡ | 1 flagged, **1 silent** | flagged ‡ | 4 |
| fresh | CORD | H | 3 flagged | flagged (27 vs 28) | 2 flagged | flagged (3 wrong values, all flagged in the file) | 4 |

Notes on the table:
- † The remaining silent result is the sum over all invoices: off by exactly the annotation disagreement
  (26.00 on dev, 8.66 on fresh).
- ‡ In F and G, "Rp 39,000" in a request is not understood. It is reported, so the result is partial, not
  wrong.
- **F's two silent sums.** "What is the total of invoices above $X?" was planned as a list, not a sum. It
  returned the right invoices, reported success, and computed no total. The previous version of this page
  scored that request as correct because it only compared document sets. H fixes it, and the sum is now
  exposed as `AgentResult.calculation`.

**Receipts, at task level, never complete without review.** Every CORD task in F and H is `partial` with
reasons: low OCR confidence, values that could not be read, or amounts in several currencies (OCR reads
some "Rp" as "¥" or "$", and Inklight refuses to add them).

One state is too optimistic. On fresh CORD, H's sum over *all* receipts reports `succeeded` while leaving
out 5 receipts with no readable total. It warns "5 document(s) had no total and were left out", and
`calculation.missing` is 5, but the state alone overstates completeness. Build I changes this (next
section). The fresh results above remain build H's and were not re-run.

### Follow-up: aggregates that leave documents out (build I, dev only)

**The change** (`69675a0`, wheel `d37bd91cca7740f5…`):
- A sum, average, minimum or maximum that leaves out documents without a value now reports `partial`, not
  `succeeded`.
- The answer says how many documents were left out, for example "(over 53 document(s); 5 document(s) with
  no total left out; …)", including when the currencies differ.
- The value itself is unchanged, and `calculation.missing` still gives the count.

**Measured on dev only.** The fresh split was not re-run, so the fresh table above is build H's and does not
include this change.

| Dev run | Field results vs H | Task outcomes vs H | Aggregates leaving documents out | …of those reported `succeeded` |
|---|---|---|---|---|
| Voxel51 dev, rules + auto | identical | identical (no state changed) | 0 | 0 |
| CORD dev, rules + auto | identical | identical (no state changed) | 1 (sum over all receipts, 2 left out) | 0 (in H already `partial`) |

Dev therefore shows **no regression, but no observable effect either**:
- On dev the only aggregate that leaves documents out was already `partial` for other reasons: low OCR
  confidence, and inferred totals.
- Dev contains no case where leaving documents out is the *only* gap, so the behaviour rests on unit tests
  in `tests/test_condition_enforcement.py`. Those tests cover a sum and an average over 4 of 5 invoices
  (`partial`, with the left-out count in the answer and the checks), a complete sum (`succeeded`), a
  filtered sum whose conditions exclude the gap (`succeeded`), and the per-currency answer.
- The motivating case, the fresh all-receipts sum, is not re-measured here.

Build I's ONNX call counts on dev equal H's. H itself makes 210 more OCR calls than F on Voxel51 dev (1,445
vs 1,235). These are second readings by the amount-consistency check, triggered by its format or magnitude
signal, that agreed with the first reading and flagged nothing.

Results: `bench/results/external/partial-I-*.json`, `provenance_partial.md`.

### Development split: baseline → fixes

The baseline was saved before any change (`base-*.json`). Failing development documents were opened and
read, root causes found, and general fixes made, with no document-specific rules.

| Step | Voxel51 dev: coverage without review / silent | CORD dev: coverage without review / silent | What changed |
|---|---|---|---|
| baseline (A and B) | 36.1% / 29.7% | 1.7% / 0.0% (94.2% missing) | — |
| fix 1 (`e08497b`) | 93.1% / 0.3% | 56.7% / 0.0% | label → value by page geometry; summary-row column titles; `$ 2 425,87`; `16,363` / `Rp. 28.636` |
| fix 2 (`2794110`) | 93.1% / 0.3% | 65.0% / 0.0% | rejoin OCR-split amounts; label + rate ("Tax 10%"); cash tendered is never the total |
| F (`05206d7`) | 93.1% / 0.3% | 65.0% / 0.0% | "from March" reported; questions that name their document |
| H (`3788bf9`) | 93.1% / 0.3% | 65.0% / 0.0% | amount-consistency check (no flags on dev); set-total sums; Rp in requests |

Root causes found by reading the failing images:

1. **Two-column blocks.** Reading order put "Seller:" and "Client:" side by side, so a label's "next line"
   belonged to the other column. A lone label now takes the value to its right on the same row, or else the
   nearest line below it in the same column.
2. **Summary rows** ("Total  $ 2 205,34  $ 220,53  $ 2 425,87"). Each value is now assigned by the column
   title above it. A row without titles is flagged.
3. **Number formats.** A space now groups thousands after a currency symbol, and thousands-grouped integers
   are amounts. A money cell must account for every digit in it.
4. **Slanted receipt photos.** A value can precede its label in reading order; the same-row rule handles
   this.
5. **OCR-split amounts and labels with a rate**, plus Indonesian tax labels (`pajak`, `ppn`, `pb1`,
   `p.rest`). This vocabulary was added from dev.
6. **Cash tendered as total** in the largest-amount fallback. Payment lines are now excluded, and the
   fallback is still flagged.

**Dev → holdout → fresh, CORD coverage without review: 65.0% → 50.8% → 47.2%.** Part of the dev gain was
fitted to what dev contained. Quote the holdout and fresh figures.

### Amount-consistency check (v2, build H)

**What it addresses:** OCR dropping a digit, so `63.000` comes back as `63.00`, a valid-looking amount
1,000 times too small. Such a value is flagged only when independent signals agree:

| Signal | Meaning |
|---|---|
| format | the document's other amounts have no cents, or it names a zero-decimal currency, but this one has cents |
| magnitude | a total or subtotal is under 1/50 of the largest other amount (cash tendered and change excluded) |
| OCR confidence | the line was read with confidence below 0.9 |
| second reading | OCR of the enlarged image region gives a different amount (images at rotation 0 only) |

**Flag rule.** A value is flagged when format agrees with another signal, or when magnitude agrees with a
disagreeing second reading.

**What a flag does:**
- The value and its OCR text are kept. Nothing is multiplied and no digit is invented.
- The warning names the reasons, the second reading and the page and box.
- Confidence is halved, and the value is no longer marked verified.

Amounts in a cents currency are never compared with zero-decimal amounts. v1 (build G) flagged any total
under half its subtotal; v2 drops that rule, because a discount, deposit or refund trips it.

**Tests** (`tests/test_amount_consistency.py`). The two holdout receipts (`015`, `032`), with their real OCR
lines and boxes, are now **regression examples**, so the holdout is no longer evidence for this check. The
tests cover:
- legitimate decimals, thousands separators, large discounts, service charges and deposits
- refunds, missing subtotals and mixed currencies
- a tax with decimals that only its notation makes unusual
- agreeing, disagreeing and inconclusive second readings
- a real crop re-read through Indra

**Evaluation** on the fresh split, which did not guide development:

| Split | Build | Values | Flagged by the check | …were wrong (silent before) | …were correct (**false alarms**) | Silent errors | Coverage without review |
|---|---|---|---|---|---|---|---|
| dev, both datasets | G (v1) | 480 | 0 | 0 | 0 | unchanged | unchanged |
| dev, both datasets | H (v2) | 480 | 0 | 0 | **0** | unchanged | unchanged |
| CORD holdout (historical) | G (v1) | 124 | 4 | 2 (1 silent before) | 2 | 2 → 1 | 50.8% → 50.0% |
| Voxel51 fresh | G, H | 359 | 0 | 0 | 0 | unchanged | unchanged |
| CORD fresh | G (v1) | 127 | 3 | 2 (1 silent before) | 1 | 6 → 5 | 47.2% → 47.2% ¶ |
| CORD fresh | **H (v2)** | 127 | **2** | **2 (both silent before)** | **0** | **6 → 4** | 47.2% → 47.2% |

¶ v1's false alarm landed on a value that was already flagged, so coverage did not change.

What changed on fresh CORD:
- **Caught (before → after).** `cord_fresh_060` total: read `161.00`, true 161,000, unflagged before. It is
  now flagged as "possible OCR misread … it has cents, but the document's other amounts are written without
  cents; it is under 1/50 of another amount on the document … Kept as read, please check the source".
  `cord_fresh_067` total (`65.00` for 65,000) is caught the same way.
- **False-alarm rate:** H flagged 0 of 887 correct values across dev and fresh, including 0 of 78 correct
  fresh CORD values.
- **Not caught, and out of scope:**
  - two digit *misreads*, not losses: `12.000` for 12,600, and `8,000` for 8,800
  - a sign read from a nearby line: `-30,000` for 30,000 (subtotal, and tax likewise)

  These four are the remaining silent receipt errors.
- **Missed type.** The historical holdout receipt `015` would only be caught here because its regression
  test now covers OCR-spaced groups (`25. 000`). How often that pattern occurs elsewhere is not measured.

### Diagnostic: the dataset's own reference text (not the OCR pipeline)

Voxel51 ships a flattened `ocr_text` for each image. Fed through extraction instead of Inklight's OCR (0
ONNX calls), it gives 33.3% value accuracy on dev, 28.3% coverage without review and 16.7% silent. It has
no line boxes, so the layout rules cannot apply. This is a diagnostic only (`diagnostic-reftext-*.json`).

### Execution history

Earlier versions of this page said the holdout was "run once". The holdout was in fact executed several
times:

| # | Holdout runs | Why | Results read before the next change? | Influence on development |
|---|---|---|---|---|
| 1 | A (partly), B and D (`2794110`) | A launch that was stopped to extend the request set. Stopping it ended the Python processes but not the shell loop, which kept running. A and B outputs were overwritten by run 2. | no | none |
| 2 | A, B and E (`2f07058`) | the planned holdout run | yes | the silent errors found here led to the digit-loss work (G, then H) |
| 3 | F (`05206d7`) | to measure the commit then being shipped; F added a fix found on generated documents, not on the holdout | yes | none (identical to E) |
| 4 | G (`e61a8d6`) | the v1 digit-loss check | yes | v2's regression examples are holdout receipts |

So the holdout is a fair, if repeated, measurement of everything up to F. It is **not** independent
evidence for the amount checks (G, H); the fresh split is. Repeating a run does not by itself leak
information, but runs 2–4 were read and run 2 guided later work.

The **fresh** split ran once per build for Voxel51, and twice for CORD. The first CORD run revealed two
annotation-parsing bugs in our preparation script (above). The CORD fresh split was re-run with the same
four wheels and no Inklight change in between. Rescoring the first run with the corrected annotations gives
identical numbers. Earlier dev runs, made while building the task harness, are not kept. They used the same
wheels and dev data.

### Speed on these sets (build F)

| | Voxel51 (1654×2339 images) | CORD (receipt photos) |
|---|---|---|
| Ingest 60 documents, rules (OCR, chunk, classify, index) | 14.9 s (0.25 s/doc) | 7.6 s (0.13 s/doc) |
| Extract 6 / 3 fields × 60 documents | 0.31 s | 0.20 s |

## Generated documents (regression checks, speed and memory)

Produced by `python bench/run.py` and `python bench/memory.py` on the code of build H (`3788bf9`). Raw output
is in `bench/results.json`. Re-running `bench/run.py` on build I (`69675a0`) changed only timings: every
accuracy, request and citation result is identical. Later commits change only the evaluation harness, tests
and documentation.

### Test set, and what it does not cover

- **40 generated invoices** with known ground truth (`synth_invoices` in `bench/run.py`, seed 7), in **three
  layouts** that differ in labels, currency notation and date order:
  - A: labelled fields with `$` amounts and mixed date formats.
  - B: no currency symbols, the currency named only in the label `TOTAL DUE (USD)`, an unlabelled
    "Dated …" line, and the vendor after `From:`.
  - C: day-first numeric dates (`05/03/2026`), a `VAT (13%)` line and trailing `USD` codes.

  Half are digital PDFs. The other half are "scans": rendered at 110–200 dpi in grayscale, rotated ±2.5°,
  with Gaussian noise σ = 12.
- **8 demo documents** (`tests/factory.py`): 3 invoices (one a scanned PNG with a deliberate arithmetic
  error), 2 contracts, 2 quarterly reports, and 1 memo containing a prompt-injection line.
- **12 constrained requests** (9 with expected document sets, 3 unsupported), **40 requests** with labelled
  intents, and **12 questions** with expected answers.

Handwriting, Arabic and other non-Latin scripts are **not** measured anywhere in this document.

### OCR engine (Indra), measured separately from the agent

| | median | p90 | n |
|---|---|---|---|
| Digital PDF page (text-layer path) | **40 ms** | 46 ms | 20 |
| Scanned image page (full OCR) | **89 ms** | 96 ms | 20 |
| Indra model load (warm disk) | 0.73 s | | |

### End to end

| Metric | rules brain | auto brain (reader 66M + embedder 33M) |
|---|---|---|
| Ingest 40 docs (validate, hash, OCR, chunk, classify, index, embed) | 3.0 s (**13.2 pages/s**) | 3.4 s (11.9 pages/s) |
| Extract 6 fields × 40 docs | 0.11 s | 0.22 s |
| Task latency (filter / compare / aggregate / summarize), already indexed | 5 / 5 / 7 / 1 ms | 6 / 5 / 8 / 1 ms |
| Peak memory, 8 documents + 2 tasks, fresh process | **447 MB** | **579 MB** |
| `import inklight` / cold `inklight --version` | 0.30 s / 0.46 s | |

### Extraction on generated invoices (240 values)

| | rules | auto |
|---|---|---|
| Overall | **96.7%** | 96.7% |
| Layout A / B / C | 100% / 100% / 89.7% | same |
| Digital / scanned | 97.5% / 95.8% | same |
| Wrong values that carried a warning or low confidence | **8 of 8** | 8 of 8 |

Unchanged by the layout fixes above. Seven of the errors are layout C's day-first dates, which are flagged
as ambiguous (`[extraction] day_first` is a per-deployment setting). The eighth is a vendor name on a scan.

### Request handling on generated invoices

| | rules | auto |
|---|---|---|
| Exact document set, 9 requests | 8/9 † | **9/9** |
| Unsupported requests flagged as `partial` with the unapplied words | 3/3 | 3/3 |

† In rules mode one scan's vendor name is not read, so "not from <vendor>" is one document short and is
returned as `partial`. It is not silent.

### Questions and citations (12 questions on the demo set)

| | rules | auto |
|---|---|---|
| Answer contains the expected value | 11/12 | **12/12** |
| Top source is the right document and contains the answer | 11/12 | **12/12** |

Before the final fix, "What are the payment terms on the Acme invoice?" was answered from the *Globex*
invoice: both say "Net 30", so the answer text looked right. A question that names its document ("the Acme
invoice", "Acme's invoice") is now answered only from documents that match that name.

### Small-model evaluation: why the 135M model does not plan

| Planner | Intent accuracy (40 requests) | Time per request |
|---|---|---|
| Deterministic rule planner | 100% † | < 1 ms |
| SmolLM2-135M-Instruct, zero-shot, log-likelihood over 10 labels | **27.5%** | 421 ms |

† The request set was written alongside the planner, so 100% is in-distribution and an upper bound, not a
generalisation claim. The 17 external request forms above are the out-of-distribution check.

### Where the time goes (decides "Rust or not")

cProfile of ingesting the 40 invoices:

| Bucket | Share |
|---|---|
| Indra OCR Python orchestration | 65.5% |
| Native C calls (ONNX Runtime inference, pdfium, OpenCV, SQLite, hashing) | 29.9% |
| Inklight's own Python | **2.2%** |
| Other Python (stdlib, pydantic) | 2.4% |

## Reproduce

```bash
python bench/prepare_external.py --root <data dir>          # Voxel51 + CORD dev and holdout
python -I bench/prepare_fresh.py --root <data dir>          # fresh split, with duplicate checks
python -I bench/external.py --data <data dir> --dataset cord --split fresh --brain rules \
    --home <empty dir> --label mine --out result.json         # run with the inklight you want to test
python bench/rescore.py bench/results/external              # five-outcome field and task tables
python bench/summarize_external.py bench/results/external --prefix fresh1   # provenance, model calls
python bench/run.py && python bench/memory.py
```

## Change log of this document

- 2026-10-24: added build I (aggregates that leave documents out report `partial`), measured on dev only and
  reported separately; the fresh tables are unchanged.
- 2026-10-24 (fourth review): applied five-outcome scoring (correct/wrong × flagged/unflagged, missing) to
  every saved prediction. Added numeric task checks: counts, sums, currency, values left out, exported rows
  and values, and refusals that name what they refuse. Evaluated the amount-consistency check v2 on a
  fresh, de-duplicated split. Corrected the "run once" wording (see
  [Execution history](#execution-history)) and the earlier coverage and precision figures. The entries
  below are kept as written at the time.
- 2026-10-24: added the digit-loss check follow-up (dev first, then the holdout once; caveat stated).
- 2026-10-24 (third review): added the external datasets, with provenance, model-call proof, four-way
  scoring, a dev baseline, the fixes, and the holdout run once. Re-measured the generated-document section
  on the final code.
- 2026-10-24 (second review): added the three review cases to request handling.
- 2026-10-24: added layouts B and C and the request-handling section.
