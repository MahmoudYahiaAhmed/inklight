"""The agent's tool allow-list. Each tool: typed args, permission, documented side effects.

There is deliberately no shell, code-execution, network or delete tool.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from ..extract import SINGULAR
from . import analysis, answer
from .context import ToolContext
from .expr import leaves
from .plan import Expr

_FIELD = r"^[a-z0-9_]{1,40}$"


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InspectArgs(_Args):
    doc_type: str | None = Field(None, max_length=30)


class SearchArgs(_Args):
    query: str = Field(min_length=1, max_length=2000)
    k: int = Field(8, ge=1, le=50)


class QuestionArgs(_Args):
    question: str = Field(min_length=1, max_length=2000)


class FieldsArgs(_Args):
    fields: list[Annotated[str, StringConstraints(pattern=_FIELD)]] = Field(default_factory=list, max_length=30)


class FilterArgs(_Args):
    where: Expr

    @model_validator(mode="after")
    def _bounded(self) -> FilterArgs:
        if len(leaves(self.where)) > 20:
            raise ValueError("at most 20 conditions")
        return self


class CalcArgs(_Args):
    op: Literal["sum", "avg", "min", "max", "count"]
    field: str = Field(pattern=_FIELD)


class SummarizeArgs(_Args):
    focus: str = Field("", max_length=2000)


class WriteArgs(_Args):
    format: Literal["csv", "json", "md"]
    name: str | None = Field(None, max_length=120)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[_Args]
    run: Callable[[ToolContext, Any], str]
    permission: Literal["read", "write"] = "read"
    side_effects: str = "none"


def _inspect(ctx: ToolContext, a: InspectArgs) -> str:
    docs = ctx.docs()
    if a.doc_type:
        wanted = SINGULAR.get(a.doc_type, a.doc_type)
        keep = [d.id for d in docs if d.doc_type == wanted]
        if keep:
            ctx.scratch.doc_ids = keep
        else:
            ctx.scratch.warn(f"No document was classified as '{wanted}'; used all {len(docs)} documents")
    kinds: dict[str, int] = {}
    for d in ctx.docs():
        kinds[d.doc_type] = kinds.get(d.doc_type, 0) + 1
    low = [d.name for d in ctx.docs() if d.mean_conf is not None and d.mean_conf < 0.8]
    if low:
        ctx.scratch.warn("Low OCR confidence in: " + ", ".join(low[:5]) + "; extracted values may be wrong")
    return f"{len(ctx.scratch.doc_ids)} documents (" + ", ".join(f"{n} {k}" for k, n in kinds.items()) + ")"


def _search(ctx: ToolContext, a: SearchArgs) -> str:
    ctx.scratch.hits = ctx.library.search(a.query, ctx.scratch.doc_ids, k=a.k)
    method = ctx.scratch.hits[0].method if ctx.scratch.hits else "keyword"
    if method != "keyword":
        ctx.scratch.brain_used.add("embedder")
    return f"{len(ctx.scratch.hits)} passages ({method})"


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(
            "inspect_documents",
            "List and classify the documents in scope; narrow to a document type.",
            InspectArgs,
            _inspect,
        ),
        Tool("search", "Retrieve the most relevant passages (BM25 + optional semantic vectors).", SearchArgs, _search),
        Tool(
            "answer",
            "Answer a question from retrieved evidence with citations.",
            QuestionArgs,
            lambda c, a: answer.answer_question(c, a.question),
        ),
        Tool(
            "cite",
            "Return the passage that best supports a statement, with its location.",
            QuestionArgs,
            lambda c, a: answer.cite(c, a.question),
        ),
        Tool(
            "extract_fields",
            "Extract typed fields from each document, with provenance.",
            FieldsArgs,
            lambda c, a: analysis.extract_fields(c, a.fields),
        ),
        Tool(
            "filter_records",
            "Keep records that satisfy all conditions.",
            FilterArgs,
            lambda c, a: analysis.filter_records(c, a.where),
        ),
        Tool(
            "calculate",
            "Deterministic sum/avg/min/max/count over a numeric field.",
            CalcArgs,
            lambda c, a: analysis.calculate(c, a.op, a.field),
        ),
        Tool(
            "compare_documents",
            "Compare documents field by field and line by line.",
            FieldsArgs,
            lambda c, a: analysis.compare_documents(c, a.fields),
        ),
        Tool(
            "find_inconsistencies",
            "Flag conflicting or inconsistent values across records.",
            FieldsArgs,
            lambda c, a: analysis.find_inconsistencies(c, a.fields),
        ),
        Tool(
            "summarize",
            "Extractive per-document summary with page citations.",
            SummarizeArgs,
            lambda c, a: answer.summarize(c, a.focus),
        ),
        Tool(
            "write_output",
            "Write results as CSV, JSON or Markdown inside the output folder.",
            WriteArgs,
            lambda c, a: analysis.write_output(c, a.format, a.name),
            permission="write",
            side_effects="creates one new file inside the configured output folder; never overwrites by default",
        ),
    ]
}


def describe_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "permission": t.permission,
            "side_effects": t.side_effects,
            "args": t.args.model_json_schema(),
        }
        for t in TOOLS.values()
    ]
