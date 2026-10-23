"""Watched-folder automation: index new or changed files, optionally run a request on them.

Polling (no extra dependency, works on every OS and network drive). Files are
only processed once their size and mtime have been stable for one interval,
so half-copied files are not read.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .agent import DocumentAgent, Policy
from .safety import SUPPORTED_EXTENSIONS
from .schemas import AgentResult

log = logging.getLogger(__name__)


@dataclass
class WatchEvent:
    path: str
    kind: str  # indexed | failed | result
    detail: str = ""
    result: AgentResult | None = None


@dataclass
class FolderWatcher:
    agent: DocumentAgent
    folder: Path
    interval: float = 5.0
    request: str | None = None
    policy: Policy | None = None
    on_event: Callable[[WatchEvent], None] | None = None
    stop: threading.Event = field(default_factory=threading.Event)
    _seen: dict[str, tuple[float, int]] = field(default_factory=dict)
    _pending: dict[str, tuple[float, int]] = field(default_factory=dict)

    def scan(self) -> list[Path]:
        """Return files that are new/changed and stable since the previous scan."""
        ready = []
        current: dict[str, tuple[float, int]] = {}
        for p in self.folder.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in SUPPORTED_EXTENSIONS or p.name.startswith("."):
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            key, sig = str(p.resolve()), (st.st_mtime, st.st_size)
            current[key] = sig
            if self._seen.get(key) == sig:
                continue
            if self._pending.get(key) == sig:
                ready.append(Path(key))
            else:
                self._pending[key] = sig
        for key in list(self._pending):
            if key not in current:
                self._pending.pop(key)
        return ready

    def tick(self) -> list[WatchEvent]:
        events: list[WatchEvent] = []
        files = self.scan()
        if not files:
            return events
        report = self.agent.add(files)
        for doc in report.documents:
            self._seen[str(Path(doc.path).resolve())] = self._pending.pop(str(Path(doc.path).resolve()), (0.0, 0))
            events.append(WatchEvent(doc.path, "indexed", f"{doc.pages} pages, {doc.doc_type}"))
        for path, error in report.failed:
            key = str(Path(path).resolve())
            self._seen[key] = self._pending.pop(key, (0.0, 0))
            events.append(WatchEvent(path, "failed", error))
        if self.request and report.added:
            result = self.agent.run_plan(
                self.agent.plan(self.request), [d.id for d in report.added], policy=self.policy
            )
            events.append(WatchEvent(str(self.folder), "result", result.answer[:200], result))
        for event in events:
            if self.on_event:
                self.on_event(event)
        return events

    def run(self) -> None:
        log.info("watching %s every %.1fs", self.folder, self.interval)
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # keep watching; report and continue
                log.exception("watch tick failed")
                if self.on_event:
                    self.on_event(WatchEvent(str(self.folder), "failed", f"{type(exc).__name__}: {exc}"))
            self.stop.wait(self.interval)


def watch(agent: DocumentAgent, folder: str | Path, **kwargs: object) -> FolderWatcher:
    return FolderWatcher(agent=agent, folder=Path(folder).resolve(), **kwargs)  # type: ignore[arg-type]
