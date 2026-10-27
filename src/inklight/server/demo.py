"""Public demo sessions: every visitor gets a library of their own, in a temporary folder deleted when it expires.

A session is a random cookie value. Its library (documents, index, questions, reviews, exports), its uploads and its
import jobs live only in that session, so a document, job or review id from another session is simply unknown. The
OCR engine and its model weights are loaded once and shared, and one import reads at a time across every visitor,
behind a short queue. Sessions end a fixed time after they start; their folder is removed by a sweeper that waits for
a running import to finish first. The demo folder is never the owner's library, and is removed when the server stops
if the server created it.
"""

from __future__ import annotations

import contextlib
import ipaddress
import logging
import secrets
import shutil
import tempfile
import threading
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..agent import DocumentAgent
from ..brains import Brain
from ..config import Settings
from ..errors import ConfigError
from ..library import Library
from ..ocr import create_engine
from .hosting import DemoLimits
from .jobs import Jobs

log = logging.getLogger(__name__)
SWEEP_SECONDS = 20.0


class DemoBusy(Exception):
    """The demo cannot take this visitor or request now; the message says why and what to do."""

    def __init__(self, message: str, status: int = 503) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Session:
    folder: Path
    agent: DocumentAgent
    jobs: Jobs
    created: float
    expires: float
    asks: dict[str, threading.Event] = field(default_factory=dict)
    asking: threading.Lock = field(default_factory=threading.Lock)
    structured: Any = None  # a Library with structure on, made when first asked for
    writes: deque[float] = field(default_factory=deque)
    reads: deque[float] = field(default_factory=deque)
    in_flight: int = 0  # requests being answered; a session is never removed under one

    def busy(self) -> bool:
        return self.jobs.active() > 0 or self.asking.locked() or self.in_flight > 0

    def queued_files(self) -> int:
        return sum(len(j["files"]) for j in self.jobs.recent() if j["state"] in ("queued", "running"))


class DemoSessions:
    def __init__(self, base: Settings, limits: DemoLimits, root: Path | None = None) -> None:
        self.limits = limits
        self._own_root = root is None
        self.root = Path(tempfile.mkdtemp(prefix="inklight-demo-")) if root is None else Path(root).resolve()
        owner = base.home.expanduser().resolve()
        if self.root == owner or owner in self.root.parents or self.root in owner.parents:
            raise ConfigError(f"The demo folder {self.root} must be separate from the library at {owner}")
        self.root.mkdir(parents=True, exist_ok=True)
        # Visitors never get the owner's outputs, remote model or optional downloads; their files are small.
        self.settings = base.with_overrides(
            home=str(self.root / "template"),
            output_dir=None,
            models={"brain": "rules", "use_writer": False, "allow_download": False, "remote_base_url": None,
                    "remote_for": "never"},
            limits={"max_file_mb": limits.max_file_mb, "max_pages": limits.max_pages,
                    "max_files_per_task": limits.max_files_per_upload},
        )  # fmt: skip
        self.engine = create_engine(self.settings.ocr)  # one OCR engine, its models loaded once, for every visitor
        self.brain = Brain(self.settings)
        self.runner = threading.BoundedSemaphore(1)  # one import reads at a time, across all sessions
        self.work = threading.BoundedSemaphore(limits.busy_slots)  # renders, questions, extraction at once
        self._sessions: dict[str, Session] = {}
        self._by_address: dict[str, deque[float]] = {}
        self._reserved = 0  # imports admitted but not yet registered as jobs
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._sweeper = threading.Thread(target=self._sweep_loop, name="inklight-demo-sweeper", daemon=True)
        self._sweeper.start()

    # -- sessions -------------------------------------------------------------

    def get(self, key: str | None) -> Session | None:
        if not key:
            return None
        with self._lock:
            session = self._sessions.get(key)
        return session if session is not None and session.expires > time.time() else None

    def create(self, address: str) -> tuple[str, Session]:
        now = time.time()
        with self._lock:
            live = [s for s in self._sessions.values() if s.expires > now]
            if len(live) >= self.limits.max_sessions:
                raise DemoBusy("The demo is full right now. Try again in a few minutes.")
            for key in [k for k, d in self._by_address.items() if not d or d[-1] < now - 3600]:
                del self._by_address[key]
            recent = self._by_address.setdefault(_network(address), deque())
            while recent and recent[0] < now - 3600:
                recent.popleft()
            if len(recent) >= self.limits.sessions_per_address_per_hour:
                raise DemoBusy("Too many demo sessions from this address in the last hour. Try again later.", 429)
            recent.append(now)
            key = secrets.token_urlsafe(32)
            folder = self.root / secrets.token_hex(8)  # not derived from the cookie
            settings = self.settings.with_overrides(home=str(folder))
            library = Library(settings, engine=self.engine, brain=self.brain)
            session = Session(
                folder=folder,
                agent=DocumentAgent(settings, library=library),
                jobs=Jobs(runner=self.runner),
                created=now,
                expires=now + self.limits.minutes * 60,
            )
            self._sessions[key] = session
        return key, session

    def pending(self) -> int:
        """Imports queued, running or admitted, across every session."""
        with self._lock:
            sessions = list(self._sessions.values())
            reserved = self._reserved
        return sum(s.jobs.active() for s in sessions) + reserved

    @contextlib.contextmanager
    def admit(self, session: Session, files: int) -> Iterator[None]:
        """Hold a place in the shared queue while an import is accepted and registered as a job. Checked and taken
        in one step, so parallel uploads cannot all pass a check made before any of them is counted. One import at
        a time per visitor; documents waiting count against the visitor's limit."""
        with self._lock:
            if session.jobs.active() > 0:
                raise DemoBusy("Your previous import is still being read: wait for it to finish.", 429)
            have = len(session.agent.library.documents()) + session.queued_files()
            if have + files > self.limits.max_documents:
                raise DemoBusy(
                    f"A demo session holds at most {self.limits.max_documents} documents ({have} now). "
                    "Remove some first.",
                    413,
                )
            waiting = self.pending()
            if waiting >= self.limits.queue:
                raise DemoBusy(
                    f"The demo is busy: {waiting} imports are waiting or being read. Try again in a minute.", 429
                )
            self._reserved += 1
        try:
            yield
        finally:
            with self._lock:
                self._reserved -= 1

    def allow(self, session: Session, write: bool) -> bool:
        """Sliding one-minute windows per session: every request, and those that change something."""
        now = time.time()
        windows = [(session.reads, self.limits.reads_per_minute)]
        if write:
            windows.append((session.writes, self.limits.requests_per_minute))
        with self._lock:
            for window, limit in windows:
                while window and window[0] < now - 60:
                    window.popleft()
                if len(window) >= limit:
                    return False
            for window, _ in windows:
                window.append(now)
            return True

    @contextlib.contextmanager
    def serving(self, session: Session) -> Iterator[None]:
        """Count a request in flight, so the sweeper never removes a session while one is being answered."""
        with self._lock:
            session.in_flight += 1
        try:
            yield
        finally:
            with self._lock:
                session.in_flight -= 1

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    # -- expiry -----------------------------------------------------------------

    def sweep(self, now: float | None = None) -> int:
        """Remove expired sessions and their folders; a session still importing or asking waits for the next
        sweep. Returns how many were removed."""
        now = time.time() if now is None else now
        with self._lock:
            done = [k for k, s in self._sessions.items() if s.expires <= now and not s.busy()]
            removed = [self._sessions.pop(k) for k in done]
        for session in removed:
            self._remove(session)
        return len(removed)

    def _remove(self, session: Session) -> None:
        with contextlib.suppress(Exception):
            session.agent.close()
        with contextlib.suppress(Exception):
            session.agent.library.close()
        if session.structured is not None:
            with contextlib.suppress(Exception):
                session.structured.close()
        shutil.rmtree(session.folder, ignore_errors=True)

    def _sweep_loop(self) -> None:
        while not self._stop.wait(SWEEP_SECONDS):
            try:
                self.sweep()
            except Exception:  # noqa: BLE001 - the sweeper must keep running; the next pass retries
                log.exception("demo cleanup failed")

    def close(self) -> None:
        self._stop.set()
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            for event in session.asks.values():
                event.set()
            self._remove(session)
        if self._own_root:
            shutil.rmtree(self.root, ignore_errors=True)


def _network(address: str) -> str:
    """The unit the per-address limit counts: an IPv4 address, or an IPv6 /64 (one site's addresses)."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return address
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)
