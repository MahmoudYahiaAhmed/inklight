# bench/results/capability-diag-baseline4.json

AUTOMATED DIAGNOSTIC, not a benchmark; C:\Users\pc\inklight-pilot-b4\venv\Lib\site-packages\inklight\__init__.py

## OCR mode `auto`: ingest 43.7 s, failed 0

| lang | type | modality | docs | ingested | type ok | key strings | word recall | search @1 | search @3 | QA | QA + source | summary in language | summary intent | fields | review opened |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ar | contract | scan | 1 | 1/1 | 0/1 | 0.33 | – | 1/1 | 1/1 | 0/3 | 0/3 | 0/1 | 0/1 | 1/1 | 1/1 |
| ar | letter | digital | 1 | 1/1 | 0/1 | 0.00 | – | 1/2 | 1/2 | 0/3 | 0/3 | 0/1 | 0/1 | 0/1 | 1/1 |
| ar | letter | scan | 1 | 1/1 | 0/1 | 0.33 | – | 1/2 | 1/2 | 0/3 | 0/3 | 0/1 | 0/1 | 0/1 | 1/1 |
| ar | report | digital | 1 | 1/1 | 0/1 | 0.33 | – | 2/2 | 2/2 | 0/3 | 0/3 | 1/1 | 0/1 | 1/1 | 1/1 |
| ar | report | scan | 1 | 1/1 | 0/1 | 0.67 | – | 2/2 | 2/2 | 0/3 | 0/3 | 0/1 | 0/1 | 0/1 | 1/1 |
| en | contract | digital | 2 | 2/2 | 2/2 | 1.00 | – | 2/2 | 2/2 | 3/6 | 3/6 | 2/2 | 2/2 | 1/4 | 2/2 |
| en | contract | scan | 1 | 1/1 | 1/1 | 1.00 | – | 1/1 | 1/1 | 0/3 | 0/3 | 1/1 | 1/1 | 1/1 | 1/1 |
| en | form | digital | 1 | 1/1 | 0/1 | 1.00 | – | 1/1 | 1/1 | 1/3 | 1/3 | 1/1 | 1/1 | 1/2 | 1/1 |
| en | form | scan | 2 | 2/2 | 0/2 | 1.00 | 0.96 | 2/2 | 2/2 | 1/6 | 1/6 | 2/2 | 2/2 | 3/4 | 2/2 |
| en | invoice | image-synthetic | 2 | 2/2 | 2/2 | 1.00 | 0.98 | 2/2 | 2/2 | 6/6 | 6/6 | 2/2 | 2/2 | 6/6 | 2/2 |
| en | invoice | scan | 2 | 2/2 | 2/2 | 0.67 | – | 2/2 | 2/2 | 2/6 | 2/6 | 2/2 | 2/2 | 4/6 | 2/2 |
| en | letter | digital | 1 | 1/1 | 0/1 | 1.00 | – | 1/1 | 1/1 | 2/3 | 1/3 | 1/1 | 1/1 | 1/1 | 1/1 |
| en | letter | scan | 1 | 1/1 | 0/1 | 1.00 | – | 1/1 | 1/1 | 0/3 | 0/3 | 1/1 | 1/1 | 1/1 | 1/1 |
| en | receipt | photo | 2 | 2/2 | 2/2 | 1.00 | – | 2/2 | 2/2 | 2/6 | 2/6 | 2/2 | 2/2 | 2/4 | 2/2 |
| en | report | digital | 1 | 1/1 | 1/1 | 1.00 | – | 1/1 | 1/1 | 1/3 | 1/3 | 1/1 | 1/1 | 1/1 | 1/1 |
| en | report | scan | 1 | 1/1 | 0/1 | 1.00 | – | 1/1 | 1/1 | 0/3 | 0/3 | 1/1 | 1/1 | 0/1 | 1/1 |
| mixed | receipt | photo | 4 | 4/4 | 1/4 | 0.92 | – | 3/5 | 5/5 | 4/12 | 4/12 | 4/4 | 4/4 | 3/7 | 4/4 |

export: {"rows": 43, "columns": ["review_id", "document", "doc_sha256", "cohort", "mode", "baseline", "field", "predicted", "predicted_raw", "confidence", "method", "warning", "flagged", "final", "entered_input", "action", "decided_by", "approved_by", "approved_at"], "all_custom_fields_exported": true, "arabic_values_exported": false}
brain usage: {"reader": {"loaded": true, "inference_calls": 459, "fallback_reason": null}, "embedder": {"loaded": true, "inference_calls": 141, "fallback_reason": null}, "writer": {"loaded": false, "inference_calls": 0, "fallback_reason": null}}
ONNX calls: {"indra/orient.onnx": 69, "indra/det.onnx": 138, "indra/script.onnx": 544, "indra/rec.onnx": 321, "indra/rec_world.onnx": 22, "indra/rec_cjk.onnx": 30, "indra/order.onnx": 121, "indra/rec_rtl.onnx": 156, "onnx/model_int8.onnx": 600}

## OCR mode `ocr`: ingest 58.1 s, failed 0

| lang | type | modality | docs | ingested | type ok | key strings | word recall | search @1 | search @3 | QA | QA + source | summary in language | summary intent | fields | review opened |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ar | contract | scan | 1 | 1/1 | 0/1 | 0.33 | – | 0/1 | 1/1 | 0/3 | 0/3 | 0/1 | 0/1 | 1/1 | 1/1 |
| ar | letter | digital | 1 | 1/1 | 0/1 | 1.00 | – | 1/2 | 2/2 | 1/3 | 1/3 | 0/1 | 0/1 | 0/1 | 1/1 |
| ar | letter | scan | 1 | 1/1 | 0/1 | 0.33 | – | 0/2 | 1/2 | 0/3 | 0/3 | 0/1 | 0/1 | 0/1 | 1/1 |
| ar | report | digital | 1 | 1/1 | 0/1 | 1.00 | – | 2/2 | 2/2 | 1/3 | 1/3 | 1/1 | 0/1 | 1/1 | 1/1 |
| ar | report | scan | 1 | 1/1 | 0/1 | 0.67 | – | 2/2 | 2/2 | 0/3 | 0/3 | 0/1 | 0/1 | 0/1 | 1/1 |
| en | contract | digital | 2 | 2/2 | 2/2 | 1.00 | 1.00 | 2/2 | 2/2 | 3/6 | 3/6 | 2/2 | 2/2 | 1/4 | 2/2 |
| en | contract | scan | 1 | 1/1 | 1/1 | 1.00 | – | 1/1 | 1/1 | 0/3 | 0/3 | 1/1 | 1/1 | 1/1 | 1/1 |
| en | form | digital | 1 | 1/1 | 0/1 | 1.00 | 0.99 | 1/1 | 1/1 | 1/3 | 1/3 | 1/1 | 1/1 | 1/2 | 1/1 |
| en | form | scan | 2 | 2/2 | 0/2 | 1.00 | 0.96 | 2/2 | 2/2 | 1/6 | 1/6 | 2/2 | 2/2 | 3/4 | 2/2 |
| en | invoice | image-synthetic | 2 | 2/2 | 2/2 | 1.00 | 0.98 | 2/2 | 2/2 | 6/6 | 6/6 | 2/2 | 2/2 | 6/6 | 2/2 |
| en | invoice | scan | 2 | 2/2 | 2/2 | 0.67 | – | 2/2 | 2/2 | 2/6 | 2/6 | 2/2 | 2/2 | 4/6 | 2/2 |
| en | letter | digital | 1 | 1/1 | 0/1 | 1.00 | 0.99 | 1/1 | 1/1 | 2/3 | 1/3 | 1/1 | 1/1 | 1/1 | 1/1 |
| en | letter | scan | 1 | 1/1 | 0/1 | 1.00 | – | 1/1 | 1/1 | 0/3 | 0/3 | 1/1 | 1/1 | 1/1 | 1/1 |
| en | receipt | photo | 2 | 2/2 | 2/2 | 1.00 | – | 2/2 | 2/2 | 2/6 | 2/6 | 2/2 | 2/2 | 2/4 | 2/2 |
| en | report | digital | 1 | 1/1 | 1/1 | 1.00 | 1.00 | 1/1 | 1/1 | 1/3 | 1/3 | 1/1 | 1/1 | 1/1 | 1/1 |
| en | report | scan | 1 | 1/1 | 0/1 | 1.00 | – | 1/1 | 1/1 | 0/3 | 0/3 | 1/1 | 1/1 | 0/1 | 1/1 |
| mixed | receipt | photo | 4 | 4/4 | 1/4 | 0.92 | – | 3/5 | 5/5 | 4/12 | 4/12 | 4/4 | 4/4 | 3/7 | 4/4 |

export: {"rows": 43, "columns": ["review_id", "document", "doc_sha256", "cohort", "mode", "baseline", "field", "predicted", "predicted_raw", "confidence", "method", "warning", "flagged", "final", "entered_input", "action", "decided_by", "approved_by", "approved_at"], "all_custom_fields_exported": true, "arabic_values_exported": false}
brain usage: {"reader": {"loaded": true, "inference_calls": 453, "fallback_reason": null}, "embedder": {"loaded": true, "inference_calls": 140, "fallback_reason": null}, "writer": {"loaded": false, "inference_calls": 0, "fallback_reason": null}}
ONNX calls: {"indra/orient.onnx": 133, "indra/det.onnx": 138, "indra/script.onnx": 819, "indra/rec.onnx": 666, "indra/rec_world.onnx": 22, "indra/rec_cjk.onnx": 30, "indra/order.onnx": 121, "indra/rec_rtl.onnx": 235, "onnx/model_int8.onnx": 593}

