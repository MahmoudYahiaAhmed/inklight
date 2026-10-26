<p align="center">
  <img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/assets/logo.svg" width="84" alt="Inklight logo">
</p>

<h1 align="center">inklight</h1>

<p align="center"><b>A local document workspace for Arabic, English and mixed documents.</b><br>
Import scans and PDFs, read their pages, text and tables, search them, review values and export what you approved, on your own machine.</p>

<p align="center">
  <a href="https://github.com/MahmoudYahiaAhmed/inklight/actions/workflows/ci.yml"><img alt="ci" src="https://github.com/MahmoudYahiaAhmed/inklight/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="status" src="https://img.shields.io/badge/status-developer%20beta%200.2.0b1-F5B544?style=flat-square&labelColor=0B0F14">
  <img alt="python" src="https://img.shields.io/badge/python-3.11%2B-22D3EE?style=flat-square&labelColor=0B0F14">
  <img alt="license" src="https://img.shields.io/badge/code-Apache--2.0-F5B544?style=flat-square&labelColor=0B0F14">
</p>

<p align="center"><img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/images/beta-turned-page.png" width="900" alt="The Inklight workspace: a synthetic English registration certificate scanned sideways, its text and tables read upright, the structure status, and raw export links, next to the page image."></p>

Inklight reads documents with [Indra OCR](https://github.com/datalab-to/indra) (Arabic and English, on CPU) and,
optionally, recovers layout and tables with [Docling](https://github.com/docling-project/docling). Everything it
shows is either **what was read** (text, boxes, tables, search hits, each linked to its page) or **a proposal for you
to check**. Nothing is uploaded anywhere.

> **Developer beta (0.2.0b1, GitHub only).** The [PyPI package 0.1.0](https://pypi.org/project/inklight/) is an older
> release without the workspace described here. This beta is for developers and careful users who check results
> against the page. It is not production software; see [Limitations](#limitations).

## Install and launch

Python 3.11+, Windows / Linux / macOS, CPU only:

```bash
pip install "inklight @ git+https://github.com/MahmoudYahiaAhmed/inklight@main"
```

```bash
inklight --version
```

```bash
inklight serve
```

`inklight --version` prints the version and the commit the build came from, for example
`inklight 0.2.0b1 (commit 1a2b3c4d5e)`. `inklight serve` opens the workspace at http://127.0.0.1:8765. Indra's OCR
models (about 76 MB) download on the first OCR run; after that everything works offline. `inklight doctor` checks the
installation.

### Optional add-ons (separate, off by default)

- **Document structure (Docling):** layout, reading order and tables on top of Indra's text, including pages scanned
  sideways. It adds about 0.5 GB of PyTorch weights. Install
  `pip install "inklight[structure] @ git+https://github.com/MahmoudYahiaAhmed/inklight@main"`, then set
  `[structure] engine = "docling"` in `~/.inklight/config.toml`. Without it, pages show OCR lines only and the
  workspace says so. Details: [docs/STRUCTURE.md](docs/STRUCTURE.md).
- **Small English models** (`inklight models pull`, about 100 MB): an English reader and embedder. They are not used
  for Arabic, where they measurably hurt.
- **A remote language model** (an OpenAI-compatible server you run yourself) can be configured for questions. It is
  off by default. A local 4B multilingual model was checked for this beta on 8 workflow tasks and did not help (0 of
  8, the same as without it), so it is not part of the supported workflow.

## Walkthrough

**1. Import.** Drop PDFs, scans, photos or text files on the upload box, or run `inklight process ./folder`. Each
file reports success or the reason it failed; a failed file does not stop the rest.

<img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/images/beta-import.png" width="760" alt="Upload of three files: one ready, one rejected as an unsupported file type, one PDF that cannot be opened, each with its reason.">

**2. Read the document.** The *Document* tab shows the OCR text of each page (Arabic right to left, mixed lines in
their own direction), the tables Docling recovered, and whether structure ran on that page. A page scanned sideways
is turned and structured upright, and the status says so (the image at the top). This is **what OCR read, not a
verified copy**: on the synthetic Arabic card below, the Arabic-Indic numbers are misread (٤٧٣١٩ is shown as
`EVY19`, the date and percentages are garbled) while the page's OCR estimate is 90%. Check every number against the
page image beside it.

<img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/images/beta-document.png" width="760" alt="A synthetic Arabic registration certificate: its text is laid out right to left and its three tables are shown, but the registration number ٤٧٣١٩ is read as EVY19 and the date and percentages are garbled.">

**3. Search and open the page.** Search covers every document, in Arabic and English. Each hit opens its page with
the passage outlined.

<img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/images/beta-search.png" width="760" alt="Search for 'Registration number' lists passages from several synthetic certificates; the first is outlined on its page.">

**4. Review and export.** *Review & export* proposes a value for each field you name, from a printed label of that
name or a typed field (a date, a total). You accept it, correct it or mark it absent; the OCR reading is kept next to
your decision. Only approved reviews are exported, with the predicted value, the raw reading, your final value, the
action, the source page and box, and who approved it; a document reviewed again keeps its earlier rows, marked
`superseded`. A proposed value with a warning (several cells on the row, Arabic and Latin text mixed, low OCR
confidence) is marked ⚠; a "number" field is never proposed from text without digits. Review covers the fields you name, not a correction of the whole text.
The *Document* tab's exports (`.txt`, `.json` with boxes and tables, tables `.csv`) are the **raw** reading and say
so in their first line.

<img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/images/beta-review.png" width="760" alt="A review of four named fields: two accepted, one corrected (the OCR had cut 'Co.'), one marked absent.">

**5. Ask (experimental).** Every result first says what it is: *extracted text*, *proposed answer: review before
use*, *supported answer* (a value at its printed label or table cell), *partial result*, *missing evidence*,
*several candidates: choose one*, or *unsupported*. When several values match, they are listed and you choose.
"Compare the registration number in these documents" shows each document's value and page, then *matches*,
*differs* or *cannot determine*. "Compare these documents" without a field is labelled a text comparison, not a
field comparison.

<table>
<tr>
<td width="50%"><img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/images/beta-compare.png" alt="Field comparison of the registration number in two synthetic certificates: 47319 on page 1 of each, result matches."></td>
<td width="50%"><img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/images/beta-candidates.png" alt="Two tables each with a company name: both values are listed as candidates and the user's choice is shown as a proposed value."></td>
</tr>
</table>

The screenshots show synthetic documents and public UN letters, captured from the running workspace at commit
`4aa23f9`.

The same from the command line:

```bash
inklight process ./documents                      # OCR, classify and index (incremental)
inklight search "رقم السجل"                       # passages with document and page
inklight show contract.pdf --page 2 --format text
inklight structure contract.pdf --format md -o contract.md   # needs the structure add-on
inklight ask a.pdf b.pdf "Compare the registration number in these documents"
inklight review export -o approved.csv
```

## What is ready and what is not

| | Status |
|---|---|
| Import with per-file errors; page viewer; rotated pages; tables | ready in this beta |
| Arabic and mixed text | shown as read; **Arabic-Indic digits are often misread**, with no per-cell warning in the Document tab |
| Search across documents, opening the page with the passage outlined | ready |
| Review of named fields; export of approved values with the original reading and source page | ready (named fields only) |
| Raw exports: text, JSON with boxes and tables, tables CSV | ready, marked as not reviewed |
| Docling structure | optional add-on |
| Ask: questions, field comparison, candidates | **experimental**: says what it found, but often finds nothing on real scans |
| Remote language model | off; not part of the beta |

## Limitations

- **Answers on real scans are weak.** On a private set of scanned Egyptian registers, tax cards and certificates,
  questions and comparisons mostly end as *missing evidence*, *cannot determine*, or a *proposed* passage that is not
  the answer. This beta reports that honestly instead of returning a wrong value as an answer; it did not make the
  answers right. A field comparison works only when the field is printed as a label with its value, or as a table
  cell.
- **OCR misreads.** Arabic-Indic digits are often misread (on the synthetic Arabic card every number is wrong), and
  stamps too. The OCR confidence shown is the reader's own estimate; it does not guarantee the text, and the
  Document tab and table view do not mark doubtful cells (Ask and review do).
- **Turned pages:** text and tables are read upright, but a table cell can still be split differently from the
  upright scan (a partner's role and share merged into one cell).
- **Proposed answers can be wrong without a specific warning.** "What is the expiry date?" on a card with only a
  registration date returns that date's line as a *proposed* answer. Treat every *proposed* result as a pointer to
  check, not as an answer.
- **Field proposals** come from printed labels and typed fields. A value that wraps onto a second line can be cut
  short, and a value in a bilingual table can include the label in the other language (flagged ⚠); correct it in
  review.
- **Classification is keyword-based** and often wrong (an Arabic UN letter labelled "contract").
- No handwriting. No time-saving or accuracy claim is made for this beta.

The historical evaluation, with every failure, is in [evaluation/AGENT_EVALUATION.md](evaluation/AGENT_EVALUATION.md) (an
agent-run workflow evaluation: the tool completed at most 1 of 38 tasks) and [evaluation/EVALUATION.md](evaluation/EVALUATION.md)
(question answering on 90 documents). A summary follows.

<details>
<summary>Historical evaluation (0.1.x development builds)</summary>

Automated evaluation on **90 original documents** (letters, contracts, reports, forms, certificates, invoices,
receipts). It covers English, Arabic and mixed language, digital and scanned. Expected answers were fixed before
any run. The table shows the **reserved split** (30 documents, held out from development), with models on (the default).

- **First access** is the one independent run of the development build. It ran from uncommitted source, now
  [reconstructed, and its re-run reproduces the stored results](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/evaluation/results/usecases/provenance/README.md)
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

Details: [EVALUATION.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/evaluation/EVALUATION.md#missing-information-not-found-d012e07).

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
Details: [EVALUATION.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/evaluation/EVALUATION.md#answers-connected-to-what-was-asked-9fc8da7).

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
its own new documents or on these. Details: [EVALUATION.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/evaluation/EVALUATION.md#labels-and-values-on-the-page-915be7b).

#### Earlier external datasets, the optional models, and what the numbers do not say

**External datasets** (fields; fresh split, build H `3788bf9`, rules; details in [BENCHMARKS.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/evaluation/BENCHMARKS.md#external-datasets)):

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
Full ablation: [EVALUATION.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/evaluation/EVALUATION.md#do-the-optional-models-harm-arabic).

**Not covered by these numbers:**
- small samples: 9 to 42 questions per row
- no human study
- no handwriting
- synthetic stand-ins for Arabic forms, certificates, invoices and contracts
- unit tests counted separately

#### Limits recorded for the 0.1.x builds

- **Scanned Egyptian registers, tax cards and VAT certificates are not supported in practice.** In an agent-run
  workflow evaluation on such documents (plus receipts, an NDA and UN letters), the tool completed at most 1 of 38
  tasks in any configuration (a correct "not in the document"); every other correct result was read off the page by
  the person. A corrected build (form labels never returned as values, several candidates listed, the documents you
  pass kept, rotated pages given structure) made failures safer but did not raise that number, with or without
  Docling structure. Details:
  [evaluation/AGENT_EVALUATION.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/evaluation/AGENT_EVALUATION.md).
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
- Current status by capability and language: [evaluation/CAPABILITIES.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/evaluation/CAPABILITIES.md). Every case, including failures:
  [evaluation/EVALUATION.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/evaluation/EVALUATION.md).

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
  OCRs a PDF page itself when its Arabic text layer is broken (a [measured heuristic](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/evaluation/CAPABILITIES.md#the-text-layer-detector-is-a-heuristic)).
- **Deterministic processing** does most of the work: it reads labels and layout in both directions, parses dates
  (including Arabic month names) and amounts, plans from your request, and computes sums exactly. It never sends
  text anywhere.
- **Document structure (optional)** comes from Docling's existing layout, reading-order and TableFormer models, run on
  Indra's stored lines with no second OCR. Table answers then come from the cell under the right heading, in the row
  of the person or item asked about ([how, and what it costs](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/docs/STRUCTURE.md)).
- **Optional models** are small and English-only. They are used where they measurably help, and skipped where they
  harm. Each result's `checks` says which ran.

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
pytest                                   # the full suite (about 900 tests)
ruff check src tests && mypy src
python -I bench/usecases/evaluate.py --help     # the evaluation above (documents: bench/usecases/README.md)
```

See [CONTRIBUTING.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/CONTRIBUTING.md), [CHANGELOG.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/CHANGELOG.md) and [CODE_OF_CONDUCT.md](https://github.com/MahmoudYahiaAhmed/inklight/blob/main/CODE_OF_CONDUCT.md).
