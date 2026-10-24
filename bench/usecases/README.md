# Use-case evaluation

An automated evaluation of Inklight on general documents in English, Arabic and mixed language: letters,
contracts, reports, forms and certificates, invoices and receipts, as digital PDFs, scans and photographs.
It is small (65 documents) and is not a benchmark leaderboard. Every number in
[docs/EVALUATION.md](../../docs/EVALUATION.md) comes from these scripts.

| File | What it is |
|---|---|
| `corpus.json` | 65 documents in two splits, `dev` (35) and `reserved` (30), with expected results written **before** any build was run on them, plus library-level tasks |
| `evaluate.py` | Full pipeline on the original files, in a fresh library, scored per document, language, type and task |
| `summarize.py` | Tables from one or several runs, side by side |
| `retrieval_ablation.py` | Keyword-only versus hybrid retrieval on the same library |
| `make_synthetic.py` | Generates the **synthetic** Arabic and bilingual documents (certificate, invoice, form, lease, salary letter) |

## Rules the evaluation follows

- **Splits are grouped.** A UN document's English and Arabic versions, one company's receipts, a contract and
  a synthetic template never straddle the two splits. `dev` documents were used to find and fix failures.
  `reserved` documents were not looked at during development. Their first access is logged in
  `reserved-access.log` (time, build, arguments) before any file is read.
- **Expected results come from the sources:** dataset annotations (CUAD, FUNSD, CORU, INV-CDIP, Voxel51), the
  generator's own data (synthetic documents), or an AI reading the original file (UN documents, IRS forms,
  Wikipedia). They are never taken from an Inklight output.
- **Full pipeline.** Each run ingests the original files into an empty library with the build under test.
  `--save-hits` and `--replay-hits` make two runs see identical search results, to isolate the reader.
- **Every case is kept:** correct, correct but flagged for review, wrong but flagged, silently wrong,
  unsupported, failed. Nothing is dropped.

## Getting the documents

The files are not in the repository. Sources and licences are in `corpus.json` (`source`, `licence`). In
short:

| Group | Where | Licence / terms |
|---|---|---|
| UN letters, reports, agreement (English and Arabic, 1974–2024) | `https://documents.un.org/api/symbol/access?s=<symbol>&l=<en\|ar>&t=pdf` | UN official documents |
| CUAD contracts | Zenodo record 4595826, `CUAD_v1.zip` → `full_contract_pdf/` | CC BY 4.0 |
| FUNSD forms | `https://guillaumejaume.github.io/FUNSD/dataset.zip` → `testing_data/images` | non-commercial research |
| INV-CDIP invoices | `https://ucsf-idl-dataset.s3.us-east-1.amazonaws.com/<a>/<b>/<c>/<d>/<id>/<id>.pdf`, labels from INV-CDIP | UCSF Industry Documents Library, research use; INV-CDIP CC BY-NC 4.0 |
| CORU receipts (Egypt, Arabic and English) | Hugging Face `abdoelsayed/CORU`, `QA/test.zip` | MIT |
| Voxel51 invoices (**synthetic**) | Hugging Face `Voxel51/high-quality-invoice-images-for-ocr` | dataset card |
| IRS Forms W-9 and W-4 | `https://www.irs.gov/pub/irs-pdf/fw9.pdf`, `fw4.pdf` | US government work |
| Arabic Wikipedia "مصر", "القاهرة" | `https://ar.wikipedia.org/api/rest_v1/page/pdf/<title>` | CC BY-SA 4.0 |
| Synthetic Arabic and bilingual documents | `python -I bench/usecases/make_synthetic.py --out <folder>` | generated here; all names are fictional |

Put every file in one folder under the `file` name `corpus.json` gives it.

## Running

```bash
python -I bench/usecases/evaluate.py --split dev --docs <folder> --models <models dir> --out runs/dev-auto --brain auto
python -I bench/usecases/evaluate.py --split dev --docs <folder> --models <models dir> --out runs/dev-rules --brain rules --save-hits runs/dev-hits.json
python -I bench/usecases/evaluate.py --split dev --docs <folder> --models <models dir> --out runs/dev-replay --brain auto --replay-hits runs/dev-hits.json
python -I bench/usecases/summarize.py runs/dev-auto/usecases.json runs/dev-rules/usecases.json
python -I bench/usecases/retrieval_ablation.py --library runs/dev-auto/home --models <models dir>
```

`<models dir>` holds `indra/` (the OCR models) and `small/` (the reader and embedder), as written by
`pilot/freeze.py freeze --models-out`. Run the scripts with the interpreter of the build you are measuring.
