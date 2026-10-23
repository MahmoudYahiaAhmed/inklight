"""The `inklight` command line."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.text import Text

from . import __version__
from ._brand import CYAN, NAME, TAGLINE
from .cli_render import banner, console, documents_table, err, hits_table, records_table, result_panel
from .config import Settings, load_settings
from .errors import InklightError

app = typer.Typer(
    name="inklight", help=f"{NAME} — {TAGLINE}", no_args_is_help=True, add_completion=False, rich_markup_mode="rich"
)
models_app = typer.Typer(help="Install and inspect the small local models.", no_args_is_help=True)
app.add_typer(models_app, name="models")

ConfigOpt = Annotated[Path | None, typer.Option("--config", "-c", help="Path to a config.toml.")]
BrainOpt = Annotated[str | None, typer.Option("--brain", help="auto | local | rules")]


def _settings(config: Path | None, brain: str | None = None) -> Settings:
    overrides = {"models": {"brain": brain}} if brain else {}
    return load_settings(config, **overrides)


def _agent(config: Path | None, brain: str | None = None, out: Path | None = None, yes: bool = False):  # type: ignore[no-untyped-def]
    from .agent import DocumentAgent

    settings = _settings(config, brain)
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


def _first_run_notice(agent) -> None:  # type: ignore[no-untyped-def]
    """Say so before Indra fetches its models, instead of appearing to hang."""
    if agent.settings.ocr.model_dir:
        return
    try:
        from huggingface_hub import try_to_load_from_cache

        cached = isinstance(try_to_load_from_cache("datalab-to/indra-ocr", "config.json"), str)
    except Exception:  # best effort only
        return
    if not cached:
        console.print(
            Text(
                "First run: downloading Indra OCR models (~76 MB, once). Licensed by Datalab under a modified "
                "OpenRAIL-M license — see THIRD_PARTY_LICENSES.md.",
                "accent",
            )
        )


def _ingest_with_progress(agent, paths: list[str], password: str | None = None, force: bool = False):  # type: ignore[no-untyped-def]
    _first_run_notice(agent)
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
        console.print(f"{NAME.lower()} {__version__}")
        raise typer.Exit()


@app.command()
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
        console.print(documents_table(report.documents))
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


@app.command()
def ask(
    args: Annotated[list[str], typer.Argument(help='[FILES/FOLDERS...] "REQUEST" — the last argument is the request.')],
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Folder the agent may write results into.")] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Allow writing results without asking.")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print the full result as JSON.")] = False,
    trace: Annotated[bool, typer.Option("--trace", help="Show the execution trace.")] = False,
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
            report = _ingest_with_progress(agent, paths) if not as_json else agent.library.add(paths)
            ids = [d.id for d in report.documents]
            if not ids:
                _fail(InklightError("No readable documents: " + "; ".join(e for _, e in report.failed)))
            with console.status("Thinking…", spinner="dots", spinner_style=CYAN) if not as_json else _null():
                result = agent.run_plan(agent.plan(request), ids, report=report, policy=policy)
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


class _null:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_: object) -> None:
        return None


@app.command()
def extract(
    files: Annotated[list[str], typer.Argument(help="Files and/or folders.")],
    schema: Annotated[Path | None, typer.Option("--schema", "-s", help="JSON schema of fields.")] = None,
    fields: Annotated[str | None, typer.Option("--fields", "-f", help="Comma-separated fields.")] = None,
    fmt: Annotated[str, typer.Option("--format", help="table | csv | json")] = "table",
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write to this file.")] = None,
    config: ConfigOpt = None,
) -> None:
    """Extract typed fields (with confidence and page provenance)."""
    from .agent.analysis import render
    from .agent.context import Policy, Scratch, ToolContext
    from .agent.plan import Intent, Plan

    if fmt not in ("table", "csv", "json"):
        _fail(InklightError("--format must be table, csv or json"))
    names = [f.strip() for f in fields.split(",")] if fields else None
    if not schema and not names:
        names = ["invoice_number", "vendor", "date", "subtotal", "tax", "total"]
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


@app.command()
def search(query: str, k: Annotated[int, typer.Option("-k", help="Results.")] = 8, config: ConfigOpt = None) -> None:
    """Search the library (keyword + semantic when installed)."""
    try:
        hits = _agent(config).library.search(query, k=k)
    except InklightError as exc:
        _fail(exc)
    console.print(hits_table(hits) if hits else Text("No matches.", "muted"))


@app.command()
def docs(config: ConfigOpt = None) -> None:
    """List indexed documents."""
    agent = _agent(config)
    items = agent.library.documents()
    console.print(
        documents_table(items) if items else Text("The library is empty. Try: inklight process ./docs", "muted")
    )


@app.command()
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


@app.command()
def remove(doc: str, config: ConfigOpt = None) -> None:
    """Remove a document (and its index) from the library. The file itself is untouched."""
    agent = _agent(config)
    info = agent.library.find(doc)
    if info is None or not agent.library.remove(info.id):
        _fail(InklightError(f"No document matches {doc!r}"))
    console.print(Text.assemble(("✓ removed ", "ok"), (info.name, "bold")))


@app.command()
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


@app.command()
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


@app.command()
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


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Bind address. Keep 127.0.0.1 unless you add auth.")] = "127.0.0.1",
    port: int = 8765,
    open_browser: Annotated[bool, typer.Option("--open/--no-open")] = True,
    config: ConfigOpt = None,
) -> None:
    """Start the local web workspace."""
    import threading
    import webbrowser

    import uvicorn

    from .server import create_app

    settings = _settings(config)
    if host not in ("127.0.0.1", "localhost", "::1"):
        err.print(
            Text(
                "⚠ Binding to a non-local address exposes your documents to the network. "
                "Set INKLIGHT_SERVER_TOKEN to require a token.",
                "warn",
            )
        )
    banner()
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host  # noqa: S104 - display only, not a bind
    url = f"http://{shown}:{port}"
    console.print(Text.assemble(("  workspace  ", "muted"), (url, "brand")))
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(settings), host=host, port=port, log_level="warning")


@app.command()
def tools() -> None:
    """List the agent's tools, permissions and side effects."""
    from .agent import DocumentAgent

    for t in DocumentAgent.tools():
        console.print(
            Text.assemble((f"{t['name']:<22}", "brand"), (f"[{t['permission']}] ", "accent"), (t["description"], ""))
        )
        if t["side_effects"] != "none":
            console.print(Text(f"{'':22}side effects: {t['side_effects']}", "muted"))


@app.command()
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
    try:
        from importlib.metadata import version

        import indra_ocr  # noqa: F401

        rows.append(("indra-ocr", version("indra-ocr"), True))
    except Exception as exc:  # report, don't crash
        rows.append(("indra-ocr", f"missing ({exc})", False))
    from .brains import Brain

    for role, info in Brain(settings).status().items():
        if role == "remote":
            rows.append(("remote model", "configured" if info["configured"] else "off (local only)", True))
        else:
            rows.append(
                (
                    f"{role} ({info['params']})",
                    info["repo"] + (" ✓" if info["installed"] else " — not installed"),
                    info["installed"] or role == "writer",
                )
            )
    for name, value, ok in rows:
        console.print(
            Text.assemble(("✓ " if ok else "✗ ", "ok" if ok else "bad"), (f"{name:<18}", "muted"), (value, ""))
        )
    if not all(ok for *_, ok in rows):
        console.print(
            Text("\nMissing models? Run: inklight models pull   (or keep using rules mode — it works offline)", "warn")
        )


@models_app.command("status")
def models_status(config: ConfigOpt = None) -> None:
    """Show which small models are installed."""
    from .brains import Brain

    for role, info in Brain(_settings(config)).status().items():
        console.print(Text(f"{role}: {json.dumps(info)}"))


@models_app.command("pull")
def models_pull(
    writer: Annotated[bool, typer.Option(help="Also fetch the 135M writer (~137 MB).")] = False,
    config: ConfigOpt = None,
) -> None:
    """Download the small models once (reader 66 MB, embedder 34 MB). Works offline afterwards."""
    from .brains import hub

    settings = _settings(config)
    roles = ["reader", "embedder"] + (["writer"] if writer else [])
    for role in roles:
        repo = getattr(settings.models, role)
        with console.status(f"Downloading {role} ({repo})…", spinner_style=CYAN):
            try:
                hub.pull(repo, hub.FILES[role], settings.model_cache)
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
