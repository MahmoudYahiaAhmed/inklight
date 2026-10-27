"""HTTP API + static workspace UI.

Security model (local-first):
* binds to localhost by default; a Host-header allow-list blocks DNS rebinding;
* every mutating request needs the ``X-Inklight: 1`` header (no CORS is
  enabled, so other sites cannot send it: CSRF protection);
* optional shared token via ``INKLIGHT_SERVER_TOKEN`` for non-local binds;
* uploads are size-limited, renamed, type-checked and stored under the home folder;
* the agent may only write into the outputs folder, and only when the user ticks
  "allow saving" for that request.
"""

from __future__ import annotations

import contextlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__, build_commit, modelstore
from .._brand import NAME, TAGLINE
from ..agent import DocumentAgent, Policy
from ..config import Settings
from ..errors import InklightError, InputRejected
from ..safety import SUPPORTED_EXTENSIONS, safe_filename
from ..structure.run import available as structure_available
from . import review_api, workspace
from .jobs import TERMINAL, Jobs
from .render import preview_png, render_page

STATIC = Path(__file__).parent / "static"
# The workspace's scripts are ES modules, which browsers run only when served as JavaScript; some Windows
# registries map .js to text/plain, so the types are set here.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


class AskBody(BaseModel):
    request: str = Field(min_length=1, max_length=4000)
    doc_ids: list[str] | None = Field(None, max_length=500)
    allow_write: bool = False
    job_id: str | None = Field(None, pattern=r"^[A-Za-z0-9_-]{6,40}$")


class ExtractBody(BaseModel):
    doc_ids: list[str] = Field(min_length=1, max_length=500)
    fields: list[str] = Field(min_length=1, max_length=30)


class SettingsBody(BaseModel):
    brain: str | None = Field(None, pattern="^(auto|local|rules)$")
    use_writer: bool | None = None


def _hostname(raw: str) -> str:
    """Host header without the port; IPv6 literals keep their brackets."""
    if raw.startswith("["):
        return raw.split("]")[0] + "]"
    return raw.rsplit(":", 1)[0] if raw.count(":") == 1 else raw


def _discard(path: Path) -> None:
    """Delete an uploaded file, and its own folder when that is now empty."""
    path.unlink(missing_ok=True)
    with contextlib.suppress(OSError):
        path.parent.rmdir()  # only succeeds for an empty per-upload folder


def create_app(settings: Settings, agent: DocumentAgent | None = None) -> FastAPI:
    owned = None if agent is not None else DocumentAgent(settings)  # an agent passed in belongs to the caller
    state: dict[str, Any] = {"agent": agent or owned, "jobs": {}, "imports": Jobs(), "swapped": []}

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        # Shutdown: agents swapped in by /api/settings share the original store, so close them first.
        for extra in state["swapped"]:
            extra.close()
            extra.library.close()
        if owned is not None:
            owned.close()

    app = FastAPI(
        title=f"{NAME} API",
        version=__version__,
        description=TAGLINE,
        docs_url="/api/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.inklight = state  # read-only introspection (tests, health checks)
    lock = threading.Lock()
    token = os.environ.get("INKLIGHT_SERVER_TOKEN", "")
    # Bound the whole upload before Starlette spools it to disk: per-file limit x a modest batch.
    max_body = int(settings.limits.max_file_mb * 1024 * 1024 * min(settings.limits.max_files_per_task, 20))
    extra_hosts = {h.strip() for h in os.environ.get("INKLIGHT_ALLOWED_HOSTS", "").split(",") if h.strip()}

    def current() -> DocumentAgent:
        return state["agent"]  # type: ignore[no-any-return]

    @app.middleware("http")
    async def guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        if _hostname(request.headers.get("host", "")) not in LOCAL_HOSTS | extra_hosts:
            return JSONResponse({"detail": "Host not allowed"}, status_code=403)
        if token and request.url.path.startswith("/api/"):
            # Header for API calls; query param only because <img> previews cannot send headers.
            given = request.headers.get("x-inklight-token") or request.query_params.get("token") or ""
            if not hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8")):
                return JSONResponse({"detail": "Missing or wrong token"}, status_code=401)
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > max_body:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-inklight") != "1":
            return JSONResponse({"detail": "Missing X-Inklight header"}, status_code=403)
        response = await call_next(request)
        if not request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"  # revalidate the workspace's files after an upgrade
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(InklightError)
    async def _inklight_error(_: Request, exc: InklightError) -> JSONResponse:
        status = 400 if isinstance(exc, InputRejected) else 422
        return JSONResponse({"detail": str(exc)}, status_code=status)

    # -- status & settings ----------------------------------------------------

    review_api.register(app, current)  # human review: /api/reviews

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        a = current()
        return {
            "name": NAME,
            "tagline": TAGLINE,
            "version": __version__,
            "commit": build_commit(),
            "models": a.library.brain.status(),
            "brain": a.settings.models.brain,
            "use_writer": a.settings.models.use_writer,
            "stats": a.library.store.stats(),
            "limits": a.settings.limits.model_dump(),
            "ocr": a.settings.ocr.model_dump(),
            "structure": {
                "enabled": a.settings.structure.enabled,
                "installed": structure_available(),
                "table_mode": a.settings.structure.table_mode,
            },
            "downloads": modelstore.downloads(),  # model files being fetched on first use: {set: state, done, total}
            "privacy": a.settings.privacy.model_dump(),
            "outputs": str(a.settings.outputs),
            "tools": DocumentAgent.tools(),
        }

    @app.post("/api/settings")
    def update_settings(body: SettingsBody) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        if body.brain is not None:
            changes["brain"] = body.brain
        if body.use_writer is not None:
            changes["use_writer"] = body.use_writer
        with lock:
            old = current()
            new_settings = old.settings.with_overrides(models=changes)
            from ..library import Library

            library = Library(new_settings, store=old.library.store, engine=old.library._engine)
            state["agent"] = DocumentAgent(new_settings, library=library)
            state["swapped"].append(state["agent"])  # released at shutdown; the store stays with its owner
        return status()

    # -- documents -----------------------------------------------------------

    @app.get("/api/documents")
    def documents() -> list[dict[str, Any]]:
        return [d.model_dump(mode="json") for d in current().library.documents()]

    async def _save_uploads(files: list[UploadFile]) -> tuple[list[Path], list[dict[str, Any]]]:
        a = current()
        limit = int(a.settings.limits.max_file_mb * 1024 * 1024)
        if len(files) > a.settings.limits.max_files_per_task:
            raise HTTPException(413, "Too many files in one upload")
        folder = a.settings.uploads
        folder.mkdir(parents=True, exist_ok=True)
        saved: list[Path] = []
        rejected: list[dict[str, Any]] = []
        for up in files:
            name = safe_filename(Path(up.filename or "upload").name, "upload")
            if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
                rejected.append({"file": up.filename, "error": "unsupported file type"})
                continue
            # Each upload in a folder of its own: the library shows the file's own name, and two uploads with
            # the same name never overwrite each other.
            target = folder / secrets.token_hex(4) / name
            target.parent.mkdir()
            size = 0
            with target.open("wb") as fh:
                while chunk := await up.read(1 << 20):
                    size += len(chunk)
                    if size > limit:
                        break
                    fh.write(chunk)
            if size > limit:
                _discard(target)
                rejected.append({"file": up.filename, "error": f"larger than {a.settings.limits.max_file_mb:g} MB"})
                continue
            saved.append(target)
        return saved, rejected

    def _import_result(report: Any, rejected: list[dict[str, Any]]) -> dict[str, Any]:
        """The response for an import; files that failed or were not read are removed from the uploads folder."""
        failed = [
            {"file": Path(p).name, "error": e.replace(f"{Path(p).name}: ", "")}
            for p, e in (report.failed if report else [])
        ]
        for p, _ in report.failed if report else []:
            _discard(Path(p))
        for p in report.cancelled if report else []:
            _discard(Path(p))
        return {
            "documents": [d.model_dump(mode="json") for d in (report.documents if report else [])],
            "failed": rejected + failed,
            "cancelled": [Path(p).name for p in (report.cancelled if report else [])],
            "warnings": list(report.warnings) if report else [],
            "seconds": round(report.seconds, 2) if report else 0,
        }

    @app.post("/api/documents")
    async def upload(files: list[UploadFile] = File(...), background: bool = False) -> dict[str, Any]:
        """Import files. By default the response comes when every file is read. With ``background=true`` it comes at
        once, with a job to follow: /api/jobs/{id} and /api/jobs/{id}/events report each file and page as it is read.
        """
        a = current()
        saved, rejected = await _save_uploads(files)
        if background:
            job = state["imports"].start_import(
                saved, rejected, a.library.add, lambda report: _import_result(report, rejected)
            )
            return {"job": job}
        try:
            report = await run_in_threadpool(a.library.add, list[str | Path](saved)) if saved else None
        except Exception:
            for path in saved:  # never leave orphaned uploads behind
                _discard(Path(path))
            raise
        return _import_result(report, rejected)

    def _structured_library() -> Any:
        """A library over the same store, OCR engine and models, with document structure on (made once)."""
        a = current()
        lib = state.get("structured")
        if lib is None or lib.store is not a.library.store:
            from ..library import Library

            settings = a.settings.with_overrides(structure={"engine": "inklight"})
            lib = Library(settings, store=a.library.store, engine=a.library.engine, brain=a.library.brain)
            state["structured"] = lib
        return lib

    @app.post("/api/documents/{doc_id}/structure")
    def structure_document_job(doc_id: str) -> dict[str, Any]:
        """Read a document again with document structure (layout, reading order, tables), as a background job
        followed like an import. Needs the structure install. The file itself is never removed."""
        from ..structure.run import available

        info = _doc(doc_id)
        if not available():
            raise HTTPException(409, 'Document structure is not installed: pip install "inklight[structure]"')
        path = Path(info.path)
        if not path.exists():
            raise HTTPException(409, f"{info.name} is no longer on disk; import it again")
        lib = _structured_library()

        def finish(report: Any) -> dict[str, Any]:
            return {
                "documents": [d.model_dump(mode="json") for d in report.documents],
                "failed": [{"file": Path(f).name, "error": e} for f, e in report.failed],
                "cancelled": [Path(f).name for f in report.cancelled],
                "warnings": list(report.warnings),
                "seconds": round(report.seconds, 2),
            }

        job = state["imports"].start_import([path], [], lib.add, finish, kind="structure")
        return {"job": job}

    @app.get("/api/jobs")
    def jobs() -> list[dict[str, Any]]:
        """Recent imports, newest first, so a reloaded page can find one still running."""
        return state["imports"].recent()  # type: ignore[no-any-return]

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict[str, Any]:
        snap = state["imports"].snapshot(job_id)
        if snap is None:
            raise HTTPException(404, "Unknown job")
        return snap  # type: ignore[no-any-return]

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str) -> StreamingResponse:
        """Server-sent events: the job's state each time it changes, until it ends."""
        if state["imports"].snapshot(job_id) is None:
            raise HTTPException(404, "Unknown job")

        async def stream() -> AsyncIterator[str]:
            version = -1
            while True:
                snap = await run_in_threadpool(state["imports"].wait, job_id, version, 15.0)
                if snap is None:
                    return
                if snap["version"] == version:
                    yield ": still running\n\n"  # keeps the connection open through proxies
                    continue
                version = snap["version"]
                yield f"data: {json.dumps(snap)}\n\n"
                if snap["state"] in TERMINAL:
                    return

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.get("/api/jobs/{job_id}/files/{index}/preview")
    def job_preview(job_id: str, index: int) -> Response:
        """The first page of a file in an import, as uploaded (before it is read), for the progress view."""
        path = state["imports"].path(job_id, index)
        png = preview_png(path) if path is not None and path.exists() else None
        if png is None:
            raise HTTPException(404, "No preview available")
        return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=600"})

    def _doc(doc_id: str):  # type: ignore[no-untyped-def]
        if not re.fullmatch(r"[0-9a-f]{16}", doc_id):
            raise HTTPException(404, "Unknown document")
        info = current().library.get(doc_id)
        if info is None:
            raise HTTPException(404, "Unknown document")
        return info

    @app.get("/api/documents/{doc_id}")
    def document(doc_id: str) -> dict[str, Any]:
        info = _doc(doc_id)
        pages = current().library.pages(doc_id)
        return {
            "document": info.model_dump(mode="json"),
            "pages": [p.model_dump(mode="json") for p in pages],
            "structure": workspace.structure_status(current(), info, pages),
        }

    @app.get("/api/documents/{doc_id}/tables")
    def document_tables(doc_id: str) -> list[dict[str, Any]]:
        """The document's tables as grids (rows of cell text, header rows, page), when its structure is stored."""
        _doc(doc_id)
        return workspace.tables(current(), doc_id)

    @app.get("/api/documents/{doc_id}/export")
    def document_export(doc_id: str, format: str = "txt") -> Response:  # noqa: A002 - the query parameter name
        """Raw extraction, as read (not reviewed): format=txt (text by page), json (pages, lines with boxes and OCR
        confidence, blocks) or tables.csv (every table's cells)."""
        info = _doc(doc_id)
        try:
            body, media, suffix = workspace.export(current(), info, format)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        name = f"{Path(info.name).stem}-raw.{suffix}"
        return Response(
            body,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{safe_filename(name, "export")}"'},
        )

    @app.get("/api/documents/{doc_id}/structure")
    def document_structure(doc_id: str, format: str = "json") -> Response:  # noqa: A002 - the query parameter name
        """The document's structure: format=json (docling-core's document format), md, html or meta (what ran)."""
        _doc(doc_id)
        stored = current().library.structure(doc_id)
        if stored is None:
            raise HTTPException(404, "No structure stored for this document")
        meta, docling_doc = stored
        if format == "meta":
            return JSONResponse(meta)
        if docling_doc is None:
            raise HTTPException(409, "The structure's text is not stored, or docling-core is not installed")
        if format == "json":
            return JSONResponse(docling_doc.export_to_dict())
        if format == "md":
            return Response(
                docling_doc.export_to_markdown(traverse_pictures=True), media_type="text/markdown; charset=utf-8"
            )
        if format == "html":
            headers = (
                {"X-Inklight-Note": "The HTML export leaves out text inside pictures; md and json keep it"}
                if any(pic.children for pic in docling_doc.pictures)
                else {}
            )
            return Response(docling_doc.export_to_html(), media_type="text/html; charset=utf-8", headers=headers)
        raise HTTPException(400, "format must be json, md, html or meta")

    @app.delete("/api/documents/{doc_id}")
    def delete(doc_id: str) -> dict[str, Any]:
        info = _doc(doc_id)
        a = current()
        a.library.remove(doc_id)
        uploads = a.settings.uploads.resolve()
        path = Path(info.path).resolve()
        if uploads in (path.parent, path.parent.parent):  # only files we stored ourselves are deleted from disk
            _discard(path)
        return {"removed": doc_id}

    @app.get("/api/documents/{doc_id}/pages/{number}/image")
    def page_image(doc_id: str, number: int) -> Response:
        info = _doc(doc_id)
        pages = {p.number: p for p in current().library.pages(doc_id)}
        page = pages.get(number)
        if page is None:
            raise HTTPException(404, "Unknown page")
        png = render_page(Path(info.path), number, page, current().settings.ocr.dpi)
        if png is None:
            raise HTTPException(404, "No preview available")
        return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=600"})

    # -- agent ---------------------------------------------------------------

    @app.post("/api/ask")
    async def ask(body: AskBody) -> dict[str, Any]:
        a = current()
        cancel = threading.Event()
        if body.job_id:
            state["jobs"][body.job_id] = cancel
        policy = Policy(allow_write=body.allow_write, output_dir=a.settings.outputs)
        try:
            result = await run_in_threadpool(
                a.ask, body.request, None, doc_ids=body.doc_ids, policy=policy, cancel=cancel
            )
        finally:
            if body.job_id:
                state["jobs"].pop(body.job_id, None)
        return result.model_dump(mode="json")

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        """Stop a running request (Ask), or an import before its next file."""
        event = state["jobs"].get(job_id)
        if event is not None:
            event.set()
            return {"cancelled": True}
        return {"cancelled": state["imports"].cancel(job_id)}

    @app.post("/api/extract")
    async def extract(body: ExtractBody) -> dict[str, Any]:
        a = current()
        paths = [_doc(i).path for i in body.doc_ids]
        records = await run_in_threadpool(a.extract, paths, body.fields)
        return {"records": [r.model_dump(mode="json") for r in records]}

    @app.get("/api/search")
    def search(q: str, k: int = 10) -> list[dict[str, Any]]:
        if not q.strip() or len(q) > 2000:
            raise HTTPException(400, "Query must be 1-2000 characters")
        return [h.model_dump(mode="json") for h in current().library.search(q, k=max(1, min(k, 50)))]

    @app.get("/api/tasks")
    def tasks(limit: int = 50) -> list[dict[str, Any]]:
        return current().library.store.list_tasks(max(1, min(limit, 200)))

    @app.get("/api/tasks/{task_id}")
    def task(task_id: str) -> dict[str, Any]:
        result = current().library.store.get_task(task_id)
        if result is None:
            raise HTTPException(404, "Unknown task")
        return result.model_dump(mode="json")

    @app.get("/api/outputs/{name}")
    def output(name: str) -> FileResponse:
        root = current().settings.outputs.resolve()
        target = (root / safe_filename(name)).resolve()
        if target.parent != root or not target.is_file():
            raise HTTPException(404, "Unknown output")
        return FileResponse(target, filename=target.name)

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app
