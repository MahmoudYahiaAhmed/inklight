"""Typed task plans. A plan is data: validated before any tool runs."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

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


Op = Literal["gt", "ge", "lt", "le", "eq", "contains", "within_days", "before", "after"]


class Condition(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    op: Op
    value: Any

    def describe(self) -> str:
        words = {
            "gt": ">",
            "ge": "≥",
            "lt": "<",
            "le": "≤",
            "eq": "=",
            "contains": "contains",
            "within_days": "within days:",
            "before": "before",
            "after": "after",
        }
        return f"{self.field} {words[self.op]} {self.value}"


class Step(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent: Intent
    query: str
    fields: tuple[str, ...] = ()
    conditions: tuple[Condition, ...] = ()
    doc_type: str | None = None
    output: Literal["csv", "json", "md"] | None = None
    output_name: str | None = None
    aggregate: Literal["sum", "avg", "min", "max", "count"] | None = None
    aggregate_field: str | None = None
    confidence: float = Field(0.5, ge=0, le=1)
    planner: str = "rules"
    steps: tuple[Step, ...] = ()
