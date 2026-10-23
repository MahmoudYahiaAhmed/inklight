# Benchmarks

Every number here was produced by `python bench/run.py` and `python bench/memory.py` on the machine
below. Raw output is in `bench/results.json`. Reproduce them yourself — numbers will differ by hardware.

**Machine:** Windows 11, AMD64 (Family 25 Model 117, AMD Zen 4 laptop part), 16 logical cores, CPU only,
Python 3.13.9, indra-ocr 1.1.x, onnxruntime 1.2x. **Date:** 2026-10-23.

## Test set

- **40 generated invoices** with known ground truth (`synth_invoices` in `bench/run.py`, seed 7):
  20 digital PDFs and 20 "scans". A scan is rendered at 110–200 dpi in grayscale, rotated ±2.5°, with
  Gaussian noise σ = 12. Vendors, label wording ("Total", "Amount Due", "Grand Total", …), date formats
  (ISO, "March 4, 2026", "04 Mar 2026", "03/04/2026") and amounts all vary.
- **8 demo documents** (`tests/factory.py`): 3 invoices (one a scanned PNG with a deliberate arithmetic
  error), 2 contracts, 2 quarterly reports, and 1 memo containing a prompt-injection line.
- **40 natural-language requests** with labelled intents, and **12 questions** with expected answers.

These are synthetic, clean-ish business documents. They do **not** represent handwriting, heavily degraded
scans, or complex tables. See Indra's own benchmarks for those.

## OCR engine (Indra) — measured separately from the agent

| | median | p90 | n |
|---|---|---|---|
| Digital PDF page (text layer path) | **44 ms** | 49 ms | 20 |
| Scanned image page (full OCR) | **97 ms** | 106 ms | 20 |
| Indra model load (warm disk) | 0.68 s | | |

## End to end

| Metric | rules brain | auto brain (reader 66M + embedder 33M) |
|---|---|---|
| Ingest 40 docs (validate, hash, OCR, chunk, classify, index, embed) | 3.26 s (**12.3 pages/s**) | 3.61 s (11.1 pages/s) |
| Extract 6 fields × 40 docs | 0.10 s | 0.24 s |
| Task latency (filter / compare / aggregate / summarize), already indexed | 4 / 5 / 5 / 1 ms | 6 / 6 / 6 / 2 ms |
| Peak memory, 8 documents + 2 tasks, fresh process | **446 MB** | **580 MB** |
| `import inklight` | 0.30 s | |
| `inklight --version` (cold CLI) | 0.46 s | |

## Accuracy

| Metric | rules | auto |
|---|---|---|
| Field accuracy, 240 values (invoice_number, vendor, date, subtotal, tax, total) | **98.8%** | 98.8% |
| — digital PDFs | 100% | 100% |
| — noisy, rotated scans | 97.5% | 97.5% |
| Wrong values that carried a warning or low confidence | **3 of 3** | 3 of 3 |
| Question answering (12 questions, answer string present) | 91.7% | 91.7% |
| Citation correctness (top source is the right document and contains the answer) | 91.7% | 91.7% |

Every miss is a `vendor` value on a scan with no "Vendor:" label, where the name is inferred from the
letterhead. Each was flagged as inferred. The rules brain misses one question ("Who is the provider…",
which needs reading comprehension). The auto brain gets that one but misses "How much notice is
needed to terminate?". The reader picked a different span.

## Small-model evaluation — why the 135M model does not plan

| Planner | Intent accuracy (40 requests) | Time per request |
|---|---|---|
| Deterministic rule planner | **100%** † | < 1 ms |
| SmolLM2-135M-Instruct, zero-shot, log-likelihood over 10 labels | **27.5%** | 438 ms |

† The request set was written alongside the planner. Treat 100% as in-distribution and as an upper bound.
The 135M result is the reason Inklight does not let a 135M model choose tools. Generative tool calling
would be even less reliable than this constrained ranking.

## Where the time goes (decides "Rust or not")

cProfile of ingesting the 40 invoices (share of total time):

| Bucket | Share |
|---|---|
| Indra OCR Python orchestration | 65.3% |
| Native C calls (ONNX Runtime inference, pdfium, OpenCV, SQLite, hashing) | 29.9% |
| Inklight's own Python | **2.3%** |
| Other Python (stdlib, pydantic) | 2.5% |

Rewriting Inklight's layer in Rust could save at most about 2% of ingest time, so it is not done. The
OCR engine is not Inklight's to rewrite, and it is already a mix of ONNX Runtime and NumPy.

## Not measured (yet)

- Comparisons against other tools or manual workflows on a shared public dataset.
- Handwriting, non-Latin scripts, complex tables.
- Linux and macOS numbers (CI runs the tests there but does not benchmark).
