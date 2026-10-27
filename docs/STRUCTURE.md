# Document structure

Optional. Install it with `pip install "inklight[structure]"`. `inklight tables FILE`, and *Extract tables* in the
workspace, turn it on for their own run. To structure every import, set it in `config.toml`:

```toml
[structure]
engine = "inklight"       # "none" (default) keeps the OCR's own layout blocks
table_mode = "accurate"   # "fast": tables about 30% faster, one Arabic answer lost in the comparison below
pages = "all"             # "tables": only pages the OCR's layout marked as table or form (misses about half)
threads = 0               # 0 = every CPU core
```

Each component keeps one job:

- **Inklight OCR** reads the text. It is the only OCR, and its lines are stored unchanged.
- **Inklight document structure** turns those lines into structure: layout regions (text, headings, lists,
  pictures, captions, tables), reading order, and each table's rows, columns, spans and header cells.
- The rest of Inklight does indexing, retrieval, answers, citations, review and the workspace.

## How it runs

`inklight/structure/run.py` hands the stages in `inklight/backends/structure/` each page and its OCR lines:

1. **The page image.** A PDF page is rendered at 144 dpi; an image file's frame is used as stored. A page the OCR
   read turned (90, 180 or 270 degrees) is turned upright first, so its boxes share the OCR's upright frame.
2. **The text cells** are the page's OCR lines, scaled from Inklight's pixel frame to the page's size in points. No
   other text is read: a PDF's own text layer is not used here.
3. **Layout**: the Heron layout model (an RT-DETR v2 detector, run as ONNX with ONNX Runtime) on the page at 72 dpi.
   Its preprocessing (a bilinear, antialiased resize to 640 x 640) reproduces the model's own image processor
   exactly. Detections under a score of 0.3 are dropped.
4. **Layout post-processing** assigns the text cells to regions, resolves overlaps and keeps every cell (orphan cells
   get regions of their own).
5. **Tables**: TableFormer (PyTorch) on each table region at 144 dpi, its predicted cells matched to the text cells.
6. **Page assembly and reading order** order the regions and build the document (docling-core's `DoclingDocument`
   format), which is stored with the document.

The code of steps 3 to 6 is taken from Docling 2.142.1 and docling-ibm-models 4.0.4, cut down to what this path runs,
and kept close to its source so it can be compared line by line; the model files are pinned in
`inklight/modelstore.py`. Before the change, Inklight ran the same models through the `docling` package. On 17
documents, the tables were identical. The OCR was identical too, as were 3 image files end to end. On PDFs, some
layout block boundaries differ, because Docling's own PDF rasteriser is not reproduced bit for bit
([CHANGELOG](../CHANGELOG.md), 0.3.0b1).

**What is checked on every document** (stored with its structure; `inklight structure DOC --format meta` shows it):

- `cells_delivered`: OCR lines handed over as text cells. This equals the stored lines with text and a box.
- `foreign_tokens`: words in the structure that are not in the OCR's lines. A value above 0 would mean another text
  source.
- `orphan_lines`: OCR lines that no structure item holds. These are kept as their own blocks, so no text
  disappears.
- `components`: the layout and table models with their pinned revisions.

**Control experiment.** Replace every OCR line with a marker word. The structure then holds the markers and nothing
else: no second OCR runs (`tests/test_structure_models.py::test_structure_runs_no_ocr_of_its_own`).

## What Inklight keeps from the structure

- **Original OCR, unchanged.** `PageContent.lines` keeps the OCR's text, boxes and confidences.
- **Blocks follow the structure's reading order.** Each block has a `ref` back to its item (`#/tables/0`). Its box
  is converted from the structure's coordinates (points, either origin) to Inklight's top-left pixel frame.
- **The structured document itself** is stored per document (`structures` table), in docling-core's format, and
  exported with docling-core's exporters:

  ```bash
  inklight structure invoice.pdf --format md|json|html|meta
  ```

  The same exports are available at `GET /api/documents/{id}/structure?format=...`.
- **Tables are searched as rows of named values.** A row reads "Company name: Golden Palm Trading Co. | Company
  type: …", so search and answers see which header a value belongs to. The cells stay in the stored document.
  This is derived text: the printed text is in `lines` and in the cells.
- **Text inside pictures** becomes `Picture-Text` blocks, which are searched like any text.

## Answers from table cells

`agent/table_answer.py` uses the table's cells:

| Question | Read from |
|---|---|
| "What is the company name?" / "ما اسم الشركة؟" | The value in the column whose header names the field, never the header itself. |
| "What is Laila Mansour's share?" / "ما نسبة مشاركة ليلى منصور؟" | The row holding the question's other words. With several rows and nothing to choose, every row's value is listed and none is picked. |
| "Who is the manager?" | The name cell of the row whose cell matches the question. |
| A field/value table ("Field \| البيان \| Value") | The value beside the row's label, in reading direction. |

More rules:

- Merged headers are read as "Contribution / Amount".
- Generic words break ties: "Company type" beats "Company name" for "the company type".
- Header qualifiers follow the label rules: "Tax registration number" does not answer "the registration number".
- A blank cell is declined as a blank field.
- A date that does not read as a date is declined.
- A cell the OCR read with confidence below 0.85 is flagged.
- The citation is the cell, with its page and box.

Field extraction uses the same reading (`agent/field_reader.py`), so `extract(fields=["registration number"])` and
"What is the registration number?" give the same cell:

- A field the typed extractor leaves empty is read at its printed label or table cell, with that cell as its source.
  It must parse as the field's type (a date, an amount, an id with a digit); a passage is never used.
- A value the typed extractor paired with its label by position across lines (under a heading, along a row) yields
  to the table's own cell. When the heading has several cells (one per partner, one per supplier table), the
  value is kept only if it is one of them, and every candidate is named in the field's warning.
- Any other difference between the typed value and the table cell is flagged for review, never resolved silently.
  A printed label outside a table fills an empty field but does not override or flag a typed value: on invoices
  and receipts the typed extractor reads labels better.

These checks also apply without structure:

- An answer that only repeats the question's words ("اسم الشركة" for "ما اسم الشركة؟") is declined.
- An answer equal to a table heading is declined.
- **Citations are verified line by line.** An excerpt of several lines (a heading and its cell, a label and its
  value) passes when each line occurs in the document.
- **An answer whose every citation fails verification is not presented as supported.** It is prefixed
  "Unverified", flagged, and its confidence is capped at 0.2.

## Measured

The measurements below were taken when the same models ran through the `docling` package (2.142.1), with
the OCR through `indra-ocr` 1.1.2. The synthetic comparison was repeated after the change and gave the same answer
on every question.

### Synthetic registration cards

Measured with `bench/structure/compare.py`. The cards are made by `bench/structure/make_synthetic.py`:
fictional companies and people, in Arabic (right to left), English and mixed. Each comes as a scan and as a
digital PDF, with column headings over values, a two-person partners table, a tax table and a stamp. The
expectations (`bench/structure/cases.json`) were written from the generator's text before any run.

Each document was read once by Indra (1.1.2, models of the pilot), and all three arms used that same OCR, in rules
mode:

- **A0**: Inklight `030dd41`, unchanged.
- **A**: this build, structure off.
- **B**: this build with Docling 2.142.1: Heron layout, TableFormer accurate, no Docling OCR.

| Answerable questions | A0 | A | B |
|---|---|---|---|
| Arabic (18): correct | 0 | 0 | **10** |
| Arabic: declined / wrong, flagged / silent wrong | 2 / 16 / 0 | 16 / 2 / 0 | 2 / 6 / 0 |
| English (18): correct (flagged) | 2 (2) | 2 (2) | **18** (0) |
| English: declined / wrong, flagged / silent wrong | 1 / 2 / 13 | 9 / 2 / 5 | 0 / 0 / 0 |
| Mixed (10): correct (flagged) | 6 (2) | 6 (3) | **10** (3) |
| Mixed: silent wrong | 4 | 3 | 0 |
| A correct answer's citation holds the value | 5 / 8 | 8 / 8 | 38 / 38 |

**Where B is wrong, the OCR is wrong.** All 6 Arabic wrong answers, and both declines, come from cells Indra
misread. The text Indra stored never contains the right value:

- "EVY19" for ٤٧٣١٩;
- "72." for ٤٠٪;
- "8.7-11-08." for ٥٢٠-٨٨١-٣٠٦;
- "11/V/V-48" for a date (declined: it does not read as a date).

All six are now flagged: their cells were read with confidence 0.63–0.82, against 0.86–0.99 for the right ones.

**Unanswerable questions.** "What is the company's capital?" is answered silently in every arm; it is not printed.
The Arabic one is flagged in every arm.

**Cost**: see [Speed](#speed) for the current defaults. Questions cost the same with or without structure (4 ms
median). With structure, peak memory is about 1.1–1.2 GB against 56 MB. The install adds PyTorch and Docling, and
about 0.7 GB of weights: Heron 164 MB, its ONNX export 164 MB, TableFormer 342 MB.

## Speed

**Measured where the time goes** with Docling's own per-stage profiler (16-core CPU, Windows, torch 2.14.1; Indra's
OCR excluded, stored and replayed).

| | Before (`13cd9a4`) | Now |
|---|---|---|
| Registration card, 1 page, 3 tables | 3.0 s | **1.4 s** |
| 9 pages, 21 tables | 15.5 s | **10.1 s** |
| Loading the models, once per process | 5.5 s | 4.6 s, during Indra's OCR of the first document |
| 7 files, 15 pages, end to end with OCR (fresh process) | 35.6 s | **28.9 s** |

- **What changed:**
  - All CPU cores are used: `threads = 0`, where it was 4.
  - The Heron layout model runs as Docling's ONNX export.
  - The models load in the background while Indra reads the first document.
  - Docling structures one document while Indra reads the next.
- **Answers are unchanged.** The comparison above gives the same result with these defaults.
- **What is left is TableFormer**, about 0.45 s per table here; it is 95% of a table-heavy page. Indra's OCR of all
  15 pages took 3 s.
- **Faster options cost answers**, so they are off by default:

| Option | 9 pages, 21 tables | Effect in the comparison |
|---|---|---|
| `table_mode = "fast"` | 7.3 s | One Arabic answer lost: a right-to-left table split wrongly |
| `table_model = "tableformer_v2"` | 8.4 s | Two answers built on Indra's misreads lost their low-confidence flag |
| `pages = "tables"` | only the pages Indra marked | On the 384 development pages, Indra's layout marked 43 of the 80 pages where Docling found tables |
| `batch_size` 9 or 16 | 13.3–14.0 s | No gain |

- **On mixed documents**, most pages have no table. Docling with these defaults took 1.15 s per page on the 384
  development pages (442 s).
- **The server keeps the models loaded.** Each CLI command loads them once.

**Export.** Every Indra line of every document was found in Docling's Markdown export of its structure, with
pictures traversed.

### The existing development corpus (structure off)

473 questions, dev to fresh4, compared with `030dd41` on the same stored libraries:

- **Models on:** no correct answer lost. One correct answer is now flagged: an OCR-garbled Arabic density value
  Indra read with low confidence. 4 wrong answers (3 of them silent) became declined or flagged.
- **Rules only:** no correct answer lost. Silent errors became declined or flagged in 5 cases. One of them is now
  marked "Unverified" because its only citation could not be found in the document.

Structure was not run on that corpus: it would need the documents to be processed again with Docling.

## Not done, or not reproduced

- **The private nine-page tax card and commercial registration PDF, and its comparison bundle, were not
  available.** The reported failures were reproduced on the synthetic cards instead:
  - column headings returned as the company name and type;
  - irrelevant passages for the English company name and registration number;
  - a registration number answered from another column;
  - a contract-like document type.

  The real document's results are unknown.
- **OCR errors are not structure errors.** The OCR misreads Arabic-Indic digits on these scans ("EVY19"). The
  structure cannot fix what was misread; Inklight flags it by the OCR's line confidence.
- **The OCR gives lines, not words.** A line spanning two table cells, such as an Arabic label and an English value
  read as one line, lands in one cell.
- **Pages the OCR read turned** (90°, 180° or 270°) are structured turned upright, so their boxes share the upright
  frame of the OCR's lines (`inklight/frames.py`; recorded per document as `rotated_pages_structured`). A page whose
  frames still do not match is listed in `rotated_pages_kept` and keeps the OCR's layout. On the evaluation's registers,
  structure on turned pages did not improve task completion (evaluation/AGENT_EVALUATION.md, AM-1).
- **The HTML export (docling-core's) leaves out text inside pictures**; there is no option for it. The Markdown export
  (pictures traversed), the JSON, and Inklight's own blocks keep that text. The CLI warns, and the server sets an
  `X-Inklight-Note` header.
- **Form widgets** of digital PDFs are not read; label-value pairs outside tables come from Inklight's label reader
  (`agent/labels.py`).
- **Model weights** (layout 171 MB, tables 213 MB) download from Hugging Face at pinned revisions the first time
  structure runs, checked by SHA-256 (`inklight models pull --structure` fetches them ahead). No document leaves
  the machine.
- **A document read before structure was turned on** is read again, with its structure, the next time it is added
  with structure on (`inklight tables`, *Extract tables*, or `inklight process` with structure on).
- **With `privacy.store_text = false`:**
  - The structure's text (the stored document) is not stored, so table answers are off.
  - The stored `meta` holds only counts and versions.
  - Chunks keep their text as before, including the "header: value" rows used for search.
- **One document is structured at a time** in a process; the models are loaded once and kept.
- **PDF pages (and turned image frames) are prepared as before the change**: a 144 dpi render stored as JPEG, seen at 72 dpi as an area average
  (layout) and at 144 dpi as a bilinear resize of that (tables).
- **A two-column table of three or more rows** whose first column (in reading order) is plain words, and whose other
  column holds a number, is read as fields and values, even when TableFormer marked its first row as a header. A
  two-row, two-column table reads either way; it is read as a heading over one row of values, so a two-field
  table ("Name | Acme / Tax number | 123") is misread.
- **Older Inklight versions** cannot add documents to a library this build has opened. Blocks gain a `ref` column
  and the search index is re-indexed (schema 4).
- **CI does not install the structure runtime.** `tests/test_structure.py` runs everywhere: it uses fixed OCR and
  docling-core's data model. `tests/test_structure_models.py` runs the real models where PyTorch is installed.

## Reproduce

```bash
pip install -e ".[structure,dev]"
python bench/structure/make_synthetic.py ./synthetic
python bench/structure/compare.py --docs ./synthetic --models PATH/TO/MODELS --out structure-compare.json \
    --baseline-src PATH/TO/030dd41/src     # optional: also run an unchanged checkout as A0
```

The stored result is `evaluation/results/structure/compare-synthetic.json`.
