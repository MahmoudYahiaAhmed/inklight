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
| `agent.text(file, *, password=None)` | `str` | The document's text, page by page, as read (raw: the first line says so). |
| `agent.tables(file, *, password=None)` | `list[dict]` | Tables from document structure: `index`, `page`, `header_rows`, `rows` (cell texts). Needs `structure={"engine": "inklight"}`. |
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

## Human review (Python)

```python
review = agent.open_review(doc_id, ["vendor", "total"], reviewer="ana", mode="review", cohort="genuine-invoice")
agent.reviews.decide(review.id, "total", reviewer="ana", action="corrected", value="1,520.00")
agent.reviews.decide(review.id, "vendor", reviewer="ana", action="accepted")
agent.reviews.approve(review.id, reviewer="ana", active_seconds=42.0)
csv_text = agent.reviews.export("csv", actor="ana")       # approved reviews only
```

Predictions are frozen when a review opens; decisions are stored next to them, never over them; the
history (`agent.reviews.events(review.id)`) is append-only. The archived invoice pilot ([pilot/README.md at `146d275`](https://github.com/MahmoudYahiaAhmed/inklight/blob/146d27556684cdd872b41e3de37d619092e1fe02/pilot/README.md)) used this to compare reviewed values with predictions.

## CLI

`inklight text | tables | extract | search | process | docs | show | remove | reindex | watch | serve | structure | doctor | models pull/status | review list/export`, and the experimental `ask | history | tools`.
Run `inklight <command> --help` for options. Exit codes: `0` ok, `1` input or usage error, `2` the task
did not succeed (`failed` / `cancelled`).

## HTTP (`inklight serve`)

Interactive docs at `/api/docs`. Non-GET requests need the header `X-Inklight: 1`. With
`INKLIGHT_SERVER_TOKEN` set, every request also needs `X-Inklight-Token`.

| Method | Path | Body / query |
|---|---|---|
| GET | `/api/status` | — |
| GET / POST | `/api/documents` | POST: multipart `files`; `?background=true` returns at once with a job to follow |
| GET | `/api/jobs`, `/api/jobs/{id}` | recent imports (newest first) and one import: each file's state, page and pages read, error |
| GET | `/api/jobs/{id}/events` | server-sent events: the import's state each time it changes, until it ends |
| GET | `/api/jobs/{id}/files/{n}/preview` | PNG of a file's first page as uploaded, while it is read |
| POST | `/api/documents/{id}/structure` | read a stored document again with document structure, as a job |
| GET | `/api/documents/{id}/tables` | the document's tables (rows of cell text, header rows, page) |
| GET | `/api/documents/{id}/export?format=txt\|json\|tables.csv` | raw exports, marked as not reviewed |
| GET / DELETE | `/api/documents/{id}` | |
| GET | `/api/documents/{id}/pages/{n}/image` | PNG in the same pixel frame as the stored boxes |
| POST | `/api/ask` | `{"request": str, "doc_ids": [..]?, "allow_write": bool, "job_id": str?}` |
| POST | `/api/jobs/{job_id}/cancel` | stops an Ask request, or an import before its next file |
| POST | `/api/extract` | `{"doc_ids": [..], "fields": [..]}` |
| GET | `/api/search?q=&k=` | |
| GET | `/api/tasks`, `/api/tasks/{id}` | |
| GET | `/api/outputs/{name}` | files the agent wrote |
| POST | `/api/settings` | `{"brain": "auto\|local\|rules", "use_writer": bool}` (runtime only) |
| GET / POST | `/api/reviews` | GET `?status=open\|approved&cohort=`; POST `{"doc_id", "reviewer", "fields"?, "mode": "review\|manual", "cohort"?, "split"?}` |
| GET | `/api/reviews/{id}` | the review (predictions hidden while a manual entry is open) and its history |
| POST | `/api/reviews/{id}/decide` | `{"field", "action": "accepted\|corrected\|entered\|absent", "value"?, "reviewer"}` |
| POST | `/api/reviews/{id}/approve` | `{"reviewer", "active_seconds"?}`; every field must have a decision |
| POST | `/api/reviews/{id}/reopen` | `{"reviewer", "reason"}` |
| POST | `/api/reviews/export` | `{"actor", "format": "csv\|json", "cohort"?}`: approved reviews only |

`INKLIGHT_PILOT_BASELINE`, when set, is recorded on every review the server opens.
