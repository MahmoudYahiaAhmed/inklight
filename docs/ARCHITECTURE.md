# Architecture

```
                 ┌──────────── user request (the only source of plans) ────────────┐
                 ▼                                                                  │
 CLI / Python API / Web UI ──► Planner ──► typed Plan (intent, fields, conditions, steps)
                                  │ rules (measured 100% on the 40-request set)
                                  │ + optional remote model (validated against the same schema)
                                  ▼
                               Runner ── max steps · time budgets · retries · cancel · trace
                                  │
       ┌───────────────┬──────────┼─────────────┬──────────────┬───────────────┐
  inspect_documents  search    answer/cite   extract_fields  filter/calculate  compare/
                       │          │             │                              inconsistencies
                       ▼          ▼             ▼                              summarize, write_output
                   Retriever   Reader 66M    Field engine (labels, types, provenance, cross-checks)
                  (FTS5 BM25    (extractive,                │
                   + bge 33M     never invents)             │
                   vectors)                                 │
                       └──────────────┬─────────────────────┘
                                      ▼
                      Library (SQLite: documents · pages · blocks · chunks · FTS · vectors · tasks)
                                      ▲
                      Ingest: validate → hash → dedupe → OCR → chunk → classify → injection scan
                                      ▲
                      OCR engines (pluggable): Indra OCR (PDF text layer first, OCR where needed),
                                               plain text / Markdown
```

## Modules

| Module | Responsibility |
|---|---|
| `config.py` | Validated, versioned settings: defaults < TOML < env (`INKLIGHT_SECTION__KEY`) < overrides. |
| `safety.py` | File sniffing and limits, discovery, safe output paths, injection signals, prompt fencing. |
| `ocr/` | `OCREngine` protocol, an `IndraEngine` that uses only Indra's public API, a `PlainTextEngine`, and a registry. |
| `chunking.py` | Layout-aware chunks: never cross pages, keep tables whole, keep headings with their text. |
| `store.py` | SQLite repository (WAL, FTS5 with Porter stemming, cascade deletes, task history). |
| `library.py` | Incremental ingest: an unchanged file is skipped, identical content at a new path reuses its OCR, and a changed file is re-read. |
| `retrieval.py` | BM25 always; with the embedder installed, semantic search fused with BM25 by reciprocal-rank fusion. |
| `extract/` | Money/date/number parsing, document classification, label-based typed fields with provenance and arithmetic checks. |
| `brains/` | Lazy model loading (`rules` / `auto` / `local`), three ONNX Runtime models, an optional OpenAI-compatible remote model. |
| `agent/` | Plan schema, rule planner, tool registry, bounded runner, answer and analysis tools, composition and citation verification. |
| `server/` | FastAPI app with the security middleware, page rendering for overlays, and the static UI. |
| `watch.py` | Polling folder watcher (picks up files once they are stable; runs an optional request per batch). |

## Conditions: one expression, executed and explained

The planner turns constraint words into **atoms**: a single condition, a range (`between`), a year or month
(two date bounds), or a vendor list. Each atom keeps the span of the request it came from.

1. **Grouping.** `or` between atoms on the same field forms one group: "between 100 and 6,000 **or** above
   10,000" becomes `(≥100 and ≤6,000) or >10,000`. The remaining operands are joined with AND, or with OR
   when every connector is "or". A mix of both across different fields is ambiguous: the plan is
   **blocked** (`unsupported`) and nothing runs.
2. **Leftovers.** What no atom consumed is scanned for constraint-like fragments: known phrases, a dangling
   "or X", an unattached proper noun, an amount with an unknown unit. These go to `not_understood`, the task is
   `partial`, and `write_output` refuses to export.
3. **Enforcement.** `steps_for()` puts `extract_fields` (requested columns ∪ condition fields) and
   `filter_records(where)` first, for every intent. The filter narrows the document scope, so every later step
   sees only matches. `validate_plan()` checks this structure, and the runner calls it before running any
   plan, including a plan from a remote model.
4. **Evaluation** is three-valued (Kleene). A missing value or an incompatible currency is *unknown*. Unknown
   is never a match: those documents are excluded, named in a warning, and the result is `partial`.
5. **Explanation.** "Understood as" is `describe(where)`: the same object the filter evaluates.

The parser is pattern-based. It is tested against the reviewers' cases, combinations, 40 generated requests
checked against a reference, and unseen paraphrases. The paraphrase rule is "exactly right, or not
`succeeded` with the unapplied part named". It cannot catch every phrasing of a constraint.

## Why a 135M model does not choose the tools

We measured it. Used as a zero-shot intent classifier (log-likelihood ranking over 10 labels, the most
reliable way to use a small model), SmolLM2-135M-Instruct scored **27.5%** on the 40-request planner set.
The deterministic planner scored **100%** on that set (see `docs/BENCHMARKS.md` — the set was written
alongside the planner, so treat 100% as an upper bound, not a generalisation claim). So the small models
do what they are good at:

* **Reader (66M, extractive QA).** It points at a span of the evidence. It cannot produce text that is
  not in the document, which makes it safe for evidence-backed answers.
* **Embedder (33M).** It improves recall for paraphrased questions ("contract end" ↔ "expiration date").
* **Writer (135M, optional).** It only rephrases an already-found answer, and its output is dropped unless
  every number and name in it appears in the evidence.

Harder or low-confidence tasks can be routed to a stronger remote model (`models.remote_for = "fallback"`).
That output passes the same checks: plans are schema-validated, and answers need a quote that really
occurs in the document.

## Why Python, and where Rust would go

Profiling ingest of 40 documents (`bench/run.py`) puts Inklight's own Python at about 2% of the time.
The rest is OCR inference, pdfium rendering and SQLite, which already run in native code. A Rust
rewrite of Inklight's layer could save at most that 2%, so we did not add one. If profiling of a future
workload changes this picture (for example very large libraries where Python-side scoring dominates),
the place to add a native component is `retrieval.py` or `extract/fields.py`, behind the same interfaces.
