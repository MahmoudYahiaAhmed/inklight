"""Final answer composition and evidence verification."""

from __future__ import annotations

from ..schemas import Record, Source, TaskState
from .answer import norm
from .context import ToolContext
from .plan import Intent, Plan


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}"
    return "—" if value is None else str(value)


def table_text(records: list[Record], limit: int = 25) -> str:
    if not records:
        return ""
    cols = list(records[0].flat())
    lines = [" | ".join(cols)]
    for record in records[:limit]:
        row = record.flat()
        lines.append(" | ".join(_fmt(row.get(c)) for c in cols))
    if len(records) > limit:
        lines.append(f"… and {len(records) - limit} more")
    return "\n".join(lines)


def verify_sources(ctx: ToolContext, sources: list[Source]) -> list[Source]:
    """Keep only sources whose excerpt really occurs in the stored document text."""
    good = []
    cache: dict[str, str] = {}
    for src in sources:
        if src.doc_id not in cache:
            cache[src.doc_id] = norm(
                ctx.library.text(src.doc_id)
                + "\n"
                + "\n".join(ln.text for p in ctx.pages(src.doc_id) for ln in p.lines)
            )
        if norm(src.excerpt)[:200] in cache[src.doc_id]:
            good.append(src)
        else:
            ctx.scratch.warn(f"Dropped a citation to {src.cite()} that could not be verified")
    return good


def _record_sources(records: list[Record]) -> list[Source]:
    out: list[Source] = []
    for record in records:
        out.extend(v.source for v in record.fields.values() if v.source is not None)
    return out


def compose(ctx: ToolContext, plan: Plan, state: TaskState) -> str:
    s = ctx.scratch
    docs = ctx.docs()
    if state == TaskState.FAILED and not s.answer and not s.records:
        return "The task could not be completed. " + (s.warnings[-1] if s.warnings else "")
    if state == TaskState.CANCELLED and not s.answer:
        return "The task was stopped before it finished (cancelled or out of time)."
    match plan.intent:
        case Intent.EXTRACT | Intent.INCONSISTENCIES if s.records and not s.answer:
            s.sources = s.sources or _record_sources(s.records)
            s.confidence = _mean_conf(s.records)
            text = f"Extracted {', '.join(plan.fields)} from {len(s.records)} document(s):\n\n{table_text(s.records)}"
        case Intent.EXTRACT:
            text = s.answer or "No fields could be extracted."
        case Intent.FILTER:
            s.sources = _record_sources(s.records)
            s.confidence = _mean_conf(s.records) if s.records else 0.6
            conds = (" or " if plan.match == "any" else " and ").join(c.describe() for c in plan.conditions)
            text = (
                f"{len(s.records)} of {len(s.records) + len(s.excluded)} document(s) match {conds}:\n\n"
                f"{table_text(s.records)}"
                if s.records
                else f"No documents match {conds}."
            )
        case Intent.AGGREGATE:
            calc = s.calc or {}
            s.sources = _record_sources(s.records)
            s.confidence = _mean_conf(s.records) if s.records else 0.0
            if calc.get("by_unit"):
                s.confidence = min(s.confidence, 0.5)
                per_unit = " · ".join(f"{u} {_fmt(v)}" for u, v in calc["by_unit"].items())
                text = (
                    f"No single {calc.get('op', '')}: the {calc.get('field', '')} values are in different "
                    f"currencies and are not converted. By currency: {per_unit}\n\n{table_text(s.records)}"
                )
            else:
                unit = f" {calc['unit']}" if calc.get("unit") else ""
                text = (
                    f"{calc.get('op', '')} of {calc.get('field', '')}: {_fmt(calc.get('result'))}{unit} "
                    f"(over {calc.get('count', 0)} document(s); computed exactly, not by a model)\n\n"
                    f"{table_text(s.records)}"
                )
        case Intent.COUNT:
            kinds: dict[str, int] = {}
            for d in docs:
                kinds[d.doc_type] = kinds.get(d.doc_type, 0) + 1
            s.confidence = 0.9
            text = f"{len(docs)} document(s) in scope: " + ", ".join(f"{n} {k}" for k, n in kinds.items())
        case Intent.PROCESS:
            s.confidence = 0.95
            pages = sum(d.pages for d in docs)
            text = (
                f"{len(docs)} document(s), {pages} page(s) are indexed and searchable. "
                "Ask a question or extract fields next."
            )
        case _:
            text = s.answer
    s.sources = verify_sources(ctx, s.sources)
    _flag_injections(ctx)
    text = _with_interpretation(plan, text)
    if s.files:
        text += "\n\nSaved: " + ", ".join(s.files)
    return text.strip()


def _with_interpretation(plan: Plan, text: str) -> str:
    """Say how a record-level request was read, and what was NOT applied, before the result."""
    if plan.intent not in (Intent.FILTER, Intent.AGGREGATE, Intent.EXTRACT, Intent.COUNT):
        return text
    if not plan.conditions and not plan.not_understood:
        return text
    head = "Understood as: " + "; ".join(plan.understood()[1:] or plan.understood())
    if plan.not_understood:
        head += "\nNot applied: " + "; ".join(f"“{x}”" for x in plan.not_understood)
    return f"{head}\n\n{text}"


def _flag_injections(ctx: ToolContext) -> None:
    """Tell the user when a document that fed this answer contains instruction-like text."""
    s = ctx.scratch
    used = {x.doc_id for x in s.sources} | {r.doc_id for r in s.records}
    if ctx.plan.intent.value in ("summarize", "compare", "count", "process"):
        used |= set(s.doc_ids)
    flagged = {r["doc_id"] for r in ctx.library.store.flagged_chunks(sorted(used))}
    for doc_id in sorted(flagged):
        doc = ctx.library.get(doc_id)
        if doc:
            s.warn(
                f"{doc.name} contains instruction-like text (possible prompt injection). "
                "It was treated as data; no action was taken because of it."
            )


def _mean_conf(records: list[Record]) -> float:
    vals = [v.confidence for r in records for v in r.fields.values() if v.value is not None]
    return round(sum(vals) / len(vals), 3) if vals else 0.0
