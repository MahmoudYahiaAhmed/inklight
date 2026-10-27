"""One named field read in one document the way an answer reads it: at its printed label, or in the table cell under
or beside its heading (labels.py, table_answer.py). Field extraction, comparison and review use this one routine, so
"extract the registration number" and "What is the registration number?" cannot disagree because one of them never
looked in the table.

Never a passage: when neither a label nor a table cell holds the field, it is not found. Several matching places
(two companies in one table, two copies of a label) come back as candidates, none chosen.
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING, Any

from ..schemas import DocumentInfo, ExtractedValue, Record, Source
from ..textnorm import fold
from .context import Policy, Scratch, ToolContext
from .plan import Intent, Plan

if TYPE_CHECKING:
    from ..extract.fields import FieldSpec
    from ..library import Library

_ARABIC = re.compile(r"[؀-ۿ]")
_DECLINED = ("I couldn't find", "I could not find", "No passage", "The documents do not")
_LOW_OCR = 0.85  # the same bar extraction uses for "low OCR confidence"
_SUPPORTED = 0.7  # the evidence an answer needs to be "supported" (runner.result_outcome)


def question_for(named: str) -> str:
    return f"ما {named}؟" if _ARABIC.search(named) else f"What is the {named}?"


def read_field(ctx: ToolContext, doc: DocumentInfo, named: str) -> dict[str, Any]:
    """{doc_id, document, status: found | several candidates | not found, value, source, warnings, candidates, at,
    confidence} for the field ``named`` (the person's words: "registration number", "رقم القيد") in ``doc``."""
    from .labels import label_answer
    from .table_answer import table_answer

    question = question_for(named)
    saved = ctx.scratch
    try:
        ctx.check()
        ctx.scratch = Scratch(doc_ids=[doc.id], explicit=True)
        at = "table cell" if table_answer(ctx, question) else "label" if label_answer(ctx, question) else None
        sub = ctx.scratch
    finally:
        ctx.scratch = saved
    head = sub.answer.split("\n\nEvidence:")[0].strip()
    entry: dict[str, Any] = {"doc_id": doc.id, "document": doc.name, "value": None, "source": None}
    if at and sub.outcome == "ambiguous":
        return entry | {"status": "several candidates", "candidates": [c.value for c in sub.candidates], "at": at}
    if at and head and not head.startswith(_DECLINED) and sub.sources:
        warnings = list(sub.warnings)
        conf = sub.sources[0].ocr_conf
        if conf is not None and conf < _LOW_OCR and not any("confidence" in w for w in warnings):
            warnings.append(f"OCR read this value with low confidence ({conf:.2f})")
        source = sub.sources[0].model_dump(mode="json")
        return entry | {"status": "found", "value": head, "source": source, "warnings": warnings, "at": at,
                        "confidence": sub.confidence}  # fmt: skip
    return entry | {"status": "not found"}


def context_for(library: Library, doc_ids: list[str]) -> ToolContext:
    """A read-only context for reading fields outside a task (extraction, review)."""
    plan = Plan(intent=Intent.ASK, query="read named fields")
    return ToolContext(library=library, plan=plan, policy=Policy(), scratch=Scratch(doc_ids=doc_ids, explicit=True))


def complete_record(
    ctx: ToolContext, doc: DocumentInfo, record: Record, wanted: list[tuple[FieldSpec, str]], *, day_first: bool
) -> Record:
    """Reconcile typed extraction with the field's printed label or table cell. ``wanted`` pairs each spec with the
    person's words for it.

    - A field typed extraction left empty is read there, with that place as its source, if it parses as the type.
    - A value the typed reader took from the line layout across lines (below a heading, along a row) yields to the
      document's table structure, which knows which cell sits under which heading: the cell's value replaces it, or,
      when the heading has several cells, it stays only if it is one of them.
    - Any other difference from a table cell is flagged for the person to check, never resolved silently. A printed
      label (no table) only fills an empty field: it does not override or flag a value the typed reader found.
    """
    from ..extract.fields import parse_typed

    fields = dict(record.fields)
    for spec, words in wanted:
        current = fields.get(spec.name) or ExtractedValue(field=spec.name)
        found = read_field(ctx, doc, words)
        if current.value is None:
            fields[spec.name] = _filled(spec, current, found, day_first, parse_typed)
        else:
            fields[spec.name] = _reconciled(spec, current, found, day_first, parse_typed)
    return record.model_copy(update={"fields": fields})


# Typed readings that pair a label with a value on another line or across a row, by position: the guess a table's
# structure settles. A value on the label's own line ("Total: 500") is not one of them.
_ACROSS_LINES = {"label-below", "label-next-line", "label-row", "label-row-column", "label-row-opposite"}


def _reconciled(
    spec: FieldSpec, current: ExtractedValue, found: dict[str, Any], day_first: bool, parse
) -> ExtractedValue:  # type: ignore[no-untyped-def]
    if found.get("at") != "table cell":
        # A value the typed reader found is not second-guessed by a printed label: on invoices and receipts the
        # typed reader is the better one (the label reading returns whole lines, and "tax" matches "Tax ID").
        return current
    typed = _key(str(current.raw or current.value))
    by_table = current.method in _ACROSS_LINES
    if found["status"] == "found" and not _same(spec, current, found["value"], day_first, parse):
        if by_table:
            cell = _filled(spec, ExtractedValue(field=spec.name), found, day_first, parse)
            if cell.value is not None:
                note = f"read in its table cell; the line layout suggested “{current.raw or current.value}”"
                return cell.model_copy(update={"warning": _join(cell.warning, note)})
        note = f"at its {found['at']} the document reads “{found['value']}” (page {found['source']['page']}); check"
        return current.model_copy(
            update={"warning": _join(current.warning, note), "confidence": round(current.confidence * 0.8, 3)}
        )
    if found["status"] == "several candidates":
        shown = "; ".join(found["candidates"][:4])
        if by_table and typed not in {_key(c) for c in found["candidates"]}:
            note = (
                f"several candidates in table cells ({shown}), and “{current.raw or current.value}” is not one of "
                "them: none chosen, pick one in Review"
            )
            return ExtractedValue(field=spec.name, warning=_join(current.warning, note))
        note = f"several candidates at a {found['at']} ({shown}); check that this is the one you mean"
        return current.model_copy(
            update={"warning": _join(current.warning, note), "confidence": round(current.confidence * 0.8, 3)}
        )
    return current


def _filled(spec: FieldSpec, current: ExtractedValue, found: dict[str, Any], day_first: bool, parse) -> ExtractedValue:  # type: ignore[no-untyped-def]
    if found["status"] == "several candidates":
        shown = "; ".join(found["candidates"][:4])
        note = f"several candidates at a {found['at']} ({shown}): none chosen, pick one in Review"
        return current.model_copy(update={"warning": _join(current.warning, note)})
    if found["status"] != "found":
        return current
    raw = found["value"]
    if found["at"] == "label" and (found["warnings"] or (found.get("confidence") or 0.0) < _SUPPORTED):
        # A printed label outside a table fills a field only when its reading would be a supported answer: cited,
        # with no warning (a label like "Tax ID" for "tax" is warned about, and then not proposed).
        return current
    parsed = parse(spec.type, _ascii_digits(raw), day_first)
    source = Source.model_validate(found["source"])
    if parsed is None:
        note = f"“{raw}” is at its {found['at']} but is not a {spec.type}: not proposed"
        return current.model_copy(update={"warning": _join(current.warning, note), "source": source})
    from ..extract.fields import _jsonable

    conf = min(found.get("confidence") or 0.0, source.ocr_conf if source.ocr_conf is not None else 1.0)
    return ExtractedValue(
        field=spec.name,
        value=_jsonable(parsed[0]),
        raw=raw,
        confidence=round(conf, 3),
        method=found["at"],
        source=source,
        verified=raw in source.excerpt,
        warning="; ".join(found["warnings"]) or None,
    )


def _same(spec: FieldSpec, current: ExtractedValue, text: str, day_first: bool, parse) -> bool:  # type: ignore[no-untyped-def]
    """Whether a cell's text holds the typed value: the same text, or the same value once parsed as the type."""
    if _key(text) == _key(str(current.raw or current.value)):
        return True
    parsed = parse(spec.type, _ascii_digits(text), day_first)
    from ..extract.fields import _jsonable

    return parsed is not None and _jsonable(parsed[0]) == current.value


def _key(value: str) -> str:
    return fold(value)  # case, spacing, punctuation and digit script do not make two readings differ


def _ascii_digits(text: str) -> str:
    """Arabic-Indic and other decimal digits as ASCII, so "٤٧٣١٩" parses as a number or an id."""
    return "".join(str(unicodedata.decimal(ch)) if ch.isdigit() and unicodedata.decimal(ch, None) is not None else ch
                   for ch in text)  # fmt: skip


def _join(a: str | None, b: str) -> str:
    return f"{a}; {b}" if a else b
