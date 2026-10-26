# Document structure: Docling on Indra's OCR

Optional. Off by default. Install it with `pip install "inklight[structure]"`, then turn it on in `config.toml`:

```toml
[structure]
engine = "docling"        # "none" (default) keeps Indra's own layout blocks
# The defaults below are the measured best without losing answers; see "Speed".
table_mode = "accurate"   # "fast": tables about 30% faster, one Arabic answer lost in the comparison
table_model = "tableformer"   # "tableformer_v2": faster, but lost two low-confidence flags
layout_runtime = "onnx"   # Heron as Docling's ONNX export; "torch" is the same model on PyTorch
pages = "all"             # "tables": only pages Indra's layout marked as table or form (misses ~half)
threads = 0               # 0 = every CPU core
# artifacts_path = "..."  # a local copy of Docling's model weights, for machines without network access
```

Each component keeps one job:

- **Indra** reads the text. It is the only OCR, and its lines are stored unchanged.
- **Docling** turns those lines into structure, using its existing components: the Heron layout model, reading
  order, headings, lists, pictures, and TableFormer for rows, columns, spans and header cells.
- **Inklight** does the rest: indexing, retrieval, answers, citations, review and the workspace.

## How Indra's text gets into Docling

Docling has no API for handing it OCR results directly. It does have a supported extension point for OCR:
- an OCR model class (`BaseOcrModel`), selected by its own options class;
- registered in Docling's OCR factory.

`inklight/structure/indra_ocr.py` implements such a model, `IndraLinesOcrModel`, which does **no recognition**:

1. For each page, it hands Docling the lines Inklight stored from Indra as `TextCell`s. Their boxes are scaled from
   Inklight's pixel frame to Docling's page units.
2. `OcrMode.FULL_PAGE` makes Docling use these cells only. Its own PDF text extraction is skipped
   (`resolve_skip_cell_extraction`).
3. A PDF is handed to Docling as images of its pages. With no text layer, TableFormer cannot match its cells to the
   PDF's own text, which it otherwise does. Without this step, Docling's tables on digital Arabic PDFs held the PDF
   layer's presentation-form letters (62 tokens Indra never read).
4. Docling's other components run unchanged: `DocumentConverter`, `StandardPdfPipeline`, the layout model,
   TableFormer with cell matching, reading-order assembly, `DoclingDocument`, and its exporters.
5. The engine is registered directly in Docling's OCR factory. Docling keeps `allow_external_plugins=False`, so no
   other third-party plugin is loaded.

**What is checked on every document** (stored with its structure; `inklight structure DOC --format meta` shows it):

- `cells_delivered`: Indra lines handed to Docling. This equals the stored lines with text and a box.
- `foreign_tokens`: words in Docling's output that are not in Indra's lines. It is 0 when Docling saw only Indra's
  text. A value above 0 would mean another text source.
- `orphan_lines`: Indra lines that no Docling item holds. These are kept as their own blocks, so no text
  disappears.
- `components`: the Docling, docling-core and Indra versions, the layout and table models, and the OCR path.

**Control experiment.** Replace every Indra line with a marker word. Docling's output is then the markers and
nothing else: no second OCR runs (`tests/test_structure_docling.py::test_docling_runs_no_ocr_of_its_own`).

## What Inklight keeps from Docling's structure

- **Original OCR, unchanged.** `PageContent.lines` keeps Indra's text, boxes and confidences.
- **Blocks follow Docling's reading order.** Each block has a `ref` back to its Docling item (`#/tables/0`). Its box
  is converted from Docling's coordinates (page units, either origin) to Inklight's top-left pixel frame.
- **The DoclingDocument itself** is stored per document (`structures` table). It is exported with Docling's own
  exporters:

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
- A cell Indra read with confidence below 0.85 is flagged.
- The citation is the cell, with its page and box.

These checks also apply without structure:

- An answer that only repeats the question's words ("اسم الشركة" for "ما اسم الشركة؟") is declined.
- An answer equal to a table heading is declined.
- **Citations are verified line by line.** An excerpt of several lines (a heading and its cell, a label and its
  value) passes when each line occurs in the document.
- **An answer whose every citation fails verification is not presented as supported.** It is prefixed
  "Unverified", flagged, and its confidence is capped at 0.2.

## Measured

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
- **OCR errors are not structure errors.** Indra misreads Arabic-Indic digits on these scans ("EVY19"). Docling
  cannot fix what was misread; Inklight flags it by Indra's line confidence.
- **Indra gives lines, not words.** A line spanning two table cells, such as an Arabic label and an English value
  read as one line, lands in one cell.
- **Pages Indra read turned** (90°, 180° or 270°) are given to Docling turned upright, so its boxes share the upright
  frame of Indra's lines (`inklight/frames.py`; recorded per document as `rotated_pages_structured`). A library
  structured before this change keeps Indra's layout on those pages until `inklight reindex`. A page whose frames
  still do not match is listed in `rotated_pages_kept` and keeps Indra's layout. On the evaluation's registers,
  structure on turned pages did not improve task completion (docs/AGENT_EVALUATION.md, AM-1).
- **Docling's HTML export leaves out text inside pictures**; there is no option for it. The Markdown export
  (pictures traversed), the JSON, and Inklight's own blocks keep that text. The CLI warns, and the server sets an
  `X-Inklight-Note` header.
- **Docling's `extract_form_fields`** reads native PDF form widgets only, so it is not used for scanned forms.
  Label-value pairs outside tables still come from Inklight's label reader (`agent/labels.py`).
- **Model weights** download from Hugging Face on Docling's first use, unless `artifacts_path` points to a local
  copy. No document leaves the machine.
- **Existing documents are not restructured automatically.** After turning structure on, run `inklight reindex`
  (or `process --force`). A new copy of a file read before structure was on is processed again, not copied.
- **With `privacy.store_text = false`:**
  - The structure's text (the DoclingDocument) is not stored, so table answers are off.
  - The stored `meta` holds only counts and versions.
  - Chunks keep their text as before, including the "header: value" rows used for search.
- **Docling runs one document at a time** in a process. Its `DocumentConverter` is not thread-safe, and its models
  are loaded once and kept.
- **Pages are rendered for Docling at 144 dpi**, one at a time, into a temporary image PDF; its images are
  JPEG-compressed.
- **A two-column table of three or more rows** whose first column (in reading order) is plain words, and whose other
  column holds a number, is read as fields and values, even when TableFormer marked its first row as a header. A
  two-row, two-column table reads either way; it is read as a heading over one row of values, so a two-field
  table ("Name | Acme / Tax number | 123") is misread.
- **Older Inklight versions** cannot add documents to a library this build has opened. Blocks gain a `ref` column
  and the search index is re-indexed (schema 4).
- **CI does not install Docling.** `tests/test_structure.py` runs everywhere: it uses fixed OCR and docling-core's
  data model. `tests/test_structure_docling.py` runs the real models where Docling is installed.

## Reproduce

```bash
pip install -e ".[structure,dev]"
python bench/structure/make_synthetic.py ./synthetic
python bench/structure/compare.py --docs ./synthetic --models PATH/TO/MODELS --out structure-compare.json \
    --baseline-src PATH/TO/030dd41/src     # optional: also run an unchanged checkout as A0
```

The stored result is `bench/results/structure/compare-synthetic.json`.
