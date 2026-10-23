# External evaluation results

Produced by `bench/external.py` and summarised by `bench/summarize_external.py`. Methods and conclusions are in
[docs/BENCHMARKS.md](../../../docs/BENCHMARKS.md#external-datasets).

| Prefix | Meaning |
|---|---|
| `base-*` | dev-split baseline, saved before any change (A = PyPI 0.1.0, B = `d0fac3d`) |
| `fix1-C-*`, `fix2-D-*` | dev split after each round of fixes |
| `final-*` | holdout run once at the end (A, B, F) plus the final build on dev (F = `05206d7`) |
| `prefinal-E-*` | build `2f07058`, identical results to F; superseded because F added a request-planning fix |
| `unplanned-D-*` | an intermediate build's holdout run started by mistake and not read before the final run |
| `diagnostic-reftext-*` | the dataset's own flattened text instead of OCR: a diagnostic, not the pipeline |
| `final_tables.md`, `baseline_tables.md` | generated tables |

Each JSON records provenance (interpreter, `inklight.__file__`, install method, wheel sha256, commit), ONNX
Runtime calls per model, `Brain.usage()` where available, and one row per scored value (document file name,
annotated value, extracted value, method, warning, confidence, outcome).

## Data sources and licences

The rows contain annotation values derived from these datasets. The document images themselves are not
included.

- **Voxel51/high-quality-invoice-images-for-ocr** (synthetic invoices), Open Database License (ODbL) 1.0,
  <https://huggingface.co/datasets/Voxel51/high-quality-invoice-images-for-ocr>. The derived values in
  these files are made available under the ODbL.
- **CORD v2** (receipts), Clova AI / NAVER, CC BY 4.0, <https://huggingface.co/datasets/naver-clova-ix/cord-v2>.
  Park et al., "CORD: A Consolidated Receipt Dataset for Post-OCR Parsing", 2019.
