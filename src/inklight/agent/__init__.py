"""DocumentAgent — the public entry point.

from inklight import DocumentAgent
agent = DocumentAgent()
result = agent.ask("Extract the invoice number, date, and total", files=["invoice.pdf"])
print(result.answer, result.sources)
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..config import Settings, load_settings
from ..errors import InputRejected
from ..library import IngestReport, Library, Progress
from ..schemas import AgentResult, Record, TaskState
from .context import Policy, Scratch, ToolContext
from .plan import Intent, Plan
from .planner import make_plan, steps_for
from .runner import Runner
from .tools import TOOLS, describe_tools


class DocumentAgent:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        library: Library | None = None,
        allow_write: bool = False,
        output_dir: str | Path | None = None,
        **overrides: Any,
    ) -> None:
        if settings is None:
            settings = load_settings(**overrides)
        elif overrides:
            settings = settings.with_overrides(**overrides)
        self.settings = settings
        self.library = library or Library(settings)
        self.policy = Policy(allow_write=allow_write, output_dir=Path(output_dir).resolve() if output_dir else None)
        lim = settings.limits
        self.runner = Runner(lim.max_steps, lim.task_timeout_s, lim.step_timeout_s, lim.max_retries)
        self._active: dict[str, threading.Event] = {}

    # -- library passthroughs ---------------------------------------------

    def add(
        self, paths: Iterable[str | Path] | str | Path, progress: Progress | None = None, password: str | None = None
    ) -> IngestReport:
        items = [paths] if isinstance(paths, str | Path) else list(paths)
        return self.library.add(items, progress=progress, password=password)

    # -- tasks -------------------------------------------------------------

    def plan(self, request: str) -> Plan:
        return make_plan(request, self.library.brain)

    def ask(
        self,
        request: str,
        files: Iterable[str | Path] | None = None,
        *,
        doc_ids: list[str] | None = None,
        progress: Progress | None = None,
        policy: Policy | None = None,
        cancel: threading.Event | None = None,
        save: bool = True,
    ) -> AgentResult:
        """Run one request over ``files`` (ingested as needed) or the whole library."""
        request = (request or "").strip()
        if not request:
            raise InputRejected("The request is empty")
        if len(request) > 4000:
            raise InputRejected("The request is longer than 4000 characters")
        report: IngestReport | None = None
        if files is not None:
            report = self.add(list(files), progress=progress)
            scope = [d.id for d in report.documents]
            if not scope:
                reasons = "; ".join(f"{Path(p).name}: {e}" for p, e in report.failed) or "no supported files"
                raise InputRejected(f"No readable documents ({reasons})")
        elif doc_ids is not None:
            scope = list(doc_ids)
        else:
            docs = sorted(self.library.documents(), key=lambda d: d.name.lower())
            scope = [d.id for d in docs if d.status.value == "ready"]
        plan = self.plan(request)
        return self.run_plan(plan, scope, report=report, policy=policy, cancel=cancel, save=save)

    def run_plan(
        self,
        plan: Plan,
        doc_ids: list[str],
        *,
        report: IngestReport | None = None,
        policy: Policy | None = None,
        cancel: threading.Event | None = None,
        save: bool = True,
    ) -> AgentResult:
        scratch = Scratch(doc_ids=list(doc_ids))
        if report:
            for path, error in report.failed:
                scratch.warn(f"Skipped {Path(path).name}: {error}")
            scratch.warnings.extend(report.warnings)
        if not doc_ids:
            scratch.warn("No documents in scope. Add some with `inklight process <folder>` or pass files=.")
        ctx = ToolContext(
            library=self.library,
            plan=plan,
            policy=policy or self.policy,
            scratch=scratch,
            cancel=cancel or threading.Event(),
        )
        if not plan.steps:
            plan = plan.model_copy(update={"steps": steps_for(plan)})
        result = self.runner.run(ctx, plan)
        if save:
            self.library.store.save_task(result)
        return result

    async def ask_async(self, request: str, files: Iterable[str | Path] | None = None, **kw: Any) -> AgentResult:
        return await asyncio.to_thread(self.ask, request, files, **kw)

    def ask_many(self, requests: list[str], files: Iterable[str | Path] | None = None) -> list[AgentResult]:
        files_list = list(files) if files is not None else None
        return [self.ask(r, files_list) for r in requests]

    def extract(
        self,
        files: Iterable[str | Path] | str | Path,
        fields: list[str] | None = None,
        schema: str | Path | dict | None = None,
    ) -> list[Record]:
        """Typed extraction without natural language: returns one Record per document."""
        from ..extract import load_schema, schema_from_dict

        items = [files] if isinstance(files, str | Path) else list(files)
        if schema is not None:
            specs = schema_from_dict(schema) if isinstance(schema, dict) else load_schema(schema)
            names = [s.name for s in specs]
        else:
            specs, names = None, list(fields or [])
        report = self.add(items)
        scope = [d.id for d in report.documents]
        if not scope:
            reasons = "; ".join(f"{Path(p).name}: {e}" for p, e in report.failed) or "no supported files"
            raise InputRejected(f"No readable documents ({reasons})")
        plan = (
            make_plan("extract " + ", ".join(names), self.library.brain)
            if names
            else make_plan("extract fields", self.library.brain)
        )
        plan = plan.model_copy(update={"intent": Intent.EXTRACT, "output": None})
        if specs is not None:
            # Custom specs carry labels/types the planner cannot know; extract them directly.
            from ..extract import extract_record

            docs = [d for d in (self.library.get(i) for i in scope) if d is not None]
            day_first = self.settings.extraction.day_first
            return [extract_record(d, self.library.pages(d.id), specs, day_first=day_first) for d in docs]
        result = self.run_plan(plan.model_copy(update={"steps": steps_for(plan)}), scope, save=False)
        if result.state == TaskState.FAILED:
            raise InputRejected(result.answer)
        return list(result.records)

    def search(self, query: str, k: int = 8) -> list[Any]:
        return self.library.search(query, k=k)

    @staticmethod
    def tools() -> list[dict[str, Any]]:
        return describe_tools()


__all__ = ["DocumentAgent", "Policy", "Plan", "Intent", "TOOLS"]
