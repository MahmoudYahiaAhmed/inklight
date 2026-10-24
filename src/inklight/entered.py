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
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

from .errors import InputRejected

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
