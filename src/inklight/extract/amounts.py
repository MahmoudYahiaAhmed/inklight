"""Amount consistency: flag amounts that OCR may have misread, without changing them.

A receipt in a currency without cents writes every amount as thousands groups ("25.000", "38,000").
OCR sometimes drops a digit, and "63.000" comes back as "63.00": a valid-looking amount that is a
thousand times too small. No single signal proves that, because a smaller total (discount, deposit,
refund), a cents amount (a tax with decimals, a foreign-currency line) or an unusual notation can
all be legitimate. So an amount is flagged only when independent signals agree:

* **format**: the document's other amounts have no cents (or the document names a zero-decimal
  currency), but this amount has two decimals;
* **magnitude**: a total or subtotal is under 1/50 of the largest other amount on the document
  (payments such as cash tendered and change excluded);
* **OCR confidence**: the amount's line was read with confidence below 0.9;
* **second reading**: OCR of the enlarged image region gives a different amount.

Flag when format agrees with any other signal, or when magnitude agrees with a second reading. The
value and its OCR text are kept; the warning gives the reasons, the second reading and the source,
confidence is halved and the value is no longer marked verified. Nothing is multiplied or rewritten.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from ..schemas import BBox, ExtractedValue
from .layout import same_row
from .values import all_money

Reread = Callable[[int, BBox], str | None]

ZERO_DECIMAL = {"IDR", "JPY", "KRW", "VND"}
CENTS_CURRENCIES = {"USD", "EUR", "GBP", "CAD", "AUD", "CHF", "INR", "EGP", "SAR", "AED"}
MAGNITUDE = 50
LOW_CONF = 0.9

# "25.000", "38,000", and OCR's "25. 000": thousands groups without cents.
_GROUPED = re.compile(r"(?<![\d.,])\d{1,3}(?:[.,] ?\d{3})+(?![\d]|[.,]\d)")
_CENTS = re.compile(r"(?<![\d.,])\d{1,3}(?:[.,]\d{3})*[.,]\d{2}(?![\d%])")
_ENDS_IN_CENTS = re.compile(r"[.,]\d{2}\s*\)?\s*$")
_ZERO_DECIMAL_WORD = re.compile(r"\bRp\.?(?=\s|\d)|\b(?:IDR|JPY|KRW|VND)\b|[¥₩₫]")
PAYMENT = re.compile(
    r"\b(cash|change|kembali(?:an)?|tunai|card|debit|credit|paid|tendered|bayar|payment)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class _Line:
    page: int
    text: str
    bbox: BBox | None
    conf: float | None


def check_amounts(
    values: dict[str, ExtractedValue],
    money_fields: Iterable[str],
    lines: Sequence[object],
    reread: Reread | None = None,
) -> dict[str, ExtractedValue]:
    """Return ``values`` with suspicious amounts flagged (a new dict; the input is not changed)."""
    placed = [_Line(ln.page, ln.text, ln.bbox, ln.conf) for ln in lines]  # type: ignore[attr-defined]
    out = dict(values)
    for name in money_fields:
        item = values.get(name)
        if item is None or item.value is None or not item.raw or item.source is None:
            continue
        reasons, second = _evidence(name, item, placed, reread)
        if reasons:
            out[name] = _flag(item, reasons, second)
    return out


def _evidence(
    name: str, item: ExtractedValue, lines: list[_Line], reread: Reread | None
) -> tuple[list[str], str | None]:
    source = item.source
    assert source is not None  # checked by the caller
    others = [ln for ln in lines if not (ln.page == source.page and ln.bbox == source.bbox)]
    format_ = _format_deviation(item, others)
    magnitude = _magnitude_break(name, item, others)
    low_conf = source.ocr_conf is not None and source.ocr_conf < LOW_CONF
    second, disagrees = None, False
    if (format_ or magnitude) and reread is not None and source.bbox is not None:
        second = reread(source.page, source.bbox)
        disagrees = _disagrees(item, second)
    if not ((format_ and (magnitude or low_conf or disagrees)) or (magnitude and disagrees)):
        return [], None
    reasons = []
    if format_:
        reasons.append(format_)
    if magnitude:
        reasons.append(magnitude)
    if low_conf:
        reasons.append(f"its line was read with low OCR confidence ({source.ocr_conf:.2f})")
    return reasons, second if disagrees else None


def _format_deviation(item: ExtractedValue, others: list[_Line]) -> str | None:
    if not _ENDS_IN_CENTS.search(item.raw or ""):
        return None
    text = "\n".join(ln.text for ln in others)
    grouped = len(_GROUPED.findall(text))
    cents = len(_CENTS.findall(text))
    zero_decimal = bool(_ZERO_DECIMAL_WORD.search(text)) or (item.unit in ZERO_DECIMAL)
    if item.unit in CENTS_CURRENCIES:
        return None  # cents are normal for an amount stated in a currency that has them
    no_cents_document = (
        (grouped >= 2 and cents == 0) or (zero_decimal and grouped > cents) or (grouped >= 3 and grouped >= 3 * cents)
    )
    if not no_cents_document:
        return None
    return f"it has cents, but the document's other amounts ({grouped}) are written without cents"


def _magnitude_break(name: str, item: ExtractedValue, others: list[_Line]) -> str | None:
    if name not in ("total", "subtotal"):
        return None
    if item.unit in CENTS_CURRENCIES and any(_ZERO_DECIMAL_WORD.search(ln.text) for ln in others):
        return None  # a dollar amount beside rupiah amounts: different currencies are not compared
    try:
        value = abs(Decimal(str(item.value)))
    except ArithmeticError:
        return None
    amounts = [a for ln in others if not _is_payment(ln, others) for a in all_money(ln.text)]
    largest = max(amounts, default=Decimal(0))
    if value == 0 or largest < MAGNITUDE * value:
        return None
    return f"it is under 1/{MAGNITUDE} of another amount on the document ({largest:,})"


def _is_payment(line: _Line, lines: list[_Line]) -> bool:
    """Cash tendered or change: the payment word is on the line, or to its left on the same row."""
    if PAYMENT.search(line.text):
        return True
    me = line.bbox
    return me is not None and any(
        o.page == line.page
        and o.bbox is not None
        and o.bbox[2] <= me[0] + 4
        and same_row(me, o.bbox)
        and PAYMENT.search(o.text)
        for o in lines
    )


def _disagrees(item: ExtractedValue, second: str | None) -> bool:
    """True when a second reading holds amounts and none of them is the stored value."""
    if not second:
        return False
    amounts = all_money(second)
    if not amounts:
        return False
    try:
        value = Decimal(str(item.value))
    except ArithmeticError:
        return False
    return all(abs(abs(a) - abs(value)) > Decimal("0.005") for a in amounts)


def _flag(item: ExtractedValue, reasons: list[str], second: str | None) -> ExtractedValue:
    src = item.source
    where = f"page {src.page}, box {tuple(round(v) for v in src.bbox)}" if src and src.bbox else "its source line"
    note = f"possible OCR misread: read {item.raw!r} ({where}); " + "; ".join(reasons)
    if second:
        note += f"; reading that area again gives {second!r}"
    note += ". Kept as read, please check the source"
    warning = f"{item.warning}; {note}" if item.warning else note
    return item.model_copy(
        update={"warning": warning, "verified": False, "confidence": round(item.confidence * 0.5, 3)}
    )
