<p align="center">
  <img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/assets/logo.svg" width="84" alt="Inklight logo">
</p>

<h1 align="center">inklight</h1>

<p align="center"><b>Local document intelligence for Arabic and English.</b><br>
OCR, search, questions with sources, summaries, field extraction, review and export, on your own machine.</p>

<p align="center">
  <a href="https://github.com/MahmoudYahiaAhmed/inklight/actions/workflows/ci.yml"><img alt="ci" src="https://github.com/MahmoudYahiaAhmed/inklight/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://pypi.org/project/inklight/"><img alt="pypi" src="https://img.shields.io/pypi/v/inklight?style=flat-square&labelColor=0B0F14&color=22D3EE"></a>
  <img alt="python" src="https://img.shields.io/badge/python-3.11%2B-22D3EE?style=flat-square&labelColor=0B0F14">
  <img alt="license" src="https://img.shields.io/badge/code-Apache--2.0-F5B544?style=flat-square&labelColor=0B0F14">
</p>

<p align="center"><img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/assets/showcase/contract-question.png" width="900" alt="The Inklight workspace answering 'Which court has jurisdiction?' on a CUAD contract, with the cited clause highlighted on page 7"></p>

Point Inklight at PDFs, scans or photos (letters, contracts, reports, forms, invoices, receipts) and ask in plain
English or Arabic. Every answer comes with **the page and passage it came from**, warnings when the evidence is weak,
and a trace of what ran. Nothing leaves your machine.

> **Where the work is.** The features below are in the **GitHub development build**. The
> [PyPI release 0.1.0](https://pypi.org/project/inklight/) predates the Arabic and general-document work. It does
> not include Arabic requests, Arabic search normalisation, broken-text-layer detection, the language routing or
> the review presets. "General documents" is the direction. What works today is measured below, document type by
> document type.

## Install

```bash
# development build (what this page describes); Python 3.11+, Windows / Linux / macOS, CPU only
pip install "inklight @ git+https://github.com/MahmoudYahiaAhmed/inklight"
inklight models pull        # optional: English reader + embedder, about 100 MB, once
```

`pip install inklight` installs the published 0.1.0 instead. Indra's OCR models (about 76 MB) download on the first OCR
run. After that, everything works offline.

```bash
inklight process ./documents                          # OCR, classify and index (incremental)
inklight ask ./documents "Which court has jurisdiction?"
inklight ask ./documents/letter.pdf "لخص هذه الوثيقة"   # one file; a folder summarises each document
inklight serve                                        # web workspace on http://127.0.0.1:8765
```

## See it work

Each example below is real output from the development build (code `2709d33`). It was run on the original file,
with `--json` output saved in [`docs/showcase/`](https://github.com/MahmoudYahiaAhmed/inklight/tree/main/docs/showcase/). The examples show successes; the failures are in
[the evaluation](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/docs/EVALUATION.md) and summarised under [Limits](#limits).

| Document | Request | Output | Evidence |
|---|---|---|---|
| Contract, digital PDF ([CUAD](https://zenodo.org/records/4595826), Imperial Garden outsourcing agreement) | `Which court has jurisdiction?` | **Miaoli District Court of Taiwan** | p.7: "herein agree to take the Miaoli District Court of Taiwan as the competent court of first instance" |
| Letter, 1983 typewritten scan ([UN S/16000](https://documents.un.org/api/symbol/access?s=S/16000&l=en&t=pdf)) | `Which city was hit by artillery fire on 8 September?` | **Abadan** | p.1: "8 September, when the city of Abadan was barraged by Iragi long-range artillery" (OCR's "Iragi" kept as read) |
| Receipt, phone photo (CORU, Egypt) | `What is the total amount?` | **The total is 50.00** | p.1: "EGP 50.00" |
| Arabic letter, digital PDF ([UN S/2023/90](https://documents.un.org/api/symbol/access?s=S/2023/90&l=ar&t=pdf)) | `لخص هذه الوثيقة` | Extractive summary, 5 sentences quoted from page 1, for example "جلسة إحاطة عقدها مجلس الأمن بشأن الحالة المتعلقة بالعراق، في 2 شباط/فبراير 2023" | every sentence is the document's own text with its page |
| Arabic tax invoice, **synthetic** ([generated](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/bench/usecases/make_synthetic.py)) | `استخرج رقم الفاتورة والتاريخ والإجمالي` | INV-7731 · شركة الواحة للتجهيزات المكتبية · 2024-05-12 · 4,600.00 | each value cites its line on p.1 |
| Any document | `Translate this letter into French` | `unsupported`: "translation is not something Inklight does" | nothing was run |

<table>
<tr>
<td width="50%"><img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/assets/showcase/arabic-summary.png" alt="Arabic summary request on a UN letter, answered with quoted sentences laid out right to left"><br><sub>An Arabic request and an Arabic summary, laid out right to left.</sub></td>
<td width="50%"><img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/assets/showcase/arabic-extract.png" alt="Arabic field extraction from a synthetic tax invoice, shown as a table"><br><sub>Fields from a <b>synthetic</b> Arabic invoice: each value comes from the label to its right.</sub></td>
</tr>
<tr>
<td width="50%"><img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/assets/showcase/scanned-letter.png" alt="Question on a 1983 typewritten scan, with the answering passage highlighted"><br><sub>A 1983 typewritten scan: the answer's passage is outlined on the page.</sub></td>
<td width="50%"><img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/assets/showcase/contract-question.png" alt="Contract question with the cited clause highlighted"><br><sub>A contract question: the clause is outlined on page 7.</sub></td>
</tr>
</table>

Screenshots were taken from the real workspace by [`bench/showcase.py`](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/bench/showcase.py), which types each request
into the app and saves the browser's picture with the result JSON next to it ([`docs/assets/showcase/`](https://github.com/MahmoudYahiaAhmed/inklight/tree/main/docs/assets/showcase/)).

## Measured results

Automated evaluation on **75 original documents** (letters, contracts, reports, forms, certificates, invoices,
receipts). It covers English, Arabic and mixed language, digital and scanned. Expected answers were fixed before
any run. The table shows the **reserved split** (30 documents, held out from development), with models on (the default).

- **First access** is the one independent run of the development build. It ran from uncommitted source, now
  [recovered and reproduced exactly](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/bench/results/usecases/provenance/README.md).
- **Rerun** is commit `8c54921`, after three fixes those same documents prompted. It is not independent.

| Questions with a cited source | P0 (`6b4cc12`) | First access | Rerun (`8c54921`) | n |
|---|---|---|---|---|
| English: correct | 25 | **30** (29 unflagged) | 30 (29 unflagged) | 42 |
| English: silently wrong | 8 | 8 | 8 | 42 |
| Arabic: correct, flagged for review | 1 | **11** | 11 | 23 |
| Arabic: silently wrong | 0 | 0 | 0 | 23 |
| Mixed: correct | 5 | 5 | 5 | 15 |
| Mixed: silently wrong | 6 | 8 | 6 | 15 |
| Arabic summary requests recognised | 0 of 9 | **9 of 9** (17 of 27 key facts, every sentence quoted verbatim) | 9 of 9 | 9 |
| Library tasks (find, compare, count, sum, filter, export, refuse) | 2 of 9 | **5 of 9** | 4 of 9 | 9 |
| "Translate / sign / email this" refused as unsupported | 0 of 2 | **2 of 2** | 2 of 2 | 2 |

The rerun fixed the two new mixed-language silent errors (both on one synthetic letter). It lost the letter
comparison, because "Letter dated" now dates only a letter's own title line.

<details>
<summary>Earlier external datasets (fields), the optional models, and what the numbers do not say</summary>

**External datasets** (fields; fresh split, build H `3788bf9`, rules; details in [BENCHMARKS.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/docs/BENCHMARKS.md#external-datasets)):

| Set | Values | Correct | Correct without review | Silently wrong |
|---|---|---|---|---|
| Voxel51 invoices (**synthetic**) | 359 | 99.4% | 91.6% | 0.3% |
| CORD receipts (genuine, Indonesia) | 127 | 61.4% | 47.2% | 3.1% |

**Optional models.** They were measured stage by stage on identical documents (dev split, P0 build). OCR text is
unchanged, because the models do not touch it. The two English models degraded **both Arabic retrieval and Arabic
answering**:
- Retrieval: with the embedder, the right Arabic document was in the top 3 for 20 of 36 questions instead of 29.
- Answering: the reader, given the same passages, turned correct Arabic answers into wrong spans (17 → 3 of 36 correct).
- Both help English: reader 16 → 20 of 53 answers; embedder top-3 retrieval 37 → 42 of 53.

So Arabic queries use keyword search and skip the reader. The writer model is off by default and was never loaded.
Full ablation: [EVALUATION.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/docs/EVALUATION.md#do-the-optional-models-harm-arabic).

**Not covered by these numbers:**
- small samples: 9 to 42 questions per row
- no human study
- no handwriting
- synthetic stand-ins for Arabic forms, certificates, invoices and contracts
- unit tests (617) counted separately

</details>

## How it works

```
documents ─► OCR (Indra) ─► deterministic processing ─────────────────────────► answer + sources + checks
             text layer      layout, labels, dates, amounts, currencies,             │
             first, OCR      classification, search index (Arabic-normalised),       │
             where needed    typed plan from your words, exact arithmetic            │
                                        │                                            │
                                        └── optional small models (English only): ───┘
                                            reader for English answers, embedder for English search
```

- **OCR** is [Indra OCR](https://github.com/datalab-to/indra), on CPU, with a right-to-left recognizer for Arabic. Inklight
  OCRs a PDF page itself when its Arabic text layer is broken (a [measured heuristic](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/docs/CAPABILITIES.md#the-text-layer-detector-is-a-heuristic)).
- **Deterministic processing** does most of the work: it reads labels and layout in both directions, parses dates
  (including Arabic month names) and amounts, plans from your request, and computes sums exactly. It never sends
  text anywhere.
- **Optional models** are small and English-only. They are used where they measurably help, and skipped where they
  harm. Each result's `checks` says which ran.

## Limits

- **Arabic questions are answered by sentence matching**, not by a model that reads Arabic. They are always flagged
  for review: 11 of 23 right on the reserved split.
- **English answers are wrong without a flag** about 1 time in 5 (8 of 42), most often on forms and long contracts.
- Receipt photos: totals and counts across receipts are often wrong (one receipt unclassified, cash amounts misread).
- Typewritten Arabic scans OCR only partly.
- Classification is keyword-based.
- No handwriting. No genuine Arabic forms or invoices were available to test, so synthetic ones stand in.
- Current status by capability and language: [docs/CAPABILITIES.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/docs/CAPABILITIES.md). Every case, including failures:
  [docs/EVALUATION.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/docs/EVALUATION.md).

<details>
<summary>Python API, configuration, security</summary>

```python
from inklight import DocumentAgent

agent = DocumentAgent()
result = agent.ask("Which court has jurisdiction?", files=["contract.pdf"])
print(result.answer, result.sources[0], result.warnings, result.checks)
records = agent.extract(["invoice.pdf"], fields=["invoice_number", "date", "total"])
```

- **API**: [docs/API.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/docs/API.md); the HTTP API is at `/api/docs` when serving.
- **Configuration**: `~/.inklight/config.toml` (see [config.example.toml](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/config.example.toml)) or environment
  variables such as `INKLIGHT_LIMITS__MAX_PAGES=50`.
- **Model modes**: `brain = "auto"` (default: small models if installed), `"rules"` (none), `"local"` (require them).
  An OpenAI-compatible remote model can be configured for low-confidence questions; it is off by default.
- **Security**: text inside documents is treated as data, never as instructions. The agent has no shell and writes
  files only where you allow. See [SECURITY.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/SECURITY.md).
</details>

## License notice: read before commercial use

Inklight's code is **Apache-2.0**. The **Indra OCR model weights** (downloaded by `indra-ocr`, not bundled) use a
**modified OpenRAIL-M license**. They are free for research, personal use, and organisations under $20M revenue and
under $20M funding. They restrict commercial use that **competes with Datalab**. A commercial document-AI product built
on Inklight and Indra needs a license from [Datalab](https://www.datalab.to/pricing), or a different OCR engine (the
OCR layer is pluggable). Full audit: [THIRD_PARTY_LICENSES.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/THIRD_PARTY_LICENSES.md).

## Development

```bash
pip install -e ".[dev]"
pytest                                   # 617 tests
ruff check src tests && mypy src
python -I bench/usecases/evaluate.py --help     # the evaluation above (documents: bench/usecases/README.md)
```

See [CONTRIBUTING.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/CONTRIBUTING.md), [CHANGELOG.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/CHANGELOG.md) and [CODE_OF_CONDUCT.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/CODE_OF_CONDUCT.md).
