"""Typed records shared by the pipeline, the agent and the public API."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

BBox = tuple[float, float, float, float]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------- OCR output


class TextLine(Frozen):
    text: str
    bbox: BBox | None = None
    conf: float | None = None


class Block(Frozen):
    """A layout block in reading order (paragraph, heading, table, ...)."""

    index: int
    label: str
    text: str
    bbox: BBox | None = None
    conf: float | None = Field(None, description="Mean OCR confidence of the lines inside the block.")
    ref: str | None = Field(
        None, description="The structure item this block comes from ('#/tables/0'), when structure is enabled."
    )


class PageContent(Frozen):
    number: int = Field(description="1-based page number.")
    width: float | None = None
    height: float | None = None
    source: str = Field("ocr", description="ocr | text | hybrid | error | plain")
    markdown: str = ""
    lines: tuple[TextLine, ...] = ()
    blocks: tuple[Block, ...] = ()
    rotation: int = 0
    note: str = ""
    ocr_ms: float | None = None

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines) if self.lines else self.markdown

    @property
    def mean_conf(self) -> float | None:
        confs = [line.conf for line in self.lines if line.conf is not None]
        return sum(confs) / len(confs) if confs else None


class DocumentContent(Frozen):
    path: str
    pages: tuple[PageContent, ...]
    total_pages: int
    engine: str
    warnings: tuple[str, ...] = ()


# ---------------------------------------------------------------- library


class DocStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class DocumentInfo(Frozen):
    id: str
    path: str
    name: str
    sha256: str
    size: int
    mtime: float
    pages: int = 0
    total_pages: int = 0
    status: DocStatus = DocStatus.PENDING
    doc_type: str = "unknown"
    engine: str = ""
    error: str | None = None
    mean_conf: float | None = None
    added_at: datetime | None = None


class Source(Frozen):
    """Where a piece of evidence came from."""

    doc_id: str
    path: str
    name: str
    page: int
    block: int | None = None
    bbox: BBox | None = None
    excerpt: str
    score: float | None = None
    ocr_conf: float | None = None

    def cite(self) -> str:
        return f"{self.name} p.{self.page}"


class ExtractedValue(Frozen):
    field: str
    value: Any = None
    raw: str | None = None
    unit: str | None = Field(None, description="Currency code for money values, when the document states one.")
    confidence: float = Field(0.0, description="How sure the reading is: label match x OCR confidence.")
    method: str = "none"
    source: Source | None = None
    verified: bool = Field(
        False,
        description="Provenance only: the raw text was found on the cited line, or subtotal + tax = total. "
        "It does not mean the value answers the user's question.",
    )
    warning: str | None = None


class Record(Frozen):
    """One row of structured output: a document's extracted fields."""

    doc_id: str
    name: str
    path: str
    fields: dict[str, ExtractedValue]

    def flat(self, columns: tuple[str, ...] | list[str] | None = None) -> dict[str, Any]:
        row: dict[str, Any] = {"document": self.name}
        for key, item in self.fields.items():
            if not columns or key in columns:
                row[key] = item.value
        return row

    def project(self, columns: tuple[str, ...] | list[str]) -> Record:
        """Only the requested output columns (fields read just to evaluate conditions are dropped)."""
        if not columns:
            return self
        return self.model_copy(update={"fields": {k: v for k, v in self.fields.items() if k in columns}})


# ---------------------------------------------------------------- agent


class StepStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"
    DENIED = "denied"


class TraceStep(Frozen):
    index: int
    tool: str
    args: dict[str, Any]
    status: StepStatus
    summary: str
    duration_ms: float
    attempts: int = 1
    error: str | None = None


class TaskState(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNSUPPORTED = "unsupported"  # could not run without guessing what was meant


# What a result is, so a person never mistakes one kind for another (the UI and API show it first):
Outcome = Literal[
    "extracted",  # text, search passages or extracted fields, shown as found: nothing was concluded
    "proposed",  # an answer drawn from the documents that a person should check before relying on it
    "supported",  # a value read beside its printed label or in its table cell, with that place cited
    "partial",  # only part of the request was done; the answer says which part
    "missing_evidence",  # the documents in scope did not show the value asked for
    "ambiguous",  # several candidates match: choose one (``candidates``)
    "unsupported",  # the operation is not available for this request
    "failed",  # an error stopped the task
]
OUTCOME_LABELS: dict[str, str] = {
    "extracted": "Extracted text / search results",
    "proposed": "Proposed answer — review before use",
    "supported": "Supported answer — value at its printed label, cited",
    "partial": "Partial result",
    "missing_evidence": "Missing evidence",
    "ambiguous": "Several candidates — choose one",
    "unsupported": "Unsupported operation",
    "failed": "Failed",
}


class Candidate(Frozen):
    """One of several values that match a question (two tables, two documents, two copies of a label)."""

    value: str
    source: Source
    context: str = ""  # where it is: the section, table or document, in words


class AgentResult(Frozen):
    task_id: str
    request: str
    intent: str
    state: TaskState
    answer: str
    confidence: float = Field(
        0.0, ge=0.0, le=1.0, description="Heuristic score: min(interpretation, evidence). Not a calibrated probability."
    )
    interpretation_confidence: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Heuristic score for how completely the request was parsed into applied conditions. "
        "It does not prove the reading is what you meant: check `interpretation`.",
    )
    evidence_confidence: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Heuristic score from label matches, OCR line confidence and arithmetic checks. "
        "Not a calibrated probability, and not a check that the answer is semantically correct.",
    )
    interpretation: tuple[str, ...] = Field((), description="How the request was read, for the user to check.")
    not_understood: tuple[str, ...] = Field((), description="Parts of the request that were NOT applied.")
    checks: tuple[str, ...] = Field(
        (),
        description="What was actually checked, kept separate: provenance (cited text exists in the document), "
        "interpretation (every part of the request applied), evidence (heuristic signals).",
    )
    sources: tuple[Source, ...] = ()
    records: tuple[Record, ...] = ()
    calculation: dict[str, Any] | None = Field(
        None,
        description="For sums, averages, minima and maxima: op, field, result, unit, count (values used), "
        "missing (documents without a value, left out) and by_unit when currencies differ.",
    )
    files_written: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    trace: tuple[TraceStep, ...] = ()
    brain: str = "rules"
    duration_ms: float = 0.0
    outcome: Outcome = Field(
        "proposed",
        description="What kind of result this is (OUTCOME_LABELS). Even a supported answer rests on OCR, which can "
        "misread: OCR confidence is the reader's own estimate, not a guarantee.",
    )
    candidates: tuple[Candidate, ...] = Field((), description="When outcome is ambiguous: the values to choose from.")
    comparison: dict[str, Any] | None = Field(
        None,
        description="A field compared across documents: field, values (one per document, with source), and "
        "verdict: matches | differs | cannot determine.",
    )

    @property
    def outcome_label(self) -> str:
        return OUTCOME_LABELS[self.outcome]

    @property
    def ok(self) -> bool:
        return self.state in (TaskState.SUCCEEDED, TaskState.PARTIAL)

    def table(self) -> list[dict[str, Any]]:
        return [record.flat() for record in self.records]


class SearchHit(Frozen):
    source: Source
    score: float
    method: Literal["keyword", "semantic", "hybrid", "scope"] = "keyword"
