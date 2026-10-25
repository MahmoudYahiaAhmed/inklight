"""Final answer composition and evidence verification."""

from __future__ import annotations

from ..schemas import Record, Source, TaskState
from .answer import norm
from .context import ToolContext
from .expr import describe
from .plan import Intent, Plan


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}"
    return "—" if value is None else str(value)


def table_text(records: list[Record], limit: int = 25, columns: tuple[str, ...] = ()) -> str:
    if not records:
        return ""
    cols = list(records[0].flat(columns))
    lines = [" | ".join(cols)]
    for record in records[:limit]:
        row = record.flat(columns)
        lines.append(" | ".join(_fmt(row.get(c)) for c in cols))
    if len(records) > limit:
        lines.append(f"… and {len(records) - limit} more")
    return "\n".join(lines)


def verify_sources(ctx: ToolContext, sources: list[Source]) -> list[Source]:
    """Keep only sources whose excerpt really occurs in the stored document text. An excerpt of several lines (a
    label and its value, a table heading and its cell) is checked line by line: each line must occur on the cited
    page, though not necessarily next to the others."""
    good = []
    cache: dict[tuple[str, int | None], str] = {}
    for src in sources:
        pieces = [norm(p)[:200] for p in src.excerpt.split("\n") if p.strip()] or [norm(src.excerpt)[:200]]
        scope = src.page if len(pieces) > 1 else None  # separate lines must share the cited page
        if (src.doc_id, scope) not in cache:
            cache[(src.doc_id, scope)] = _text_of(ctx, src.doc_id, scope)
        if all(p in cache[(src.doc_id, scope)] for p in pieces):
            good.append(src)
        else:
            ctx.scratch.warn(f"Dropped a citation to {src.cite()} that could not be verified")
    return good


def _text_of(ctx: ToolContext, doc_id: str, page: int | None) -> str:
    """The stored text of a document, or of one of its pages (its OCR lines and blocks)."""
    pages = [p for p in ctx.pages(doc_id) if page is None or p.number == page]
    parts = [ln.text for p in pages for ln in p.lines] + [b.text for p in pages for b in p.blocks]
    if page is None:
        parts.insert(0, ctx.library.text(doc_id))
    return norm("\n".join(parts))


def _record_sources(records: list[Record]) -> list[Source]:
    out: list[Source] = []
    for record in records:
        out.extend(v.source for v in record.fields.values() if v.source is not None)
    return out


def compose(ctx: ToolContext, plan: Plan, state: TaskState) -> str:
    s = ctx.scratch
    docs = ctx.docs()
    cols = plan.fields
    if plan.blocked:
        s.confidence = 0.0
        return _with_interpretation(plan, "Nothing was run:\n" + "\n".join(f"- {b}" for b in plan.blocked))
    if state == TaskState.FAILED and not s.answer and not s.records:
        return "The task could not be completed. " + (s.warnings[-1] if s.warnings else "")
    if state == TaskState.CANCELLED and not s.answer:
        return "The task was stopped before it finished (cancelled or out of time)."
    where = describe(plan.where) if plan.where is not None else ""
    matched = f" (matching {where})" if where else ""
    match plan.intent:
        case Intent.EXTRACT | Intent.INCONSISTENCIES if s.records and not s.answer:
            s.sources = s.sources or _record_sources(s.records)
            s.confidence = _mean_conf(s.records)
            text = (
                f"Extracted {', '.join(cols)} from {len(s.records)} document(s){matched}:\n\n"
                f"{table_text(s.records, columns=cols)}"
            )
        case Intent.EXTRACT if plan.where is not None and not s.records:
            s.confidence = 0.6
            text = f"No documents match {where}."
        case Intent.EXTRACT:
            text = s.answer or "No fields could be extracted."
        case Intent.FILTER:
            s.sources = _record_sources(s.records)
            s.confidence = _mean_conf(s.records) if s.records else 0.6
            text = (
                f"{len(s.records)} of {len(s.records) + len(s.excluded)} document(s) match {where}:\n\n"
                f"{table_text(s.records, columns=cols)}"
                if s.records
                else f"No documents match {where}."
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
                    f"currencies and are not converted. By currency: {per_unit}{_left_out(calc)}\n\n"
                    f"{table_text(s.records, columns=cols)}"
                )
            else:
                unit = f" {calc['unit']}" if calc.get("unit") else ""
                text = (
                    f"{calc.get('op', '')} of {calc.get('field', '')}: {_fmt(calc.get('result'))}{unit} "
                    f"(over {calc.get('count', 0)} document(s){matched}{_left_out(calc)}; "
                    "computed exactly, not by a model)\n\n"
                    f"{table_text(s.records, columns=cols)}"
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
            if plan.where is not None and not docs:
                text = f"No documents match {where}, so there was nothing to {plan.intent.value}."
    cited = bool(s.sources)
    s.sources = verify_sources(ctx, s.sources)
    if cited and not s.sources and plan.intent == Intent.ASK:
        text = _unverified(ctx, text)
    _flag_injections(ctx)
    text = _with_interpretation(plan, text)
    if s.files:
        text += "\n\nSaved: " + ", ".join(s.files)
    return text.strip()


def _unverified(ctx: ToolContext, text: str) -> str:
    """An answer whose every citation failed verification is not presented as supported."""
    if text.startswith(("I couldn't find", "I could not find", "No passage", "The documents do not")):
        return text
    s = ctx.scratch
    s.confidence = min(s.confidence, 0.2)
    s.warn("Low confidence: none of this answer's citations could be verified in the document text; it is unsupported.")
    s.notes.append("evidence: no citation verified, answer marked unsupported")
    return f"Unverified (no citation could be confirmed in the document text):\n{text}"


def _left_out(calc: dict) -> str:
    missing = calc.get("missing") or 0
    return f"; {missing} document(s) with no {calc.get('field', 'value')} left out" if missing else ""


def _with_interpretation(plan: Plan, text: str) -> str:
    """Say how the request was read, and what was NOT applied, before the result."""
    if plan.where is None and not plan.not_understood and not plan.blocked:
        return text
    head = "Understood as: " + "; ".join(plan.understood()[1:] or plan.understood())
    if plan.not_understood:
        head = (
            "PARTIAL RESULT, not the complete answer to your request.\n"
            + head
            + "\nNot applied: "
            + "; ".join(f"“{x}”" for x in plan.not_understood)
            + "\nThe documents below match only the parts that were applied."
        )
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
