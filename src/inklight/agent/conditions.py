"""Read conditions out of a request — and report what could not be read.

Every condition records the span of the request it came from. Whatever is left
over is scanned for constraint-like words ("paid late", "last month", a stray
amount); those are returned as *not understood* so the agent can say so instead
of silently answering a broader question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from ..extract import SINGULAR
from ..extract.values import parse_dates, parse_number
from .plan import Condition

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
_CUR = r"E£|[$€£]|USD|EUR|GBP|EGP|SAR|AED"
_CUR_CODE = {"$": "USD", "€": "EUR", "£": "GBP", "E£": "EGP"}
_NOT_AMOUNT = r"(?!\s*(?:days?|weeks?|months?|years?|pages?|items?|docs?|documents?|files?|lines?|%))"
_FIELD_WORDS = r"(?P<field>tax|subtotal|total|amount|value|vat|price)"
_FIELD_MAP = {"amount": "total", "price": "total", "value": "contract_value", "vat": "tax"}

_CMP_RE = re.compile(
    rf"(?:{_FIELD_WORDS}\s+(?:is\s+|of\s+)?)?"
    r"(?P<op>" + "|".join(sorted((re.escape(k) for k in _CMP), key=len, reverse=True)) + r")\s*"
    rf"(?P<cur>{_CUR})?\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<mult>k|m|thousand|million)?\b"
    rf"(?:\s*(?P<cur2>USD|EUR|GBP|EGP|SAR|AED)\b)?{_NOT_AMOUNT}",
    re.IGNORECASE,
)
_BETWEEN_RE = re.compile(
    rf"(?:{_FIELD_WORDS}\s+(?:is\s+)?)?\bbetween\s+(?P<c1>{_CUR})?\s*(?P<n1>\d[\d,]*(?:\.\d+)?)\s*(?P<m1>k|m)?\s+"
    rf"and\s+(?P<c2>{_CUR})?\s*(?P<n2>\d[\d,]*(?:\.\d+)?)\s*(?P<m2>k|m)?\b{_NOT_AMOUNT}",
    re.IGNORECASE,
)
_WITHIN_RE = re.compile(
    r"\b(?P<what>expir\w*|due|end(?:s|ing)?|renew\w*|terminat\w*)\b[^.]{0,30}?\b(?:within|in the next|in)\s+"
    r"(?P<n>\d+)\s*(?P<unit>day|week|month|year)s?",
    re.IGNORECASE,
)
_DATE_CMP_RE = re.compile(r"\b(?P<op>before|after|since|until|prior to)\s+(?P<rest>.{4,30})", re.IGNORECASE)
_YEAR_RE = re.compile(
    r"\b(?:in|during|for|from|dated)\s+(?:the\s+year\s+)?(?P<y>(?:19|20)\d\d)\b(?!\s*[-/.]\d)", re.IGNORECASE
)
_NEG_PARTY_RE = re.compile(
    r"\b(?:not\s+(?:from|by)|except(?:\s+(?:from|for))?|excluding|other\s+than)\s+", re.IGNORECASE
)
_VENDOR_RE = re.compile(
    r"\b(?:from|by|issued\s+by|billed\s+by|sent\s+by)\s+(?:(?:the\s+)?(?:vendor|supplier)\s+)?"
    r"|\b(?:vendor|supplier)\s+(?:is\s+|named\s+)?",
    re.IGNORECASE,
)
_CUSTOMER_RE = re.compile(
    r"\b(?:billed\s+to|issued\s+to|for\s+(?:the\s+)?(?:customer|client)|customer|client)\s+"
    r"(?:is\s+|named\s+)?",
    re.IGNORECASE,
)

_MONTHS = {
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
    "january",
    "february",
    "march",
    "april",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
}
_NAME_STOP = {
    "above",
    "over",
    "below",
    "under",
    "with",
    "and",
    "or",
    "that",
    "which",
    "who",
    "where",
    "whose",
    "in",
    "on",
    "before",
    "after",
    "between",
    "since",
    "until",
    "dated",
    "paid",
    "is",
    "are",
    "was",
    "were",
    "for",
    "to",
    "as",
    "than",
    "more",
    "less",
    "greater",
    "at",
    "exceeding",
    "exceeds",
    "into",
    "within",
    "expiring",
    "due",
    "of",
}
_NAME_REJECT = {
    "the",
    "these",
    "those",
    "all",
    "my",
    "our",
    "this",
    "that",
    "last",
    "next",
    "each",
    "every",
    "any",
    "a",
    "an",
    "them",
    "it",
    "here",
    "there",
    "now",
    "today",
    "folder",
    "batch",
    "file",
    "files",
    "document",
    "documents",
    "page",
    "pages",
    "is",
    "are",
    "named",
}

_UNSUPPORTED_RE = re.compile(
    r"\b(?:un)?paid(?:\s+(?:late|early|on\s+time|in\s+full))?\b"
    r"|\b(?:overdue|outstanding|late|pending|approved|rejected|disputed|cancell?ed|refunded|signed|unsigned"
    r"|duplicated?|recurring|partial(?:ly)?)\b"
    r"|\b(?:last|next|this|previous|past)\s+(?:\d+\s+)?(?:days?|weeks?|months?|quarters?|years?)\b"
    r"|\b(?:yesterday|today|tomorrow|recent(?:ly)?|q[1-4])\b"
    r"|\btop\s+\d+\b"
    r"|\b(?:not|except|excluding|without|unless)\b(?:\s+\w+){0,2}"
    rf"|(?:{_CUR})\s?\d[\d,]*(?:\.\d+)?\s*[km]?\b|\b\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|GBP|EGP|SAR|AED)\b",
    re.IGNORECASE,
)


@dataclass
class Parsed:
    conditions: list[Condition] = field(default_factory=list)
    spans: list[tuple[int, int]] = field(default_factory=list)
    match: str = "all"
    not_understood: list[str] = field(default_factory=list)


def _free(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    return all(end <= s or start >= e for s, e in spans)


def _amount(num: str | None, mult: str | None) -> float | None:
    value = parse_number(num or "")
    if value is None:
        return None
    mult = (mult or "").lower()
    if mult in ("k", "thousand"):
        value *= 1000
    elif mult in ("m", "million"):
        value *= 1_000_000
    return float(value)


def _unit(*raw: str | None) -> str | None:
    for r in raw:
        if r:
            return _CUR_CODE.get(r, r.upper())
    return None


def _name_after(text: str, pos: int) -> tuple[str, int] | None:
    """Up to three name tokens starting at ``pos``; None when it is not a name."""
    tokens: list[str] = []
    end = pos
    for m in re.finditer(r"[^\s]+", text[pos:]):
        raw = m.group(0)
        word = raw.strip(",.;:!?\"'()")
        if not word or word.lower() in _NAME_STOP or re.match(r"^[$€£]|^\d", word) or len(tokens) == 3:
            break
        tokens.append(word)
        end = pos + m.start() + len(raw.rstrip(",.;:!?\"')"))
        if raw[-1:] in ",.;:!?":
            break
    if not tokens:
        return None
    first = tokens[0].lower()
    doc_words = set(SINGULAR) | set(SINGULAR.values())
    if first in _NAME_REJECT or first in _MONTHS or first in doc_words or first.rstrip("s") in doc_words:
        return None
    if re.fullmatch(r"(?:19|20)\d\d|[qQ][1-4]|[hH][12]|(?:FY|fy)\d{2,4}", tokens[0]):
        return None  # a year or a reporting period, not a party
    return " ".join(tokens), end


def parse(request: str, today: date) -> Parsed:
    out = Parsed()
    spans = out.spans

    def add(cond: Condition, start: int, end: int) -> None:
        out.conditions.append(cond)
        spans.append((start, end))

    for m in _BETWEEN_RE.finditer(request):
        lo, hi = _amount(m.group("n1"), m.group("m1")), _amount(m.group("n2"), m.group("m2"))
        if lo is None or hi is None:
            continue
        fld = _FIELD_MAP.get((m.group("field") or "total").lower(), (m.group("field") or "total").lower())
        unit = _unit(m.group("c1"), m.group("c2"))
        add(Condition(field=fld, op="ge", value=min(lo, hi), unit=unit), m.start(), m.end())
        out.conditions.append(Condition(field=fld, op="le", value=max(lo, hi), unit=unit))
        spans.append((m.end(), m.end()))  # keeps conditions and spans aligned

    for m in _CMP_RE.finditer(request):
        value = _amount(m.group("num"), m.group("mult"))
        if value is None or not _free(spans, m.start(), m.end()):
            continue
        fld = (m.group("field") or "total").lower()
        add(
            Condition(
                field=_FIELD_MAP.get(fld, fld),
                op=_CMP[m.group("op").lower()],
                value=value,  # type: ignore[arg-type]
                unit=_unit(m.group("cur"), m.group("cur2")),
            ),
            m.start(),
            m.end(),
        )

    for m in _WITHIN_RE.finditer(request):
        days = int(m.group("n")) * {"day": 1, "week": 7, "month": 30, "year": 365}[m.group("unit").lower()]
        fld = "due_date" if m.group("what").lower().startswith("due") else "expiry_date"
        add(Condition(field=fld, op="within_days", value=days), m.start(), m.end())

    for m in _DATE_CMP_RE.finditer(request):
        hits = parse_dates(m.group("rest"))
        if hits and _free(spans, m.start(), m.end()):
            op = "before" if m.group("op").lower() in ("before", "until", "prior to") else "after"
            fld = "expiry_date" if re.search(r"\b(expir\w*|end(?:s|ing)?)\b", request, re.I) else "date"
            end = m.start("rest") + hits[0][2] + len(hits[0][1])
            add(Condition(field=fld, op=op, value=hits[0][0].isoformat()), m.start(), end)  # type: ignore[arg-type]

    for m in _YEAR_RE.finditer(request):
        if not _free(spans, m.start(), m.end()):
            continue
        y = int(m.group("y"))
        add(Condition(field="date", op="after", value=date(y - 1, 12, 31).isoformat()), m.start(), m.end())
        out.conditions.append(Condition(field="date", op="before", value=date(y + 1, 1, 1).isoformat()))
        spans.append((m.end(), m.end()))

    for regex, fld, op in (
        (_NEG_PARTY_RE, "vendor", "not_contains"),
        (_CUSTOMER_RE, "customer", "contains"),
        (_VENDOR_RE, "vendor", "contains"),
    ):
        for m in regex.finditer(request):
            if not _free(spans, m.start(), m.end()):
                continue
            named = _name_after(request, m.end())
            if named is None:
                continue
            name, end = named
            add(Condition(field=fld, op=op, value=name), m.start(), end)  # type: ignore[arg-type]

    out.match = _combine(request, out)
    out.not_understood.extend(_leftovers(request, spans))
    return out


def _combine(request: str, parsed: Parsed) -> str:
    """'or' between every pair of conditions → any; a mix of 'and' and 'or' is reported, not guessed."""
    real = sorted((s, e) for s, e in parsed.spans if e > s)
    if len(real) < 2:
        return "all"
    gaps = [request[e1:s2].lower() for (_, e1), (s2, _) in zip(real, real[1:], strict=False)]
    ors = [bool(re.search(r"\bor\b", g)) for g in gaps]
    if all(ors):
        return "any"
    if any(ors):
        parsed.not_understood.append("a mix of 'and' and 'or' (applied every condition with AND)")
    return "all"


def _leftovers(request: str, spans: list[tuple[int, int]]) -> list[str]:
    masked = list(request)
    for s, e in spans:
        masked[s:e] = " " * (e - s)
    rest = "".join(masked)
    found: list[str] = []
    hits = [(m.start(), m.group(0).strip()) for m in _UNSUPPORTED_RE.finditer(rest)]
    # "from X" / "by X" left over = a party we could not attach (checked separately so it never
    # swallows a following phrase such as "from last month").
    for m in _LEFTOVER_PARTY_RE.finditer(rest):
        named = _name_after(rest, m.end())
        if named is not None:
            hits.append((m.start(), rest[m.start() : named[1]].strip()))
    for _, phrase in sorted(hits):
        if phrase and phrase.lower() not in (f.lower() for f in found):
            found.append(phrase)
    return found


_LEFTOVER_PARTY_RE = re.compile(r"\b(?:from|by)\s+", re.IGNORECASE)
