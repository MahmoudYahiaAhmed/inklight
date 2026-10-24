"""Strict parsing of amounts a person types (review corrections, manual entry).

Extraction reads amounts out of noisy document text and has to be lenient. A reviewer's input is the ground
truth, so here nothing is guessed: an input is either one well-formed amount or it is rejected with the
reason. Characters are never deleted to make an input fit ("100 + 20" is not 10020, "1e3" is not 13).

Accepted, after Unicode normalisation (NFKC):

* digits: ASCII or any Unicode decimal digits (Arabic-Indic ``٠١٢``, Extended Arabic-Indic, ...);
* an optional sign: a leading ``-`` / ``−``, or accounting parentheses ``(45.00)``;
* at most one currency token, before or after the number: ``$ € £ ¥ ₹ ₩ ₫ E£ Rp`` or a code such as ``USD``;
* digit groups of exactly 3 after the first, separated by one consistent separator: ``,`` ``.`` space,
  no-break space, apostrophe, or the Arabic thousands separator ``٬``;
* a decimal part after ``.`` ``,`` or the Arabic decimal separator ``٫``.

Which separator is decimal: when both ``.`` and ``,`` appear, the last one. When only one appears once and is
followed by exactly three digits ("63.000", "1,234"), it groups thousands, as amounts on documents do;
followed by one or two digits ("12.50", "12,5") it is decimal. Money has at most two decimals.

Rejected: any other character (operators, letters, exponents), two currencies, a sign plus parentheses,
irregular groups ("1,2,3", lakh-style "1,23,456"), mixed group separators, more decimals than allowed.

Dates (``parse_entered_date``) follow the same rule: the whole input is exactly one date. Accepted are the
numeric forms extraction reads ("01/31/82", "12-03-91", "2026-01-31") and a month name with the day and a
2- or 4-digit year, written the way invoices print them: "JAN04/00", "04-JAN-00", "04JAN2000", "Jan. 4, 2000".
Two-digit years follow extraction (00-69 -> 2000s, 70-99 -> 1900s). Extra words, two dates, an impossible day
or a missing year are rejected.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

from .errors import InputRejected
from .extract.values import _MON, _MONTHS, _year, parse_dates

_CURRENCY = r"(?:E£|Rp\.?|[$€£¥₹₩₫]|USD|EUR|GBP|IDR|EGP|SAR|AED|JPY|INR|CAD|AUD|CHF|KWD|QAR)"
_CURRENCY_AT = re.compile(
    rf"^\s*(?P<cur>{_CURRENCY})\s*(?P<rest>.*?)\s*$|^\s*(?P<rest2>.*?)\s*(?P<cur2>{_CURRENCY})\s*$", re.I
)
_GROUP_SEPARATORS = {",", ".", " ", "'", "٬"}
_DECIMAL_SEPARATORS = {".", ",", "٫"}


def _ascii_digits(text: str) -> str:
    out = []
    for ch in text:
        if ch.isdigit() and not ch.isascii():
            try:
                out.append(str(unicodedata.decimal(ch)))
                continue
            except ValueError:
                pass
        out.append(ch)
    return "".join(out)


_SEP = r"[\s\-/.]"
_NAMED_DATES = (
    re.compile(rf"{_MON}\.?{_SEP}*(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?{_SEP}+(?P<y>\d{{4}}|\d{{2}})", re.I),
    re.compile(rf"(?P<d>\d{{1,2}})(?:st|nd|rd|th)?{_SEP}*{_MON}\.?,?{_SEP}*(?P<y>\d{{4}}|\d{{2}})", re.I),
)


def parse_entered_date(text: str) -> date:
    """One typed date, or InputRejected saying why. The whole input must be the date."""
    original = text
    s = _ascii_digits(unicodedata.normalize("NFKC", text)).strip()
    if not s:
        raise InputRejected("Enter a value, or mark the field absent")
    for pattern in _NAMED_DATES:
        m = pattern.fullmatch(s)
        if m:
            y = int(m["y"]) if len(m["y"]) == 4 else _year(m["y"])
            try:
                return date(y, _MONTHS[m["mon"][:3].lower()], int(m["d"]))
            except ValueError:
                raise InputRejected(f"{original!r} is not a real date") from None
    hits = parse_dates(s)
    if len(hits) == 1 and hits[0][1] == s:
        return hits[0][0]
    raise InputRejected(
        f"{original!r} is not one date: type it as the invoice prints it (JAN04/00, 04-Jan-2000, 01/31/82) "
        "or as 2000-01-04, with nothing else"
    )


def parse_entered_amount(text: str, *, money: bool = True) -> tuple[Decimal, str | None]:
    """(value, currency token or None) for one typed amount, or InputRejected saying why."""
    original = text
    s = _ascii_digits(unicodedata.normalize("NFKC", text)).strip()
    s = s.replace("−", "-")  # minus sign
    if not s:
        raise InputRejected("Enter a value, or mark the field absent")
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    currency = None
    m = _CURRENCY_AT.match(s)
    if m and (m.group("cur") or m.group("cur2")):
        currency = m.group("cur") or m.group("cur2")
        s = (m.group("rest") if m.group("cur") else m.group("rest2")) or ""
        if re.search(_CURRENCY, s, re.I):
            raise InputRejected(f"{original!r} names more than one currency")
    if s.startswith("-"):
        if negative:
            raise InputRejected(f"{original!r} has both a minus sign and parentheses")
        negative, s = True, s[1:].strip()
    if not s or not re.fullmatch(r"\d(?:[\d.,' ٬٫]*\d)?", s):
        raise InputRejected(
            f"{original!r} is not a plain amount: use digits with one currency and optional separators "
            "(expressions, letters and exponents are not accepted)"
        )
    value = _number(s, original, money)
    return (-value if negative else value), currency


def _number(body: str, original: str, money: bool) -> Decimal:
    seps = [(i, ch) for i, ch in enumerate(body) if not ch.isdigit()]
    if not seps:
        return Decimal(body)
    decimal_at: int | None = None
    kinds = {ch for _, ch in seps}
    last_i, last = seps[-1]
    digits_after = len(body) - last_i - 1
    if last == "٫":
        decimal_at = last_i
    elif {".", ","} <= kinds:
        decimal_at = last_i if last in (".", ",") else None
        if decimal_at is None:
            raise InputRejected(f"{original!r} mixes separators in a way that cannot be read")
    elif last in (".", ",") and [ch for _, ch in seps].count(last) == 1 and digits_after != 3:
        decimal_at = last_i
    groups_part = body if decimal_at is None else body[:decimal_at]
    decimals = "" if decimal_at is None else body[decimal_at + 1 :]
    if decimal_at is not None and (not decimals.isdigit() or (money and len(decimals) > 2)):
        raise InputRejected(f"{original!r} has {len(decimals)} decimals; an amount has at most 2")
    group_seps = {ch for i, ch in seps if decimal_at is None or i < decimal_at}
    if len(group_seps) > 1 or (group_seps and not group_seps <= _GROUP_SEPARATORS):
        raise InputRejected(f"{original!r} mixes different thousands separators")
    groups = re.split(r"[,. '٬]", groups_part)
    if any(not g.isdigit() for g in groups) or not 1 <= len(groups[0]) <= 3 and len(groups) > 1:
        raise InputRejected(f"{original!r} has irregular digit groups")
    if any(len(g) != 3 for g in groups[1:]):
        raise InputRejected(f"{original!r} has irregular digit groups (thousands come in groups of three)")
    try:
        return Decimal("".join(groups) + (f".{decimals}" if decimals else ""))
    except InvalidOperation as exc:  # pragma: no cover - the patterns above admit only digits
        raise InputRejected(f"{original!r} is not a valid amount") from exc
