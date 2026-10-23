"""Turn a natural-language request into a bounded, typed plan.

Plans come only from the user's request, never from document text, so an
instruction hidden in a PDF cannot add or change tool calls.

The rule planner is deterministic and measured (see bench/). When it is
unsure and a remote model is configured, the remote model may propose a plan,
which is validated against the same schema and the same tool allow-list.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import Any

from pydantic import ValidationError

from ..brains import Brain
from ..errors import ModelUnavailable
from ..extract import SINGULAR, resolve_field
from ..extract.values import parse_dates, parse_number
from .plan import Condition, Intent, Plan, Step

log = logging.getLogger(__name__)

_MONEY_FIELDS = {"tax", "subtotal", "total", "contract_value", "amount"}
_CMP = {
    "above": "gt",
    "over": "gt",
    "greater than": "gt",
    "more than": "gt",
    "exceeding": "gt",
    "exceeds": "gt",
    "higher than": "gt",
    "larger than": "gt",
    ">": "gt",
    "at least": "ge",
    ">=": "ge",
    "minimum of": "ge",
    "below": "lt",
    "under": "lt",
    "less than": "lt",
    "lower than": "lt",
    "smaller than": "lt",
    "<": "lt",
    "at most": "le",
    "<=": "le",
    "maximum of": "le",
    "equal to": "eq",
    "exactly": "eq",
}
_CMP_RE = re.compile(
    r"(?:(?P<field>tax|subtotal|total|amount|value|vat|price)\s+(?:is\s+|of\s+)?)?"
    r"(?P<op>" + "|".join(sorted((re.escape(k) for k in _CMP), key=len, reverse=True)) + r")\s*"
    r"(?P<cur>[$€£])?\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<mult>k|m|thousand|million)?\b"
    # "under 30 days" or "at least 2 pages" are not amounts.
    r"(?!\s*(?:days?|weeks?|months?|years?|pages?|items?|docs?|documents?|files?|lines?|%))",
    re.IGNORECASE,
)
_WITHIN_RE = re.compile(
    r"\b(?P<what>expir\w*|due|end(?:s|ing)?|renew\w*|terminat\w*)\b[^.]{0,30}?\b(?:within|in the next|in)\s+"
    r"(?P<n>\d+)\s*(?P<unit>day|week|month|year)s?",
    re.IGNORECASE,
)
_DATE_CMP_RE = re.compile(r"\b(?P<op>before|after|since|until|prior to)\s+(?P<rest>.{4,30})", re.IGNORECASE)

_FIELD_LEAD = re.compile(
    r"(?:\bcsv\s+(?:file\s+)?(?:of|with)|\bjson\s+(?:file\s+)?(?:of|with)|\btable\s+(?:of|with)|\bextract(?:ing)?|"
    r"\bpull(?:\s+out)?|\bget|\blist|\bcolumns?|\bfields?|\bcontaining|\bwith columns)\s+(?P<rest>.+)",
    re.IGNORECASE,
)
_FIELD_STOP = re.compile(
    r"\b(?:from|in|for|across|then|and (?:create|save|export|write|flag|find|compare|show|put)|flag|that|which|"
    r"where|whose|above|over|below|under|into|to a|as a|as csv|as json|within|expir\w*)\b|[.;?!]",
    re.IGNORECASE,
)
_NOISE = {
    "",
    "the",
    "a",
    "an",
    "all",
    "every",
    "each",
    "of",
    "their",
    "its",
    "these",
    "those",
    "this",
    "me",
    "data",
    "info",
    "information",
    "details",
    "fields",
    "values",
    "records",
    "documents",
    "files",
    "it",
    "them",
    "everything",
    "and",
    "csv",
    "json",
    "table",
}


def _fields(request: str) -> list[str]:
    m = _FIELD_LEAD.search(request)
    if not m:
        return []
    segment = _FIELD_STOP.split(m.group("rest"))[0]
    parts = re.split(r",|\band\b|&|/|\+", segment, flags=re.IGNORECASE)
    out: list[str] = []
    for part in parts:
        word = re.sub(r"\s+", " ", part).strip(" :'\"").lower()
        word = re.sub(r"^(?:the|all|every|each|their|its)\s+", "", word)
        word = re.sub(r"\s+(?:of|from|in)$", "", word)
        if word in _NOISE or word in SINGULAR or word.rstrip("s") in SINGULAR.values() or len(word) > 40:
            continue
        name = resolve_field(word).name
        if name not in out:
            out.append(name)
    return out


def _doc_type(text: str) -> str | None:
    for plural, singular in SINGULAR.items():
        if re.search(rf"\b({plural}|{singular})\b", text):
            return singular
    return None


def _conditions(request: str, today: date) -> list[Condition]:
    conds: list[Condition] = []
    for m in _CMP_RE.finditer(request):
        num = parse_number(m.group("num"))
        if num is None:
            continue
        mult = (m.group("mult") or "").lower()
        if mult in ("k", "thousand"):
            num *= 1000
        elif mult in ("m", "million"):
            num *= 1_000_000
        field = (m.group("field") or "total").lower()
        field = {"amount": "total", "price": "total", "value": "contract_value", "vat": "tax"}.get(field, field)
        conds.append(Condition(field=field, op=_CMP[m.group("op").lower()], value=float(num)))  # type: ignore[arg-type]
    for m in _WITHIN_RE.finditer(request):
        days = int(m.group("n")) * {"day": 1, "week": 7, "month": 30, "year": 365}[m.group("unit").lower()]
        field = "due_date" if m.group("what").lower().startswith("due") else "expiry_date"
        conds.append(Condition(field=field, op="within_days", value=days))
    for m in _DATE_CMP_RE.finditer(request):
        hits = parse_dates(m.group("rest"))
        if hits:
            op = "before" if m.group("op").lower() in ("before", "until", "prior to") else "after"
            field = "expiry_date" if re.search(r"\b(expir\w*|end(?:s|ing)?)\b", request, re.I) else "date"
            conds.append(Condition(field=field, op=op, value=hits[0][0].isoformat()))  # type: ignore[arg-type]
    return conds


def _output(text: str) -> tuple[str | None, str | None]:
    fmt = None
    if re.search(r"\b(csv|spreadsheet|excel)\b", text):
        fmt = "csv"
    elif re.search(r"\bjson\b", text):
        fmt = "json"
    elif re.search(r"\b(markdown|md file|report file|write (?:a|the) report)\b", text):
        fmt = "md"
    name = re.search(r"\b(?:called|named|to|as)\s+[\"']?([\w\- ]+\.(?:csv|json|md))\b", text)
    return fmt, name.group(1) if name else None


_AGG_RE = re.compile(
    r"\b(sum|total of all|add up|combined|in total|average|mean|maximum|highest|largest|"
    r"minimum|lowest|smallest)\b"
)


def rule_plan(request: str, today: date | None = None) -> Plan:
    today = today or date.today()
    text = request.lower().strip()
    fields = _fields(request)
    conds = _conditions(request, today)
    doc_type = _doc_type(text)
    output, output_name = _output(text)
    confidence = 0.8
    aggregate = aggregate_field = None

    if re.search(r"\b(compare|comparison|differences?|differ|versus|vs\.?|what changed|diff)\b", text):
        intent = Intent.COMPARE
    elif re.search(r"\b(inconsisten\w*|discrepanc\w*|mismatch\w*|conflicting|duplicates?)\b", text) or (
        re.search(r"\bflag\b", text) and not conds
    ):
        # "flag invoices above $10,000" is a filter: a threshold beats the bare word "flag".
        intent = Intent.INCONSISTENCIES
    elif re.search(r"\b(summar\w*|overview|tl;?dr|key points|gist|outline)\b", text):
        intent = Intent.SUMMARIZE
    elif re.search(
        r"\b(find|show|locate|highlight)\b.{0,25}\b(paragraph|passage|section|sentence|clause|"
        r"location|page|evidence|quote)\b|\bwhere does it say\b|\bsupporting\b|\bwhich page\b",
        text,
    ):
        intent = Intent.FIND
    elif re.search(
        r"\b(how many|count|number of)\s+(?:of\s+)?(?:the\s+|my\s+|these\s+)?(documents?|files?|pdfs?|"
        r"pages?|invoices?|contracts?|receipts?|reports?|forms?|letters?|agreements?|bills?)\b",
        text,
    ):
        intent = Intent.COUNT
    elif (m := _AGG_RE.search(text)) and (doc_type or conds or re.search(r"\b(all|these|every)\b", text)):
        intent = Intent.AGGREGATE
        word = m.group(1)
        aggregate = (
            "avg"
            if word in ("average", "mean")
            else "max"
            if word in ("maximum", "highest", "largest")
            else "min"
            if word in ("minimum", "lowest", "smallest")
            else "sum"
        )
        money = [f for f in fields if f in _MONEY_FIELDS]
        aggregate_field = money[0] if money else ("tax" if re.search(r"\btax|vat\b", text) else "total")
        fields = fields or [aggregate_field]
    elif conds and (doc_type or re.search(r"\b(find|which|list|show|every|all)\b", text)):
        intent = Intent.FILTER
    elif output or re.search(r"\b(extract|pull out|pull|tabulate|table of|list (?:all|the|every))\b", text):
        intent = Intent.EXTRACT
    elif re.search(r"\b(convert|process|index|ingest|make (?:them |it )?searchable|ocr)\b", text):
        intent = Intent.PROCESS
    else:
        intent = Intent.ASK
        confidence = 0.6 if re.search(r"^(what|who|when|where|which|how|is|are|does|did|why)\b|\?$", text) else 0.4

    if intent in (Intent.EXTRACT, Intent.FILTER) and not fields:
        fields = _default_fields(doc_type)
        confidence = min(confidence, 0.7)
    if intent == Intent.INCONSISTENCIES and not fields:
        fields = ["customer", "vendor", "email", "phone", "total"]
    for cond in conds:
        if cond.field not in fields:
            fields.append(cond.field)

    plan = Plan(
        intent=intent,
        query=request.strip(),
        fields=tuple(fields),
        conditions=tuple(conds),
        doc_type=doc_type,
        output=output,
        output_name=output_name,  # type: ignore[arg-type]
        aggregate=aggregate,
        aggregate_field=aggregate_field,
        confidence=confidence,
    )  # type: ignore[arg-type]
    return plan.model_copy(update={"steps": steps_for(plan)})


def _default_fields(doc_type: str | None) -> list[str]:
    if doc_type == "contract":
        return ["effective_date", "expiry_date", "contract_value"]
    if doc_type == "receipt":
        return ["vendor", "date", "total"]
    return ["invoice_number", "vendor", "date", "total"]


def steps_for(plan: Plan) -> tuple[Step, ...]:
    """The minimum tool sequence for an intent. Tools are from a fixed allow-list."""
    scope = Step(tool="inspect_documents", args={"doc_type": plan.doc_type})
    fields = list(plan.fields)
    out: list[Step] = [scope]
    match plan.intent:
        case Intent.ASK:
            out += [Step(tool="search", args={"query": plan.query}), Step(tool="answer", args={"question": plan.query})]
        case Intent.FIND:
            out += [Step(tool="search", args={"query": plan.query}), Step(tool="cite", args={"question": plan.query})]
        case Intent.EXTRACT:
            out.append(Step(tool="extract_fields", args={"fields": fields}))
        case Intent.FILTER:
            out += [
                Step(tool="extract_fields", args={"fields": fields}),
                Step(tool="filter_records", args={"conditions": [c.model_dump() for c in plan.conditions]}),
            ]
        case Intent.AGGREGATE:
            out.append(Step(tool="extract_fields", args={"fields": fields}))
            if plan.conditions:
                out.append(Step(tool="filter_records", args={"conditions": [c.model_dump() for c in plan.conditions]}))
            out.append(Step(tool="calculate", args={"op": plan.aggregate, "field": plan.aggregate_field}))
        case Intent.COMPARE:
            out.append(Step(tool="compare_documents", args={"fields": fields}))
        case Intent.INCONSISTENCIES:
            out += [
                Step(tool="extract_fields", args={"fields": fields}),
                Step(tool="find_inconsistencies", args={"fields": fields}),
            ]
        case Intent.SUMMARIZE:
            out.append(Step(tool="summarize", args={"focus": plan.query}))
        case Intent.COUNT:
            pass
        case Intent.PROCESS:
            pass
    if plan.output and plan.intent in (
        Intent.EXTRACT,
        Intent.FILTER,
        Intent.INCONSISTENCIES,
        Intent.AGGREGATE,
        Intent.SUMMARIZE,
        Intent.COMPARE,
        Intent.ASK,
        Intent.FIND,
    ):
        out.append(Step(tool="write_output", args={"format": plan.output, "name": plan.output_name}))
    return tuple(out)


# ---------------------------------------------------------------- remote assist

_REMOTE_SYSTEM = (
    "You convert a user's document-processing request into a JSON plan. Reply with JSON only, keys: "
    "intent (one of: ask, find, extract, filter, aggregate, compare, inconsistencies, summarize, count, process), "
    "fields (list of snake_case field names), conditions (list of {field, op, value}; op one of gt, ge, lt, le, "
    "eq, contains, within_days, before, after), doc_type (invoice, receipt, contract, report, form, letter or "
    "null), output (csv, json, md or null), aggregate (sum, avg, min, max, count or null), aggregate_field."
)


def remote_plan(request: str, brain: Brain) -> Plan | None:
    remote = brain.remote
    if remote is None:
        return None
    try:
        raw = remote.chat(_REMOTE_SYSTEM, f"Request: {request}", max_tokens=300, json_mode=True)
        data: dict[str, Any] = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("plan is not a JSON object")
        raw_fields, raw_conds = data.get("fields") or [], data.get("conditions") or []
        if not isinstance(raw_fields, list) or not isinstance(raw_conds, list):
            raise ValueError("fields and conditions must be lists")
        conditions = tuple(Condition(**c) for c in raw_conds)
        fields = [resolve_field(str(f)).name for f in raw_fields]
        fields += [c.field for c in conditions if c.field not in fields]  # filters need their fields extracted
        extras = {k: data[k] for k in ("intent", "doc_type", "output") if data.get(k) is not None}
        if extras.get("intent") == "aggregate":
            extras["aggregate"] = data.get("aggregate") or "sum"
            extras["aggregate_field"] = data.get("aggregate_field") or (fields[0] if fields else "total")
            fields = fields or [extras["aggregate_field"]]
        plan = Plan(
            query=request, planner="remote", confidence=0.75, fields=tuple(fields), conditions=conditions, **extras
        )
    except ModelUnavailable as exc:
        log.warning("remote planner unavailable, using rules: %s", exc)
        return None
    except (ValueError, TypeError, ValidationError) as exc:  # a malformed plan falls back to rules
        log.warning("remote plan rejected, using rules: %s", exc)
        return None
    return plan.model_copy(update={"steps": steps_for(plan)})


def make_plan(request: str, brain: Brain, today: date | None = None) -> Plan:
    plan = rule_plan(request, today)
    mode = brain.settings.models.remote_for
    if mode == "always" or (mode == "fallback" and plan.confidence < 0.5):
        better = remote_plan(request, brain)
        if better is not None:
            return better
    return plan


def horizon(days: int, today: date | None = None) -> date:
    return (today or date.today()) + timedelta(days=days)
