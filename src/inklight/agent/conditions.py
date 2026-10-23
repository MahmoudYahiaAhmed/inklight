"""Read conditions out of a request — and report what could not be read.

Every condition records the span of the request it came from. Whatever is left
over is scanned for constraint-like words ("paid late", "last month", a stray
amount); those are returned as *not understood* so the agent can say so instead
of silently answering a broader question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..extract import SINGULAR
from ..extract.values import parse_dates, parse_number
from .expr import group
from .plan import Condition, Group

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
_MONTH_NUM = {
    m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])
}
_CUR_CODE = {"$": "USD", "€": "EUR", "£": "GBP", "E£": "EGP"}
_NOT_AMOUNT = r"(?!\s*(?:days?|weeks?|months?|years?|pages?|items?|docs?|documents?|files?|lines?|%))"
_FIELD_WORDS = r"(?P<field>tax|subtotal|total|amount|value|vat|price)"
_FIELD_MAP = {"amount": "total", "price": "total", "value": "contract_value", "vat": "tax"}

_CMP_RE = re.compile(
    rf"(?:{_FIELD_WORDS}\s+(?:is\s+|of\s+)?)?"
    r"(?P<op>" + "|".join(sorted((re.escape(k) for k in _CMP), key=len, reverse=True)) + r")\s*"
    rf"(?P<cur>{_CUR})?\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<mult>k|m|thousand|grand|million)?\b"
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
_MONTH_YEAR_RE = re.compile(
    r"\b(?:in|during|for|from|dated)\s+(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?"
    r"|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?\s+(?P<y>(?:19|20)\d\d)\b",
    re.IGNORECASE,
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
    "their",
    "its",
    "his",
    "her",
    "both",
    "either",
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
    r"|\b(?:under|over|less\s+than|more\s+than|after|before|at\s+least|at\s+most)\s+\d+\s*"
    r"(?:days?|weeks?|months?|years?)\b"
    r"|\b(?:in|during|from|for|since|before|after|until)\s+(?:january|february|march|april|may|june|july|august|september|october|november"
    r"|december)\b(?!\s*\d)"
    r"|\btop\s+\d+\b"
    r"|\b(?:not|except|excluding|without|unless)\b(?:\s+\w+){0,2}"
    rf"|(?:{_CUR})\s?\d[\d,]*(?:\.\d+)?\s*[km]?\b|\b\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|GBP|EGP|SAR|AED)\b",
    re.IGNORECASE,
)


@dataclass
class Atom:
    """One recognised condition (or a grouped range/list), with the span of the request it came from."""

    expr: Condition | Group
    start: int
    end: int
    key: str  # what it constrains ("total", "date", "vendor"): same-key alternatives group together


@dataclass
class Parsed:
    atoms: list[Atom] = field(default_factory=list)
    where: Condition | Group | None = None
    not_understood: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    reported: list[tuple[int, int]] = field(default_factory=list)  # read, reported as not applied, never a condition

    @property
    def spans(self) -> list[tuple[int, int]]:
        return [(a.start, a.end) for a in self.atoms]

    @property
    def consumed(self) -> list[tuple[int, int]]:
        return self.spans + self.reported

    @property
    def conditions(self) -> list[Condition]:
        from .expr import leaves

        return leaves(self.where)


def _free(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    return all(end <= s or start >= e for s, e in spans)


def _amount(num: str | None, mult: str | None) -> float | None:
    value = parse_number(num or "")
    if value is None:
        return None
    mult = (mult or "").lower()
    if mult in ("k", "thousand", "grand"):
        value *= 1000
    elif mult in ("m", "million"):
        value *= 1_000_000
    return float(value)


def _unknown_unit(word: str) -> bool:
    """A word right after an amount that is neither a connector, a filler nor a known unit."""
    low = word.lower()
    known = {"usd", "eur", "gbp", "egp", "sar", "aed", "dollars", "dollar", "euros", "euro", "pounds", "pound"}
    return not (low in known or low in _FILLER or low in _NAME_STOP or low in _VERBS or low in _FIELD_VOCAB)


def _unit(*raw: str | None) -> str | None:
    for r in raw:
        if r:
            return _CUR_CODE.get(r, r.upper())
    return None


# Words that end a name and can never start one: request verbs, output words, field words.
_VERBS = {
    "create", "save", "export", "write", "show", "list", "find", "flag", "compare", "extract", "summarize",
    "summarise", "sum", "count", "make", "put", "give", "then", "also", "csv", "json", "table", "file",
    "report", "get", "pull", "read", "add", "including", "plus",
}  # fmt: skip


def _field_words() -> set[str]:
    from ..extract.fields import ALIASES, CATALOG

    words: set[str] = set()
    for spec in CATALOG.values():
        for label in spec.all_labels():
            words.update(label.split())
        words.update(spec.name.split("_"))
    for alias in ALIASES:
        words.update(alias.split())
    return {w for w in words if w.isalpha()}


_FIELD_VOCAB = _field_words()


def _name_after(text: str, pos: int) -> tuple[str, int] | None:
    """Up to three name tokens starting at ``pos``; None when it is not a name."""
    tokens: list[str] = []
    end = pos
    for m in re.finditer(r"[^\s]+", text[pos:]):
        raw = m.group(0)
        word = raw.strip(",.;:!?\"'()")
        low = word.lower()
        if not word or low in _NAME_STOP or low in _VERBS or re.match(r"^[$€£]|^\d", word) or len(tokens) == 3:
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
    if first in _FIELD_VOCAB or first.rstrip("s") in _FIELD_VOCAB:
        return None  # "and total", "and dates": a field, not a party
    if re.fullmatch(r"(?:19|20)\d\d|[qQ][1-4]|[hH][12]|(?:FY|fy)\d{2,4}", tokens[0]):
        return None  # a year or a reporting period, not a party
    return " ".join(tokens), end


# After a party name: ", X", " or X", " and X", ", or X", optionally repeating "from"/"by".
_COORD_RE = re.compile(
    r"(?:\s*,\s*(?:(?P<a>or|and|nor)\s+)?|\s+(?P<b>or|and|nor)\s+)(?:(?:from|by|issued\s+by)\s+)?", re.IGNORECASE
)


def _party_list(request: str, start: int) -> tuple[list[str], int] | None:
    """A name, plus any coordinated names ("Acme or Globex", "Acme, Globex and Initech")."""
    first = _name_after(request, start)
    if first is None:
        return None
    names, end = [first[0]], first[1]
    while True:
        m = _COORD_RE.match(request, end)
        if m is None:
            break
        nxt = _name_after(request, m.end())
        if nxt is None:
            break
        names.append(nxt[0])
        end = nxt[1]
    return names, end


def parse(request: str, today: date, known_words: frozenset[str] = frozenset()) -> Parsed:
    out = Parsed()

    def add(expr: Condition | Group, start: int, end: int, key: str) -> None:
        out.atoms.append(Atom(expr, start, end, key))

    def free(start: int, end: int) -> bool:
        return _free(out.consumed, start, end)

    for m in _BETWEEN_RE.finditer(request):
        lo, hi = _amount(m.group("n1"), m.group("m1")), _amount(m.group("n2"), m.group("m2"))
        if lo is None or hi is None:
            continue
        fld = _FIELD_MAP.get((m.group("field") or "total").lower(), (m.group("field") or "total").lower())
        unit = _unit(m.group("c1"), m.group("c2"))
        rng = group(
            "all",
            [
                Condition(field=fld, op="ge", value=min(lo, hi), unit=unit),
                Condition(field=fld, op="le", value=max(lo, hi), unit=unit),
            ],
        )
        add(rng, m.start(), m.end(), fld)

    for m in _CMP_RE.finditer(request):
        value = _amount(m.group("num"), m.group("mult"))
        if value is None or not free(m.start(), m.end()):
            continue
        unit_word = re.match(r"\s*([A-Za-z]+)", request[m.end() :])
        if unit_word and _unknown_unit(unit_word.group(1)):
            # "over 5 bucks", "above 3 lakh": an amount with a unit we do not know is reported,
            # never read as a plain number.
            out.not_understood.append(request[m.start() : m.end() + unit_word.end()].strip())
            out.reported.append((m.start(), m.end() + unit_word.end()))
            continue
        fld = (m.group("field") or "total").lower()
        fld = _FIELD_MAP.get(fld, fld)
        cond = Condition(
            field=fld,
            op=_CMP[m.group("op").lower()],  # type: ignore[arg-type]
            value=value,
            unit=_unit(m.group("cur"), m.group("cur2")),
        )
        add(cond, m.start(), m.end(), fld)

    for m in _WITHIN_RE.finditer(request):
        days = int(m.group("n")) * {"day": 1, "week": 7, "month": 30, "year": 365}[m.group("unit").lower()]
        fld = "due_date" if m.group("what").lower().startswith("due") else "expiry_date"
        add(Condition(field=fld, op="within_days", value=days), m.start(), m.end(), fld)

    for m in _DATE_CMP_RE.finditer(request):
        hits = parse_dates(m.group("rest"))
        if hits and free(m.start(), m.end()):
            op = "before" if m.group("op").lower() in ("before", "until", "prior to") else "after"
            fld = "expiry_date" if re.search(r"\b(expir\w*|end(?:s|ing)?)\b", request, re.I) else "date"
            end = m.start("rest") + hits[0][2] + len(hits[0][1])
            add(Condition(field=fld, op=op, value=hits[0][0].isoformat()), m.start(), end, fld)  # type: ignore[arg-type]

    for m in _MONTH_YEAR_RE.finditer(request):
        if not free(m.start(), m.end()):
            continue
        y, mon = int(m.group("y")), _MONTH_NUM[m.group("mon")[:3].lower()]
        start = date(y, mon, 1)
        nxt = date(y + (mon == 12), mon % 12 + 1, 1)
        month = group(
            "all",
            [
                Condition(field="date", op="after", value=(start - timedelta(days=1)).isoformat()),
                Condition(field="date", op="before", value=nxt.isoformat()),
            ],
        )
        add(month, m.start(), m.end(), "date")

    for m in _YEAR_RE.finditer(request):
        if not free(m.start(), m.end()):
            continue
        y = int(m.group("y"))
        year = group(
            "all",
            [
                Condition(field="date", op="after", value=date(y - 1, 12, 31).isoformat()),
                Condition(field="date", op="before", value=date(y + 1, 1, 1).isoformat()),
            ],
        )
        add(year, m.start(), m.end(), "date")

    for m in _POSSESSIVE_RE.finditer(request):
        # "Show acme's invoices", "Acme Supplies’ bills": the owner of the documents is the vendor.
        # Coordinated owners ("Initech’s and Globex's invoices") are collected backwards into one group.
        names: list[str] = []
        apos_at, first_at = m.start("apos"), None
        while True:
            name, name_at = _possessor(request, apos_at)
            if name is None:
                break
            names.insert(0, name)
            first_at = name_at
            prev = _PREV_POSSESSIVE_RE.search(request[:name_at])
            if prev is None:
                break
            apos_at = prev.start("apos")
        if not names or first_at is None or not free(first_at, m.end("apos")):
            continue
        owners: list[Condition | Group] = [Condition(field="vendor", op="contains", value=n) for n in names]
        add(group("any", owners), first_at, m.end("apos"), "vendor")

    for regex, fld, op in (
        (_NEG_PARTY_RE, "vendor", "not_contains"),
        (_CUSTOMER_RE, "customer", "contains"),
        (_VENDOR_RE, "vendor", "contains"),
    ):
        for m in regex.finditer(request):
            if not free(m.start(), m.end()):
                continue
            listed = _party_list(request, m.end())
            if listed is None or not free(m.start(), listed[1]):
                continue
            names, end = listed
            conds: list[Condition | Group] = [Condition(field=fld, op=op, value=n) for n in names]  # type: ignore[arg-type]
            # "from Acme or Globex" = either; "not from Acme or Globex" = neither (De Morgan).
            add(group("all" if op == "not_contains" else "any", conds), m.start(), end, fld)

    out.atoms.sort(key=lambda a: a.start)
    out.where = _combine(request, out)
    out.not_understood.extend(_leftovers(request, out.consumed, known_words))
    return out


def _connector(gap: str) -> str:
    gap = gap.lower()
    if re.search(r"\bor\b", gap):
        return "or"
    return "and"


def _combine(request: str, parsed: Parsed) -> Condition | Group | None:
    """Group the atoms without guessing.

    1. ``or`` between atoms on the same field makes one group: "between A and B or above C".
    2. The remaining operands are joined with AND, or with OR when every connector is "or".
    3. A mix of "and" and "or" across different fields is ambiguous: reported and blocked.
    """
    atoms = parsed.atoms
    if not atoms:
        return None
    runs: list[list[Atom]] = [[atoms[0]]]
    joins: list[str] = []
    for prev, atom in zip(atoms, atoms[1:], strict=False):
        conn = _connector(request[prev.end : atom.start])
        if conn == "or" and atom.key == runs[-1][-1].key:
            runs[-1].append(atom)
        else:
            runs.append([atom])
            joins.append(conn)
    operands = [group("any", [a.expr for a in run]) if len(run) > 1 else run[0].expr for run in runs]
    if len(operands) == 1:
        return operands[0]
    if all(j == "and" for j in joins):
        return group("all", operands)
    if all(j == "or" for j in joins):
        return group("any", operands)
    from .expr import describe

    parts = " | ".join(describe(o) for o in operands)
    parsed.blocked.append(
        f"'and' and 'or' are mixed across different conditions ({parts}); the grouping is ambiguous, "
        "so nothing was filtered. Rephrase with one connector, or split it into two requests."
    )
    return None


# Words that may be left over without meaning a constraint was dropped.
_FILLER = {
    "a", "an", "the", "all", "any", "every", "each", "of", "for", "in", "on", "with", "to", "and", "or", "that",
    "which", "who", "were", "was", "are", "is", "be", "been", "have", "has", "had", "me", "my", "our", "your",
    "please", "find", "show", "list", "get", "give", "extract", "pull", "out", "read", "create", "make", "save",
    "export", "write", "put", "into", "as", "csv", "json", "markdown", "md", "file", "table", "spreadsheet",
    "report", "what", "how", "many", "much", "there", "these", "those", "this", "them", "it", "its",
    "their", "documents", "document", "files", "records", "sum", "total", "totals", "average", "mean", "count",
    "number", "numbers", "maximum", "minimum", "highest", "lowest", "largest", "smallest", "flag", "inconsistent",
    "inconsistencies", "duplicates", "duplicate", "compare", "summarize", "summarise", "summary", "values", "value",
    "field", "fields", "columns", "column", "do", "does", "did", "i", "we", "you", "can", "could", "would", "should",
    "need", "want", "only", "just", "also", "then", "by", "from", "between", "above", "below", "over", "under",
    "not", "except", "excluding", "named", "called", "s", "amount", "amounts", "data", "info", "information",
    "details", "everything", "match", "matching", "where", "whose", "dated", "issued", "billed", "sent", "own",
}  # fmt: skip


def _leftovers(request: str, spans: list[tuple[int, int]], known_words: frozenset[str] = frozenset()) -> list[str]:
    masked = list(request)
    for s, e in spans:
        masked[s:e] = " " * (e - s)
    rest = "".join(masked)
    hits = [(m.start(), m.group(0).strip()) for m in _UNSUPPORTED_RE.finditer(rest)]
    # "from X" / "by X" left over = a party we could not attach (checked separately so it never
    # swallows a following phrase such as "from last month").
    for m in _LEFTOVER_PARTY_RE.finditer(rest):
        named = _name_after(rest, m.end())
        if named is not None:
            hits.append((m.start(), rest[m.start() : named[1]].strip()))
    hits.extend(_dangling(rest, spans))
    hits.extend(_unknown_names(request, rest, known_words))
    found: list[str] = []
    # Longest phrase first at each position, so "last month" wins over the bare word "last".
    for _, _, phrase in sorted((at, -len(p), p) for at, p in hits):
        if phrase and not any(phrase.lower() in f.lower() or f.lower() in phrase.lower() for f in found):
            found.append(phrase)
    return found


def _dangling(rest: str, spans: list[tuple[int, int]]) -> list[tuple[int, str]]:
    """A connector right after a condition followed by words no condition used: "… Acme above $5,000 or Globex"."""
    out = []
    for _, end in spans:
        m = re.match(
            r"\s*(?:,\s*)?(?P<conj>\bor\b|\band\b|\bnor\b|,)\s+(?P<words>[^\s,.;]+(?:\s+[^\s,.;]+){0,2})", rest[end:]
        )
        if m is None:
            continue
        words = [w.strip("\"'()") for w in m.group("words").split()]
        meaningful = [w for w in words if w and w.lower() not in _FILLER and w.lower().rstrip("s") not in _FILLER]
        if meaningful and (meaningful[0][:1].isupper() or meaningful[0][:1].isdigit() or meaningful[0][:1] in "$€£"):
            out.append((end, f"{m.group('conj')} {' '.join(words)}".strip()))
    return out


_LEFTOVER_PARTY_RE = re.compile(r"\b(?:from|by)\s+", re.IGNORECASE)


_APOS = "'’ʼ"  # straight, right single quote, modifier apostrophe
_POSSESSIVE_RE = re.compile(
    rf"(?P<apos>[{_APOS}]s|s[{_APOS}])\s+(?:(?:invoices?|receipts?|bills?|contracts?|documents?|statements?|orders?)\b)",
    re.IGNORECASE,
)
# A possessive ending right before ", " / " and " / " or " (the text up to the next owner's name).
_PREV_POSSESSIVE_RE = re.compile(
    rf"(?P<apos>[{_APOS}]s|s[{_APOS}])\s*(?:,\s*(?:(?:and|or)\s+)?|\s+(?:and|or)\s+)$", re.IGNORECASE
)
_DOC_NOUNS = {"invoice", "invoices", "receipt", "receipts", "bill", "bills", "contract", "contracts", "document",
              "documents", "statement", "statements", "order", "orders"}  # fmt: skip


def _possessor(text: str, apos_at: int) -> tuple[str | None, int]:
    """The name before a possessive ("show ACME Supplies's"), without leading request words."""
    # In "Supplies’ invoices" the match starts at the final s, which belongs to the name.
    head = text[: apos_at + 1] if text[apos_at : apos_at + 1] in ("s", "S") else text[:apos_at]
    # Stop at the previous owner ("Acme's, Globex" -> "Globex"): an apostrophe-s, a comma, and/or.
    bounds = list(re.finditer(rf"[{_APOS}]s\b|s[{_APOS}]|,|\band\b|\bor\b", head, re.IGNORECASE))
    start = bounds[-1].end() if bounds else 0
    tokens = [t for t in re.finditer(r"[A-Za-z0-9&.\-]+", head) if t.start() >= start][-3:]
    words = [t.group(0) for t in tokens]
    while words and (words[0].lower() in _FILLER or words[0].lower() in _VERBS or words[0].lower() in _NAME_REJECT):
        words.pop(0)
        tokens.pop(0)
    if not words or words[-1].lower() in _FILLER or words[-1].lower() in _NAME_REJECT:
        return None, apos_at
    return " ".join(words), tokens[0].start()


_CODES = {"usd", "eur", "gbp", "egp", "sar", "aed", "csv", "json", "pdf", "pdfs", "ocr", "md", "i", "q1", "q2", "q3",
          "q4", "vat", "po", "id", "k", "m"}  # fmt: skip
_CONTENT_OK = {
    "kindly", "please", "thanks", "thank", "now", "here", "again", "too", "every", "single", "whole", "entire",
    "us", "they", "he", "she", "him", "them", "theirs", "ours", "mine", "yours", "one", "ones", "some", "several",
    "invoice", "invoiced", "billed", "paid", "pay", "payable", "due", "amounts", "money", "cost", "costs", "price",
    "prices", "dollar", "dollars", "euro", "euros", "pound", "pounds", "currency", "vendor", "vendors", "supplier",
    "suppliers", "customer", "customers", "client", "clients", "issued", "dated", "date", "dates", "year", "years",
    "month", "months", "day", "days", "week", "weeks", "greater", "higher", "larger", "less", "lower", "smaller",
    "more", "most", "least", "than", "equal", "exactly", "up", "down", "both", "either", "neither", "nor", "also",
    "including", "included", "include", "inclusive", "rows", "row", "list", "lists", "listing", "display", "view",
    "see", "tell", "need", "want", "like", "look", "looking", "search", "came", "come", "sent", "send", "received",
    "receive", "got", "made", "by", "via", "per", "total", "grand", "sum", "add", "added", "calculate", "compute",
    "spreadsheet", "excel", "export", "exported", "save", "saved", "download", "file", "named", "called",
}  # fmt: skip


def _unknown_names(request: str, rest: str, known_words: frozenset[str]) -> list[tuple[int, str]]:
    """Words no condition used and that are not part of the request vocabulary.

    For a record-level request every word must either be understood or reported: "show acme invoices"
    (lowercase, no "from") cannot silently become "show every invoice". The vocabulary is closed and
    small on purpose; an unusual but harmless word costs a `partial`, which is measured, not hidden.
    """
    doc_words = set(SINGULAR) | set(SINGULAR.values()) | _DOC_NOUNS
    out = []
    for m in re.finditer(rf"[A-Za-z][A-Za-z0-9&.{_APOS}\-]*", rest):
        word = m.group(0).rstrip("." + _APOS)
        if re.fullmatch(r"[\w\-]+\.(?:csv|json|md)", word, re.IGNORECASE):
            continue  # an output file name ("out.json")
        low = re.sub(rf"[{_APOS}]s$", "", word.lower())
        if (
            low in _FILLER
            or low in _CONTENT_OK
            or low in _FIELD_VOCAB
            or low.rstrip("s") in _FIELD_VOCAB
            or low in doc_words
            or low in _MONTHS
            or low in _VERBS
            or low in _CODES
            or low in known_words
            or low in _NAME_STOP
        ):
            continue
        out.append((m.start(), word))
    return out
