"""Deterministic parsers for money, numbers, dates, emails and phone numbers."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

_CURRENCY = r"(?:E£|[$€£¥₹]|USD|EUR|GBP|CAD|AUD|INR|JPY|CHF|EGP|SAR|AED|IDR|Rp\.?)"
# Thousands groups use ',' '.' or a non-breaking/thin space — a plain space only right after a
# currency symbol ("$ 2 425,87"); elsewhere it would glue a quantity column onto an amount ("2 150.00").
# A number followed by '%' is a rate, not money.
MONEY_RE = re.compile(
    rf"(?P<neg>-|\()?\s*(?P<cur1>{_CURRENCY})?\s*"
    rf"(?P<num>(?(cur1)\d{{1,3}}(?: \d{{3}})+[.,]\d{{2}}(?![\d.,])|(?!))"
    rf"|\d{{1,3}}(?:[,.  ]\d{{3}})+(?:[.,]\d{{1,2}})?|\d+(?:[.,]\d{{1,2}})?)(?![\d.,]*\s*%)"
    rf"\s*(?P<cur2>{_CURRENCY})?(?P<close>\))?",
    re.IGNORECASE,
)
_MONTHS = {
    m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])
}
_MON = (
    r"(?P<mon>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
DATE_PATTERNS = [
    re.compile(r"\b(?P<y>\d{4})[-/.](?P<m>\d{1,2})[-/.](?P<d>\d{1,2})\b"),
    re.compile(r"\b(?P<a>\d{1,2})[-/.](?P<b>\d{1,2})[-/.](?P<y>\d{4}|\d{2})\b"),
    # Month names, with a 2- or 4-digit year, spaced or compact as invoices print them: "14 Mar 2026",
    # "04-JAN-00", "19Jun'22", "March 14, 2026", "JAN04/00". A year followed by ".5" or ":30" is an amount
    # or a time, not a year ("QTY 2 MAY 15.00").
    re.compile(
        rf"\b(?P<d>\d{{1,2}})(?:st|nd|rd|th)?[\s\-/.]*{_MON}\.?,?[\s\-/.']*(?P<y>\d{{4}}|\d{{2}})\b(?![.,:]\d)",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b{_MON}\.?[\s\-/.]*(?P<d>\d{{1,2}})(?![.,]\d)(?:st|nd|rd|th)?,?[\s\-/.']+(?P<y>\d{{4}}|\d{{2}})\b(?![.,:]\d)",
        re.IGNORECASE,
    ),
]
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?)?\d{3,4}[\s.-]\d{3,4}(?:[\s.-]\d{2,4})?")


def parse_number(raw: str) -> Decimal | None:
    s = re.sub(r"[\s  ]", "", raw)
    if not s:
        return None
    # Decide the decimal separator: the last of ',' or '.' followed by 1-2 digits.
    m = re.search(r"[.,](\d{1,2})$", s)
    if m:
        whole, frac = s[: m.start()], m.group(1)
        whole = re.sub(r"[.,]", "", whole)
        s = f"{whole}.{frac}"
    else:
        s = re.sub(r"[.,]", "", s)
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_money(text: str) -> tuple[Decimal, str | None] | None:
    """First monetary amount in ``text`` as (amount, currency)."""
    for m in MONEY_RE.finditer(text):
        cur = m.group("cur1") or m.group("cur2")
        num = m.group("num")
        # Bare integers without a currency, decimals or thousands groups are rarely money (dates, counts).
        if not cur and not _money_shaped(num):
            continue
        value = parse_number(num)
        if value is None:
            continue
        # "(40.00)" is negative; a lone "(" before a number ("(see note) 40.00") is not.
        if m.group("neg") == "-" or (m.group("neg") == "(" and m.group("close")):
            value = -value
        return value, _norm_currency(cur)
    return None


def all_money(text: str) -> list[Decimal]:
    out = []
    for m in MONEY_RE.finditer(text):
        cur, num = m.group("cur1") or m.group("cur2"), m.group("num")
        if cur or _money_shaped(num):
            value = parse_number(num)
            if value is not None:
                out.append(value)
    return out


def _money_shaped(num: str) -> bool:
    """Cents ("40.00") or thousands groups ("16,363", "7.000": currencies without cents, like IDR)."""
    return bool(re.search(r"[.,]\d{2}$", num) or re.fullmatch(r"\d{1,3}(?:[,.]\d{3})+", num))


def _norm_currency(cur: str | None) -> str | None:
    if not cur:
        return None
    key = cur.rstrip(".").upper()
    return {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR", "E£": "EGP", "RP": "IDR"}.get(key, key)


def _year(y: str) -> int:
    n = int(y)
    return n + 2000 if n < 70 else (n + 1900 if n < 100 else n)


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_dates(text: str, day_first: bool = False) -> list[tuple[date, str, int]]:
    """All dates in ``text`` as (date, raw text, position), in order of appearance."""
    found: dict[int, tuple[date, str, int]] = {}
    for pattern in DATE_PATTERNS:
        for m in pattern.finditer(text):
            if any(start <= m.start() < start + len(raw) for start, (_, raw, _) in found.items()):
                continue
            g = m.groupdict()
            if g.get("mon"):
                parsed = _safe_date(_year(g["y"]), _MONTHS[g["mon"][:3].lower()], int(g["d"]))
            elif "a" in g and g.get("a"):
                a, b, y = int(g["a"]), int(g["b"]), _year(g["y"])
                if a > 12:
                    parsed = _safe_date(y, b, a)
                elif b > 12:
                    parsed = _safe_date(y, a, b)
                else:
                    parsed = _safe_date(y, b, a) if day_first else _safe_date(y, a, b)
            else:
                parsed = _safe_date(int(g["y"]), int(g["m"]), int(g["d"]))
            if parsed:
                found[m.start()] = (parsed, m.group(0), m.start())
    return [found[k] for k in sorted(found)]


def parse_date(text: str) -> date | None:
    hits = parse_dates(text)
    return hits[0][0] if hits else None
