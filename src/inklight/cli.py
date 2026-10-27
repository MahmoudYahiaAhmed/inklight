"""The `inklight` command line."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.text import Text

from . import __version__, build_commit
from ._brand import CYAN, NAME, TAGLINE
from .cli_render import (
    banner,
    console,
    documents_table,
    err,
    hits_table,
    records_table,
    result_panel,
    tables_table,
)
from .config import Settings, load_settings
from .errors import InklightError, InputRejected

app = typer.Typer(
    name="inklight", help=f"{NAME} — {TAGLINE}", no_args_is_help=True, add_completion=False, rich_markup_mode="rich"
)
models_app = typer.Typer(
    help="Download (once) and check the models: OCR, document structure, Ask.", no_args_is_help=True
)
app.add_typer(models_app, name="models", rich_help_panel="Setup")
review_app = typer.Typer(
    help="Human review of extracted values (open reviews in `inklight serve`).", no_args_is_help=True
)
app.add_typer(review_app, name="review", rich_help_panel="Review and export")

ConfigOpt = Annotated[Path | None, typer.Option("--config", "-c", help="Path to a config.toml.")]
BrainOpt = Annotated[str | None, typer.Option("--brain", help="auto | local | rules")]


def _settings(config: Path | None, brain: str | None = None) -> Settings:
    overrides = {"models": {"brain": brain}} if brain else {}
    return load_settings(config, **overrides)


def _agent(
    config: Path | None, brain: str | None = None, out: Path | None = None, yes: bool = False, structure: bool = False
):  # type: ignore[no-untyped-def]  # noqa: E501
    from .agent import DocumentAgent

    settings = _settings(config, brain)
    if structure and not settings.structure.enabled:  # an operation that needs it turns it on for this run
        settings = settings.with_overrides(structure={"engine": "inklight"})
    agent = DocumentAgent(settings, allow_write=bool(out) or yes, output_dir=out)
    _OPENED.append(agent)  # closed by the root context's close callback
    return agent


_OPENED: list = []


def _close_opened() -> None:
    while _OPENED:
        _OPENED.pop().close()


def _fail(exc: Exception) -> None:
    err.print(Text.assemble(("✗ ", "bad"), (str(exc), "")))
    raise typer.Exit(1)


def _progress() -> Progress:
    return Progress(
        SpinnerColumn(style=CYAN),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(complete_style=CYAN),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )


def _ensure_models(settings) -> None:  # type: ignore[no-untyped-def]
    """Fetch the models a run needs before it starts, with a progress bar on first use (verified copies are used
    as they are, without network access)."""
    from . import modelstore
    from .structure.run import available as structure_available

    wanted = [(modelstore.OCR, settings.ocr.model_dir)]
    if settings.structure.enabled and structure_available():
        tables = modelstore.TABLES if settings.structure.table_mode == "accurate" else modelstore.TABLES_FAST
        wanted += [(modelstore.LAYOUT, None), (tables, None)]
    for model, local in wanted:
        if modelstore.locate(model, local) is not None:
            continue
        if modelstore.offline():
            try:
                modelstore.ensure(model, local)  # says what is missing and how to fetch it
            except InklightError as exc:
                _fail(exc)
        mb = model.size / 1e6
        console.print(Text(f"First use: downloading the {model.title} models ({mb:.0f} MB, once).", "accent"))
        with _progress() as bar:
            task = bar.add_task(f"Downloading {model.title}", total=model.size)

            def on(_what: str, done: int, total: int, task=task, bar=bar) -> None:  # type: ignore[no-untyped-def]
                bar.update(task, completed=done, total=total)

            try:
                modelstore.ensure(model, local, progress=on)
            except InklightError as exc:
                _fail(exc)


def _ingest_with_progress(agent, paths: list[str], password: str | None = None, force: bool = False):  # type: ignore[no-untyped-def]
    from .safety import discover, needs_ocr

    # Fetch models up front only for files that can need them: text files are read without any model.
    files, _ = discover(list(paths), agent.settings.limits.max_files_per_task)
    if any(needs_ocr(f) for f in files):
        _ensure_models(agent.settings)
    with _progress() as bar:
        task = bar.add_task("Reading documents", total=None)

        def on(event: str, path: str, info: dict) -> None:
            if event == "start":
                bar.update(task, total=info["total"], description=f"Reading {Path(path).name}")
            else:
                bar.advance(task)

        return agent.library.add(paths, progress=on, password=password, force=force)


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: Annotated[bool, typer.Option("--version", help="Show the version.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Debug logging.")] = False,
) -> None:
    # Every agent a command opens is closed when the command ends, on success, error or typer.Exit.
    ctx.call_on_close(_close_opened)
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s"
    )
    if version:
        console.print(f"{NAME.lower()} {__version__} (commit {build_commit()})")
        raise typer.Exit()


@app.command(rich_help_panel="Library")
def process(
    paths: Annotated[list[str], typer.Argument(help="Files and/or folders.")],
    password: Annotated[str | None, typer.Option(help="Password for protected PDFs.")] = None,
    force: Annotated[bool, typer.Option(help="Re-read even if unchanged.")] = False,
    config: ConfigOpt = None,
) -> None:
    """OCR, classify and index documents into the local library."""
    banner()
    try:
        agent = _agent(config)
        report = _ingest_with_progress(agent, paths, password, force)
    except InklightError as exc:
        _fail(exc)
    if report.documents:
        console.print(documents_table(report.documents, agent.library.store.page_sources()))
    for path, error in report.failed:
        console.print(Text.assemble(("✗ ", "bad"), (Path(path).name, "bold"), (f"  {error}", "muted")))
    for w in report.warnings:
        console.print(Text.assemble(("⚠ ", "warn"), (w, "warn")))
    rate = report.pages / report.seconds if report.seconds and report.pages else 0
    console.print(
        Text(
            f"{len(report.added)} new, {len(report.unchanged)} unchanged, {len(report.failed)} failed · "
            f"{report.pages} pages in {report.seconds:.1f}s" + (f" ({rate:.1f} pages/s)" if rate else ""),
            "muted",
        )
    )
    if report.failed and not report.documents:
        raise typer.Exit(1)


@app.command(rich_help_panel="Extract")
def text(
    file: Annotated[str, typer.Argument(help="A PDF, image or text file.")],
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write to this file.")] = None,
    password: Annotated[str | None, typer.Option(help="Password for a protected PDF.")] = None,
    config: ConfigOpt = None,
) -> None:
    """Extract a document's text, page by page (raw extraction: not reviewed)."""
    try:
        agent = _agent(config, brain="rules")
        _ingest_with_progress(agent, [file], password)
        body = agent.text(file, password=password)
    except InklightError as exc:
        _fail(exc)
    _write_or_print(body, out)


@app.command(rich_help_panel="Extract")
def tables(
    file: Annotated[str, typer.Argument(help="A PDF or image file.")],
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write a CSV (.csv) or JSON (.json) file.")] = None,
    password: Annotated[str | None, typer.Option(help="Password for a protected PDF.")] = None,
    config: ConfigOpt = None,
) -> None:
    """Extract a document's tables: rows, columns and header cells (needs document structure installed)."""
    from . import exports
    from .structure.run import available

    if not available():
        _fail(InputRejected('Table extraction needs document structure: pip install "inklight[structure]"'))
    try:
        agent = _agent(config, brain="rules", structure=True)
        _ingest_with_progress(agent, [file], password)
        found = agent.tables(file, password=password)
        info = agent.library.find(file) or agent._one(file, password)
        if out and out.suffix.lower() == ".csv":
            body = exports.export(agent, info, "tables.csv")[0]
        elif out:
            body = json.dumps({"note": exports.RAW_NOTE, "tables": found}, ensure_ascii=False, indent=1)
        else:
            body = ""
    except InklightError as exc:
        _fail(exc)
    if out:
        _write_or_print(body, out)
        return
    if not found:
        console.print(Text("No table found in this document.", "muted"))
        return
    for t in found:
        console.print(tables_table(t))
    console.print(Text(exports.RAW_NOTE, "muted"))


def _write_or_print(body: str, out: Path | None) -> None:
    if out:
        out.write_text(body, encoding="utf-8", newline="")
        err.print(Text.assemble(("✓ wrote ", "ok"), (str(out), "bold")))
    else:
        sys.stdout.write(body)


@app.command(rich_help_panel="Experimental")
def ask(
    args: Annotated[list[str], typer.Argument(help='[FILES/FOLDERS...] "REQUEST" — the last argument is the request.')],
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Folder the agent may write results into.")] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Allow writing results without asking.")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print the full result as JSON.")] = False,
    trace: Annotated[bool, typer.Option("--trace", help="Show the execution trace.")] = False,
    doc: Annotated[
        list[str] | None,
        typer.Option("--doc", "-d", help="A library document (id or file name) to ask about; repeat for several."),
    ] = None,
    brain: BrainOpt = None,
    config: ConfigOpt = None,
) -> None:
    """Ask a question or give a task in plain language."""
    from .agent import Policy

    *paths, request = args
    try:
        agent = _agent(config, brain, out, yes)
        confirm = None
        if not yes and out is None and sys.stdin.isatty():
            confirm = lambda msg: typer.confirm(msg, default=True)  # noqa: E731
        policy = Policy(
            allow_write=bool(out or yes or confirm),
            output_dir=out.resolve() if out else None,
            confirm=confirm,
        )
        if not as_json:
            banner()
        if paths:
            missing = [p for p in paths if not Path(p).exists()]
            if missing:
                _fail(InputRejected("File not found: " + ", ".join(missing) + " (give the path of each document)"))
            report = _ingest_with_progress(agent, paths) if not as_json else agent.library.add(paths)
            ids = [d.id for d in report.documents]
            if not ids:
                _fail(InklightError("No readable documents: " + "; ".join(e for _, e in report.failed)))
            with console.status("Thinking…", spinner="dots", spinner_style=CYAN) if not as_json else _null():
                # The files named on the command line are the person's choice of documents (explicit scope).
                result = agent.run_plan(agent.plan(request), ids, report=report, policy=policy, explicit=True)
        elif doc:
            # Library documents as they are: one that failed or is still being read is reported, not re-read.
            ids = _library_ids(agent, doc)
            with console.status("Thinking…", spinner="dots", spinner_style=CYAN) if not as_json else _null():
                result = agent.ask(request, doc_ids=ids, policy=policy)
        else:
            with console.status("Thinking…", spinner="dots", spinner_style=CYAN) if not as_json else _null():
                result = agent.ask(request, policy=policy)
    except InklightError as exc:
        _fail(exc)
    if as_json:
        print(result.model_dump_json(indent=2))
    else:
        result_panel(result, show_trace=trace)
    if not result.ok:
        raise typer.Exit(2)


def _library_ids(agent: Any, refs: list[str]) -> list[str]:
    """Library document ids for each id or file name given, in order; an unknown one is an error."""
    docs = agent.library.documents()
    ids = []
    for ref in refs:
        match = [d.id for d in docs if d.id == ref] or [d.id for d in docs if d.name == ref]
        if not match:
            raise InputRejected(f"No library document {ref!r} (see `inklight docs`)")
        if len(match) > 1:
            raise InputRejected(f"Several library documents are named {ref!r}: give its id (see `inklight docs`)")
        ids.append(match[0])
    return ids


class _null:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_: object) -> None:
        return None


@app.command(rich_help_panel="Extract")
def extract(
    files: Annotated[list[str], typer.Argument(help="Files and/or folders.")],
    schema: Annotated[Path | None, typer.Option("--schema", "-s", help="JSON schema of fields.")] = None,
    fields: Annotated[str | None, typer.Option("--fields", "-f", help="Comma-separated fields.")] = None,
    fmt: Annotated[str, typer.Option("--format", help="table | csv | json")] = "table",
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write to this file.")] = None,
    config: ConfigOpt = None,
) -> None:
    """Extract named fields: each value read at its printed label, with its page and box (raw: review before use)."""
    from .agent.analysis import render
    from .agent.context import Policy, Scratch, ToolContext
    from .agent.plan import Intent, Plan

    if fmt not in ("table", "csv", "json"):
        _fail(InklightError("--format must be table, csv or json"))
    names = [f.strip() for f in fields.split(",") if f.strip()] if fields else None
    if not schema and not names:
        _fail(InputRejected('Name the fields to extract, e.g. --fields "registration number, date, total"'))
    try:
        agent = _agent(config)
        records = agent.extract(files, fields=names, schema=schema)
    except InklightError as exc:
        _fail(exc)
    if fmt == "table" and not out:
        banner()
        console.print(records_table(records))
        warnings = [f"{r.name} · {k}: {v.warning}" for r in records for k, v in r.fields.items() if v.warning]
        for w in warnings[:20]:
            console.print(Text.assemble(("⚠ ", "warn"), (w, "warn")))
        return
    kind = "json" if fmt == "table" else fmt
    ctx = ToolContext(
        library=agent.library,
        plan=Plan(intent=Intent.EXTRACT, query="extract"),
        policy=Policy(),
        scratch=Scratch(records=records),
    )
    content = render(ctx, kind)
    if out:
        out.write_text(content, encoding="utf-8", newline="")
        console.print(Text.assemble(("✓ saved ", "ok"), (str(out), "bold")))
    else:
        sys.stdout.write(content)


@app.command(rich_help_panel="Extract")
def search(query: str, k: Annotated[int, typer.Option("-k", help="Results.")] = 8, config: ConfigOpt = None) -> None:
    """Search the library (keyword + semantic when installed)."""
    try:
        hits = _agent(config).library.search(query, k=k)
    except InklightError as exc:
        _fail(exc)
    console.print(hits_table(hits) if hits else Text("No matches.", "muted"))


@app.command(rich_help_panel="Library")
def docs(config: ConfigOpt = None) -> None:
    """List indexed documents."""
    agent = _agent(config)
    items = agent.library.documents()
    if not items:
        console.print(Text("The library is empty. Try: inklight process ./docs", "muted"))
        return
    console.print(documents_table(items, agent.library.store.page_sources()))


@app.command(rich_help_panel="Library")
def show(
    doc: str,
    page: Annotated[int | None, typer.Option(help="Only this page.")] = None,
    fmt: Annotated[str, typer.Option("--format", help="md | text | json")] = "md",
    config: ConfigOpt = None,
) -> None:
    """Print a document's extracted Markdown, text or JSON (with boxes)."""
    agent = _agent(config)
    info = agent.library.find(doc)
    if info is None:
        _fail(InklightError(f"No document matches {doc!r}"))
    pages = [p for p in agent.library.pages(info.id) if page is None or p.number == page]
    if fmt == "json":
        print(
            json.dumps(
                {"document": info.model_dump(mode="json"), "pages": [p.model_dump(mode="json") for p in pages]},
                indent=2,
            )
        )
        return
    for p in pages:
        console.print(Text(f"── {info.name} · page {p.number} · {p.source}", "muted"))
        sys.stdout.write((p.markdown if fmt == "md" else p.text) + "\n")


@app.command(rich_help_panel="Library")
def remove(doc: str, config: ConfigOpt = None) -> None:
    """Remove a document (and its index) from the library. The file itself is untouched."""
    agent = _agent(config)
    info = agent.library.find(doc)
    if info is None or not agent.library.remove(info.id):
        _fail(InklightError(f"No document matches {doc!r}"))
    console.print(Text.assemble(("✓ removed ", "ok"), (info.name, "bold")))


@app.command(rich_help_panel="Library")
def reindex(
    doc: Annotated[str | None, typer.Argument(help="Document id/name; all when omitted.")] = None,
    config: ConfigOpt = None,
) -> None:
    """Re-read documents from disk and rebuild their index."""
    agent = _agent(config)
    ids = None
    if doc:
        info = agent.library.find(doc)
        if info is None:
            _fail(InklightError(f"No document matches {doc!r}"))
        ids = [info.id]
    report = agent.library.reindex(ids)
    console.print(Text(f"Re-indexed {len(report.added)} document(s); {len(report.failed)} failed", "muted"))
    for w in report.warnings:
        console.print(Text.assemble(("⚠ ", "warn"), (w, "warn")))


@app.command(rich_help_panel="Experimental")
def history(limit: int = 20, config: ConfigOpt = None) -> None:
    """Recent agent tasks."""
    from rich.table import Table

    rows = _agent(config).library.store.list_tasks(limit)
    table = Table(box=None, header_style="muted")
    for col in ("task", "when", "intent", "state", "ms", "request"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            r["id"], r["created_at"][:19], r["intent"], r["state"], f"{r['duration_ms']:.0f}", r["request"][:70]
        )
    console.print(table)


@app.command(rich_help_panel="Library")
def watch(
    folder: Path,
    request: Annotated[str | None, typer.Option("--request", "-r", help="Run this on each new batch.")] = None,
    interval: Annotated[float, typer.Option(help="Seconds between scans.")] = 5.0,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Folder results may be written to.")] = None,
    config: ConfigOpt = None,
) -> None:
    """Watch a folder: index new files and optionally run a request on them."""
    from .agent import Policy
    from .watch import FolderWatcher

    if not folder.is_dir():
        _fail(InklightError(f"Not a folder: {folder}"))
    agent = _agent(config, out=out)
    banner()
    console.print(Text(f"Watching {folder.resolve()} every {interval:g}s — Ctrl+C to stop", "muted"))

    def on(event) -> None:  # type: ignore[no-untyped-def]
        style = {"indexed": "ok", "failed": "bad", "result": "brand"}[event.kind]
        console.print(
            Text.assemble((f"{event.kind:>8} ", style), (Path(event.path).name, "bold"), (f"  {event.detail}", "muted"))
        )
        if event.result:
            result_panel(event.result)

    w = FolderWatcher(
        agent=agent,
        folder=folder.resolve(),
        interval=max(interval, 0.5),
        request=request,
        policy=Policy(allow_write=bool(out), output_dir=out.resolve() if out else None),
        on_event=on,
    )
    try:
        w.run()
    except KeyboardInterrupt:
        w.stop.set()
        console.print(Text("stopped", "muted"))


@app.command(rich_help_panel="Workspace")
def serve(
    host: Annotated[
        str, typer.Option(help="Address to listen on. 127.0.0.1: this computer only. 0.0.0.0: every interface.")
    ] = "127.0.0.1",
    port: int = 8765,
    public_url: Annotated[
        str | None,
        typer.Option(help="The address visitors open (server IP, domain or reverse-proxy URL); its host is accepted."),
    ] = None,
    allowed_host: Annotated[
        list[str] | None, typer.Option(help="Another host name browsers may use (repeatable).")
    ] = None,
    demo: Annotated[
        bool, typer.Option("--demo", help="Public demo: each visitor gets a temporary library of their own.")
    ] = False,
    demo_dir: Annotated[str | None, typer.Option(help="Folder for the demo's temporary libraries.")] = None,
    demo_minutes: Annotated[int | None, typer.Option(min=5, max=1440, help="Lifetime of a demo session.")] = None,
    no_token: Annotated[
        bool, typer.Option("--no-token", help="Serve a private workspace on a network without a token.")
    ] = False,
    trusted_proxy: Annotated[
        list[str] | None, typer.Option(help="Reverse proxy address whose X-Forwarded headers are trusted.")
    ] = None,
    open_browser: Annotated[bool, typer.Option("--open/--no-open")] = True,
    share: Annotated[
        bool,
        typer.Option(
            "--share",
            help="Make a public https link through a Cloudflare quick tunnel (no account; downloads Cloudflare's "
            "cloudflared once, pinned and checked). Needs INKLIGHT_SERVER_TOKEN, or --demo.",
        ),
    ] = False,
    config: ConfigOpt = None,
) -> None:
    """Start the web workspace: on this computer (default), as a private workspace on a network, or as a demo.

    --share gives a public https link from anywhere, Colab or a remote machine included, without opening a port."""
    import threading
    import webbrowser

    import uvicorn

    from .server import create_app
    from .server.launch import check_share, plan

    settings = _settings(config)
    if share:
        try:
            check_share(host=host, public_url=public_url, demo=demo, no_token=no_token, trusted_proxies=trusted_proxy)
        except InklightError as exc:
            _fail(exc)
        _serve_shared(settings, port=port, demo=demo, demo_dir=demo_dir, demo_minutes=demo_minutes,
                      allowed_hosts=allowed_host)  # fmt: skip
        return
    try:
        launch = plan(
            settings,
            host=host,
            port=port,
            public_url=public_url,
            allowed_hosts=allowed_host,
            demo=demo,
            demo_dir=demo_dir,
            demo_minutes=demo_minutes,
            no_token=no_token,
            trusted_proxies=trusted_proxy,
            open_browser=open_browser,
        )
    except InklightError as exc:
        _fail(exc)
    banner()
    for label, text in launch.lines:
        style = "brand" if label == "workspace" else ""
        console.print(Text.assemble((f"  {label:<11}", "muted"), (text, style)))
    for warning in launch.warnings:
        err.print(Text(f"⚠ {warning}", "warn"))
    if launch.open_url:
        url = launch.open_url
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app_ = create_app(settings, hosting=launch.hosting)
    uvicorn.run(
        app_,
        host=host,
        port=port,
        log_level="warning",
        proxy_headers=launch.proxy_ips is not None,
        forwarded_allow_ips=launch.proxy_ips,
    )


def _serve_shared(settings: Settings, *, port: int, demo: bool, demo_dir: str | None, demo_minutes: int | None,
                  allowed_hosts: list[str] | None) -> None:  # fmt: skip
    from .server.share_serve import Output, serve_shared

    banner()
    with _progress() as bar:
        task = bar.add_task("cloudflared (MB)", total=None, visible=False)

        def progress(done: int, total: int) -> None:
            bar.update(task, completed=done // 1_000_000, total=total // 1_000_000, visible=True)

        def line(label: str, text: str) -> None:
            bar.update(task, visible=False)
            console.print(Text.assemble((f"  {label:<12}", "muted"), (text, "brand" if label == "public link" else "")))

        out = Output(
            say=lambda text: console.print(Text(text, "muted")),
            line=line,
            fail=lambda text: err.print(Text.assemble(("✗ ", "bad"), (text, ""))),
            progress=progress,
        )
        ok = serve_shared(settings, out, port=port, demo=demo, demo_dir=demo_dir, demo_minutes=demo_minutes,
                          allowed_hosts=allowed_hosts)  # fmt: skip
    if not ok:
        raise typer.Exit(1)


@app.command(rich_help_panel="Experimental")
def tools() -> None:
    """List the agent's tools, permissions and side effects."""
    from .agent import DocumentAgent

    for t in DocumentAgent.tools():
        console.print(
            Text.assemble((f"{t['name']:<22}", "brand"), (f"[{t['permission']}] ", "accent"), (t["description"], ""))
        )
        if t["side_effects"] != "none":
            console.print(Text(f"{'':22}side effects: {t['side_effects']}", "muted"))


@app.command(rich_help_panel="Extract")
def structure(
    doc: str,
    fmt: Annotated[str, typer.Option("--format", help="md | json | html | meta")] = "md",
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write to this file.")] = None,
    config: ConfigOpt = None,
) -> None:
    """Export a document's structure: Markdown, its JSON (docling-core's document format), HTML, or what ran (meta).

    Needs the document to have been processed with [structure] engine = "inklight"."""
    agent = _agent(config)
    info = agent.library.find(doc)
    if info is None:
        _fail(InklightError(f"No document matches {doc!r}"))
    stored = agent.library.structure(info.id)
    if stored is None:
        _fail(InklightError(f'{info.name} has no stored structure: process it with [structure] engine = "inklight"'))
    meta, document = stored
    if fmt == "meta":
        text = json.dumps(meta, ensure_ascii=False, indent=2)
    elif document is None:
        _fail(
            InklightError(
                "The structure's text is not stored (privacy.store_text = false), or the structure runtime is missing"
            )
        )
    elif fmt == "json":
        text = json.dumps(document.export_to_dict(), ensure_ascii=False, indent=2)
    elif fmt == "html":
        text = document.export_to_html()
        if any(pic.children for pic in document.pictures):
            console.print(Text("Note: the HTML export leaves out text inside pictures; md and json keep it.", "warn"))
    elif fmt == "md":
        text = document.export_to_markdown(traverse_pictures=True)  # text inside pictures included
    else:
        _fail(InklightError(f"Unknown format {fmt!r}: use md, json, html or meta"))
    if out:
        out.write_text(text, encoding="utf-8")
        console.print(Text(f"Wrote {out}", "ok"))
    else:
        sys.stdout.write(text + "\n")


@app.command(rich_help_panel="Setup")
def doctor(config: ConfigOpt = None) -> None:
    """Check the installation, models and configuration."""
    import platform

    banner()
    settings = _settings(config)
    rows = [
        ("python", platform.python_version(), sys.version_info >= (3, 11)),
        ("platform", f"{platform.system()} {platform.machine()}", True),
        ("home", str(settings.home), True),
        ("cpu cores", str(os.cpu_count()), True),
    ]
    from . import modelstore
    from .structure.run import available as structure_available

    def model_row(name: str, model: modelstore.ModelSet, local: str | None, needed: bool) -> None:
        info = modelstore.status(model, local)
        if info["installed"]:
            rows.append((name, f"ready ({model.size / 1e6:.0f} MB, revision {model.revision[:7]})", True))
        else:
            why = info.get("problem") or "not downloaded yet: `inklight models pull` (or it downloads on first use)"
            rows.append((name, str(why), not needed and "problem" not in info))

    model_row("OCR models", modelstore.OCR, settings.ocr.model_dir, True)
    wanted = settings.structure.enabled
    if structure_available():
        rows.append(("structure", "on" if wanted else 'installed, off ([structure] engine = "inklight")', True))
        if wanted:
            tables = modelstore.TABLES if settings.structure.table_mode == "accurate" else modelstore.TABLES_FAST
            model_row("layout model", modelstore.LAYOUT, None, True)
            model_row("table model", tables, None, True)
    else:
        rows.append(
            (
                "structure",
                'not installed: pip install "inklight[structure]"' + (" (it is turned on)" if wanted else ""),
                not wanted,
            )
        )
    from .brains import Brain

    for role, info in Brain(settings).status().items():
        if role == "remote":
            rows.append(("remote model", "configured" if info["configured"] else "off (local only)", True))
        else:  # optional: used by Ask and English search only, so never a failure
            note = "installed" if info["installed"] else "not installed (optional, for Ask)"
            rows.append((f"Ask {role} ({info['params']})", note, True))
    for name, value, ok in rows:
        console.print(
            Text.assemble(("✓ " if ok else "✗ ", "ok" if ok else "bad"), (f"{name:<20}", "muted"), (value, ""))
        )
    if not all(ok for *_, ok in rows):
        console.print(
            Text("\nRun: inklight models pull   (downloads the missing models once; then it all works offline)", "warn")
        )


@review_app.command("list")
def review_list(
    status: Annotated[str | None, typer.Option(help="open or approved")] = None,
    cohort: Annotated[str | None, typer.Option(help="Only this cohort.")] = None,
    config: ConfigOpt = None,
) -> None:
    """List reviews: document, mode, cohort, status, undecided fields, approval."""
    agent = _agent(config, brain="rules")
    for r in agent.reviews.find(status=status, cohort=cohort):
        undecided = sum(f.action is None for f in r.fields)
        approved = f"approved by {r.approved_by} {r.approved_at}" if r.approved_by else f"{undecided} undecided"
        console.print(Text(f"{r.id}  {r.status:<8} {r.mode:<6} {r.cohort or '-':<16} {r.doc_name}  ({approved})"))


@review_app.command("export")
def review_export(
    out: Annotated[Path, typer.Option("--out", "-o", help="File to write (.csv or .json).")],
    actor: Annotated[str, typer.Option(help="Who exports (recorded in each review's history).")],
    cohort: Annotated[str | None, typer.Option(help="Only this cohort.")] = None,
    config: ConfigOpt = None,
) -> None:
    """Export approved reviews: prediction, warning, decision and approval, one row per field."""
    if out.exists():  # checked first: the export is recorded in each review's history
        _fail(InklightError(f"{out} exists; choose a new file name"))
    fmt = "json" if out.suffix.lower() == ".json" else "csv"
    agent = _agent(config, brain="rules")
    try:
        content = agent.reviews.export(fmt, actor=actor, cohort=cohort)  # type: ignore[arg-type]
    except InklightError as exc:
        _fail(exc)
    out.write_text(content, encoding="utf-8", newline="")
    console.print(Text(f"✓ wrote {out}", "ok"))


@models_app.command("status")
def models_status(config: ConfigOpt = None) -> None:
    """Show where each model is, its pinned revision and whether its files are complete and verified."""
    from . import modelstore
    from .brains import Brain

    settings = _settings(config)
    for model in modelstore.SETS.values():
        local = settings.ocr.model_dir if model is modelstore.OCR else None
        console.print(Text(f"{model.title}: {json.dumps(modelstore.status(model, local))}"))
    for role, info in Brain(settings).status().items():
        console.print(Text(f"{role} (Ask): {json.dumps(info)}"))


@models_app.command("pull")
def models_pull(
    structure: Annotated[
        bool | None, typer.Option(help="Also fetch the document structure models (~384 MB); default: when it is on.")
    ] = None,
    ask: Annotated[
        bool, typer.Option(help="Also fetch the small models Ask uses (reader 66 MB, embedder 34 MB).")
    ] = True,
    writer: Annotated[bool, typer.Option(help="Also fetch the 135M writer (~137 MB) for Ask.")] = False,
    config: ConfigOpt = None,
) -> None:
    """Download the models once (OCR ~76 MB, and the ones asked for); everything runs offline afterwards."""
    from . import modelstore
    from .brains import hub

    settings = _settings(config)
    wanted = [(modelstore.OCR, settings.ocr.model_dir)]
    if structure or (structure is None and settings.structure.enabled):
        tables = modelstore.TABLES if settings.structure.table_mode == "accurate" else modelstore.TABLES_FAST
        wanted += [(modelstore.LAYOUT, None), (tables, None)]
    for model, local in wanted:
        with _progress() as bar:
            task = bar.add_task(f"{model.title}", total=model.size)

            def on(_what: str, done: int, total: int, task=task, bar=bar) -> None:  # type: ignore[no-untyped-def]
                bar.update(task, completed=done, total=total)

            try:
                folder = modelstore.ensure(model, local, progress=on)
            except InklightError as exc:
                _fail(exc)
        console.print(Text.assemble(("✓ ", "ok"), (f"{model.title:<40}", "bold"), (str(folder), "muted")))
    roles = (["reader", "embedder"] if ask else []) + (["writer"] if writer else [])
    for role in roles:
        repo = getattr(settings.models, role)
        with console.status(f"Downloading {role} ({repo})…", spinner_style=CYAN):
            try:
                hub.pull(repo, hub.FILES[role], settings.model_cache, getattr(settings.models, f"{role}_revision"))
            except Exception as exc:
                _fail(InklightError(f"{role}: {exc}"))
        console.print(Text.assemble(("✓ ", "ok"), (f"{role:<9}", "bold"), (repo, "muted")))


def main() -> None:
    # Hugging Face's Windows symlink warning is noise for end users; caching still works.
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    if os.name == "nt":
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                with contextlib.suppress(ValueError):
                    reconfigure(encoding="utf-8")
    app()


if __name__ == "__main__":
    main()
