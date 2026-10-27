"""DocumentAgent — the public entry point.

from inklight import DocumentAgent
with DocumentAgent() as agent:
    print(agent.text("letter.pdf"))                                   # the text, page by page
    record = agent.extract(["card.pdf"], fields=["registration number"])[0]
    hits = agent.search("رقم القيد")                                   # passages, each with its page
    # agent.tables("report.pdf") needs document structure: DocumentAgent(structure={"engine": "inklight"})
    # agent.ask(...) is experimental
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..config import Settings, load_settings
from ..errors import InklightError, InputRejected
from ..extract import resolve_field
from ..library import IngestReport, Library, Progress
from ..review import Mode, Review, ReviewStore
from ..schemas import AgentResult, DocStatus, ExtractedValue, Record, TaskState
from .context import Policy, Scratch, ToolContext
from .coverage import unavailable_warning
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
        self._owns_library = library is None  # a library passed in belongs to the caller
        self._reviews: ReviewStore | None = None
        self.library = library or Library(settings)
        self.policy = Policy(allow_write=allow_write, output_dir=Path(output_dir).resolve() if output_dir else None)
        lim = settings.limits
        self.runner = Runner(lim.max_steps, lim.task_timeout_s, lim.step_timeout_s, lim.max_retries)
        self._active: set[threading.Event] = set()
        self._idle = threading.Condition()
        self._closed = False

    # -- lifecycle ----------------------------------------------------------

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self, timeout: float = 10.0) -> None:
        """Cancel running tasks, wait up to ``timeout`` s for them, then release what the agent owns.

        Idempotent. A library passed to the constructor is left open for its owner to close.
        """
        with self._idle:
            if self._closed:
                return
            self._closed = True
            for event in self._active:
                event.set()
            self._idle.wait_for(lambda: not self._active, timeout=timeout)
        if self._owns_library:
            self.library.close()

    def __enter__(self) -> DocumentAgent:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _start(self, cancel: threading.Event | None) -> threading.Event:
        with self._idle:
            if self._closed:
                raise InklightError("This DocumentAgent is closed")
            event = cancel or threading.Event()
            self._active.add(event)
            return event

    def _finish(self, event: threading.Event) -> None:
        with self._idle:
            self._active.discard(event)
            self._idle.notify_all()

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
        explicit = files is not None or doc_ids is not None
        return self.run_plan(plan, scope, report=report, policy=policy, cancel=cancel, save=save, explicit=explicit)

    def run_plan(
        self,
        plan: Plan,
        doc_ids: list[str],
        *,
        report: IngestReport | None = None,
        policy: Policy | None = None,
        cancel: threading.Event | None = None,
        save: bool = True,
        explicit: bool = False,
    ) -> AgentResult:
        ready, unavailable = self._readiness(doc_ids)
        requested = list(dict.fromkeys(doc_ids))  # the selection as given, once each
        scratch = Scratch(doc_ids=ready, explicit=explicit, requested=requested, unavailable=unavailable)
        if report:
            for path, error in report.failed:
                scratch.warn(f"Skipped {Path(path).name}: {error}")
                scratch.unavailable.append(
                    {"doc_id": None, "document": Path(path).name, "status": "failed", "error": str(error)}
                )
            scratch.warnings.extend(report.warnings)
        for item in scratch.unavailable[: len(unavailable)]:
            scratch.warn(unavailable_warning(item))
        if scratch.unavailable:
            scratch.partial = True  # an answer from part of the selection is not an answer for all of it
        if not doc_ids and not scratch.unavailable:
            scratch.warn("No documents in scope. Add some with `inklight process <folder>` or pass files=.")
        event = self._start(cancel)  # close() cancels tasks still running and waits for them
        try:
            ctx = ToolContext(
                library=self.library,
                plan=plan,
                policy=policy or self.policy,
                scratch=scratch,
                cancel=event,
            )
            if not plan.steps:
                plan = plan.model_copy(update={"steps": steps_for(plan)})
            result = self.runner.run(ctx, plan)
            if save:
                self.library.store.save_task(result)
            return result
        finally:
            self._finish(event)

    def _readiness(self, doc_ids: list[str]) -> tuple[list[str], list[dict[str, Any]]]:
        """Split a selection into the documents that can be read now and those that cannot (failed, still being read,
        or no longer in the library). Nothing is re-processed here: asking a question never retries an import."""
        ready: list[str] = []
        unavailable: list[dict[str, Any]] = []
        for doc_id in dict.fromkeys(doc_ids):
            doc = self.library.get(doc_id)
            if doc is not None and doc.status == DocStatus.READY:
                ready.append(doc_id)
            elif doc is None:
                unavailable.append({"doc_id": doc_id, "document": doc_id, "status": "missing", "error": None})
            else:
                unavailable.append(
                    {"doc_id": doc_id, "document": doc.name, "status": doc.status.value, "error": doc.error}
                )
        return ready, unavailable

    async def ask_async(self, request: str, files: Iterable[str | Path] | None = None, **kw: Any) -> AgentResult:
        return await asyncio.to_thread(self.ask, request, files, **kw)

    def ask_many(self, requests: list[str], files: Iterable[str | Path] | None = None) -> list[AgentResult]:
        files_list = list(files) if files is not None else None
        return [self.ask(r, files_list) for r in requests]

    @property
    def reviews(self) -> ReviewStore:
        """Human review of extracted values (see inklight.review)."""
        if self._reviews is None:
            self._reviews = ReviewStore(self.library.store)
        return self._reviews

    def open_review(
        self,
        doc_id: str,
        fields: list[str],
        *,
        reviewer: str,
        mode: Mode = "review",
        cohort: str | None = None,
        split: str | None = None,
        baseline: str | None = None,
    ) -> Review:
        """Extract ``fields`` from one library document and open a review of the predictions."""
        doc = self.library.get(doc_id)
        if doc is None:
            raise InputRejected(f"Unknown document {doc_id!r}")
        names = [resolve_field(f).name for f in fields]
        record = self.extract([doc.path], fields=names)[0]
        record = self._fill_from_labels(doc_id, record, names)
        return self.reviews.open(
            doc, record, names, mode=mode, reviewer=reviewer, cohort=cohort, split=split, baseline=baseline
        )

    def _fill_from_labels(self, doc_id: str, record: Record, names: list[str]) -> Record:
        """A field the typed extractor left empty is proposed from the same place an answer would come from: the
        value printed at a label of that name, or in the table cell under that heading. Only such supported values
        are used (a passage is never proposed as a field's value); the reviewer still decides each one."""
        filled = dict(record.fields)
        for name in names:
            current = filled.get(name)
            if current is not None and current.value is not None:
                continue
            result = self.ask(f"What is the {name.replace('_', ' ')}?", doc_ids=[doc_id], save=False)
            if result.outcome != "supported" or not result.sources:
                continue
            value = result.answer.split("\n\nEvidence:")[0].strip()
            filled[name] = ExtractedValue(
                field=name,
                value=value,
                raw=value,
                confidence=result.evidence_confidence,
                method="label or table cell",
                warning=None,
                source=result.sources[0],
            )
        return record.model_copy(update={"fields": filled})

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
        elif fields:
            # Named fields are read directly, in any language ("رقم القيد"), without going through the planner.
            specs = [resolve_field(f) for f in fields]
            names = [s.name for s in specs]
        else:
            specs, names = None, []
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
            return [
                extract_record(d, self.library.pages(d.id), specs, day_first=day_first, reread=self.library.rereader(d))
                for d in docs
            ]
        result = self.run_plan(plan.model_copy(update={"steps": steps_for(plan)}), scope, save=False)
        if result.state == TaskState.FAILED:
            raise InputRejected(result.answer)
        return list(result.records)

    def text(self, file: str | Path, *, password: str | None = None) -> str:
        """A document's text as read, page by page (raw extraction: not reviewed). No question, plan or model."""
        from .. import exports

        return exports.export(self, self._one(file, password), "txt")[0]

    def tables(self, file: str | Path, *, password: str | None = None) -> list[dict[str, Any]]:
        """The tables document structure recovered, each ``{"index", "page", "header_rows", "rows"}`` with
        ``rows`` a list of cell texts (raw extraction: not reviewed). Needs document structure turned on."""
        from .. import exports

        if not self.settings.structure.enabled:
            raise InputRejected(
                'Table extraction needs document structure: pip install "inklight[structure]", then '
                'DocumentAgent(structure={"engine": "inklight"}) or [structure] engine = "inklight" in the config'
            )
        return exports.tables(self, self._one(file, password).id)

    def _one(self, file: str | Path, password: str | None) -> Any:
        report = self.add([file], password=password)
        if not report.documents:
            reasons = "; ".join(f"{Path(p).name}: {e}" for p, e in report.failed) or "not a supported file"
            raise InputRejected(f"Could not read {Path(file).name} ({reasons})")
        return report.documents[0]

    def search(self, query: str, k: int = 8) -> list[Any]:
        return self.library.search(query, k=k)

    @staticmethod
    def tools() -> list[dict[str, Any]]:
        return describe_tools()


__all__ = ["DocumentAgent", "Policy", "Plan", "Intent", "TOOLS"]
