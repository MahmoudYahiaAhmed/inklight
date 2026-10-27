"""Structured tools: extraction, filtering, calculation, comparison, consistency, output."""

from __future__ import annotations

import csv
import difflib
import io
import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from ..errors import PermissionDenied, ToolError
from ..extract import CATALOG, extract_record, resolve_field
from ..extract.fields import parse_typed
from ..safety import safe_output_path
from ..schemas import ExtractedValue, Record, Source
from ..textnorm import fold
from .answer import norm
from .context import ToolContext
from .coverage import unavailable_reason
from .expr import evaluate, leaves
from .plan import Condition, Group

# ---------------------------------------------------------------- extract

QUESTIONS = {
    "vendor": "Which company issued this document?",
    "customer": "Who is the document billed or addressed to?",
    "invoice_number": "What is the invoice number?",
    "date": "What is the date of the document?",
    "due_date": "When is payment due?",
    "expiry_date": "When does the agreement expire?",
    "effective_date": "When does the agreement take effect?",
    "total": "What is the total amount due?",
    "tax": "How much is the tax?",
}
_LABEL_WORDS = {label for spec in CATALOG.values() for label in spec.all_labels()}


def extract_fields(ctx: ToolContext, fields: list[str]) -> str:
    specs = [resolve_field(f) for f in fields]
    records = []
    for doc in ctx.docs():
        ctx.check()
        record = extract_record(
            doc,
            ctx.pages(doc.id),
            specs,
            day_first=ctx.settings.extraction.day_first,
            reread=ctx.library.rereader(doc),
        )
        record = _reader_fill(ctx, record, specs)
        records.append(record)
        for name, value in record.fields.items():
            if value.warning and value.value is not None:
                ctx.scratch.warn(f"{doc.name} · {name}: {value.warning}")
    ctx.scratch.records = records
    found = sum(1 for r in records for v in r.fields.values() if v.value is not None)
    total = len(records) * len(specs)
    return f"{found}/{total} values from {len(records)} documents"


def _reader_fill(ctx: ToolContext, record: Record, specs: list[Any]) -> Record:
    """Ask the extractive reader for fields that have no labelled value."""
    reader = ctx.brain.reader
    if reader is None:
        return record
    missing = [s for s in specs if record.fields[s.name].value is None or record.fields[s.name].method != "label"]
    if not missing:
        return record
    chunks = ctx.library.store.chunks_for([record.doc_id])[:12]
    if not chunks:
        return record
    updated = dict(record.fields)
    for spec in missing:
        ctx.check()
        current = updated[spec.name]
        if current.value is not None and current.method != "none":
            continue  # a heuristic value exists; the reader only fills real gaps
        question = QUESTIONS.get(spec.name) or f"What is the {spec.description.lower() or spec.name.replace('_', ' ')}?"
        spans = reader.answer(question, [src.excerpt for _, src in chunks], top=1, check=ctx.check)
        if not spans or spans[0].score < 0.35:
            continue
        span = spans[0]
        if ":" in span.text or span.text.lower() in _LABEL_WORDS:
            continue  # the reader picked a label, not a value
        parsed = parse_typed(spec.type, span.text, ctx.settings.extraction.day_first)
        if parsed is None:
            continue
        src: Source = chunks[span.passage][1]
        value = parsed[0]
        value = float(value) if isinstance(value, Decimal) else value
        value = value.isoformat() if isinstance(value, date) else value
        updated[spec.name] = ExtractedValue(
            field=spec.name,
            value=value,
            raw=span.text,
            confidence=round(span.score * 0.8, 3),
            method="reader",
            source=src.model_copy(update={"excerpt": src.excerpt[max(0, span.start - 80) : span.end + 80]}),
            verified=span.text in src.excerpt,
            warning="found by the reader model without a label; please check",
        )
        ctx.scratch.brain_used.add("reader")
    return record.model_copy(update={"fields": updated})


# ---------------------------------------------------------------- filter


def _as_decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def matches(item: ExtractedValue, cond: Condition, today: date) -> tuple[bool | None, str | None]:
    """(True/False, None), or (None, reason) when the value is missing or not comparable."""
    value = item.value
    if value is None:
        return None, "missing"
    if cond.op in ("contains", "not_contains"):
        found = _norm_name(str(cond.value)) in _norm_name(str(value))
        return (found if cond.op == "contains" else not found), None
    if cond.op in ("within_days", "before", "after"):
        d = _as_date(value)
        limit = _as_date(cond.value)
        if d is None or (cond.op != "within_days" and limit is None):
            return None, "missing"
        if cond.op == "within_days":
            return today <= d <= today + timedelta(days=int(cond.value)), None
        return (d < limit if cond.op == "before" else d > limit), None  # type: ignore[operator]
    if cond.unit and item.unit and cond.unit != item.unit:
        return None, "currency"  # never compare EUR 6,000 with a USD threshold
    a, b = _as_decimal(value), _as_decimal(cond.value)
    if a is None or b is None:
        if cond.op == "eq":
            return str(value).strip().lower() == str(cond.value).strip().lower(), None
        return None, "missing"
    return {"gt": a > b, "ge": a >= b, "lt": a < b, "le": a <= b, "eq": a == b}[cond.op], None


def _norm_name(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s&]", " ", text.lower())).strip()


def filter_records(ctx: ToolContext, where: Condition | Group, today: date | None = None) -> str:
    """Keep the records for which ``where`` is True, then narrow the document scope to them.

    Unknown (a missing value, or a currency that cannot be compared) is never a match: those
    records are excluded and named in a warning, separately from the true non-matches.
    """
    today = today or date.today()
    conditions = leaves(where)
    kept, dropped, unknown, wrong_currency = [], [], [], []
    for record in ctx.scratch.records:

        def check(cond: Condition, record: Record = record) -> tuple[bool | None, frozenset[str]]:
            verdict, reason = matches(record.fields.get(cond.field, ExtractedValue(field=cond.field)), cond, today)
            return verdict, frozenset({reason}) if reason else frozenset()

        verdict, reasons = evaluate(where, check)
        if verdict is True:
            kept.append(record)
        elif verdict is False:
            dropped.append(record)
        elif "currency" in reasons:
            wrong_currency.append(record)
        else:
            unknown.append(record)
    ctx.scratch.records = kept
    ctx.scratch.excluded = dropped + unknown + wrong_currency
    if unknown or wrong_currency:
        # Some documents could not be evaluated, so the selection may be incomplete.
        ctx.scratch.partial = True
    # Every later step (answering, comparing, summarizing, counting) works on the matches only.
    kept_ids = {r.doc_id for r in kept}
    ctx.scratch.doc_ids = [d for d in ctx.scratch.doc_ids if d in kept_ids]
    if unknown:
        names = ", ".join(r.name for r in unknown[:5]) + (" …" if len(unknown) > 5 else "")
        fields = ", ".join(sorted({c.field for c in conditions}))
        ctx.scratch.warn(f"{len(unknown)} document(s) had no readable {fields} and were excluded: {names}")
    if wrong_currency:
        units = sorted({c.unit for c in conditions if c.unit})
        names = ", ".join(r.name for r in wrong_currency[:5])
        ctx.scratch.warn(
            f"{len(wrong_currency)} document(s) are in a different currency than {'/'.join(units)} and were "
            f"excluded; Inklight does not convert currencies: {names}"
        )
    return f"{len(kept)} match, {len(dropped)} do not, {len(unknown) + len(wrong_currency)} not comparable"


# ---------------------------------------------------------------- calculate


def calculate(ctx: ToolContext, op: str, field: str) -> str:
    values: list[tuple[Decimal, Record, str | None]] = []
    for record in ctx.scratch.records:
        item = record.fields.get(field, ExtractedValue(field=field))
        d = _as_decimal(item.value)
        if d is not None:
            values.append((d, record, item.unit))
    missing = len(ctx.scratch.records) - len(values)
    groups: dict[str | None, list[Decimal]] = {}
    for d, _, unit in values:
        groups.setdefault(unit, []).append(d)
    calc: dict[str, Any] = {"op": op, "field": field, "count": len(values), "missing": missing, "unit": None}
    stated = [u for u in groups if u]
    if op != "count" and len(stated) == 1 and None in groups:
        # Amounts with no currency beside one stated currency: combine them, but say so.
        unstated = len(groups.pop(None))
        groups[stated[0]] = [v for v, _, _ in values]
        ctx.scratch.warn(
            f"{unstated} {field} value(s) state no currency; they were assumed to be {stated[0]} like the others."
        )
    if op != "count" and len(groups) > 1:
        # Adding $100 and EUR 100 gives a number that means nothing: report per currency instead.
        calc["result"] = None
        calc["by_unit"] = {(u or "unstated"): float(round(_aggregate(op, vs), 2)) for u, vs in groups.items()}
        ctx.scratch.partial = True
        ctx.scratch.warn(
            f"The {field} values are in different currencies ({', '.join(u or 'unstated' for u in groups)}). "
            "Inklight does not convert currencies, so no combined result was computed."
        )
    else:
        result = (
            Decimal(len(values)) if op == "count" else (_aggregate(op, [v for v, _, _ in values]) if values else None)
        )
        calc["result"] = None if result is None else float(round(result, 2))
        calc["unit"] = next(iter(groups)) if len(groups) == 1 and op != "count" else None
    ctx.scratch.calc = calc
    if missing:
        # A sum or average over part of the documents is not the answer to the request: partial, not succeeded.
        ctx.scratch.partial = True
        ctx.scratch.warn(f"{missing} document(s) had no {field} and were left out of the {op}")
    return f"{op}({field}) = {calc.get('result', calc.get('by_unit'))} over {len(values)} values"


def _aggregate(op: str, values: list[Decimal]) -> Decimal:
    if op == "sum":
        return sum(values, Decimal(0))
    if op == "avg":
        return sum(values, Decimal(0)) / len(values)
    if op == "max":
        return max(values)
    if op == "min":
        return min(values)
    raise ToolError(f"Unknown operation {op!r}")


# ---------------------------------------------------------------- compare


def compare_documents(ctx: ToolContext, fields: list[str]) -> str:
    docs = ctx.docs()
    s = ctx.scratch
    if len(docs) < 2 and docs and len(docs) + len(s.unavailable) >= 2:
        # Two documents were selected but one cannot be read: say so, rather than "select two documents".
        named = _named_field(ctx.plan.query)
        if named and not fields:
            return _compare_field(ctx, docs, named)
        s.answer = (
            f"Not compared: only {len(docs)} of the {len(docs) + len(s.unavailable)} selected documents can be read."
        )
        s.partial = True
        return "comparison: not enough readable documents"
    if len(docs) < 2:
        raise ToolError(
            "Comparison needs at least two documents: select them (Ctrl/⌘-click in the workspace) or give each file"
        )
    docs = docs[:5]
    if len(ctx.docs()) > 5:
        ctx.scratch.warn("Compared the first 5 documents only")
    named = _named_field(ctx.plan.query)
    if named and not fields:
        return _compare_field(ctx, docs, named)
    types = {d.doc_type for d in docs}
    if not fields:
        # Field-level comparison only where fields are meaningful; otherwise compare the text.
        fields = (
            ["invoice_number", "vendor", "date", "subtotal", "tax", "total"]
            if types <= {"invoice", "receipt"}
            else ["effective_date", "expiry_date", "contract_value"]
            if types == {"contract"}
            else []
        )
    specs = [resolve_field(f) for f in fields]
    day_first = ctx.settings.extraction.day_first
    records = [
        extract_record(d, ctx.pages(d.id), specs, day_first=day_first, reread=ctx.library.rereader(d)) for d in docs
    ]
    ctx.scratch.records = records
    base, base_doc = records[0], docs[0]
    lines: list[str] = []
    sources: list[Source] = []
    for other, doc in zip(records[1:], docs[1:], strict=True):
        ctx.check()
        diffs = []
        for spec in specs:
            a, b = base.fields[spec.name], other.fields[spec.name]
            if a.value != b.value and (a.value is not None or b.value is not None):
                diffs.append(
                    f"{spec.name}: {a.value if a.value is not None else '—'} → "
                    f"{b.value if b.value is not None else '—'}"
                )
                sources.extend(x.source for x in (a, b) if x.source)
        text_a = [norm(x) for x in ctx.library.text(base_doc.id).splitlines() if x.strip()]
        text_b = [norm(x) for x in ctx.library.text(doc.id).splitlines() if x.strip()]
        only_a = [x for x in text_a if x not in set(text_b)]
        only_b = [x for x in text_b if x not in set(text_a)]
        ratio = difflib.SequenceMatcher(None, "\n".join(text_a), "\n".join(text_b), autojunk=False).ratio()
        block = [f"**{base_doc.name} vs {doc.name}** — text similarity {ratio:.0%}"]
        if specs:
            shown = ", ".join(sp.name.replace("_", " ") for sp in specs)
            found_any = any(x.fields[sp.name].value is not None for x in (base, other) for sp in specs)
            block.append(
                f"Fields compared ({shown}), as extracted:\n" + "\n".join(f"  - {d}" for d in diffs)
                if diffs
                else f"Fields compared ({shown}), as extracted: no difference in the values read"
                + ("" if found_any else " (no value was found in either document)")
            )
        changed = _changed_numbers(only_a, only_b)
        if changed:
            block.append("Changed figures: " + "; ".join(changed[:8]))
        if only_a or only_b:
            block.append(
                f"Lines only in {base_doc.name} ({len(only_a)}):\n" + "\n".join(f"  - {x[:160]}" for x in only_a[:5])
            )
            block.append(
                f"Lines only in {doc.name} ({len(only_b)}):\n" + "\n".join(f"  - {x[:160]}" for x in only_b[:5])
            )
        lines.append("\n".join(block))
    ctx.scratch.answer = "\n\n".join(lines)
    if not sources:
        for doc in docs:
            first = ctx.library.store.chunks_for([doc.id])[:1]
            sources.extend(src for _, src in first)
    ctx.scratch.sources = sources[:10]
    ctx.scratch.confidence = 0.8
    if not specs:
        # A diff of the text is not a comparison of what the person asked about: say so, and show it as found.
        ctx.scratch.answer = (
            "Text comparison only — not a field comparison. To compare one value, name it (“compare the "
            "registration number in these documents”).\n\n" + ctx.scratch.answer
        )
        ctx.scratch.outcome = "extracted"
    return f"compared {len(docs)} documents"


# Words of a comparison request that are not the field compared.
_COMPARE_WORDS = set(
    [
        "compare",
        "comparison",
        "compared",
        "match",
        "matches",
        "matching",
        "same",
        "different",
        "differ",
        "differs",
        "difference",
        "between",
        "and",
        "with",
        "against",
        "versus",
        "vs",
        "these",
        "those",
        "this",
        "that",
        "two",
        "both",
        "each",
        "all",
        "the",
        "a",
        "an",
        "in",
        "of",
        "on",
        "from",
        "for",
        "to",
        "is",
        "are",
        "do",
        "does",
        "whether",
        "document",
        "documents",
        "file",
        "files",
        "paper",
        "papers",
        "record",
        "records",
        "check",
        "verify",
        "explain",
        "show",
        "list",
        "tell",
        "me",
        "what",
        "which",
        "differences",
        "any",
        "changes",
        "changed",
        "please",
        "قارن",
        "قارني",
        "مقارنه",
        "مقارنة",
        "بين",
        "و",
        "مع",
        "هل",
        "نفس",
        "مطابق",
        "يطابق",
        "متطابق",
        "تطابق",
        "في",
        "كل",
        "من",
        "على",
        "المستندين",
        "الوثيقتين",
        "الملفين",
        "المستندات",
        "الوثائق",
        "الملفات",
        "المستند",
        "الوثيقة",
        "الملف",
        "الورقتين",
        "اتنين",
        "اثنين",
    ]
)
_DECLINED = ("I couldn't find", "I could not find")


# Words that introduce the documents compared ("… in the contract and the register", "… في العقد").
_DOC_BOUNDARY = set(
    [
        "in",
        "within",
        "across",
        "with",
        "against",
        "versus",
        "vs",
        "between",
        "on",
        "from",
        "for",
        "في",
        "مع",
        "على",
        "من",
        "عبر",
        "داخل",
    ]
)
_DOC_TYPE_WORDS = set(
    [
        "contract",
        "contracts",
        "agreement",
        "agreements",
        "register",
        "registers",
        "registry",
        "extract",
        "extracts",
        "certificate",
        "certificates",
        "card",
        "cards",
        "invoice",
        "invoices",
        "receipt",
        "receipts",
        "letter",
        "letters",
        "report",
        "reports",
        "form",
        "forms",
        "nda",
        "commercial",
        "العقد",
        "العقود",
        "عقد",
        "الاتفاقيه",
        "الاتفاقية",
        "مستخرج",
        "الشهاده",
        "الشهادة",
        "البطاقه",
        "البطاقة",
        "الفاتوره",
        "الفاتورة",
        "الخطاب",
        "الرساله",
        "الرسالة",
        "التقرير",
    ]
)


def _named_field(request: str) -> str:
    """The field a comparison request names, or "" when it names none: the words before the ones that introduce
    the documents ("compare the registration number | in the contract and the register" -> "registration number",
    "قارن بين رقم السجل | في العقد ومستخرج السجل" -> "رقم السجل"). Words that only describe documents ("compare
    these two contracts") name no field."""
    kept: list[str] = []
    for word in re.findall(r"[^\W\d_]+", request):
        key = word.casefold()
        if key in _DOC_BOUNDARY and kept:
            break
        if key not in _COMPARE_WORDS and len(word) > 1:
            kept.append(word)
    if not kept or all(w.casefold() in _DOC_TYPE_WORDS for w in kept):
        return ""
    return " ".join(kept) if len(kept) <= 6 else ""


def _compare_field(ctx: ToolContext, docs: list[Any], named: str) -> str:
    """Read the named field in each document on its own (its printed label or table cell), show each value with its
    evidence, then say whether they match. Any document without a single readable value: cannot determine."""
    from .context import Scratch
    from .labels import label_answer
    from .table_answer import table_answer

    question = f"ما {named}؟" if re.search(r"[؀-ۿ]", named) else f"What is the {named}?"
    saved = ctx.scratch
    values: list[dict[str, Any]] = []
    try:
        for doc in docs:
            ctx.check()
            ctx.scratch = Scratch(doc_ids=[doc.id], explicit=True)
            used = table_answer(ctx, question) or label_answer(ctx, question)
            sub = ctx.scratch
            head = sub.answer.split("\n\nEvidence:")[0].strip()
            entry: dict[str, Any] = {"doc_id": doc.id, "document": doc.name, "value": None, "source": None}
            if used and sub.outcome == "ambiguous":
                entry["status"] = "several candidates"
                entry["candidates"] = [c.value for c in sub.candidates]
            elif used and head and not head.startswith(_DECLINED) and sub.sources:
                entry |= {"status": "found", "value": head, "source": sub.sources[0].model_dump(mode="json")}
                entry["warnings"] = list(sub.warnings)
                conf = sub.sources[0].ocr_conf
                if conf is not None and conf < _LOW_OCR and not any("confidence" in w for w in sub.warnings):
                    entry["warnings"].append(f"OCR read this value with low confidence ({conf:.2f})")
            else:
                entry["status"] = "not found"
            values.append(entry)
    finally:
        ctx.scratch = saved
    for item in ctx.scratch.unavailable:
        values.append({**_entry_of(item), "status": "not available", "reason": unavailable_reason(item)})
    found = [v for v in values if v["status"] == "found"]
    flagged = [v for v in found if v.get("warnings")]
    if len(found) == len(values):
        keys = {_value_key(v["value"]) for v in found}
        verdict = "matches" if len(keys) == 1 else "differs"
        if verdict == "differs" and flagged:
            verdict = "cannot determine"  # a difference resting on a doubtful reading is not a finding
    else:
        verdict = "cannot determine"
    s = ctx.scratch
    for v in flagged:
        for w in v["warnings"]:
            s.warn(f"{v['document']}: {w}")
    lines = [f"Compared “{named}” in {len(values)} documents:"]
    for v in values:
        if v["status"] == "found":
            doubt = " ⚠ " + "; ".join(v["warnings"]) if v.get("warnings") else ""
            lines.append(f"- {v['document']}: {v['value']} (page {v['source']['page']}){doubt}")
        elif v["status"] == "not available":
            lines.append(f"- {v['document']}: not compared: {v['reason']}")
        elif v["status"] == "several candidates":
            lines.append(f"- {v['document']}: several candidates ({', '.join(v['candidates'][:4])}) — choose one")
        else:
            lines.append(f"- {v['document']}: not found at a printed label or table cell")
    why = {
        "matches": "the values read are the same",
        "differs": "the values read are different",
        "cannot determine": "a value was read with low confidence; check the documents yourself"
        if flagged and len(found) == len(values)
        else "not every selected document could be read"
        if any(v["status"] == "not available" for v in values)
        else "a value could not be read in every document; check the documents yourself",
    }[verdict]
    lines.append(f"Result: {verdict} — {why}. Check the cited places: OCR can misread a value.")
    s.answer = "\n".join(lines)
    s.sources = [Source.model_validate(v["source"]) for v in found]
    s.comparison = {"field": named, "values": values, "verdict": verdict}
    s.outcome = "partial" if verdict == "cannot determine" else "proposed"
    s.confidence = 0.6 if verdict != "cannot determine" else 0.3
    if verdict == "cannot determine":
        s.partial = True
    return f"field comparison: {verdict}"


def _entry_of(item: dict[str, Any]) -> dict[str, Any]:
    return {"doc_id": item["doc_id"], "document": item["document"], "value": None, "source": None}


_LOW_OCR = 0.85  # the same bar extraction uses for "low OCR confidence"


def _value_key(value: str) -> str:
    """A value compared across documents: digits in Latin form, without spaces or punctuation, case folded
    (textnorm.fold; a digit-like sign with no decimal value, such as "²", is kept as it is)."""
    return fold(value)


def _changed_numbers(only_a: list[str], only_b: list[str]) -> list[str]:
    """Pair lines that differ only in their figures and report old → new."""
    out = []
    shape = re.compile(r"(?<![A-Za-z])\$?\d(?:[\d,]*\d)?(?:\.\d+)?%?")
    for a in only_a:
        for b in only_b:
            # Lines pair up when they match with every digit masked ("Q1" vs "Q2" included).
            if re.sub(r"\d+", "#", a) == re.sub(r"\d+", "#", b) and a != b:
                pairs = [f"{x} → {y}" for x, y in zip(shape.findall(a), shape.findall(b), strict=False) if x != y]
                if pairs:
                    out.append(f"{', '.join(pairs)} (in “{a[:70]}”)")
                break
    return out


# ---------------------------------------------------------------- inconsistencies


def _key(text: str) -> str:
    text = re.sub(r"\b(inc|ltd|llc|corp|co|corporation|limited|company|plc|gmbh)\b\.?", "", text.lower())
    return fold(text, keep="@")  # every script kept: different Arabic names are different keys


def find_inconsistencies(ctx: ToolContext, fields: list[str]) -> str:
    issues: list[str] = []
    sources: list[Source] = []
    records = ctx.scratch.records
    for name in fields:
        seen: dict[str, list[tuple[str, Record]]] = {}
        values = [
            (str(r.fields[name].value), r)
            for r in records
            if name in r.fields and r.fields[name].value is not None and isinstance(r.fields[name].value, str)
        ]
        for value, record in values:
            placed = False
            for key in list(seen):
                ratio = difflib.SequenceMatcher(None, key, _key(value)).ratio()
                if key == _key(value) or ratio >= 0.85:
                    seen[key].append((value, record))
                    placed = True
                    break
            if not placed:
                seen[_key(value)] = [(value, record)]
        for group in seen.values():
            variants = sorted({v for v, _ in group})
            if len(variants) > 1:
                where = "; ".join(f"“{v}” in {r.name}" for v, r in group[:6])
                issues.append(f"{name}: {len(variants)} spellings of what looks like one value — {where}")
                sources.extend(src for _, r in group if (src := r.fields[name].source) is not None)
    for record in records:
        total = record.fields.get("total")
        if total and total.warning and "does not equal" in total.warning:
            issues.append(f"{record.name}: subtotal + tax does not equal total")
            if total.source:
                sources.append(total.source)
        d, due = record.fields.get("date"), record.fields.get("due_date")
        if d and due and d.value and due.value and str(due.value) < str(d.value):
            issues.append(f"{record.name}: due date {due.value} is before the document date {d.value}")
    empty = [r.name for r in records if all(v.value is None for v in r.fields.values())]
    ctx.scratch.sources = sources[:12]
    if empty:
        ctx.scratch.warn(f"{len(empty)} document(s) had none of the requested fields: " + ", ".join(empty[:5]))
    if issues:
        ctx.scratch.answer = f"Found {len(issues)} possible inconsistencies:\n" + "\n".join(f"- {i}" for i in issues)
    else:
        ctx.scratch.answer = f"No inconsistencies found across {len(records)} documents for: {', '.join(fields)}."
    ctx.scratch.confidence = 0.75
    return f"{len(issues)} issues"


# ---------------------------------------------------------------- write


def render(ctx: ToolContext, fmt: str) -> str:
    s = ctx.scratch
    # Export exactly the filtered records, with only the columns that were asked for.
    records = [r.project(ctx.plan.fields) for r in s.records]
    rows = [r.flat() for r in records]
    if fmt == "csv":
        fields: list[str] = []
        for record in records:
            for name in record.fields:
                if name not in fields:
                    fields.append(name)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["document", *fields, *[f"{f}_confidence" for f in fields], "pages", "warnings"])
        for record in records:
            vals = [record.fields[f].value if f in record.fields else None for f in fields]
            confs = [record.fields[f].confidence if f in record.fields else None for f in fields]
            pages = sorted({v.source.page for v in record.fields.values() if v.source})
            warns = "; ".join(f"{k}: {v.warning}" for k, v in record.fields.items() if v.warning)
            writer.writerow(
                [_csv_safe(record.name), *map(_csv_safe, vals), *confs, " ".join(map(str, pages)), _csv_safe(warns)]
            )
        if not records and s.answer:
            writer.writerow(["answer"])
            writer.writerow([_csv_safe(s.answer)])
        return buf.getvalue()
    if fmt == "json":
        return json.dumps(
            {
                "request": ctx.plan.query,
                "understood_as": list(ctx.plan.understood()),
                "answer": s.answer,
                "rows": rows,
                "records": [r.model_dump(mode="json") for r in records],
                "calculation": s.calc,
                "sources": [x.model_dump(mode="json") for x in s.sources],
                "warnings": s.warnings,
            },
            indent=2,
            default=str,
        )
    out = [f"# {ctx.plan.query}\n", s.answer or "", ""]
    if rows:
        cols = list(rows[0])
        out += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        out += ["| " + " | ".join(_md_cell(r.get(c, "")) for c in cols) + " |" for r in rows]
    if s.sources:
        out += ["", "## Sources"] + [f"- {x.cite()}: “{x.excerpt[:200]}”" for x in s.sources]
    if s.warnings:
        out += ["", "## Warnings"] + [f"- {w}" for w in s.warnings]
    return "\n".join(out) + "\n"


def _md_cell(value: Any) -> str:
    """Document text must not break out of a Markdown table cell."""
    return str(_csv_safe(value)).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _csv_safe(value: Any) -> Any:
    """Neutralise spreadsheet formula injection from document text."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "|", "\t", "\r"):
        return "'" + value
    return value


def write_output(ctx: ToolContext, fmt: str, name: str | None) -> str:
    if ctx.plan.not_understood:
        # A file looks final; never let a partial selection pass for the full request.
        raise ToolError(
            "Not saved: part of the request was not applied ("
            + "; ".join(f"“{x}”" for x in ctx.plan.not_understood)
            + "), so the selection may be incomplete. Rephrase the request, or remove that part, to export."
        )
    policy = ctx.policy
    content = render(ctx, fmt)
    root = policy.output_dir or ctx.settings.outputs
    stem = name or f"inklight-{ctx.plan.intent.value}-{date.today().isoformat()}.{fmt}"
    if not stem.lower().endswith(f".{fmt}"):
        stem = f"{stem}.{fmt}"
    target = safe_output_path(root, stem, {f".{fmt}"})
    if not policy.allow_write:
        raise PermissionDenied(
            f"Writing {target.name} needs permission (CLI: --yes or --out DIR; Python: allow_write=True)"
        )
    if target.exists() and not policy.overwrite:
        base, suffix, n = target.stem, target.suffix, 2
        while target.exists():
            target = target.with_name(f"{base}-{n}{suffix}")
            n += 1
    if policy.confirm is not None and not policy.confirm(f"Write {len(content):,} bytes to {target}?"):
        raise PermissionDenied("The user declined the file write")
    root.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8", newline="")
    ctx.scratch.files.append(str(target))
    return f"wrote {target.name} ({len(content):,} bytes)"
