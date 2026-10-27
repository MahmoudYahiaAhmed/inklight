<p align="center">
  <img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/assets/logo.svg" width="84" alt="Inklight logo">
</p>

<h1 align="center">Inklight</h1>

<p align="center"><b>A local document workspace for Arabic, English and mixed documents.</b><br>
Extract text, tables and named fields from scans and PDFs, search them, check each value against its place on the
page, and export what you approved, on your own computer.</p>

<p align="center">
  <a href="https://github.com/MahmoudYahiaAhmed/inklight/actions/workflows/ci.yml"><img alt="ci" src="https://github.com/MahmoudYahiaAhmed/inklight/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="status" src="https://img.shields.io/badge/status-developer%20beta%200.3.0b2-F5B544?style=flat-square&labelColor=0B0F14">
  <img alt="python" src="https://img.shields.io/badge/python-3.11%2B-22D3EE?style=flat-square&labelColor=0B0F14">
  <img alt="license" src="https://img.shields.io/badge/code-Apache--2.0-F5B544?style=flat-square&labelColor=0B0F14">
</p>

<p align="center"><img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/images/workspace-fields.png" width="900" alt="The Inklight workspace: a synthetic registration certificate scanned sideways, with the company name read at its label and its source outlined on the page as the file shows it."></p>

Everything Inklight shows is either **what was read** (text, boxes, tables and search matches, each linked to its
place on the page) or **a value for you to check**. Documents are read on your computer and never uploaded.

> **Developer beta (0.3.0b2).** For developers and careful users who check results against the page; see
> [Limitations](#limitations). It is a pre-release, so pip needs `--pre` or the exact version; a plain
> `pip install inklight` installs the older 0.1.0.

## Install and launch

Python 3.11 or newer, on Windows, Linux or macOS, CPU only:

```bash
pip install --pre "inklight[structure]"
```

```bash
inklight serve
```

The workspace opens at http://127.0.0.1:8765. The first time a document is read, Inklight downloads its OCR models
(76 MB) with a progress bar. The first time tables are extracted, it downloads the document structure models (384 MB).
Each file is checked against a pinned SHA-256, an interrupted download resumes, and after that everything works
offline (set `INKLIGHT_OFFLINE=1` to make sure nothing is fetched). `inklight models pull --structure` fetches
everything ahead of time; `inklight doctor` checks the installation. Without `[structure]` the install is smaller and
everything except table extraction works.

## The workspace

Choose an operation at the top, open a document from the library on the left (click its name; tick its box to use
several in one operation), and the page opens on the canvas in the middle with the result beside it. The marks on the
page say what they are: a detected region, a search match, the source of a value, or a value to check; the readout
under the page gives the marked box's page coordinates. Dark and light themes (or the system's), keyboard use,
screen-reader announcements and reduced motion are supported. Motion follows what the server reports: bytes uploaded,
pages read, regions found, rows loaded; a stage it cannot measure is shown as running, never as a percentage.

**Import.** Drop files on *Add documents*. Each file has a timeline of what the server reports: upload, waiting, OCR
(with each page as it finishes), structure, stored, or the stage where it failed and why. The file being read is shown
under a scan line; it marks nothing on the page until the reading is stored. *Stop after the
current file* stops the import before its next file. A reloaded page finds a running import again.

<img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/images/workspace-import.png" width="760" alt="An import of four files: the first being read by OCR under a scan line over its first page, three waiting; each file shows a timeline of upload, waiting, OCR and stored.">

**Extract text.** The text of the open document page by page, in reading order, beside the page. Arabic is right
to left and every line keeps its own direction. The downloads (`.txt`, and `.json` with boxes) are the raw reading
and say so. This is what the OCR read, not a verified copy: on this synthetic Arabic card the Arabic-Indic digits are
misread (٤٧٣١٩ is read as `EVY19`).

<img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/images/workspace-text.png" width="760" alt="A synthetic Arabic registration certificate with its text in reading order on the right; the registration number is misread as EVY19.">

**Extract tables.** Rows, columns and header cells recovered by document structure; *Show on page* outlines the table.
A document read without structure can be read again with it from here.

<img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/images/workspace-tables.png" width="760" alt="Two tables from a synthetic suppliers sheet; the second is outlined on the page.">

**Extract fields.** Name the values you want ("company name, registration number"). Each is read where it is printed
next to its label and keeps its page and box; choose a value to see its source (above, on a page scanned sideways).
A value with a warning is marked *check*; a value not found says *not found*. **Search** finds passages in Arabic or
English and opens each match at its place.

<img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/images/workspace-search.png" width="760" alt="Search for السجل التجاري: one match, highlighted in yellow on the synthetic Arabic card.">

**Review and export.** Name the fields, then accept, correct or mark each value absent, and approve. The OCR reading
is kept next to your decision. *Download approved values* exports only approved reviews, one row per field with the
extracted value, the decision, who approved it and its source page and box. A document reviewed again keeps its
earlier rows, marked `superseded`.

<img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/images/workspace-review.png" width="760" alt="A review of two fields on the turned card: the company name corrected to add 'Co.', the tax office accepted, ready to approve; the reviewer's name is shown with the decisions.">

**Ask (experimental).** A question in plain words. Every result says what it is (*extracted text*, *proposed
answer*, *supported answer* at a printed label, *partial*, *missing evidence*, *several candidates* or *failed*) and
cites where it read. Treat every answer as a lead to check.

<img src="https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/docs/images/workspace-light.png" width="760" alt="The light theme: a synthetic Arabic card with its detected regions, and Ask marked experimental.">

The screenshots show synthetic documents and public UN letters, from the running workspace.

## Command line

The examples use three synthetic documents from this repository's [examples/](examples/README.md) folder. They
are not installed with the package; download them (on Windows PowerShell, type `curl.exe`):

```bash
curl -L --remote-name-all https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/examples/documents/invoice_initech_scan.png https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/examples/documents/suppliers.pdf https://raw.githubusercontent.com/MahmoudYahiaAhmed/inklight/main/examples/documents/registration-card-turned.pdf
```

```bash
inklight text invoice_initech_scan.png
inklight tables suppliers.pdf -o tables.csv
inklight extract registration-card-turned.pdf --fields "company name, tax office"
inklight search "Golden Palm"
inklight review export --actor "Your name" -o approved.csv
```

`text` and `tables` read the file (once; the library keeps it) and print or save the result. `extract` needs the
fields to read; no schema is assumed. `inklight --help` lists the rest: the library (`process`, `docs`, `show`,
`remove`), setup (`doctor`, `models`) and the experimental `ask`.

## Python

```python
from inklight import DocumentAgent

with DocumentAgent(structure={"engine": "inklight"}) as agent:
    print(agent.text("invoice_initech_scan.png"))
    for table in agent.tables("suppliers.pdf"):
        print(table["page"], table["rows"])
    record = agent.extract(["registration-card-turned.pdf"], fields=["company name"])[0]
    value = record.fields["company_name"]
    print(value.value, value.source.page, value.source.bbox)
    for hit in agent.search("Golden Palm"):
        print(hit.source.name, hit.source.page)
```

`DocumentAgent()` without `structure` reads text and fields; `tables()` then says how to turn structure on.
[examples/quickstart.py](examples/quickstart.py) runs the same steps from a checkout.
The HTTP API is documented at `/api/docs` while `inklight serve` runs, and in [docs/API.md](docs/API.md).

## What is supported

| | Status |
|---|---|
| Import (PDF, scans, photos, text), with each file's progress and errors; rotated pages | supported |
| Extract text, page by page, Arabic, English and mixed | supported; **Arabic-Indic digits are often misread** |
| Extract tables (rows, columns, header cells) | supported with `[structure]` |
| Extract named fields, each with its page and box | supported; values are proposals to check |
| Search across documents, opening each match on its page | supported |
| Review, approval and export of approved values; raw exports | supported |
| Ask: questions, comparisons, candidates | **experimental** |
| A remote language model for Ask | off by default; not part of the supported workflow |

## Limitations

- **OCR misreads.** Arabic-Indic digits are often misread (every number on the synthetic Arabic card), and so are
  stamps. The OCR confidence is the reader's own estimate. It does not guarantee the text, and the text and table
  views do not mark doubtful cells (fields and review do).
- **Field values can be wrong without a warning**: a value that wraps onto a second line can be cut short ("Golden
  Palm Trading" for "Golden Palm Trading Co."), and a number printed apart from its label can be missed. Review is
  where they are corrected.
- **Turned pages**: text, tables and sources are placed on the page as the file shows it, but a table cell can be
  split differently from an upright scan.
- **Ask on real scans is weak.** On scanned business registers and certificates, questions mostly end as *missing
  evidence*, *cannot determine*, or a proposed passage that is not the answer.
- **Classification** (letter, invoice, certificate …) is keyword-based and often wrong. No handwriting.

## How it works

```
file ─► Inklight OCR ─────────────► text lines with boxes ─► search index, fields, review
        PDF text layer where sound,          │
        OCR elsewhere; page orientation      └─► Inklight document structure (optional):
                                                  layout, tables, reading order on those lines
```

- **Inklight OCR** detects and recognises text lines (Latin, Arabic and other scripts), finds each page's
  orientation and reading order, and keeps a PDF's own text layer where it is sound. It runs with ONNX Runtime.
- **Inklight document structure** finds layout regions, recovers tables (rows, columns, spans, headers) and orders
  them, using the OCR's lines as its text, so nothing is read twice. It runs with ONNX Runtime (layout) and PyTorch
  (tables).
- **Models** are downloaded from Hugging Face at pinned revisions and checked by hash; `inklight models status`
  shows where each one is. The OCR models come from `datalab-to/indra-ocr`, the layout model from
  `docling-project/docling-layout-heron-onnx` and the table model from `docling-project/docling-models`; the code
  that runs them is in `src/inklight/backends/`, with each source project's license.
- **Fields and answers** are read deterministically from labels, layout and tables. Optional small English models
  (`inklight models pull`) help English search and Ask only.
- **Your library** (documents read, reviews, exports) is stored in `~/.inklight`, outside the Python environment, so
  every installation opens the same library; `inklight serve` prints its folder. Set `INKLIGHT_HOME` to use another
  folder, for example a fresh one to try Inklight. Nothing is added to it until you import a document.
- **Configuration**: `~/.inklight/config.toml` (see [config.example.toml](config.example.toml)) or environment
  variables such as `INKLIGHT_LIMITS__MAX_PAGES=50`. Security: text inside documents is treated as data, never as
  instructions, and the workspace accepts requests only from this computer ([SECURITY.md](SECURITY.md)).

## Evaluation

**[Technical report](evaluation/REPORT.md)** ([printable HTML](evaluation/REPORT.html)): what Inklight 0.3 is, what
was measured on the current build, a comparison with five document parsers using only their published numbers
(Inklight has run no public parsing benchmark), selected examples and failures.

The measurements behind earlier releases, with every failure, are in [evaluation/](evaluation/README.md): an
agent-run workflow evaluation on scanned business documents (the tool completed at most 1 of 38 tasks), question
answering on 90 documents, and external receipt and invoice datasets. They were taken before the OCR and structure
models ran inside Inklight. The same models on 17 documents gave identical OCR, identical tables, and the same
answers on the synthetic structure benchmark; see [CHANGELOG.md](CHANGELOG.md).

## License notice: read before commercial use

Inklight's code is **Apache-2.0**. The **OCR model weights** (downloaded on first use, not bundled) use a **modified
OpenRAIL-M license**. They are free for research, personal use, and organisations under $20M revenue and under $20M
funding, and they restrict commercial use that competes with Datalab. Full audit:
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

## Development

```bash
pip install -e ".[structure,dev]"
pytest
ruff check src tests && mypy src
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).
