
### Provenance

| Build | Version | Commit | Harness commit | Wheel sha256 | Installed from | `inklight.__file__` |
|---|---|---|---|---|---|---|
| PyPI 0.1.0 | 0.1.0 | PyPI release 0.1.0 (built from 914d321) | 54355d782d9a57e768ca18daf11380895370689f (bench/ modified) | `4922dc132df4743e…` | pip from package index (PyPI) | `…atchpad\evalenv\venvA\Lib\site-packages\inklight\__init__.py` |
| final | 0.1.1.dev0 | 05206d7349caf7e8f81ba4b64b1a9d4405cfba27 | 54355d782d9a57e768ca18daf11380895370689f (bench/ modified) | `1a751494d703cd01…` | pip, local wheel inklight-0.1.1.dev0-py3-none-any.whl | `…atchpad\evalenv\venvF\Lib\site-packages\inklight\__init__.py` |
| amount check v2 | 0.1.1.dev0 | 3788bf92bcef70c601a1185c19e6066949bbf720 | 54355d782d9a57e768ca18daf11380895370689f (bench/ modified) | `b02ccba3b4511e3f…` | pip, local wheel inklight-0.1.1.dev0-py3-none-any.whl | `…atchpad\evalenv\venvH\Lib\site-packages\inklight\__init__.py` |

### Model execution

| Build | Dataset | Split | Brain | OCR calls | Reader calls | Embedder calls | Writer | Brain usage |
|---|---|---|---|---|---|---|---|---|
| PyPI 0.1.0 | cord | dev | auto | 770 | 2306 | 7 | 0 | Brain.usage() not available in this version |
| PyPI 0.1.0 | cord | dev | rules | 770 | 0 | 0 | 0 | Brain.usage() not available in this version |
| PyPI 0.1.0 | voxel51 | dev | auto | 1235 | 2465 | 16 | 0 | Brain.usage() not available in this version |
| PyPI 0.1.0 | voxel51 | dev | rules | 1235 | 0 | 0 | 0 | Brain.usage() not available in this version |
| final | cord | dev | auto | 770 | 1671 | 6 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| final | cord | dev | rules | 770 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
| final | voxel51 | dev | auto | 1235 | 0 | 16 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| final | voxel51 | dev | rules | 1235 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
| amount check v2 | cord | dev | auto | 770 | 1673 | 6 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| amount check v2 | cord | dev | rules | 770 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
| amount check v2 | voxel51 | dev | auto | 1445 | 0 | 16 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| amount check v2 | voxel51 | dev | rules | 1445 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
