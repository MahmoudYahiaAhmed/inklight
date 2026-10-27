"""HTTP API + static workspace UI.

Security model (local-first):
* binds to localhost by default; a Host-header allow-list blocks DNS rebinding;
* every mutating request needs the ``X-Inklight: 1`` header (no CORS is
  enabled, so other sites cannot send it: CSRF protection);
* a shared token (``INKLIGHT_SERVER_TOKEN``) for a private workspace on a network; it gives access to one shared
  library (hosting.py);
* a public demo gives each visitor a temporary library of their own and never the owner's (demo.py);
* uploads are size-limited, renamed, type-checked and stored under the home folder;
* the agent may only write into the outputs folder, and only when the user ticks
  "allow saving" for that request.
"""

from __future__ import annotations

import contextlib
import contextvars
import hmac
import json
import mimetypes
import re
import secrets
import threading
from collections.abc import AsyncIterator, Iterator
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
from .demo import DemoBusy, DemoSessions, Session
from .hosting import LOCAL_HOSTS, DemoLimits, Hosting, is_ip_host
from .jobs import TERMINAL, Jobs
from .render import preview_png, render_page

STATIC = Path(__file__).parent / "static"
# The workspace's scripts are ES modules, which browsers run only when served as JavaScript; some Windows
# registries map .js to text/plain, so the types are set here.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/css", ".css")
DEMO_COOKIE = "inklight_demo"
TOKEN_COOKIE = "inklight_access"  # noqa: S105 - a cookie name, not a secret
_visitor: contextvars.ContextVar[Session | None] = contextvars.ContextVar("inklight_visitor", default=None)


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


def create_app(settings: Settings, agent: DocumentAgent | None = None, hosting: Hosting | None = None) -> FastAPI:
    hosting = hosting or Hosting.from_env()
    # A public demo never opens the owner's library: every visitor gets a temporary one (demo.py).
    demo = DemoSessions(settings, hosting.demo or DemoLimits(), hosting.demo_dir) if hosting.mode == "demo" else None
    owned = None if agent is not None or demo is not None else DocumentAgent(settings)  # a passed agent is the caller's
    state: dict[str, Any] = {"agent": agent or owned, "jobs": {}, "imports": Jobs(), "swapped": [], "demo": demo}

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        # Shutdown: agents swapped in by /api/settings share the original store, so close them first.
        for extra in state["swapped"]:
            extra.close()
            extra.library.close()
        if owned is not None:
            owned.close()
        if demo is not None:
            demo.close()

    app = FastAPI(
        title=f"{NAME} API",
        version=__version__,
        description=TAGLINE,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",  # under /api/, so the token and the demo session apply to it
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.inklight = state  # read-only introspection (tests, health checks)
    lock = threading.Lock()
    token = hosting.token
    # What the access cookie holds: derived from the token, so the cookie never carries the token itself.
    access_mark = hmac.new(token.encode("utf-8"), b"inklight-workspace-access", "sha256").hexdigest() if token else ""
    limits = demo.settings.limits if demo is not None else settings.limits
    # Bound the whole upload before Starlette spools it to disk: per-file limit x a modest batch.
    max_body = int(limits.max_file_mb * 1024 * 1024 * min(limits.max_files_per_task, 20))
    allowed_hosts = LOCAL_HOSTS | hosting.allowed_hosts
    https_only = (hosting.public_url or "").startswith("https://")  # cookies Secure even if the proxy is not trusted

    def visitor() -> Session:
        session = _visitor.get()
        if session is None:
            raise HTTPException(401, "No demo session: reload the page")
        return session

    def current() -> DocumentAgent:
        return visitor().agent if demo is not None else state["agent"]  # type: ignore[no-any-return]

    def imports() -> Jobs:
        """Import jobs: the visitor's own in a demo, the server's otherwise."""
        return visitor().jobs if demo is not None else state["imports"]  # type: ignore[no-any-return]

    def asks() -> dict[str, threading.Event]:
        return visitor().asks if demo is not None else state["jobs"]  # type: ignore[no-any-return]

    def not_in_demo(what: str) -> None:
        if demo is not None:
            raise HTTPException(403, f"{what} is not available in the public demo")

    @contextlib.contextmanager
    def admitted(files: int) -> Iterator[None]:
        """A public demo reads one file at a time for everyone; a full queue is refused, not left waiting."""
        if demo is None:
            yield
            return
        try:
            with demo.admit(visitor(), files):
                yield
        except DemoBusy as exc:
            raise HTTPException(exc.status, str(exc)) from exc

    def in_worker(gate: threading.Lock | None, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Run ``func`` in the thread pool. In a demo the visitor's gate is released by that thread when it ends, not
        by this request (which a closed connection can cancel first), and a shared slot bounds the work."""
        if gate is None:
            return run_in_threadpool(func, *args, **kwargs)

        def run() -> Any:
            try:
                with demo.work:  # type: ignore[union-attr]
                    return func(*args, **kwargs)
            finally:
                gate.release()

        return run_in_threadpool(run)

    @app.middleware("http")
    async def guard(request: Request, call_next):  # type: ignore[no-untyped-def]
        name = _hostname(request.headers.get("host", "")).lower()
        if name not in allowed_hosts and not (hosting.ip_hosts and is_ip_host(name)):
            shown = name[:80] or "(none)"
            return JSONResponse(
                {"detail": f"Host not allowed: {shown}. Inklight answers only for the host names it was started "
                 f"with. To use this one, start it with --public-url https://{shown}/ (or --allowed-host {shown})."},
                status_code=403,
            )  # fmt: skip
        token_cookie = False
        if token and request.url.path.startswith("/api/"):
            # The page sends the token in a header; previews and event streams (which cannot) send the cookie set
            # by the first good request. The cookie holds a value derived from the token, and no URL ever holds
            # either, so neither reaches a proxy's or server's access log.
            given = request.headers.get("x-inklight-token", "")
            if given:
                if not hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8")):
                    return JSONResponse({"detail": "Missing or wrong token"}, status_code=401)
                token_cookie = request.cookies.get(TOKEN_COOKIE) != access_mark
            elif not hmac.compare_digest(request.cookies.get(TOKEN_COOKIE, "").encode(), access_mark.encode()):
                return JSONResponse({"detail": "Missing or wrong token"}, status_code=401)
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > max_body:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-inklight") != "1":
            return JSONResponse({"detail": "Missing X-Inklight header"}, status_code=403)
        if demo is not None and request.method in ("POST", "PUT", "PATCH") and not length.isdigit():
            # A body without a declared size (chunked) could not be bounded before it is stored.
            return JSONResponse({"detail": "A request body must declare its length"}, status_code=411)
        new_key = None
        bound = None
        session: Session | None = None
        if demo is not None and request.url.path.startswith("/api/"):
            session = demo.get(request.cookies.get(DEMO_COOKIE))
            if session is None:
                if request.url.path != "/api/status":  # only loading the workspace starts a session
                    return JSONResponse(
                        {"detail": "Your demo session has ended (its files were deleted) or has not started. "
                         "Reload the page to start a new one."},
                        status_code=401,
                    )  # fmt: skip
                try:
                    new_key, session = await run_in_threadpool(
                        demo.create, request.client.host if request.client else "unknown"
                    )
                except DemoBusy as exc:
                    return JSONResponse({"detail": str(exc)}, status_code=exc.status)
            assert session is not None  # noqa: S101 - set just above, or the request returned
            if not demo.allow(session, write=request.method not in ("GET", "HEAD", "OPTIONS")):
                return JSONResponse({"detail": "Too many requests: wait a minute and try again."}, status_code=429)
            bound = _visitor.set(session)
        try:
            if session is not None and demo is not None:
                with demo.serving(session):
                    response = await call_next(request)
            else:
                response = await call_next(request)
        finally:
            if bound is not None:
                _visitor.reset(bound)
        if new_key is not None and demo is not None:
            response.set_cookie(
                DEMO_COOKIE,
                new_key,
                max_age=demo.limits.minutes * 60,
                httponly=True,
                samesite="strict",
                secure=https_only or request.url.scheme == "https",
            )
        if token_cookie:
            response.set_cookie(
                TOKEN_COOKIE,
                access_mark,
                httponly=True,
                samesite="strict",
                secure=https_only or request.url.scheme == "https",
            )
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
            "hosting": hosting_status(),
        }

    def hosting_status() -> dict[str, Any]:
        if demo is None:
            return {
                "mode": hosting.mode,
                "shared_library": hosting.mode == "private",
                "stream_progress": hosting.stream_progress,
            }
        session = visitor()
        return {
            "mode": "demo",
            "shared_library": False,
            "stream_progress": hosting.stream_progress,
            "expires_at": session.expires,
            "minutes": demo.limits.minutes,
            "limits": {
                "max_documents": demo.limits.max_documents,
                "max_file_mb": demo.limits.max_file_mb,
                "max_pages": demo.limits.max_pages,
                "max_files_per_upload": demo.limits.max_files_per_upload,
            },
        }

    @app.post("/api/settings")
    def update_settings(body: SettingsBody) -> dict[str, Any]:
        not_in_demo("Changing settings")
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
        lib = current().library
        sources = lib.store.page_sources()
        # read_as: how each document's text was obtained (pages by source), as the workspace labels it
        return [d.model_dump(mode="json") | {"read_as": sources.get(d.id, {})} for d in lib.documents()]

    async def _save_uploads(files: list[UploadFile]) -> tuple[list[Path], list[dict[str, Any]]]:
        a = current()
        limit = int(a.settings.limits.max_file_mb * 1024 * 1024)
        if len(files) > a.settings.limits.max_files_per_task:
            raise HTTPException(413, f"Too many files in one upload (at most {a.settings.limits.max_files_per_task})")
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
        if demo is not None and not background:
            raise HTTPException(400, "The public demo imports in the background (background=true)")
        if background:
            with admitted(len(files)):
                saved, rejected = await _save_uploads(files)
                job = imports().start_import(
                    saved,
                    rejected,
                    a.library.add,
                    lambda report: _import_result(report, rejected),
                    on_error=_discard_all,
                )
            return {"job": job}
        saved, rejected = await _save_uploads(files)
        try:
            report = await run_in_threadpool(_add_exclusively, a, list[str | Path](saved)) if saved else None
        except Exception:
            for path in saved:  # never leave orphaned uploads behind
                _discard(Path(path))
            raise
        return _import_result(report, rejected)

    def _structured_library() -> Any:
        """A library over the same store, OCR engine and models, with document structure on (made once)."""
        a = current()
        holder: Any = visitor() if demo is not None else None
        lib = holder.structured if holder is not None else state.get("structured")
        if lib is None or lib.store is not a.library.store:
            from ..library import Library

            settings = a.settings.with_overrides(structure={"engine": "inklight"})
            lib = Library(settings, store=a.library.store, engine=a.library.engine, brain=a.library.brain)
            if holder is not None:
                holder.structured = lib
            else:
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

        with admitted(0):  # the document is already counted; the import still takes a place in the queue
            job = imports().start_import([path], [], lib.add, finish, kind="structure")
        return {"job": job}

    def _discard_all(paths: list[Path]) -> None:
        for path in paths:
            _discard(path)

    def _add_exclusively(a: DocumentAgent, paths: list[str | Path]) -> Any:
        with imports().runner:  # one library read at a time, background jobs included
            return a.library.add(paths)

    @app.get("/api/jobs")
    def jobs() -> list[dict[str, Any]]:
        """Recent imports, newest first, so a reloaded page can find one still running."""
        return imports().recent()

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict[str, Any]:
        snap = imports().snapshot(job_id)
        if snap is None:
            raise HTTPException(404, "Unknown job")
        return snap

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str) -> StreamingResponse:
        """Server-sent events: the job's state each time it changes, until it ends."""
        jobs = imports()  # the visitor's own jobs, taken now: the stream runs after this request's context
        if jobs.snapshot(job_id) is None:
            raise HTTPException(404, "Unknown job")

        async def stream() -> AsyncIterator[str]:
            version = -1
            while True:
                snap = await run_in_threadpool(jobs.wait, job_id, version, 5.0)
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
        path = imports().path(job_id, index)
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
        if demo is not None:
            with demo.work:  # rendering is CPU work: bounded across every visitor
                png = render_page(Path(info.path), number, page, current().settings.ocr.dpi)
        else:
            png = render_page(Path(info.path), number, page, current().settings.ocr.dpi)
        if png is None:
            raise HTTPException(404, "No preview available")
        return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=600"})

    # -- agent ---------------------------------------------------------------

    @app.post("/api/ask")
    async def ask(body: AskBody) -> dict[str, Any]:
        a = current()
        running = asks()
        cancel = threading.Event()
        gate = visitor().asking if demo is not None else None
        if gate is not None and not gate.acquire(blocking=False):
            raise HTTPException(429, "One question at a time in the demo: wait for the current one to finish")
        if body.job_id:
            running[body.job_id] = cancel
        policy = Policy(allow_write=body.allow_write and demo is None, output_dir=a.settings.outputs)
        try:
            result = await in_worker(
                gate, a.ask, body.request, None, doc_ids=body.doc_ids, policy=policy, cancel=cancel
            )
        finally:
            if body.job_id:
                running.pop(body.job_id, None)
        return result.model_dump(mode="json")

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        """Stop a running request (Ask), or an import before its next file."""
        event = asks().get(job_id)
        if event is not None:
            event.set()
            return {"cancelled": True}
        return {"cancelled": imports().cancel(job_id)}

    @app.post("/api/extract")
    async def extract(body: ExtractBody) -> dict[str, Any]:
        a = current()
        paths = [_doc(i).path for i in body.doc_ids]
        gate = visitor().asking if demo is not None else None
        if gate is not None and not gate.acquire(blocking=False):
            raise HTTPException(429, "One request at a time in the demo: wait for the current one to finish")
        records = await in_worker(gate, a.extract, paths, body.fields)
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
        not_in_demo("Saved outputs")
        root = current().settings.outputs.resolve()
        target = (root / safe_filename(name)).resolve()
        if target.parent != root or not target.is_file():
            raise HTTPException(404, "Unknown output")
        return FileResponse(target, filename=target.name)

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app
