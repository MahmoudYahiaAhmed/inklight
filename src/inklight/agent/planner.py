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
from ..errors import ModelUnavailable, PlanError
from ..extract import CATALOG, SINGULAR, resolve_field
from . import conditions as _cond
from . import expr as _expr
from .plan import Condition, Group, Intent, Plan, Step

log = logging.getLogger(__name__)

_MONEY_FIELDS = {"tax", "subtotal", "total", "contract_value", "amount"}
_FIELD_LEAD = re.compile(
    r"(?:\bcsv\s+(?:file\s+)?(?:of|with)|\bjson\s+(?:file\s+)?(?:of|with)|\btable\s+(?:of|with)|\bextract(?:ing)?|"
    r"\bpull(?:\s+out)?|\bget|\blist|\bexport|\bshow(?:\s+me)?|\bgive\s+me|\bcolumns?|\bfields?|\bcontaining|"
    r"\bwith columns)\s+(?P<rest>.+)",
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
    # "give me a table of vendor and total": the container words are not a column.
    segment = re.sub(
        r"^\s*(?:(?:a|an|the)\s+)?(?:table|list|csv|spreadsheet|json|report|summary|breakdown)\s+"
        r"(?:file\s+)?(?:of|with)\s+",
        "",
        segment,
        flags=re.IGNORECASE,
    )
    parts = re.split(r",|\band\b|&|/|\+", segment, flags=re.IGNORECASE)
    out: list[str] = []
    for part in parts:
        word = re.sub(r"\s+", " ", part).strip(" :'\"").lower()
        word = re.sub(r"^(?:the|all|every|each|their|its)\s+", "", word)
        word = re.sub(r"\s+(?:of|from|in)$", "", word)
        if word in _NOISE or word in SINGULAR or word.rstrip("s") in SINGULAR.values() or len(word) > 40:
            continue
        doc_words = set(SINGULAR) | set(SINGULAR.values())
        known_field = resolve_field(word).name in CATALOG
        if any(a in word for a in "'’ʼ") or (not known_field and any(w in doc_words for w in word.split())):
            continue  # "acme's invoices" names documents, not a column ("invoice number" is a column)
        name = resolve_field(word).name
        if name not in out:
            out.append(name)
    return out


def _doc_type(text: str) -> str | None:
    for plural, singular in SINGULAR.items():
        if re.search(rf"\b({plural}|{singular})\b", text):
            return singular
    return None


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
    known = frozenset(w for f in fields for w in f.split("_"))  # requested columns are not dropped names
    parsed = _cond.parse(request, today, known)
    conds = bool(parsed.atoms)  # recognised constraints, even when their grouping is ambiguous (blocked)
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
    elif not conds and re.search(
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
    elif conds and not fields and _open_question(text):
        # "What are the payment terms on Acme's invoice?" asks about one document's content: the
        # question is answered, from the documents the conditions select, never turned into a list.
        intent = Intent.ASK
        confidence = 0.6
    elif conds and (doc_type or re.search(r"\b(find|which|list|show|every|all)\b", text)):
        intent = Intent.FILTER
    elif output or re.search(r"\b(extract|pull out|pull|tabulate|table of|list (?:all|the|every))\b", text):
        intent = Intent.EXTRACT
    elif re.search(r"\b(convert|process|index|ingest|make (?:them |it )?searchable|ocr)\b", text):
        intent = Intent.PROCESS
    elif doc_type and (
        re.search(r"\b(list|show|find|which|get|give me)\b", text)
        # A plural ("Acme or Globex invoices") asks for a set of records; a singular question
        # ("the total of the Globex invoice?") stays a question answered from evidence.
        or (parsed.not_understood and re.search(rf"\b({'|'.join(SINGULAR)})\b", text))
    ):
        # "find overdue invoices": a record-level request even when no condition was recognised,
        # so anything not understood is reported rather than answered as free text.
        intent = Intent.EXTRACT
        confidence = 0.6
    elif conds:
        # A question that carries conditions ("how many invoices above $5,000", "totals from Acme")
        # is answered over the matching records, never by ignoring the conditions.
        intent = Intent.FILTER
    else:
        intent = Intent.ASK
        confidence = 0.6 if re.search(r"^(what|who|when|where|which|how|is|are|does|did|why)\b|\?$", text) else 0.4

    # Record-level tasks must apply every constraint; anything the parser could not turn into a
    # condition is reported, and the task cannot claim full success.
    scoped_question = intent == Intent.ASK and parsed.where is not None
    not_understood = list(parsed.not_understood) if intent in _RECORD_INTENTS or scoped_question else []
    if not_understood:
        confidence = min(confidence, 0.4)

    if intent in (Intent.EXTRACT, Intent.FILTER) and not fields:
        fields = _default_fields(doc_type)
        if intent == Intent.EXTRACT:  # which fields to pull was a guess; a filter's own conditions were not
            confidence = min(confidence, 0.7)
    if intent == Intent.INCONSISTENCIES and not fields:
        fields = ["customer", "vendor", "email", "phone", "total"]
    # `fields` stays the requested output columns; condition fields are added only to what is
    # extracted (see steps_for), never to what is shown or exported.

    blocked = list(parsed.blocked)
    if parsed.where is not None and intent == Intent.PROCESS:
        blocked.append("conditions do not apply to indexing; ask for the matching documents instead")
    if blocked:
        confidence = min(confidence, 0.3)

    plan = Plan(
        intent=intent,
        query=request.strip(),
        fields=tuple(fields),
        where=None if blocked else parsed.where,
        doc_type=doc_type,
        output=output,
        output_name=output_name,  # type: ignore[arg-type]
        aggregate=aggregate,
        aggregate_field=aggregate_field,
        not_understood=tuple(not_understood),
        blocked=tuple(blocked),
        confidence=confidence,
    )  # type: ignore[arg-type]
    return plan.model_copy(update={"steps": steps_for(plan)})


_RECORD_INTENTS = {Intent.FILTER, Intent.AGGREGATE, Intent.EXTRACT, Intent.COUNT, Intent.INCONSISTENCIES}


_OPEN_QUESTION = re.compile(r"^(?:what|who|when|where|why|how|is|are|does|did|do|was|were)\b")
_SET_WORDS = re.compile(r"\b(?:which|list|show|find|how many|count|every|all|each)\b")


def _open_question(text: str) -> bool:
    """A question about one document ("what are the terms on the Acme invoice?"), not about a set."""
    plural = re.search(rf"\b(?:{'|'.join(SINGULAR)})\b", text)
    return bool(_OPEN_QUESTION.match(text.strip())) and not plural and not _SET_WORDS.search(text)


def _default_fields(doc_type: str | None) -> list[str]:
    if doc_type == "contract":
        return ["effective_date", "expiry_date", "contract_value"]
    if doc_type == "receipt":
        return ["vendor", "date", "total"]
    return ["invoice_number", "vendor", "date", "total"]


def steps_for(plan: Plan) -> tuple[Step, ...]:
    """The minimum tool sequence for an intent. Tools are from a fixed allow-list.

    When the plan has a ``where`` expression it is enforced FIRST, for every intent: the fields the
    output needs plus the fields the conditions need are extracted, the expression filters the
    records, and the document scope narrows to the matches. Every later step (answer, compare,
    summarize, count, calculate, export) therefore sees only matching documents.
    """
    scope = Step(tool="inspect_documents", args={"doc_type": plan.doc_type})
    if plan.blocked:
        return (scope,)
    fields = list(plan.fields)
    needed = list(
        dict.fromkeys([*fields, *_expr.fields(plan.where), *([plan.aggregate_field] if plan.aggregate_field else [])])
    )
    needed = [f for f in needed if f]
    out: list[Step] = [scope]
    extracted = False
    if plan.where is not None:
        out += [
            Step(tool="extract_fields", args={"fields": needed}),
            Step(tool="filter_records", args={"where": plan.where.model_dump(mode="json")}),
        ]
        extracted = True
    match plan.intent:
        case Intent.ASK:
            out += [Step(tool="search", args={"query": plan.query}), Step(tool="answer", args={"question": plan.query})]
        case Intent.FIND:
            out += [Step(tool="search", args={"query": plan.query}), Step(tool="cite", args={"question": plan.query})]
        case Intent.EXTRACT | Intent.FILTER:
            if not extracted:
                out.append(Step(tool="extract_fields", args={"fields": needed}))
        case Intent.AGGREGATE:
            if not extracted:
                out.append(Step(tool="extract_fields", args={"fields": needed}))
            out.append(Step(tool="calculate", args={"op": plan.aggregate, "field": plan.aggregate_field}))
        case Intent.COMPARE:
            out.append(Step(tool="compare_documents", args={"fields": fields}))
        case Intent.INCONSISTENCIES:
            if not extracted:
                out.append(Step(tool="extract_fields", args={"fields": needed}))
            out.append(Step(tool="find_inconsistencies", args={"fields": fields}))
        case Intent.SUMMARIZE:
            out.append(Step(tool="summarize", args={"focus": plan.query}))
        case Intent.COUNT | Intent.PROCESS:
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


_PREP_TOOLS = {"inspect_documents", "extract_fields", "filter_records"}


def validate_plan(plan: Plan) -> None:
    """Refuse a plan whose steps do not enforce what it claims.

    A plan that shows conditions in "Understood as" must filter with exactly that expression, after
    extracting every field the expression reads, and before any step that uses the records or the
    document scope (answering, counting, calculating, comparing, summarizing, exporting).
    """
    tools = [s.tool for s in plan.steps]
    if plan.blocked and tools != ["inspect_documents"]:
        raise PlanError("a blocked plan must not run any tool beyond inspecting the documents")
    if plan.where is None:
        if "filter_records" in tools:
            raise PlanError("the plan filters, but states no conditions")
        return
    filters = [i for i, s in enumerate(plan.steps) if s.tool == "filter_records"]
    if len(filters) != 1:
        raise PlanError("a plan with conditions must filter exactly once")
    at = filters[0]
    try:
        executed = Plan.model_validate({"intent": plan.intent, "query": "", "where": plan.steps[at].args["where"]})
    except (KeyError, ValidationError) as exc:
        raise PlanError(f"the filter step has no valid expression: {exc}") from exc
    if executed.where != plan.where:
        raise PlanError("the filter step does not execute the conditions the plan states")
    extracted = {f for s in plan.steps[:at] if s.tool == "extract_fields" for f in s.args.get("fields", [])}
    missing = set(_expr.fields(plan.where)) - extracted
    if missing:
        raise PlanError(f"conditions read fields that are never extracted: {sorted(missing)}")
    early = [s.tool for s in plan.steps[:at] if s.tool not in _PREP_TOOLS]
    if early:
        raise PlanError(f"these steps would run before the conditions are applied: {early}")


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
        conditions: list[Condition | Group] = [Condition(**c) for c in raw_conds]
        match = data.get("match", "all")
        if match not in ("all", "any"):
            raise ValueError("match must be 'all' or 'any'")
        fields = [resolve_field(str(f)).name for f in raw_fields]
        extras = {k: data[k] for k in ("intent", "doc_type", "output") if data.get(k) is not None}
        if extras.get("intent") == "aggregate":
            extras["aggregate"] = data.get("aggregate") or "sum"
            extras["aggregate_field"] = data.get("aggregate_field") or (fields[0] if fields else "total")
            fields = fields or [extras["aggregate_field"]]
        where = _expr.group(match, conditions) if conditions else None
        plan = Plan(query=request, planner="remote", confidence=0.75, fields=tuple(fields), where=where, **extras)
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
