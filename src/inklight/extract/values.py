"""Deterministic parsers for money, numbers, dates, emails and phone numbers."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

_CURRENCY = (
    r"(?:E£|[$€£¥₹]|USD|EUR|GBP|CAD|AUD|INR|JPY|CHF|EGP|SAR|AED|IDR|Rp\.?"
    # Egypt, Saudi Arabia, the UAE: "L.E" / "LE" (not inside a word), ج.م, جنيه, ر.س, ريال, د.إ, درهم
    r"|(?<![A-Za-z])L\.?E\b\.?|ج\.?\s?م\b\.?|جنيه(?:ا)?(?:\s+مصري)?|ر\.?\s?س\b\.?|ريال(?:\s+سعودي)?"
    r"|د\.?\s?إ\b\.?|درهم(?:\s+إماراتي)?)"
)
# "ثمانية آلاف جنيه مصري (8,000 ج.م)", "twenty dollars ($20.00)": parentheses after a written-out amount restate
# it; they are not an accounting negative. Nor are parentheses after an Arabic word (prose, not a ledger).
_AMOUNT_WORDS_BEFORE = re.compile(
    rf"(?:{_CURRENCY}|dollars?|euros?|pounds?|riyals?|dirhams?|dinars?|دينار|[ء-ي]{{2,}})\s*$", re.IGNORECASE
)
_CURRENCY_CODES = {
    "$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₹": "INR", "E£": "EGP", "RP": "IDR",
    "LE": "EGP", "جم": "EGP", "جنيه": "EGP", "جنيها": "EGP", "جنيهمصري": "EGP", "جنيهامصري": "EGP",
    "رس": "SAR", "ريال": "SAR", "ريالسعودي": "SAR", "دإ": "AED", "درهم": "AED", "درهمإماراتي": "AED",
}  # fmt: skip
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
# Arabic month names: the Gregorian names used in Egypt and the Gulf, and the Levantine/Iraqi names. UN documents
# write both ("18 كانون الثاني/يناير 2023"). Written plain here; letter variants are matched by _ar_class.
_AR_MONTHS = {
    "يناير": 1, "فبراير": 2, "مارس": 3, "ابريل": 4, "مايو": 5, "يونيو": 6, "يونيه": 6, "يوليو": 7, "يوليه": 7,
    "اغسطس": 8, "سبتمبر": 9, "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12,
    "كانون الثاني": 1, "شباط": 2, "اذار": 3, "نيسان": 4, "ايار": 5, "حزيران": 6, "تموز": 7, "اب": 8,
    "ايلول": 9, "تشرين الاول": 10, "تشرين الثاني": 11, "كانون الاول": 12,
}  # fmt: skip
_AR_VARIANTS = {"ا": "[اأإآ]", "ي": "[يى]", "ه": "[هة]"}


def _ar_class(name: str) -> str:
    return "".join(_AR_VARIANTS.get(c, re.escape(c)) for c in name).replace(r"\ ", r"\s+")


_AR_MONTH_NAMES = sorted(_AR_MONTHS, key=len, reverse=True)
_AR_MON = "|".join(_ar_class(m) for m in _AR_MONTH_NAMES)
_AR_LETTER = "[" + chr(0x621) + "-" + chr(0x64A) + "]"
AR_DATE_RE = re.compile(
    rf"(?<!\d)(?P<d>\d{{1,2}})\s+(?P<amon>{_AR_MON})(?!{_AR_LETTER})(?:\s*/\s*(?:{_AR_MON})(?!{_AR_LETTER}))?"
    rf"\s*،?\s*(?P<y>\d{{4}})(?!\d)"
)


def _ar_month(raw: str) -> int | None:
    plain = re.sub(r"\s+", " ", raw.strip())
    for name in _AR_MONTH_NAMES:
        if re.fullmatch(_ar_class(name), plain):
            return _AR_MONTHS[name]
    return None


DATE_PATTERNS.append(AR_DATE_RE)
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
        restates = m.group("neg") == "(" and _AMOUNT_WORDS_BEFORE.search(text[: m.start()])
        if m.group("neg") == "-" or (m.group("neg") == "(" and m.group("close") and not restates):
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
    key = re.sub(r"[.\s]", "", cur).upper()
    return _CURRENCY_CODES.get(key, key)


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
            if g.get("amon"):
                month = _ar_month(g["amon"])
                parsed = _safe_date(int(g["y"]), month, int(g["d"])) if month else None
            elif g.get("mon"):
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
