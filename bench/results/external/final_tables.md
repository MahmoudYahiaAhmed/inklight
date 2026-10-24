
### Provenance

| Build | Version | Commit | Wheel sha256 | Installed from | `inklight.__file__` |
|---|---|---|---|---|---|
| PyPI 0.1.0 | 0.1.0 | PyPI release 0.1.0 (built from 914d321) | `4922dc132df4743e…` | pip from package index (PyPI) | `…atchpad\evalenv\venvA\Lib\site-packages\inklight\__init__.py` |
| before fixes | 0.1.1.dev0 | d0fac3d1a48c0a0031ffdb00fba248daf5b2fa6a | `cd8494905e32673b…` | pip, local wheel inklight-0.1.1.dev0-py3-none-any.whl | `…atchpad\evalenv\venvB\Lib\site-packages\inklight\__init__.py` |
| final | 0.1.1.dev0 | 05206d7349caf7e8f81ba4b64b1a9d4405cfba27 | `1a751494d703cd01…` | pip, local wheel inklight-0.1.1.dev0-py3-none-any.whl | `…atchpad\evalenv\venvF\Lib\site-packages\inklight\__init__.py` |

### Field extraction

| Build | Dataset | Split | Brain | Values | Correct (useful coverage) | Abstained | Wrong, flagged | Wrong, silent | Precision when unflagged |
|---|---|---|---|---|---|---|---|---|---|
| PyPI 0.1.0 | cord (receipts, genuine) | holdout | auto | 124 | 3.2% | 89.5% | 4.8% | 2.4% | 57.1% |
| PyPI 0.1.0 | cord (receipts, genuine) | holdout | rules | 124 | 3.2% | 89.5% | 4.8% | 2.4% | 57.1% |
| PyPI 0.1.0 | voxel51 (invoices, synthetic) | holdout | auto | 360 | 41.7% | 16.7% | 10.8% | 30.8% | 57.5% |
| PyPI 0.1.0 | voxel51 (invoices, synthetic) | holdout | rules | 360 | 41.7% | 27.5% | 0.0% | 30.8% | 57.5% |
| before fixes | cord (receipts, genuine) | holdout | auto | 124 | 3.2% | 89.5% | 4.8% | 2.4% | 57.1% |
| before fixes | cord (receipts, genuine) | holdout | rules | 124 | 3.2% | 89.5% | 4.8% | 2.4% | 57.1% |
| before fixes | voxel51 (invoices, synthetic) | holdout | auto | 360 | 41.7% | 16.7% | 10.8% | 30.8% | 57.5% |
| before fixes | voxel51 (invoices, synthetic) | holdout | rules | 360 | 41.7% | 27.5% | 0.0% | 30.8% | 57.5% |
| final | cord (receipts, genuine) | dev | auto | 120 | 78.3% | 14.2% | 7.5% | 0.0% | 100.0% |
| final | cord (receipts, genuine) | dev | rules | 120 | 78.3% | 15.0% | 6.7% | 0.0% | 100.0% |
| final | cord (receipts, genuine) | holdout | auto | 124 | 69.4% | 18.5% | 10.5% | 1.6% | 97.7% |
| final | cord (receipts, genuine) | holdout | rules | 124 | 68.5% | 19.4% | 10.5% | 1.6% | 97.7% |
| final | voxel51 (invoices, synthetic) | dev | auto | 360 | 99.4% | 0.0% | 0.3% | 0.3% | 99.7% |
| final | voxel51 (invoices, synthetic) | dev | rules | 360 | 99.4% | 0.0% | 0.3% | 0.3% | 99.7% |
| final | voxel51 (invoices, synthetic) | holdout | auto | 360 | 99.7% | 0.0% | 0.0% | 0.3% | 99.7% |
| final | voxel51 (invoices, synthetic) | holdout | rules | 360 | 99.7% | 0.0% | 0.0% | 0.3% | 99.7% |

### Per field (rules brain)

| Build | Dataset | Split | Field | n | Correct | Abstained | Wrong, flagged | Wrong, silent |
|---|---|---|---|---|---|---|---|---|
| PyPI 0.1.0 | cord | holdout | subtotal | 40 | 2.5% | 97.5% | 0.0% | 0.0% |
| PyPI 0.1.0 | cord | holdout | tax | 25 | 0.0% | 100.0% | 0.0% | 0.0% |
| PyPI 0.1.0 | cord | holdout | total | 59 | 5.1% | 79.7% | 10.2% | 5.1% |
| PyPI 0.1.0 | voxel51 | holdout | customer | 60 | 15.0% | 0.0% | 0.0% | 85.0% |
| PyPI 0.1.0 | voxel51 | holdout | date | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| PyPI 0.1.0 | voxel51 | holdout | invoice_number | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| PyPI 0.1.0 | voxel51 | holdout | tax | 60 | 0.0% | 100.0% | 0.0% | 0.0% |
| PyPI 0.1.0 | voxel51 | holdout | total | 60 | 0.0% | 0.0% | 0.0% | 100.0% |
| PyPI 0.1.0 | voxel51 | holdout | vendor | 60 | 35.0% | 65.0% | 0.0% | 0.0% |
| before fixes | cord | holdout | subtotal | 40 | 2.5% | 97.5% | 0.0% | 0.0% |
| before fixes | cord | holdout | tax | 25 | 0.0% | 100.0% | 0.0% | 0.0% |
| before fixes | cord | holdout | total | 59 | 5.1% | 79.7% | 10.2% | 5.1% |
| before fixes | voxel51 | holdout | customer | 60 | 15.0% | 0.0% | 0.0% | 85.0% |
| before fixes | voxel51 | holdout | date | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| before fixes | voxel51 | holdout | invoice_number | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| before fixes | voxel51 | holdout | tax | 60 | 0.0% | 100.0% | 0.0% | 0.0% |
| before fixes | voxel51 | holdout | total | 60 | 0.0% | 0.0% | 0.0% | 100.0% |
| before fixes | voxel51 | holdout | vendor | 60 | 35.0% | 65.0% | 0.0% | 0.0% |
| final | cord | dev | subtotal | 37 | 75.7% | 21.6% | 2.7% | 0.0% |
| final | cord | dev | tax | 25 | 64.0% | 32.0% | 4.0% | 0.0% |
| final | cord | dev | total | 58 | 86.2% | 3.4% | 10.3% | 0.0% |
| final | cord | holdout | subtotal | 40 | 77.5% | 22.5% | 0.0% | 0.0% |
| final | cord | holdout | tax | 25 | 48.0% | 48.0% | 4.0% | 0.0% |
| final | cord | holdout | total | 59 | 71.2% | 5.1% | 20.3% | 3.4% |
| final | voxel51 | dev | customer | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| final | voxel51 | dev | date | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| final | voxel51 | dev | invoice_number | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| final | voxel51 | dev | tax | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| final | voxel51 | dev | total | 60 | 98.3% | 0.0% | 0.0% | 1.7% |
| final | voxel51 | dev | vendor | 60 | 98.3% | 0.0% | 1.7% | 0.0% |
| final | voxel51 | holdout | customer | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| final | voxel51 | holdout | date | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| final | voxel51 | holdout | invoice_number | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| final | voxel51 | holdout | tax | 60 | 100.0% | 0.0% | 0.0% | 0.0% |
| final | voxel51 | holdout | total | 60 | 98.3% | 0.0% | 0.0% | 1.7% |
| final | voxel51 | holdout | vendor | 60 | 100.0% | 0.0% | 0.0% | 0.0% |

### Requests

| Build | Split | Brain | Supported: correct | Supported: flagged | Supported: silent wrong | Unsupported: useful abstention | Unsupported: silent wrong |
|---|---|---|---|---|---|---|---|
| PyPI 0.1.0 | holdout | auto | 2/13 | 0/13 | 11/13 | 3/4 | 1/4 |
| PyPI 0.1.0 | holdout | rules | 2/13 | 0/13 | 11/13 | 3/4 | 1/4 |
| before fixes | holdout | auto | 5/13 | 0/13 | 8/13 | 3/4 | 1/4 |
| before fixes | holdout | rules | 1/13 | 5/13 | 7/13 | 3/4 | 1/4 |
| final | dev | auto | 13/13 | 0/13 | 0/13 | 4/4 | 0/4 |
| final | dev | rules | 13/13 | 0/13 | 0/13 | 4/4 | 0/4 |
| final | holdout | auto | 13/13 | 0/13 | 0/13 | 4/4 | 0/4 |
| final | holdout | rules | 13/13 | 0/13 | 0/13 | 4/4 | 0/4 |

### Model execution

| Build | Dataset | Split | Brain | OCR calls | Reader calls | Embedder calls | Writer | Brain usage |
|---|---|---|---|---|---|---|---|---|
| PyPI 0.1.0 | cord | holdout | auto | 818 | 242 | 6 | 0 | Brain.usage() not available in this version |
| PyPI 0.1.0 | cord | holdout | rules | 818 | 0 | 0 | 0 | Brain.usage() not available in this version |
| PyPI 0.1.0 | voxel51 | holdout | auto | 1248 | 3048 | 15 | 0 | Brain.usage() not available in this version |
| PyPI 0.1.0 | voxel51 | holdout | rules | 1248 | 0 | 0 | 0 | Brain.usage() not available in this version |
| before fixes | cord | holdout | auto | 818 | 242 | 6 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| before fixes | cord | holdout | rules | 818 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
| before fixes | voxel51 | holdout | auto | 1248 | 3048 | 15 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| before fixes | voxel51 | holdout | rules | 1248 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
| final | cord | dev | auto | 770 | 103 | 6 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| final | cord | dev | rules | 770 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
| final | cord | holdout | auto | 818 | 116 | 6 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| final | cord | holdout | rules | 818 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
| final | voxel51 | dev | auto | 1235 | 0 | 16 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| final | voxel51 | dev | rules | 1235 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
| final | voxel51 | holdout | auto | 1248 | 0 | 15 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| final | voxel51 | holdout | rules | 1248 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
