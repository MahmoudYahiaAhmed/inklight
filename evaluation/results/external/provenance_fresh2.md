
### Provenance

| Build | Version | Commit | Harness commit | Wheel sha256 | Installed from | `inklight.__file__` |
|---|---|---|---|---|---|---|
| PyPI 0.1.0 | 0.1.0 | PyPI release 0.1.0 (built from 914d321) | a7ee6faa2eabd719f195d5280a87fd995773f07a (bench/ modified) | `4922dc132df4743e…` | pip from package index (PyPI) | `…atchpad\evalenv\venvA\Lib\site-packages\inklight\__init__.py` |
| final | 0.1.1.dev0 | 05206d7349caf7e8f81ba4b64b1a9d4405cfba27 | a7ee6faa2eabd719f195d5280a87fd995773f07a (bench/ modified) | `1a751494d703cd01…` | pip, local wheel inklight-0.1.1.dev0-py3-none-any.whl | `…atchpad\evalenv\venvF\Lib\site-packages\inklight\__init__.py` |
| digit-loss check | 0.1.1.dev0 | e61a8d6a77097d950449acaa07234a4bf4b84bc1 | a7ee6faa2eabd719f195d5280a87fd995773f07a (bench/ modified) | `518a871902240766…` | pip, local wheel inklight-0.1.1.dev0-py3-none-any.whl | `…atchpad\evalenv\venvG\Lib\site-packages\inklight\__init__.py` |
| amount check v2 | 0.1.1.dev0 | 3788bf92bcef70c601a1185c19e6066949bbf720 | a7ee6faa2eabd719f195d5280a87fd995773f07a (bench/ modified) | `b02ccba3b4511e3f…` | pip, local wheel inklight-0.1.1.dev0-py3-none-any.whl | `…atchpad\evalenv\venvH\Lib\site-packages\inklight\__init__.py` |

### Model execution

| Build | Dataset | Split | Brain | OCR calls | Reader calls | Embedder calls | Writer | Brain usage |
|---|---|---|---|---|---|---|---|---|
| PyPI 0.1.0 | cord | fresh | auto | 798 | 2364 | 7 | 0 | Brain.usage() not available in this version |
| PyPI 0.1.0 | cord | fresh | rules | 798 | 0 | 0 | 0 | Brain.usage() not available in this version |
| final | cord | fresh | auto | 798 | 1775 | 6 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| final | cord | fresh | rules | 798 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
| digit-loss check | cord | fresh | auto | 798 | 1775 | 6 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| digit-loss check | cord | fresh | rules | 798 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
| amount check v2 | cord | fresh | auto | 870 | 1782 | 6 | 0 | reader: loaded=True, embedder: loaded=True, writer: loaded=False |
| amount check v2 | cord | fresh | rules | 870 | 0 | 0 | 0 | reader: loaded=False, embedder: loaded=False, writer: loaded=False |
