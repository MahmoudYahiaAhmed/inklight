"""Rich rendering for the CLI, in the Inklight palette."""

from __future__ import annotations

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from ._brand import AMBER, CYAN, NAME, TAGLINE
from .schemas import AgentResult, DocumentInfo, Record, SearchHit, StepStatus

THEME = Theme(
    {"brand": f"bold {CYAN}", "accent": AMBER, "muted": "grey58", "ok": "green3", "bad": "red3", "warn": AMBER}
)
console = Console(theme=THEME, highlight=False)
err = Console(theme=THEME, stderr=True, highlight=False)

MARK = "◆"


def banner() -> None:
    console.print(Text.assemble((f"{MARK} ", f"bold {CYAN}"), (NAME.lower(), "bold"), ("  ", ""), (TAGLINE, "muted")))


def conf_style(conf: float | None) -> str:
    if conf is None:
        return "muted"
    return "ok" if conf >= 0.8 else "warn" if conf >= 0.5 else "bad"


def documents_table(docs: list[DocumentInfo]) -> Table:
    table = Table(box=None, header_style="muted", pad_edge=False)
    for col in ("id", "name", "type", "pages", "OCR conf", "status"):
        table.add_column(col)
    for d in docs:
        conf = f"{d.mean_conf:.2f}" if d.mean_conf is not None else "—"
        status = "ok" if d.status.value == "ready" else "bad" if d.status.value == "failed" else "warn"
        table.add_row(
            Text(d.id[:8], "muted"),
            d.name,
            d.doc_type,
            str(d.pages),
            Text(conf, conf_style(d.mean_conf)),
            Text(d.status.value, status),
        )
    return table


def records_table(records: list[Record]) -> Table:
    table = Table(box=None, header_style="muted", pad_edge=False)
    fields = []
    for r in records:
        for f in r.fields:
            if f not in fields:
                fields.append(f)
    table.add_column("document")
    for f in fields:
        table.add_column(f)
    for r in records:
        cells = [Text(r.name, "bold")]
        for f in fields:
            v = r.fields.get(f)
            if v is None or v.value is None:
                cells.append(Text("—", "muted"))
            else:
                shown = f"{v.value:,.2f}" if isinstance(v.value, float) else str(v.value)
                cells.append(Text(shown + ("" if not v.warning else " ⚠"), conf_style(v.confidence)))
        table.add_row(*cells)
    return table


def result_panel(result: AgentResult, show_trace: bool = False) -> None:
    title = Text.assemble(
        (f"{MARK} ", f"bold {CYAN}"),
        (result.intent, "bold"),
        ("  ·  ", "muted"),
        (result.state.value, "ok" if result.ok else "bad"),
        ("  ·  understood ", "muted"),
        (f"{result.interpretation_confidence:.2f}", conf_style(result.interpretation_confidence)),
        ("  ·  evidence ", "muted"),
        (f"{result.evidence_confidence:.2f}", conf_style(result.evidence_confidence)),
    )
    parts = result.answer.split("\n\n")
    head = parts.pop(0) if parts and parts[0].startswith("Understood as") else None
    body: list = []
    if head:
        for line in head.splitlines():
            style = "warn" if line.startswith("Not applied") else "muted"
            body.append(Text(line, style))
        body.append(Text(""))
    if result.records and result.intent in ("extract", "filter", "aggregate", "inconsistencies"):
        body += [Text(parts[0] if parts else ""), Text(""), records_table(list(result.records))]
    else:
        body.append(Text("\n\n".join(parts)))
    style = {"supported": "ok", "missing_evidence": "bad", "unsupported": "bad", "failed": "bad"}.get(
        result.outcome, "warn"
    )
    outcome = Text.assemble((" Outcome: ", "muted"), (result.outcome_label, f"bold {style}"))
    if result.outcome != "supported":
        outcome.append("  (check the evidence before relying on it)", "muted")
    console.print(outcome)
    console.print(Panel(Group(*body), title=title, title_align="left", border_style=CYAN, padding=(1, 2)))
    for c in result.candidates:
        console.print(
            Text.assemble(
                (" • ", "brand"),
                (c.value, "bold"),
                (f"  {c.context or c.source.name}" + ("" if "page" in c.context else f", p.{c.source.page}"), "muted"),
            )
        )
    if result.sources:
        console.print(Text("Evidence", "accent"))
        for i, s in enumerate(result.sources[:6], 1):
            conf = f" · OCR estimate {s.ocr_conf:.2f}" if s.ocr_conf is not None else ""
            excerpt = s.excerpt.replace("\n", " ")
            console.print(
                Text.assemble(
                    (f" [{i}] ", "brand"),
                    (s.cite(), "bold"),
                    (conf, "muted"),
                    ("  “" + excerpt[:150] + ("…" if len(excerpt) > 150 else "") + "”", ""),
                )
            )
    for w in result.warnings:
        console.print(Text.assemble((" ⚠ ", "warn"), (w, "warn")))
    for f in result.files_written:
        console.print(Text.assemble((" ✓ saved ", "ok"), (f, "bold")))
    if show_trace:
        trace_table(result)
    console.print(Text(f"{result.duration_ms:,.0f} ms · brain: {result.brain} · task {result.task_id}", "muted"))


def trace_table(result: AgentResult) -> None:
    table = Table(title="Execution trace", title_justify="left", title_style="accent", box=None, header_style="muted")
    for col in ("#", "tool", "status", "ms", "summary"):
        table.add_column(col)
    for step in result.trace:
        style = {StepStatus.OK: "ok", StepStatus.DENIED: "warn"}.get(step.status, "bad")
        table.add_row(
            str(step.index + 1),
            step.tool,
            Text(step.status.value, style),
            f"{step.duration_ms:.0f}",
            step.error or step.summary,
        )
    console.print(table)


def hits_table(hits: list[SearchHit]) -> Table:
    table = Table(box=None, header_style="muted")
    for col in ("score", "where", "excerpt"):
        table.add_column(col)
    for h in hits:
        table.add_row(f"{h.score:.3f}", h.source.cite(), h.source.excerpt.replace("\n", " ")[:120])
    return table
