# Benchmarks

Every number here was produced by `python bench/run.py` and `python bench/memory.py`. Raw output is in
`bench/results.json`. Reproduce them yourself: numbers will differ by hardware.

**Machine:** Windows 11, AMD64 (AMD Zen 4 laptop part), 16 logical cores, CPU only, Python 3.13.9,
indra-ocr 1.1.x, onnxruntime 1.2x. **Date:** 2026-10-24.

## Test set, and what it does not cover

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
- **9 constrained requests** with expected document sets, **40 requests** with labelled intents, and
  **12 questions** with expected answers.

These are still generated documents written by the same author as the code. They are not unseen documents
from real users. Handwriting, complex tables, Arabic and other non-Latin scripts are **not** measured. Treat
the accuracy figures as regression checks, not as field performance.

## OCR engine (Indra), measured separately from the agent

| | median | p90 | n |
|---|---|---|---|
| Digital PDF page (text-layer path) | **43 ms** | 49 ms | 20 |
| Scanned image page (full OCR) | **98 ms** | 107 ms | 20 |
| Indra model load (warm disk) | 0.75 s | | |

## End to end

| Metric | rules brain | auto brain (reader 66M + embedder 33M) |
|---|---|---|
| Ingest 40 docs (validate, hash, OCR, chunk, classify, index, embed) | 3.3 s (**12.2 pages/s**) | 3.7 s (11.0 pages/s) |
| Extract 6 fields × 40 docs | 0.11 s | 0.21 s |
| Task latency (filter / compare / aggregate / summarize), already indexed | 5 / 5 / 5 / 1 ms | 6 / 6 / 7 / 1 ms |
| Peak memory, 8 documents + 2 tasks, fresh process | **446 MB** | **580 MB** |
| `import inklight` / cold `inklight --version` | 0.26 s / 0.44 s | |

## Extraction accuracy (240 values: invoice_number, vendor, date, subtotal, tax, total)

| | rules | auto |
|---|---|---|
| Overall | **96.7%** | 96.7% |
| Layout A / B / C | 100% / 100% / 89.7% | same |
| Digital / scanned | 97.5% / 95.8% | same |
| `date` field | 82.5% | 82.5% |
| Wrong values that carried a warning or low confidence | **8 of 8** | 8 of 8 |

The 7 date errors are layout C's day-first dates such as `05/03/2026`, read month-first by default. Each is
now flagged as an ambiguous date. Setting `[extraction] day_first = true` reads them correctly, but would
then misread month-first documents, so the order is a per-deployment setting. The other error is a vendor
name on a scan.

## Request handling (does it answer the question that was asked?)

Expected document sets come from ground truth, so an extraction error also costs a point here.

| Request | rules | auto |
|---|---|---|
| Find invoices above $5,000 | exact | exact |
| Find invoices from <vendor> above $2,000 | exact | exact |
| Find invoices below $1,000 or above $10,000 | exact | exact |
| invoices between $1,000 and $3,000 | exact | exact |
| invoices not from <vendor> | 1 document short (its vendor was not read and was reported as unreadable) | exact |
| how many invoices are above $8,000? | exact | exact |
| **Exact-set accuracy** | **5/6** | **6/6** |
| Unsupported requests flagged as partial with the unapplied words ("paid late", "last month", "top 3") | 3/3 | 3/3 |
| Sum of all totals equals the ground-truth sum | yes | yes |

## Questions and citations (12 questions on the demo set)

| | rules | auto |
|---|---|---|
| Answer contains the expected value | 11/12 (91.7%) | **12/12** |
| Top source is the right document and contains the answer | 11/12 | 11/12 |

With 6 and 12 items, one question is 8–17 points. The small models' advantage here (auto 12/12 and 6/6 vs
rules 11/12 and 5/6) is real on this set but too small to generalise from.

## Small-model evaluation: why the 135M model does not plan

| Planner | Intent accuracy (40 requests) | Time per request |
|---|---|---|
| Deterministic rule planner | **100%** † | < 1 ms |
| SmolLM2-135M-Instruct, zero-shot, log-likelihood over 10 labels | **27.5%** | 564 ms |

† The request set was written alongside the planner. Treat 100% as in-distribution and an upper bound.

## Where the time goes (decides "Rust or not")

cProfile of ingesting the 40 invoices:

| Bucket | Share |
|---|---|
| Indra OCR Python orchestration | 66.6% |
| Native C calls (ONNX Runtime inference, pdfium, OpenCV, SQLite, hashing) | 28.9% |
| Inklight's own Python | **2.1%** |
| Other Python (stdlib, pydantic) | 2.4% |

## Change log of this document

- 2026-10-24: Added layouts B and C and the request-handling section, in response to an external review.
  Overall field accuracy fell from 98.8% (one layout) to 96.7% (three layouts). Flagged errors rose from
  3 of 3 to 8 of 8, after fixing ambiguous dates, which had been wrong silently.
