"""Per-task state shared by tools. Lives only for one task; never persisted as memory."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..errors import TaskCancelled
from ..schemas import DocumentInfo, PageContent, Record, SearchHit, Source

if TYPE_CHECKING:
    from ..library import Library
    from .plan import Plan


@dataclass(frozen=True)
class Policy:
    """What the agent may do beyond reading. Writing is off unless granted."""

    allow_write: bool = False
    output_dir: Path | None = None
    confirm: Callable[[str], bool] | None = None
    overwrite: bool = False


@dataclass
class Scratch:
    doc_ids: list[str] = field(default_factory=list)
    hits: list[SearchHit] = field(default_factory=list)
    records: list[Record] = field(default_factory=list)
    excluded: list[Record] = field(default_factory=list)
    answer: str = ""
    confidence: float = 0.0
    sources: list[Source] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    calc: dict[str, Any] | None = None
    brain_used: set[str] = field(default_factory=set)
    partial: bool = False  # a tool could only do part of the job (e.g. mixed currencies)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


@dataclass
class ToolContext:
    library: Library
    plan: Plan
    policy: Policy
    scratch: Scratch = field(default_factory=Scratch)
    cancel: threading.Event = field(default_factory=threading.Event)
    deadline: float = float("inf")
    _pages: dict[str, list[PageContent]] = field(default_factory=dict)

    @property
    def brain(self) -> Any:
        return self.library.brain

    @property
    def settings(self) -> Any:
        return self.library.settings

    def check(self) -> None:
        """Cooperative cancellation point; tools call this inside loops."""
        if self.cancel.is_set():
            raise TaskCancelled("Task was cancelled")
        if time.monotonic() > self.deadline:
            raise TaskCancelled("Task time budget exhausted")

    def docs(self) -> list[DocumentInfo]:
        out = []
        for doc_id in self.scratch.doc_ids:
            doc = self.library.get(doc_id)
            if doc is not None:
                out.append(doc)
        return out

    def pages(self, doc_id: str) -> list[PageContent]:
        if doc_id not in self._pages:
            self._pages[doc_id] = self.library.pages(doc_id)
        return self._pages[doc_id]
