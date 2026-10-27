"""The document library: validate, OCR once, chunk, classify and index.

Re-adding an unchanged file is free (same path + same SHA-256). An identical
file at a new path reuses the stored extraction instead of running OCR again.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .brains import Brain
from .chunking import chunk_page
from .config import Settings, load_settings
from .errors import InklightError, InputRejected, OCRError
from .extract import classify
from .ocr import OCREngine, PlainTextEngine, create_engine
from .retrieval import Retriever
from .safety import check_file, discover, injection_signals
from .schemas import BBox, DocStatus, DocumentContent, DocumentInfo, PageContent, SearchHit
from .store import Store

log = logging.getLogger(__name__)

Progress = Callable[[str, str, dict], None]
_STRUCTURE_CACHE = 8
_MAX_WAITING = 1  # documents read and waiting for their structure: one keeps OCR and structure both busy


@dataclass
class IngestReport:
    added: list[DocumentInfo] = field(default_factory=list)
    unchanged: list[DocumentInfo] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def documents(self) -> list[DocumentInfo]:
        return self.added + self.unchanged

    @property
    def pages(self) -> int:
        return sum(d.pages for d in self.added)


def doc_id_for(path: Path) -> str:
    return hashlib.sha256(str(path.resolve()).lower().encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class _Read:
    """A file the OCR has read, waiting to be structured and indexed."""

    path: Path
    kind: str
    doc_id: str
    base: DocumentInfo
    content: DocumentContent
    password: str | None


class Library:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        store: Store | None = None,
        engine: OCREngine | None = None,
        brain: Brain | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.settings.home.mkdir(parents=True, exist_ok=True)
        # Close only what this library created: a store or brain passed in belongs to the caller.
        self._owns_store = store is None
        self._owns_brain = brain is None
        self.store = store or Store(self.settings.db_path)
        self._engine = engine
        self._text_engine = PlainTextEngine()
        self.brain = brain or Brain(self.settings)
        self.retriever = Retriever(self.store, self.brain)
        self._structures: dict[tuple[str, int], Any] = {}  # parsed structured documents, a few at a time
        self._closed = False

    @property
    def engine(self) -> OCREngine:
        if self._engine is None:
            self._engine = create_engine(self.settings.ocr)
        return self._engine

    # -- ingest ------------------------------------------------------------

    def add(
        self,
        paths: list[str | Path] | str | Path,
        *,
        password: str | None = None,
        force: bool = False,
        progress: Progress | None = None,
    ) -> IngestReport:
        """Add files and/or folders. Never raises for a single bad file; see report.failed."""
        started = time.perf_counter()
        if isinstance(paths, str | Path):
            paths = [paths]
        files, skipped = discover(list(paths), self.settings.limits.max_files_per_task)
        report = IngestReport(warnings=skipped)
        structured = self.settings.structure.enabled
        if structured and files:
            self._preload_structure()  # the structure models load while the OCR reads the first document
        # With structure on, document i is structured on one worker while the OCR reads document i+1.
        worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="inklight-structure") if structured else None
        waiting: deque[tuple[Path, Future[tuple[DocumentInfo, bool]]]] = deque()
        try:
            for i, path in enumerate(files):
                if progress:
                    progress("start", str(path), {"index": i, "total": len(files)})
                try:
                    step = self._read_one(path, password=password, force=force)
                except InklightError as exc:
                    self._record(report, path, None, exc, progress)
                    continue
                if not isinstance(step, _Read):
                    self._record(report, path, step, None, progress)
                elif worker is None:
                    self._record(report, path, *self._finish_safely(step), progress)
                else:
                    while len(waiting) >= _MAX_WAITING:  # bound the documents held in memory
                        self._collect(report, waiting.popleft(), progress)
                    waiting.append((path, worker.submit(self._finish, step)))
            while waiting:
                self._collect(report, waiting.popleft(), progress)
        finally:
            if worker is not None:
                worker.shutdown(wait=True)
        if report.added:
            try:
                self.retriever.index_embeddings()
            except Exception as exc:  # embeddings are optional; keyword search still works
                report.warnings.append(f"Semantic index skipped: {exc}")
        report.seconds = time.perf_counter() - started
        return report

    def _record(
        self,
        report: IngestReport,
        path: Path,
        done: tuple[DocumentInfo, bool] | None,
        error: InklightError | None,
        progress: Progress | None,
    ) -> None:
        if error is not None or done is None:
            report.failed.append((str(path), str(error)))
            if progress:
                progress("failed", str(path), {"error": str(error)})
            return
        info, fresh = done
        (report.added if fresh else report.unchanged).append(info)
        if progress:
            progress("done", str(path), {"pages": info.pages, "fresh": fresh, "status": info.status.value})

    def _collect(
        self, report: IngestReport, item: tuple[Path, Future[tuple[DocumentInfo, bool]]], progress: Progress | None
    ) -> None:
        path, future = item
        try:
            self._record(report, path, future.result(), None, progress)
        except InklightError as exc:
            self._record(report, path, None, exc, progress)

    def _finish_safely(self, step: _Read) -> tuple[tuple[DocumentInfo, bool] | None, InklightError | None]:
        try:
            return self._finish(step), None
        except InklightError as exc:
            return None, exc

    def _preload_structure(self) -> None:
        """Start loading the structure models in the background (once per process). A failure is reported later, by
        the document whose structure could not be built."""
        from .structure.run import preload

        preload(self.settings.structure)

    def _ingest_one(self, path: Path, *, password: str | None, force: bool) -> tuple[DocumentInfo, bool]:
        """Read, structure and index one file (the steps ``add`` overlaps across files)."""
        step = self._read_one(path, password=password, force=force)
        return self._finish(step) if isinstance(step, _Read) else step

    def _read_one(self, path: Path, *, password: str | None, force: bool) -> _Read | tuple[DocumentInfo, bool]:
        """Check and OCR a file; an unchanged file or an identical copy is done here."""
        checked = check_file(path, self.settings.limits.max_file_mb)
        doc_id = doc_id_for(checked.path)
        existing = self.store.get_document(doc_id)
        unstructured = (
            self.settings.structure.enabled and checked.kind != "text" and self.store.get_structure(doc_id) is None
        )  # read before structure was turned on: read it again, with its structure
        if (
            existing
            and existing.sha256 == checked.sha256
            and existing.status == DocStatus.READY
            and not force
            and not unstructured
        ):
            return existing, False
        base = DocumentInfo(
            id=doc_id,
            path=str(checked.path),
            name=checked.path.name,
            sha256=checked.sha256,
            size=checked.size,
            mtime=checked.mtime,
            status=DocStatus.PENDING,
        )
        self.store.upsert_document(base)
        twin = None if force else self.store.find_ready_by_hash(checked.sha256)
        if twin and self.settings.structure.engine != "none" and self.store.get_structure(twin.id) is None:
            twin = None  # read before structure was on: structure it now rather than copy it without
        if twin and twin.id != doc_id:
            self.store.copy_content(twin.id, doc_id)
            info = base.model_copy(
                update={
                    "pages": twin.pages,
                    "total_pages": twin.total_pages,
                    "status": DocStatus.READY,
                    "doc_type": twin.doc_type,
                    "engine": twin.engine,
                    "mean_conf": twin.mean_conf,
                }
            )
            self.store.upsert_document(info)
            return info, True
        engine = self._text_engine if checked.kind == "text" else self.engine
        if not engine.supports(checked.kind):
            raise InputRejected(f"{checked.path.name}: engine {engine.name} cannot read {checked.kind}")
        try:
            content = engine.read(checked.path, max_pages=self.settings.limits.max_pages, password=password)
        except OCRError as exc:
            self.store.clear_content(doc_id)  # an old extraction of a changed file must not stay searchable
            self.store.upsert_document(base.model_copy(update={"status": DocStatus.FAILED, "error": str(exc)}))
            raise
        return _Read(checked.path, checked.kind, doc_id, base, content, password)

    def _finish(self, step: _Read) -> tuple[DocumentInfo, bool]:
        """Structure (when on), chunk, classify and store a document the OCR has read."""
        doc_id, base = step.doc_id, step.base
        content, structure = self._structure(step.path, step.kind, step.content, step.password)
        chunks = [c for page in content.pages for c in chunk_page(page)]
        flagged = {i for i, c in enumerate(chunks) if injection_signals(c.text)}
        text = "\n".join(c.text for c in chunks)
        doc_type, _ = classify(text)
        confs = [p.mean_conf for p in content.pages if p.mean_conf is not None]
        good_pages = [p for p in content.pages if p.source != "error"]
        status = DocStatus.READY if good_pages else DocStatus.FAILED
        error = None if good_pages else "; ".join(content.warnings) or "no readable pages"
        self.store.save_content(
            doc_id, content, chunks, flagged, store_text=self.settings.privacy.store_text, structure=structure
        )
        info = base.model_copy(
            update={
                "pages": len(content.pages),
                "total_pages": content.total_pages,
                "status": status,
                "doc_type": doc_type,
                "engine": content.engine,
                "error": error,
                "mean_conf": round(sum(confs) / len(confs), 4) if confs else None,
            }
        )
        self.store.upsert_document(info)
        if status == DocStatus.FAILED:
            raise OCRError(f"{step.path.name}: {error}")
        if not self.settings.privacy.log_document_text:
            log.info("indexed %s (%d pages, %d chunks)", info.name, info.pages, len(chunks))
        return info, True

    def _structure(
        self, path: Path, kind: str, content: DocumentContent, password: str | None = None
    ) -> tuple[DocumentContent, tuple[str, str, str] | None]:
        """The document structure on the OCR just read, when enabled. A failure keeps the OCR's own layout and says so;
        it never fails the document."""
        settings = self.settings.structure
        if not settings.enabled or kind == "text":
            return content, None
        from .structure import ENGINE, structure_document

        try:
            done = structure_document(path, content, settings, password)
        except Exception as exc:  # noqa: BLE001 - structure is an addition, never a reason to lose the document
            log.warning("structure skipped for %s: %s", path.name, exc)
            return content.model_copy(
                update={"warnings": (*content.warnings, f"Document structure skipped: {type(exc).__name__}: {exc}")}
            ), None
        meta = json.dumps(done.meta, ensure_ascii=False)
        return done.content, (ENGINE, meta, done.document_json)

    def structure(self, doc_id: str) -> tuple[dict, Any] | None:
        """(meta, structured document) stored for a document, or None. The document is None when text is not stored
        (privacy.store_text = false) or docling-core is not installed."""
        stored = self.store.get_structure(doc_id)
        if stored is None:
            return None
        from .structure import load_document

        _engine, meta, document = stored
        key = (doc_id, hash(document))  # parsing a large structure costs more than hashing its JSON
        if key not in self._structures:
            if len(self._structures) >= _STRUCTURE_CACHE:
                self._structures.pop(next(iter(self._structures)))
            self._structures[key] = load_document(document)
        return meta, self._structures[key]

    # -- queries -----------------------------------------------------------

    def documents(self) -> list[DocumentInfo]:
        return self.store.list_documents()

    def get(self, doc_id: str) -> DocumentInfo | None:
        return self.store.get_document(doc_id)

    def pages(self, doc_id: str) -> list[PageContent]:
        return self.store.get_pages(doc_id)

    def text(self, doc_id: str) -> str:
        return self.store.document_text(doc_id)

    def search(self, query: str, doc_ids: list[str] | None = None, k: int = 8) -> list[SearchHit]:
        return self.retriever.search(query, doc_ids, k)

    def find(self, ref: str) -> DocumentInfo | None:
        """Look a document up by id, id prefix, path or file name."""
        doc = self.store.get_document(ref)
        if doc:
            return doc
        p = Path(ref).expanduser()
        if p.exists():
            return self.store.get_document(doc_id_for(p))
        matches = [d for d in self.documents() if d.id.startswith(ref) or d.name == ref]
        return matches[0] if len(matches) == 1 else None

    def remove(self, doc_id: str) -> bool:
        return self.store.delete_document(doc_id)

    def reindex(self, doc_ids: list[str] | None = None, progress: Progress | None = None) -> IngestReport:
        docs = [d for d in self.documents() if doc_ids is None or d.id in doc_ids]
        missing = [d for d in docs if not Path(d.path).exists()]
        report = self.add([d.path for d in docs if Path(d.path).exists()], force=True, progress=progress)
        report.warnings.extend(f"Source file missing, kept old index: {d.path}" for d in missing)
        return report

    @property
    def closed(self) -> bool:
        return self._closed

    def rereader(self, doc: DocumentInfo) -> Callable[[int, BBox], str | None] | None:
        """A function that OCRs one region of ``doc`` again, or None when its engine cannot.

        Used to double-check a suspicious amount; the stored reading is never replaced.
        """
        if not self.settings.extraction.second_reading:
            return None
        engine = self.engine
        reread = getattr(engine, "reread", None)
        path = Path(doc.path)
        if reread is None or doc.engine != getattr(engine, "name", None) or not path.is_file():
            return None

        def again(page: int, bbox: BBox) -> str | None:  # only runs for a suspicious amount
            rotation = next((p.rotation for p in self.pages(doc.id) if p.number == page), 0)
            text: str | None = reread(path, page, bbox, rotation)
            return text

        return again

    def close(self) -> None:
        """Release what this library owns (database connection, loaded models). Idempotent."""
        if self._closed:
            return
        self._closed = True
        if self._owns_brain:
            self.brain.close()
        if self._owns_store:
            self.store.close()

    def __enter__(self) -> Library:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
