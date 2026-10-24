
### Provenance

| Build | Version | Commit | Wheel sha256 | Installed from | `inklight.__file__` |
|---|---|---|---|---|---|
| digit-loss check | 0.1.1.dev0 | e61a8d6a77097d950449acaa07234a4bf4b84bc1 | `518a871902240766…` | pip, local wheel inklight-0.1.1.dev0-py3-none-any.whl | `…atchpad\evalenv\venvG\Lib\site-packages\inklight\__init__.py` |

### Field extraction

| Build | Dataset | Split | Brain | Values | Correct (useful coverage) | Abstained | Wrong, flagged | Wrong, silent | Precision when unflagged |
|---|---|---|---|---|---|---|---|---|---|
| digit-loss check | cord (receipts, genuine) | dev | auto | 120 | 78.3% | 14.2% | 7.5% | 0.0% | 100.0% |
| digit-loss check | cord (receipts, genuine) | dev | rules | 120 | 78.3% | 15.0% | 6.7% | 0.0% | 100.0% |
| digit-loss check | cord (receipts, genuine) | holdout | auto | 124 | 69.4% | 18.5% | 11.3% | 0.8% | 98.9% |
| digit-loss check | cord (receipts, genuine) | holdout | rules | 124 | 68.5% | 19.4% | 11.3% | 0.8% | 98.8% |
| digit-loss check | voxel51 (invoices, synthetic) | dev | auto | 360 | 99.4% | 0.0% | 0.3% | 0.3% | 99.7% |
| digit-loss check | voxel51 (invoices, synthetic) | dev | rules | 360 | 99.4% | 0.0% | 0.3% | 0.3% | 99.7% |
| digit-loss check | voxel51 (invoices, synthetic) | holdout | auto | 360 | 99.7% | 0.0% | 0.0% | 0.3% | 99.7% |
| digit-loss check | voxel51 (invoices, synthetic) | holdout | rules | 360 | 99.7% | 0.0% | 0.0% | 0.3% | 99.7% |

### Per field (rules brain)

| Build | Dataset | Split | Field | n | Correct | Abstained | Wrong, flagged | Wrong, silent |
|---|---|---|---|---|---|---|---|---|
| digit-loss check | cord | dev | subtotal | 37 | 75.7% | 21.6% | 2.7% | 0.0% |
| digit-loss check | cord | dev | tax | 25 | 64.0% | 32.0% | 4.0% | 0.0% |
| digit-loss check | cord | dev | total | 58 | 86.2% | 3.4% | 10.3% | 0.0% |
| digit-loss check | cord | holdout | subtotal | 40 | 77.5% | 22.5% | 0.0% | 0.0% |
| digit-loss check | cord | holdout | tax | 25 | 48.0% | 48.0% | 4.0% | 0.0% |
| digit-loss check | cord | holdout | total | 59 | 71.2% | 5.1% | 22.0% | 1.7% |
| digit-loss check | voxel51 | dev | customer | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| digit-loss check | voxel51 | dev | date | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| digit-loss check | voxel51 | dev | invoice_number | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| digit-loss check | voxel51 | dev | tax | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| digit-loss check | voxel51 | dev | total | 60 | 98.3% | 0.0% | 0.0% | 1.7% |
| digit-loss check | voxel51 | dev | vendor | 60 | 98.3% | 0.0% | 1.7% | 0.0% |
| digit-loss check | voxel51 | holdout | customer | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| digit-loss check | voxel51 | holdout | date | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| digit-loss check | voxel51 | holdout | invoice_number | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| digit-loss check | voxel51 | holdout | tax | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| digit-loss check | voxel51 | holdout | total | 60 | 98.3% | 0.0% | 0.0% | 1.7% |
| digit-loss check | voxel51 | holdout | vendor | 60 | 100.0% | 0.0% | 0.0% | 0.0% |

### Requests

| Build | Split | Brain | Supported: correct | Supported: flagged | Supported: silent wrong | Unsupported: useful abstention | Unsupported: silent wrong |
|---|---|---|---|---|---|---|---|
| digit-loss check | dev | auto | 13/13 | 0/13 | 0/13 | 4/4 | 0/4 |
| digit-loss check | dev | rules | 13/13 | 0/13 | 0/13 | 4/4 | 0/4 |
| digit-loss check | holdout | auto | 13/13 | 0/13 | 0/13 | 4/4 | 0/4 |
| digit-loss check | holdout | rules | 13/13 | 0/13 | 0/13 | 4/4 | 0/4 |

### Model execution

| Build | Dataset | Split | Brain | OCR calls | Reader calls | Embedder calls | Writer | Brain usage |
|---|---|---|---|---|---|---|---|---|
| digit-loss check | cord | dev | auto | 770 | 103 | 6 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| digit-loss check | cord | dev | rules | 770 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
| digit-loss check | cord | holdout | auto | 818 | 116 | 6 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| digit-loss check | cord | holdout | rules | 818 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
| digit-loss check | voxel51 | dev | auto | 1235 | 0 | 16 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| digit-loss check | voxel51 | dev | rules | 1235 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
| digit-loss check | voxel51 | holdout | auto | 1248 | 0 | 15 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| digit-loss check | voxel51 | holdout | rules | 1248 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
