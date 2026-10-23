# API reference

## Python

```python
from inklight import DocumentAgent, Policy, load_settings

agent = DocumentAgent()                                   # settings from ~/.inklight/config.toml + env
agent = DocumentAgent(load_settings(models={"brain": "rules"}), allow_write=True, output_dir="out")
```

| Call | Returns | Notes |
|---|---|---|
| `agent.ask(request, files=None, *, doc_ids=None, policy=None, cancel=None, progress=None)` | `AgentResult` | Ingests `files` (incrementally) first. Without `files` it runs over the whole library. `cancel` is a `threading.Event`. |
| `await agent.ask_async(request, files=None, **kw)` | `AgentResult` | Runs `ask` in a worker thread. |
| `agent.ask_many(requests, files=None)` | `list[AgentResult]` | |
| `agent.extract(files, fields=[...] \| schema=path_or_dict)` | `list[Record]` | Typed extraction, no natural language. |
| `agent.add(paths, progress=None, password=None)` | `IngestReport` | `.added`, `.unchanged`, `.failed`, `.warnings`, `.seconds` |
| `agent.plan(request)` | `Plan` | Inspect the plan without running it. |
| `agent.search(query, k=8)` | `list[SearchHit]` | |
| `DocumentAgent.tools()` | `list[dict]` | Name, description, permission, side effects, JSON schema of the arguments. |

`AgentResult` fields:
- `answer` and `intent`.
- `state`: `succeeded | partial | failed | cancelled | unsupported`.
- `interpretation`: how the request was read, rendered from the executed expression.
- `not_understood`: parts of the request that were not applied.
- `checks`: provenance, interpretation and evidence, stated separately.
- `confidence`, `interpretation_confidence`, `evidence_confidence`: heuristic scores, not probabilities.
- `sources`: each a `Source` with `doc_id, path, name, page, block, bbox, excerpt, score, ocr_conf`.
- `records`: `Record.fields[name]` → `ExtractedValue`, with only the requested columns.
- `files_written`, `warnings`, `trace` (`TraceStep`), `brain`, `duration_ms`.
- `table()`: a list of flat dicts.

Conditions are a typed expression on `Plan.where` (`Condition`, or `Group(kind="all"|"any", items=...)`), and
`agent.expr.describe/evaluate/leaves` work on it. `agent.planner.validate_plan(plan)` raises `PlanError` when
the steps would not enforce `where`.

`Policy(allow_write=False, output_dir=None, confirm=None, overwrite=False)` controls the `write_output` tool.
`confirm` is a callback `(message) -> bool`, called before every write.

Library: `agent.library.documents()`, `.get(id)`, `.find(id|prefix|path|name)`, `.pages(id)`, `.text(id)`,
`.remove(id)`, `.reindex(ids=None)`.

Errors (all subclass `InklightError`): `InputRejected`, `OCRError`, `ModelUnavailable`, `PermissionDenied`
(`UnsafePath`), `ConfigError`, `ToolError`, `TaskCancelled`, `LimitExceeded`.

Custom OCR engine:
```python
from inklight.ocr import register_engine
register_engine("tesseract", lambda ocr_settings: MyTesseractEngine(ocr_settings))   # implements OCREngine
# then: [ocr] engine = "tesseract"
```

## CLI

`inklight process | ask | extract | search | docs | show | remove | reindex | history | watch | serve | tools | doctor | models pull/status`.
Run `inklight <command> --help` for options. Exit codes: `0` ok, `1` input or usage error, `2` the task
did not succeed (`failed` / `cancelled`).

## HTTP (`inklight serve`)

Interactive docs at `/api/docs`. Non-GET requests need the header `X-Inklight: 1`. With
`INKLIGHT_SERVER_TOKEN` set, every request also needs `X-Inklight-Token`.

| Method | Path | Body / query |
|---|---|---|
| GET | `/api/status` | — |
| GET / POST | `/api/documents` | POST: multipart `files` |
| GET / DELETE | `/api/documents/{id}` | |
| GET | `/api/documents/{id}/pages/{n}/image` | PNG in the same pixel frame as the stored boxes |
| POST | `/api/ask` | `{"request": str, "doc_ids": [..]?, "allow_write": bool, "job_id": str?}` |
| POST | `/api/jobs/{job_id}/cancel` | |
| POST | `/api/extract` | `{"doc_ids": [..], "fields": [..]}` |
| GET | `/api/search?q=&k=` | |
| GET | `/api/tasks`, `/api/tasks/{id}` | |
| GET | `/api/outputs/{name}` | files the agent wrote |
| POST | `/api/settings` | `{"brain": "auto\|local\|rules", "use_writer": bool}` (runtime only) |
