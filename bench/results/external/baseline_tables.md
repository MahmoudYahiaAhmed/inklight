
### Provenance

| Build | Version | Commit | Wheel sha256 | Installed from | `inklight.__file__` |
|---|---|---|---|---|---|
| PyPI 0.1.0 | 0.1.0 | PyPI release 0.1.0 (built from 914d321) | `4922dc132df4743e…` | pip from package index (PyPI) | `…atchpad\evalenv\venvA\Lib\site-packages\inklight\__init__.py` |
| before fixes | 0.1.1.dev0 | d0fac3d1a48c0a0031ffdb00fba248daf5b2fa6a | `cd8494905e32673b…` | pip, local wheel inklight-0.1.1.dev0-py3-none-any.whl | `…atchpad\evalenv\venvB\Lib\site-packages\inklight\__init__.py` |

### Field extraction

| Build | Dataset | Split | Brain | Values | Correct (useful coverage) | Abstained | Wrong, flagged | Wrong, silent | Precision when unflagged |
|---|---|---|---|---|---|---|---|---|---|
| PyPI 0.1.0 | cord (receipts, genuine) | dev | auto | 120 | 2.5% | 94.2% | 3.3% | 0.0% | 100.0% |
| PyPI 0.1.0 | cord (receipts, genuine) | dev | rules | 120 | 2.5% | 94.2% | 3.3% | 0.0% | 100.0% |
| PyPI 0.1.0 | voxel51 (invoices, synthetic) | dev | auto | 360 | 45.3% | 16.7% | 8.3% | 29.7% | 60.4% |
| PyPI 0.1.0 | voxel51 (invoices, synthetic) | dev | rules | 360 | 45.3% | 24.7% | 0.3% | 29.7% | 60.4% |
| before fixes | cord (receipts, genuine) | dev | auto | 120 | 2.5% | 94.2% | 3.3% | 0.0% | 100.0% |
| before fixes | cord (receipts, genuine) | dev | rules | 120 | 2.5% | 94.2% | 3.3% | 0.0% | 100.0% |
| before fixes | voxel51 (invoices, synthetic) | dev | auto | 360 | 45.3% | 16.7% | 8.3% | 29.7% | 60.4% |
| before fixes | voxel51 (invoices, synthetic) | dev | rules | 360 | 45.3% | 24.7% | 0.3% | 29.7% | 60.4% |

### Per field (rules brain)

| Build | Dataset | Split | Field | n | Correct | Abstained | Wrong, flagged | Wrong, silent |
|---|---|---|---|---|---|---|---|---|
| PyPI 0.1.0 | cord | dev | subtotal | 37 | 2.7% | 97.3% | 0.0% | 0.0% |
| PyPI 0.1.0 | cord | dev | tax | 25 | 0.0% | 100.0% | 0.0% | 0.0% |
| PyPI 0.1.0 | cord | dev | total | 58 | 3.4% | 89.7% | 6.9% | 0.0% |
| PyPI 0.1.0 | voxel51 | dev | customer | 60 | 20.0% | 0.0% | 0.0% | 80.0% |
| PyPI 0.1.0 | voxel51 | dev | date | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| PyPI 0.1.0 | voxel51 | dev | invoice_number | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| PyPI 0.1.0 | voxel51 | dev | tax | 60 | 0.0% | 100.0% | 0.0% | 0.0% |
| PyPI 0.1.0 | voxel51 | dev | total | 60 | 1.7% | 0.0% | 0.0% | 98.3% |
| PyPI 0.1.0 | voxel51 | dev | vendor | 60 | 50.0% | 48.3% | 1.7% | 0.0% |
| before fixes | cord | dev | subtotal | 37 | 2.7% | 97.3% | 0.0% | 0.0% |
| before fixes | cord | dev | tax | 25 | 0.0% | 100.0% | 0.0% | 0.0% |
| before fixes | cord | dev | total | 58 | 3.4% | 89.7% | 6.9% | 0.0% |
| before fixes | voxel51 | dev | customer | 60 | 20.0% | 0.0% | 0.0% | 80.0% |
| before fixes | voxel51 | dev | date | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| before fixes | voxel51 | dev | invoice_number | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| before fixes | voxel51 | dev | tax | 60 | 0.0% | 100.0% | 0.0% | 0.0% |
| before fixes | voxel51 | dev | total | 60 | 1.7% | 0.0% | 0.0% | 98.3% |
| before fixes | voxel51 | dev | vendor | 60 | 50.0% | 48.3% | 1.7% | 0.0% |

### Requests

| Build | Split | Brain | Supported: correct | Supported: flagged | Supported: silent wrong | Unsupported: useful abstention | Unsupported: silent wrong |
|---|---|---|---|---|---|---|---|
| PyPI 0.1.0 | dev | auto | 2/6 | 0/6 | 4/6 | 0/0 | 0/0 |
| PyPI 0.1.0 | dev | rules | 2/6 | 0/6 | 4/6 | 0/0 | 0/0 |
| before fixes | dev | auto | 2/6 | 0/6 | 4/6 | 0/0 | 0/0 |
| before fixes | dev | rules | 1/6 | 0/6 | 4/6 | 0/0 | 0/0 |

### Model execution

| Build | Dataset | Split | Brain | OCR calls | Reader calls | Embedder calls | Writer | Brain usage |
|---|---|---|---|---|---|---|---|---|
| PyPI 0.1.0 | cord | dev | auto | 770 | 0 | 0 | 0 | Brain.usage() not available in this version |
| PyPI 0.1.0 | cord | dev | rules | 770 | 0 | 0 | 0 | Brain.usage() not available in this version |
| PyPI 0.1.0 | voxel51 | dev | auto | 1235 | 0 | 0 | 0 | Brain.usage() not available in this version |
| PyPI 0.1.0 | voxel51 | dev | rules | 1235 | 0 | 0 | 0 | Brain.usage() not available in this version |
| before fixes | cord | dev | auto | 770 | 0 | 0 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| before fixes | cord | dev | rules | 770 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
| before fixes | voxel51 | dev | auto | 1235 | 0 | 0 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| before fixes | voxel51 | dev | rules | 1235 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
