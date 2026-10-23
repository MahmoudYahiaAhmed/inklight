"""Typed task plans. A plan is data: validated before any tool runs."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Intent(StrEnum):
    ASK = "ask"
    FIND = "find"
    EXTRACT = "extract"
    FILTER = "filter"
    AGGREGATE = "aggregate"
    COMPARE = "compare"
    INCONSISTENCIES = "inconsistencies"
    SUMMARIZE = "summarize"
    COUNT = "count"
    PROCESS = "process"


Op = Literal["gt", "ge", "lt", "le", "eq", "contains", "not_contains", "within_days", "before", "after"]

_OP_WORDS = {
    "gt": ">",
    "ge": ">=",
    "lt": "<",
    "le": "<=",
    "eq": "=",
    "contains": "contains",
    "not_contains": "does not contain",
    "within_days": "within the next",
    "before": "before",
    "after": "after",
}


class Condition(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["cond"] = "cond"
    field: str
    op: Op
    value: Any
    unit: str | None = Field(None, description="Currency code for money thresholds (USD, EUR, ...).")

    def describe(self) -> str:
        name = self.field.replace("_", " ")
        if self.op in ("contains", "not_contains"):
            return f'{name} {_OP_WORDS[self.op]} "{self.value}"'
        if self.op == "within_days":
            return f"{name} within the next {self.value} days"
        value = f"{self.value:,.2f}".rstrip("0").rstrip(".") if isinstance(self.value, float) else str(self.value)
        return f"{name} {_OP_WORDS[self.op]} {value}" + (f" {self.unit}" if self.unit else "")


class Group(BaseModel):
    """``all`` = AND, ``any`` = OR over two or more operands (see ``agent.expr``)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["all", "any"]
    items: tuple[Expr, ...] = Field(min_length=2)


Expr = Annotated[Condition | Group, Field(discriminator="kind")]
Group.model_rebuild()


class Step(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent: Intent
    query: str
    fields: tuple[str, ...] = ()
    where: Expr | None = Field(None, description="The validated Boolean expression the filter step executes.")
    doc_type: str | None = None
    output: Literal["csv", "json", "md"] | None = None
    output_name: str | None = None
    aggregate: Literal["sum", "avg", "min", "max", "count"] | None = None
    aggregate_field: str | None = None
    not_understood: tuple[str, ...] = Field((), description="Parts of the request no tool can apply.")
    blocked: tuple[str, ...] = Field((), description="Reasons the request cannot run without guessing.")
    confidence: float = Field(0.5, ge=0, le=1)
    planner: str = "rules"
    steps: tuple[Step, ...] = ()

    @property
    def conditions(self) -> tuple[Condition, ...]:
        """Every leaf condition of ``where`` (read-only view; ``where`` is what runs)."""
        from .expr import leaves

        return tuple(leaves(self.where))

    def understood(self) -> tuple[str, ...]:
        """How the request was read, rendered from the same ``where`` the filter executes."""
        from .expr import describe

        out = [f"task: {self.intent.value}"]
        if self.doc_type:
            out.append(f"documents: {self.doc_type}s")
        if self.where is not None:
            out.append("where " + describe(self.where))
        if self.aggregate:
            out.append(f"compute: {self.aggregate} of {self.aggregate_field}")
        if self.fields and self.intent.value in ("extract", "filter", "aggregate", "inconsistencies"):
            out.append("columns: " + ", ".join(self.fields))
        if self.output:
            out.append(f"output: {self.output} file")
        return tuple(out)
