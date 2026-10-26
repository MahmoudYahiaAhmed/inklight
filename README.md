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

<p align="center"><img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/assets/showcase/lead.png" width="900" alt="Two real screenshots of the Inklight workspace. Example 1: the Arabic question 'من وقّع الرسالة؟' on UN letter S/2025/380 is answered 'فاسيلي نيبينزيا', citing the signature line outlined on page 1. Example 2: 'What is the product?' on a scanned FUNSD insertion-order form is answered 'NEWPORT', citing 'PRODUCT: NEWPORT' outlined on the page."></p>

<p align="center"><sub>Two separate examples, both genuine documents, captured from the running workspace at commit <code>915be7b</code>:
<a href="https://documents.un.org/api/symbol/access?s=S/2025/380&l=ar&t=pdf">UN S/2025/380 (Arabic)</a> and
<a href="https://guillaumejaume.github.io/FUNSD/">FUNSD</a> form 93106788.
Requests, answers and evidence as the app returned them:
<a href="https://github.com/MahmoudYahiaAhmed/inklight/blob/main/docs/assets/showcase/arabic-letter-signer.json">example 1</a>,
<a href="https://github.com/MahmoudYahiaAhmed/inklight/blob/main/docs/assets/showcase/form-label-value.json">example 2</a>.
The library lists the form as an "invoice": that is the classifier's real (wrong) label.</sub></p>

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

The screenshots and the newest examples below were made with commit `915be7b`; to reproduce them exactly, install
that commit: `pip install "inklight @ git+https://github.com/MahmoudYahiaAhmed/inklight@915be7b"`.

`pip install inklight` installs the published 0.1.0 instead. Indra's OCR models (about 76 MB) download on the first OCR
run. After that, everything works offline.

Optional: `pip install "inklight[structure]"` adds [Docling](https://github.com/docling-project/docling)'s layout,
reading-order and table models on top of Indra's text (PyTorch, about 0.5 GB of weights; off until `[structure]
engine = "docling"`). See [docs/STRUCTURE.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/docs/STRUCTURE.md).

```bash
inklight process ./documents                          # OCR, classify and index (incremental)
inklight ask ./documents "Which court has jurisdiction?"
inklight ask ./documents/letter.pdf "لخص هذه الوثيقة"   # one file; a folder summarises each document
inklight serve                                        # web workspace on http://127.0.0.1:8765
```

## See it work

Each example below is real output from the development build: the first four from commit `915be7b`, the rest from
`2709d33`. Each was run on the original file, with `--json` output saved in [`docs/showcase/`](https://github.com/MahmoudYahiaAhmed/inklight/tree/main/docs/showcase/). The examples show successes; the failures are in
[the evaluation](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/docs/EVALUATION.md) and summarised under [Limits](#limits).

| Document | Request | Output | Evidence |
|---|---|---|---|
| Letter, digital PDF ([UN S/2025/300](https://documents.un.org/api/symbol/access?s=S/2025/300&l=en&t=pdf)), dated 9 May 2025 | `When will the open debate be held?` | **Tuesday, 20 May 2025** | p.1: "The open debate will be held on Tuesday, 20 May 2025, at 10 a.m." (the event's date, not the letter's) |
| Arabic letter, digital PDF ([UN S/2025/380](https://documents.un.org/api/symbol/access?s=S/2025/380&l=ar&t=pdf)) | `من وقّع الرسالة؟` | **فاسيلي نيبينزيا** | p.1, signature line: "(توقيع) فاسيلي نيبينزيا" |
| Form, scan ([FUNSD](https://guillaumejaume.github.io/FUNSD/) 93106788, magazine insertion order) | `What is the product?` | **NEWPORT** | p.1: "PRODUCT: NEWPORT", label and value paired by their row on the page |
| Receipt, phone photo, English and Arabic (CORU, Costa Coffee) | `ما قيمة ضريبة القيمة المضافة؟` | **The tax is 8.60** | p.1, the amount's box on the "VAT ضريبة القيمة المضافة" row, read as a separate column (a development example: this receipt guided the change) |
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
<td width="50%"><img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/assets/showcase/letter-event-date.png" alt="Question on UN letter S/2025/300 answered 'Tuesday, 20 May 2025', with the sentence outlined on page 1"><br><sub>A letter dated 9 May: the open debate's date (20 May) comes from the sentence about it, outlined on page 1.</sub></td>
<td width="50%"><img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/assets/showcase/mixed-receipt-vat.png" alt="Arabic question on an English and Arabic receipt answered 'The tax is 8.60', with the amount outlined"><br><sub>An Arabic question on a mixed receipt: the VAT amount was read in a separate column and paired with its row (development example).</sub></td>
</tr>
</table>

Screenshots were taken from the real workspace by [`bench/showcase.py`](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/bench/showcase.py), which types each request
into the app and saves the browser's picture with the result JSON next to it ([`docs/assets/showcase/`](https://github.com/MahmoudYahiaAhmed/inklight/tree/main/docs/assets/showcase/)).
The top image stacks two of those screenshots unedited under caption bars
([`bench/showcase_compose.py`](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/bench/showcase_compose.py)). To reproduce the newest four:

```bash
inklight process -c config.toml ./showcase-docs        # the four documents named above, in one folder
inklight serve -c config.toml --port 8777 --no-open
python bench/showcase.py --url http://127.0.0.1:8777 --cases bench/showcase_cases_v2.json --out docs/assets/showcase --width 1440 --height 900
python bench/showcase_compose.py --out docs/assets/showcase/lead.png "Example 1|Arabic letter, UN S/2025/380 (genuine): who signed it|docs/assets/showcase/arabic-letter-signer.png" "Example 2|English form, FUNSD 93106788 scan (genuine): the value beside its label|docs/assets/showcase/form-label-value.png"
```

## Measured results

Automated evaluation on **90 original documents** (letters, contracts, reports, forms, certificates, invoices,
receipts). It covers English, Arabic and mixed language, digital and scanned. Expected answers were fixed before
any run. The table shows the **reserved split** (30 documents, held out from development), with models on (the default).

- **First access** is the one independent run of the development build. It ran from uncommitted source, now
  [reconstructed, and its re-run reproduces the stored results](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/bench/results/usecases/provenance/README.md)
  (the same behaviour, not the original bytes).
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

**Questions the documents cannot answer** (`d012e07`, a separate split of 15 new genuine documents, first run). A
question about something the documents never mention ("What is the IBAN?" over a letter) is declined. At `d012e07`
the wording was "Not found: …"; it is now **"I couldn't find supporting evidence for “IBAN” in the processed text"**.
OCR can miss words, so the answer no longer claims the fact is absent.

| | Before (`6c1659c`) | After (`d012e07`) | n |
|---|---|---|---|
| Unanswerable, subject never mentioned: declined | 0 | **18** | 19 |
| Unanswerable, subject mentioned but value missing: declined | 0 | 1 | 11 |
| Unanswerable, answered silently | 10 | 7 | 30 |
| Answerable, declined | 0 | **0** | 42 |

Details: [EVALUATION.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/docs/EVALUATION.md#missing-information-not-found-d012e07).

**Answers connected to what was asked** (`9fc8da7`, 11 more new genuine documents, first run). The sender is not the
addressee, a letter's own date is not an event's, and a total that includes tax is not the tax.

| 44 answerable questions | Before (`2752a6d`) | After (`9fc8da7`) |
|---|---|---|
| Correct (flagged) | 26 (+4) | **30** (+3) |
| Declined although answerable | 0 | 1 |
| Wrong, flagged | 7 | 4 |
| Wrong, not flagged | 7 | 6 |
| Unanswerable (subject mentioned, value missing), answered without a flag | 4 of 8 | **1** of 8 |

One correct receipt answer became a silent error ("VAT-Inclusive" was not recognised as a qualifier).
Details: [EVALUATION.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/docs/EVALUATION.md#answers-connected-to-what-was-asked-9fc8da7).

**Labels and values on the page** (`915be7b`, a further 10 new genuine documents: letters, Wikipedia infoboxes in
English and Arabic, scanned forms, receipts; first run). A question that names a printed label ("What is the
product?", "ما الرمز البريدي للأقصر؟") is answered with the value beside it, with its page and box.

| 44 answerable questions | Before (`21f1dac`) | After (`915be7b`) |
|---|---|---|
| Correct (flagged) | 25 (+2) | **30** (+2) |
| Declined although answerable | 0 | 1 |
| Wrong, flagged | 8 | 3 |
| Wrong, not flagged | 9 | 8 |

An earlier version that paired labels with values only for dates and amounts (`bcd4752`) made **no difference** on
its own new documents or on these. Details: [EVALUATION.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/docs/EVALUATION.md#labels-and-values-on-the-page-915be7b).

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
- **Document structure (optional)** comes from Docling's existing layout, reading-order and TableFormer models, run on
  Indra's stored lines with no second OCR. Table answers then come from the cell under the right heading, in the row
  of the person or item asked about ([how, and what it costs](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/docs/STRUCTURE.md)).
- **Optional models** are small and English-only. They are used where they measurably help, and skipped where they
  harm. Each result's `checks` says which ran.

## Limits

- **Scanned Egyptian registers, tax cards and VAT certificates are not supported in practice.** In an agent-run
  workflow evaluation on such documents (plus receipts, an NDA and UN letters), the tool completed 2 of 76 task runs;
  every other correct result was read off the page by the person. Docling structure did not change this. Details:
  [docs/AGENT_EVALUATION.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/docs/AGENT_EVALUATION.md).
- **Arabic questions are mostly answered by sentence matching**, not by a model that reads Arabic, and those
  answers are flagged for review (11 of 23 right on the reserved split). A value printed beside a label, a letter's
  sender, addressee or signer, and a labelled field are read from the page itself and are not flagged.
- **English answers are wrong without a flag** about 1 time in 5 (8 of 42), most often on forms and long contracts.
- **Missing facts.** A question whose subject the document mentions but whose value it does not ("when will the
  debate be held?") is now usually declined. On new documents, 1 of 8 was still answered without a flag. The check
  can also decline a fact that is there: a table value printed under its column header ("CAPTION:") was declined as
  a blank field.
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
