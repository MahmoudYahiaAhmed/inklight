"""Amount consistency: suspicious amounts are flagged, never rewritten, and only on agreeing evidence."""

from pathlib import Path

import pytest

from inklight.extract.fields import extract_record, resolve_field
from inklight.schemas import DocumentInfo, PageContent, TextLine

MISREAD = "possible OCR misread"


def _doc():
    return DocumentInfo(id="d" * 16, path="/x/r.png", name="r.png", sha256="0", size=1, mtime=0)


def _page(*items, conf=0.99):
    """(text, x0, y0, x1, y1) or (text, x0, y0, x1, y1, conf), in reading order."""
    lines = []
    for item in items:
        text, *box = item
        c = box.pop() if len(box) == 5 else conf
        lines.append(TextLine(text=text, bbox=tuple(box), conf=c))
    return [PageContent(number=1, lines=tuple(lines))]


def _get(pages, *names, reread=None):
    rec = extract_record(_doc(), pages, [resolve_field(n) for n in names], reread=reread)
    return {n: rec.fields[n] for n in names}


def _flagged(value):
    return MISREAD in (value.warning or "")


# ---------------------------------------------------------------- the two receipts that were silently wrong

# CORD holdout 015, as Indra read it: "63.000" came back as "63.00"; OCR also split "25. 000" and "70. 000".
CORD_015 = _page(
    ("1 Lemon Tea (L.)", 37.3, 515.7, 237.2, 544.2, 0.9468),
    ("25. 000", 423.7, 529.9, 495.1, 554.2, 0.9458),
    ("1 Caramel Small", 34.5, 543.1, 236.7, 573.6, 0.9407),
    ("38.000", 425.0, 558.5, 495.6, 580.4, 0.9969),
    ("TOTAL", 266.7, 629.0, 327.4, 656.1, 0.9931),
    ("63.00", 421.5, 619.7, 493.5, 661.1, 0.9811),
    ("70. 000", 427.1, 695.8, 500.9, 721.8, 0.9505),
    ("CASH", 18.4, 691.2, 74.1, 718.2, 0.9933),
    ("CHANGED", 17.1, 719.8, 109.2, 751.1, 0.9982),
    ("7.000", 438.0, 725.2, 503.5, 752.4, 0.9486),
)

# CORD holdout 032: subtotal 24.000 read right, grand total read as "24.00".
CORD_032 = _page(
    ("1 ICE TEA", 354.6, 1615.0, 520.0, 1667.0),
    ("024.000", 527.6, 1615.5, 740.8, 1667.9, 0.8837),
    ("24.000", 1370.0, 1639.4, 1542.8, 1684.8, 0.9994),
    ("SUB-TOTAL", 354.6, 1755.2, 611.8, 1806.0, 0.994),
    ("24.000", 1369.0, 1777.8, 1541.5, 1822.0, 0.9988),
    ("GRANO TOTAL", 550.7, 1918.0, 839.7, 2010.0, 0.73),
    ("24.00", 1374.7, 1932.1, 1539.2, 2012.1, 0.9633),
)


def test_regression_015_flagged_and_kept_as_read():
    total = _get(CORD_015, "total")["total"]
    assert total.value == 63.0 and total.raw == "63.00"  # never multiplied, never "repaired"
    assert _flagged(total) and not total.verified and total.confidence < 0.7
    assert "without cents" in total.warning and "1/50" in total.warning
    assert "page 1" in total.warning  # where to look


def test_regression_015_ignores_cash_tendered_as_the_reference_amount():
    assert "70,000" not in _get(CORD_015, "total")["total"].warning


def test_regression_032_flags_the_total_but_not_the_correct_subtotal():
    got = _get(CORD_032, "subtotal", "total")
    assert _flagged(got["total"]) and got["total"].value == 24.0
    assert not _flagged(got["subtotal"]) and got["subtotal"].value == 24000.0


# ---------------------------------------------------------------- legitimate amounts stay unflagged


def test_decimal_amounts_on_an_ordinary_invoice():
    pages = _page(
        ("Subtotal: $1,000.00", 100, 100, 400, 120),
        ("Tax: $100.00", 100, 140, 400, 160),
        ("Total: $1,100.00", 100, 180, 400, 200),
    )
    assert not any(_flagged(v) for v in _get(pages, "subtotal", "tax", "total").values())


def test_thousands_separators_on_a_receipt():
    pages = _page(
        ("Sub Total", 100, 100, 250, 120),
        ("55,908", 600, 100, 700, 120),
        ("Pajak", 100, 140, 250, 160),
        ("5,592", 600, 140, 700, 160),
        ("Total", 100, 180, 250, 200),
        ("61,500", 600, 180, 700, 200),
    )
    assert not any(_flagged(v) for v in _get(pages, "subtotal", "tax", "total").values())


def test_large_discount_is_not_a_misread():
    pages = _page(
        ("Subtotal: $10,000.00", 100, 100, 400, 120),
        ("Voucher: -$9,850.00", 100, 140, 400, 160),
        ("Total: $150.00", 100, 180, 400, 200),
    )
    assert not _flagged(_get(pages, "total")["total"])


def test_discount_on_a_no_cents_receipt():
    pages = _page(
        ("Subtotal", 100, 100, 250, 120),
        ("100.000", 600, 100, 700, 120),
        ("Diskon 60%", 100, 140, 250, 160),
        ("-60.000", 600, 140, 700, 160),
        ("Total", 100, 180, 250, 200),
        ("40.000", 600, 180, 700, 200),
    )
    assert not any(_flagged(v) for v in _get(pages, "subtotal", "total").values())


def test_service_charge():
    pages = _page(
        ("Subtotal", 100, 100, 250, 120),
        ("100,000", 600, 100, 700, 120),
        ("Service 5%", 100, 140, 250, 160),
        ("5,000", 600, 140, 700, 160),
        ("PB1 10%", 100, 180, 250, 200),
        ("10,500", 600, 180, 700, 200),
        ("Total", 100, 220, 250, 240),
        ("115,500", 600, 220, 700, 240),
    )
    assert not any(_flagged(v) for v in _get(pages, "subtotal", "tax", "total").values())


def test_deposit_and_small_balance_due():
    pages = _page(
        ("Contract total: $12,000.00", 100, 100, 400, 120),
        ("Deposit received: $11,950.00", 100, 140, 400, 160),
        ("Balance due: $50.00", 100, 180, 400, 200),
    )
    assert not _flagged(_get(pages, "total")["total"])


def test_refund():
    pages = _page(
        ("Returned item", 100, 100, 300, 120),
        ("$45.00", 600, 100, 700, 120),
        ("Refund total: -$45.00", 100, 140, 400, 160),
    )
    assert not _flagged(_get(pages, "total")["total"])


def test_missing_subtotal_receipt_read_correctly():
    pages = _page(
        ("1 Lemon Tea", 37, 515, 237, 544),
        ("25.000", 423, 529, 495, 554),
        ("1 Caramel Small", 34, 543, 236, 573),
        ("38.000", 425, 558, 495, 580),
        ("TOTAL", 266, 629, 327, 656),
        ("63.000", 421, 619, 493, 661),
    )
    total = _get(pages, "total")["total"]
    assert total.value == 63000.0 and not _flagged(total)


def test_mixed_currencies_a_dollar_amount_on_a_rupiah_receipt():
    pages = _page(
        ("Nasi Goreng", 100, 100, 300, 120),
        ("Rp 45.000", 600, 100, 700, 120),
        ("Es Teh", 100, 140, 300, 160),
        ("Rp 8.000", 600, 140, 700, 160),
        ("Total: USD 3.50", 100, 180, 400, 200),
    )
    assert not _flagged(_get(pages, "total")["total"])


def test_tax_with_decimals_on_a_no_cents_receipt_needs_more_than_its_notation():
    pages = _page(
        ("Subtotal", 100, 100, 250, 120),
        ("55,908", 600, 100, 700, 120),
        ("PB1 10%", 100, 140, 250, 160),
        ("5,590.80", 600, 140, 700, 160),
        ("Total", 100, 180, 250, 200),
        ("61,498", 600, 180, 700, 200),
    )
    tax = _get(pages, "tax", reread=lambda page, box: "5,590.80")["tax"]
    assert not _flagged(tax)  # format alone; the second reading agrees


# ---------------------------------------------------------------- corroboration


def test_unusual_notation_plus_low_ocr_confidence_is_flagged():
    pages = _page(
        ("Subtotal", 100, 100, 250, 120),
        ("55,908", 600, 100, 700, 120),
        ("PB1 10%", 100, 140, 250, 160),
        ("5,590.80", 600, 140, 700, 160, 0.71),
        ("Total", 100, 180, 250, 200),
        ("61,498", 600, 180, 700, 200),
    )
    tax = _get(pages, "tax")["tax"]
    assert _flagged(tax) and "low OCR confidence (0.71)" in tax.warning and tax.value == 5590.8


def test_small_total_confirmed_by_a_second_reading_is_flagged_with_both_readings():
    pages = _page(
        ("Subtotal: $10,000.00", 100, 100, 400, 120),
        ("Total", 100, 180, 200, 200),
        ("$150.00", 600, 180, 700, 200),
    )
    calls = []

    def reread(page, box):
        calls.append((page, box))
        return "$15,000.00"

    total = _get(pages, "total", reread=reread)["total"]
    assert calls == [(1, (600, 180, 700, 200))]
    assert _flagged(total) and total.value == 150.0
    assert "reading that area again gives '$15,000.00'" in total.warning


def test_small_total_with_an_agreeing_second_reading_is_not_flagged():
    pages = _page(
        ("Subtotal: $10,000.00", 100, 100, 400, 120),
        ("Total", 100, 180, 200, 200),
        ("$150.00", 600, 180, 700, 200),
    )
    assert not _flagged(_get(pages, "total", reread=lambda page, box: "$150.00")["total"])


def test_second_reading_without_an_amount_is_inconclusive():
    pages = _page(
        ("Subtotal: $10,000.00", 100, 100, 400, 120),
        ("Total", 100, 180, 200, 200),
        ("$150.00", 600, 180, 700, 200),
    )
    assert not _flagged(_get(pages, "total", reread=lambda page, box: "TOTAL")["total"])


def test_no_second_reading_is_attempted_for_unremarkable_amounts():
    pages = _page(("Subtotal: $1,000.00", 100, 100, 400, 120), ("Total: $1,100.00", 100, 180, 400, 200))
    calls = []
    _get(pages, "subtotal", "total", reread=lambda page, box: calls.append(1))
    assert calls == []


# ---------------------------------------------------------------- the real engine re-reads a crop


def test_indra_rereads_an_image_region(tmp_path):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    from inklight.config import OCRSettings
    from inklight.errors import ModelUnavailable
    from inklight.ocr.indra import IndraEngine

    img = np.full((300, 900), 255, dtype=np.uint8)
    cv2.putText(img, "TOTAL", (40, 160), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 0, 3)
    cv2.putText(img, "63.000", (560, 160), cv2.FONT_HERSHEY_SIMPLEX, 1.6, 0, 3)
    path = Path(tmp_path) / "receipt.png"
    cv2.imwrite(str(path), img)
    engine = IndraEngine(OCRSettings())
    try:
        engine.converter()
    except ModelUnavailable:
        pytest.skip("Indra models are not available offline")
    text = engine.reread(path, 1, (550.0, 120.0, 780.0, 170.0))
    assert text is not None and "63" in text
    assert engine.reread(path, 1, (550.0, 120.0, 780.0, 170.0), rotation=90) is None
    assert engine.reread(path, 2, (550.0, 120.0, 780.0, 170.0)) is None
