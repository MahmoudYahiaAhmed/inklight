# Benchmarks

Two kinds of measurement live here, and they answer different questions:

1. **External datasets** (`bench/external.py`): real OCR on the original image files of two public datasets
   Inklight was not written against, scored against the datasets' own annotations, with a development split
   used for fixing and a holdout split run once at the end. This is the closest thing to field performance
   we have.
2. **Generated documents** (`bench/run.py`, `bench/memory.py`): synthetic invoices written by the same author
   as the code. They are regression checks and speed/memory measurements, not evidence of accuracy on real
   documents.

**Machine:** Windows 11, AMD64 (AMD Zen 4 laptop part), 16 logical cores, CPU only. External runs: Python
3.12.10 in fresh virtual environments. Generated-document runs: Python 3.13.9. **Date:** 2026-10-24.

## Scoring: four separate properties

A value or request is never just "right" or "wrong". Each one is scored as exactly one of:

| Outcome | Meaning | Counts as solving? |
|---|---|---|
| **correct** | the value / document set matches the annotation, and nothing was flagged | **yes** (this is *useful coverage*) |
| **abstained** | no value (field), or the request came back `partial` / `unsupported` with the unapplied words listed | no |
| **wrong, flagged** | wrong, but carried a warning or confidence < 0.7 | no |
| **wrong, silent** | wrong, unflagged, confidence ≥ 0.7. **The failure that matters most.** | no |

Warnings and refusals never count as solving. "Precision when unflagged" is correct ÷ (correct + silent wrong):
how often an unflagged value can be trusted.

## External datasets

| Dataset | What it is | Documents used | Fields scored |
|---|---|---|---|
| [Voxel51/high-quality-invoice-images-for-ocr](https://huggingface.co/datasets/Voxel51/high-quality-invoice-images-for-ocr) (ODbL) | **synthetic** invoices, rendered images, English, USD with `2 425,87` notation, two-column Seller/Client blocks, Net/VAT/Gross summary tables | 60 dev + 60 holdout | vendor, customer, invoice_number, date, tax, total |
| [naver-clova-ix/cord-v2](https://huggingface.co/datasets/naver-clova-ix/cord-v2) (CC-BY-4.0) | **genuine** photographed restaurant receipts, Indonesia, IDR without cents (`16,363`, `7.000`), slanted and creased photos | 60 dev (validation split) + 60 holdout (test split) | total, subtotal, tax (only where annotated) |

**Receipts are reported separately from invoices, and genuine-invoice validation is incomplete.** Voxel51
invoices are synthetic; CORD documents are genuine but are receipts. We found no openly licensed set of
*genuine* invoices with field annotations we could download, so **how Inklight performs on real-world
invoices is not yet measured.**

Splits are deterministic (`sha1` of the source id, `bench/prepare_external.py`). The holdout was not opened,
run or inspected while fixing. Dataset images and annotations are not redistributed in this repository;
the per-value result files in `bench/results/external/` reference them by file name.

### Which code ran (provenance)

Every result file records the interpreter, `inklight.__file__`, the install method, the wheel's sha256 and
the git commit. Each build had its own virtual environment and every run its own empty `INKLIGHT_HOME`, so
no run read another's library database or the user's `~/.inklight`.

| Build | Version | Commit | Wheel sha256 | Installed from |
|---|---|---|---|---|
| PyPI 0.1.0 | 0.1.0 | release built from `914d321` | `4922dc132df4743e…` | `pip install inklight==0.1.0` (PyPI) |
| before fixes | 0.1.1.dev0 | `d0fac3d` | `cd8494905e32673b…` | local wheel |
| final | 0.1.1.dev0 | `05206d7` | `1a751494d703cd01…` | local wheel |

Full hashes, paths and the intermediate builds are in `bench/results/external/*.json`.

### Proof that the models ran

`onnxruntime.InferenceSession.run` is wrapped by the harness, independently of Inklight's own counters, and
every call is counted per model file. From the final build on the holdout:

| Dataset | Brain | OCR model calls (det, rec, order, orient, script) | Reader (66M) calls | Embedder (33M) calls | Writer (135M) |
|---|---|---|---|---|---|
| Voxel51 | rules | 1,248 | 0 | 0 | not loaded |
| Voxel51 | auto | 1,248 | **0** | 15 | not loaded |
| CORD | rules | 818 | 0 | 0 | not loaded |
| CORD | auto | 818 | 116 | 6 | not loaded |

`Brain.usage()` reports the same loads and inference counts. 0.1.0 has no `Brain.usage()`; the ONNX
counts are the evidence there. Note: on Voxel51 the auto brain's reader is never consulted, because labelled
values are found first, and in 0.1.0 it ran 3,048 times without lifting accuracy. On CORD it adds one
correct value out of 124. **The small models contribute little to field extraction on these sets**; the
gains below come from layout handling in deterministic code.

### Holdout results (run once, at the end)

**Fields**

| Build | Dataset | Brain | Values | Correct | Abstained | Wrong, flagged | **Wrong, silent** | Precision when unflagged |
|---|---|---|---|---|---|---|---|---|
| PyPI 0.1.0 | Voxel51 (synthetic invoices) | rules | 360 | 41.7% | 27.5% | 0.0% | **30.8%** | 57.5% |
| **final** | Voxel51 (synthetic invoices) | rules | 360 | **99.7%** | 0.0% | 0.0% | **0.3%** (1) | 99.7% |
| PyPI 0.1.0 | CORD (genuine receipts) | rules | 124 | 3.2% | 89.5% | 4.8% | **2.4%** | 57.1% |
| **final** | CORD (genuine receipts) | rules | 124 | **68.5%** | 19.4% | 10.5% | **1.6%** (2) | 97.7% |
| **final** | CORD (genuine receipts) | auto | 124 | 69.4% | 18.5% | 10.5% | 1.6% (2) | 97.7% |

The "before fixes" build (0.1.1.dev0 at `d0fac3d`) scores the same as PyPI 0.1.0 on every field, because the
earlier 0.1.1 work changed request handling, not extraction.

The three silent errors on the holdout:

- **Voxel51 `batch1-0217`, total.** Inklight read the "Gross worth" total, 8,405.45. The annotation says
  7,641.32, which is the document's *net* amount (7,641.32 × 1.10 VAT = 8,405.45). We believe the
  annotation is wrong; the same happens once on dev (`batch1-0487`). It is still scored as an error.
- **CORD `015` and `032`, total.** OCR dropped a digit: `63.000` was read as `63.00`, so the total came out
  as 63 instead of 63,000. A cross-check would catch both (a two-decimal amount on a receipt whose other
  amounts use thousands groups, or a total 1,000× below its subtotal). It was found on the holdout and
  is **not** fixed here, so that the holdout stays a clean measurement. It is the first item for the next
  round.

Per field (final build, rules, holdout): Voxel51 vendor, customer, invoice_number, date and tax are 60/60;
total is 59/60. On CORD, subtotal is 77.5% correct (22.5% abstained), tax 48.0% (48.0% abstained) and total
71.2% (20.3% wrong but flagged, 3.4% silent). Totals are often flagged because the inferred fallback (largest
amount) is used when OCR makes the "Total" row unreadable.

**Requests** (17 forms on the Voxel51 holdout documents, run end to end through `agent.plan` and
`run_plan`; expected document sets come from the annotations)

| Form | Example | PyPI 0.1.0 | final |
|---|---|---|---|
| threshold ×2 | Find invoices above $1,080 / below $1,080 | silent wrong ×2 | correct ×2 |
| range | Find invoices between $230 and $7,052 | silent wrong | correct |
| count | how many invoices are above $1,080? | silent wrong | correct |
| sum | What is the total of invoices above $1,080? | silent wrong | correct |
| vendor | Find invoices from Cruz-Carter | correct | correct |
| vendor OR | … from Cruz-Carter or Carpenter-Johnston | silent wrong | correct |
| vendor AND threshold | … from Cruz-Carter above $1,080 | silent wrong | correct |
| possessive ×4 | Show Cruz-Carter's invoices · lower case · curly ’ · name first: "Cruz-Carter's invoices above $1,080" | silent wrong ×4 | correct ×4 |
| year | Find invoices in 2016 | correct | correct |
| unsupported ×4 | paid late · from last month · top 5 · from March | 3 abstained, **1 silent** ("from March") | **4 abstained** (`partial`, phrase listed) |
| **Supported: correct / silent wrong** | | **2/13 / 11/13** | **13/13 / 0/13** |
| **Unsupported: useful abstention** | | 3/4 | **4/4** |

Most of 0.1.0's request failures are extraction failures (no total read, so no threshold can match). The
same 17 forms on dev give the same final result: 13/13 and 4/4.

### Development split: baseline → fixes (the self-correction loop)

The baseline was saved before any change (`bench/results/external/base-*.json`). Failing development
documents were opened and read, root causes found, and general fixes made. No document-specific rules were
added.

| Step | Voxel51 dev correct / silent | CORD dev correct / silent | What changed (all general) |
|---|---|---|---|
| baseline (0.1.0 and `d0fac3d`) | 45.3% / 29.7% | 2.5% / 0.0% (94.2% abstained) | — |
| fix 1 (`e08497b`) | 99.4% / 0.3% | 68.3% / 0.0% | label → value by page geometry; summary-row column titles; `$ 2 425,87`; `16,363` / `Rp. 28.636` |
| fix 2 (`2794110`) | 99.4% / 0.3% | 78.3% / 0.0% | rejoin OCR-split amounts; label + rate ("Tax 10%"); cash tendered is never the total |
| final (`05206d7`) | 99.4% / 0.3% | 78.3% / 0.0% | "from March" reported; questions that name their document (no extraction change) |

Root causes found by reading the failing images:

1. **Two-column blocks.** Reading order puts "Seller:" and "Client:" side by side, and then both
   addresses. The value "after" a label was therefore the other column's line, giving an IBAN as the
   customer or the seller's name as the customer. Customer was silently wrong on 80% of dev invoices.
   *Fix:* when lines have boxes, a lone label takes the value to its right on the same row, or else the
   nearest line below it in the same column.
2. **Summary rows.** "Total  $ 2 205,34  $ 220,53  $ 2 425,87" holds net, VAT and gross amounts, and the first
   one was taken as the total. *Fix:* each value on a multi-value row is assigned by the column title above
   it ("Net worth" → subtotal, "VAT" → tax, "Gross worth" → total). A row without titles is flagged.
3. **Number formats.** `$ 2 425,87` was read as 2, and IDR `16,363` / `7.000` (no cents) were not read as
   money at all. *Fix:* a space groups thousands right after a currency symbol, and thousands-grouped
   integers are amounts. A money cell must account for every digit in it, so `14 709,00` is never 709,00.
4. **Slanted receipt photos.** A value often precedes its label in reading order ("17,999" then "Grand
   Total"). The same-row rule, which chooses by vertical overlap, fixes it.
5. **OCR splits** (`177` `870`) and **labels with a rate** ("Pajak Rest 102" for "10%"), plus Indonesian
   tax labels (`pajak`, `ppn`, `pb1`, `p.rest`). The vocabulary was added from dev; the holdout shows how
   far it generalises.
6. **Cash tendered as total.** When no total label is readable, the largest-amount fallback took the cash
   handed over. Payment and change lines are now excluded. The fallback is still flagged.

**Dev → holdout gap.** Voxel51: 99.4% → 99.7%. CORD: 78.3% → 68.5%. Part of the CORD dev gain came from fitting
vocabulary to what dev contained. The holdout figure is the one to quote.

### Diagnostic: the dataset's own reference text (not the OCR pipeline)

Voxel51 ships a flattened `ocr_text` for each image. Fed through extraction instead of Inklight's OCR (0 ONNX
calls), it scores **33.3%** correct with 16.7% silent wrong on dev. It has no line boxes, so the layout rules
cannot apply. This is a diagnostic only (`diagnostic-reftext-*.json`). It shows that the gains come from
using the OCR geometry, not from the text alone.

### An unplanned holdout run, disclosed

The first holdout launch was stopped so the request set could be extended. The stop ended the Python
processes but not the shell loop, which went on to run an intermediate build (`2794110`) on the holdout. Its
results were not read before the final run, and nothing was changed because of them. They are kept as
`unplanned-D-*.json`, and their field numbers equal the final build's.

### Speed on these sets (final build)

| | Voxel51 (1654×2339 images) | CORD (receipt photos) |
|---|---|---|
| Ingest 60 documents, rules (OCR, chunk, classify, index) | 14.9 s (0.25 s/doc) | 7.6 s (0.13 s/doc) |
| Extract 6 / 3 fields × 60 documents | 0.31 s | 0.20 s |

## Generated documents (regression checks, speed and memory)

Produced by `python bench/run.py` and `python bench/memory.py` on the final code. Raw output is in
`bench/results.json`.

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
| Digital PDF page (text-layer path) | **43 ms** | 50 ms | 20 |
| Scanned image page (full OCR) | **98 ms** | 104 ms | 20 |
| Indra model load (warm disk) | 0.73 s | | |

### End to end

| Metric | rules brain | auto brain (reader 66M + embedder 33M) |
|---|---|---|
| Ingest 40 docs (validate, hash, OCR, chunk, classify, index, embed) | 3.3 s (**12.2 pages/s**) | 3.6 s (11.1 pages/s) |
| Extract 6 fields × 40 docs | 0.11 s | 0.22 s |
| Task latency (filter / compare / aggregate / summarize), already indexed | 5 / 5 / 5 / 1 ms | 7 / 6 / 6 / 2 ms |
| Peak memory, 8 documents + 2 tasks, fresh process | **446 MB** | **579 MB** |
| `import inklight` / cold `inklight --version` | 0.28 s / 0.45 s | |

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
| SmolLM2-135M-Instruct, zero-shot, log-likelihood over 10 labels | **27.5%** | 476 ms |

† The request set was written alongside the planner, so 100% is in-distribution and an upper bound, not a
generalisation claim. The 17 external request forms above are the out-of-distribution check.

### Where the time goes (decides "Rust or not")

cProfile of ingesting the 40 invoices:

| Bucket | Share |
|---|---|
| Indra OCR Python orchestration | 66.4% |
| Native C calls (ONNX Runtime inference, pdfium, OpenCV, SQLite, hashing) | 29.1% |
| Inklight's own Python | **2.1%** |
| Other Python (stdlib, pydantic) | 2.4% |

## Reproduce

```bash
python bench/prepare_external.py --root <data dir>          # downloads Voxel51 + CORD splits
python -I bench/external.py --data <data dir> --dataset cord --split dev --brain rules \
    --home <empty dir> --label mine --out result.json         # run with the inklight you want to test
python bench/summarize_external.py bench/results/external --prefix final
python bench/run.py && python bench/memory.py
```

## Change log of this document

- 2026-10-24 (third review): added the external datasets, with provenance, model-call proof, four-way
  scoring, a dev baseline, the fixes, and the holdout run once. Re-measured the generated-document section
  on the final code.
- 2026-10-24 (second review): added the three review cases to request handling.
- 2026-10-24: added layouts B and C and the request-handling section.
