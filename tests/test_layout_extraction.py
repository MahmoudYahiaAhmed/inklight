"""Label -> value lookup by page geometry: two-column blocks, summary rows, slanted receipts."""

from decimal import Decimal

from inklight.extract.fields import extract_record, resolve_field
from inklight.extract.values import parse_money
from inklight.schemas import DocumentInfo, PageContent, TextLine


def _doc():
    return DocumentInfo(id="d" * 16, path="/x/inv.png", name="inv.png", sha256="0", size=1, mtime=0)


def _placed(*items):
    """(text, x0, y0, x1, y1) in reading order."""
    return [
        PageContent(number=1, lines=tuple(TextLine(text=t, bbox=(a, b, c, d), conf=0.99) for t, a, b, c, d in items))
    ]


def _get(pages, *names):
    rec = extract_record(_doc(), pages, [resolve_field(n) for n in names])
    return {n: rec.fields[n] for n in names}


# Seller/Client side by side: reading order puts both labels before both names.
TWO_COLUMN = _placed(
    ("Seller:", 133, 447, 255, 471),
    ("Client:", 826, 446, 949, 472),
    ("Wright, Martin and Carter", 142, 510, 501, 536),
    ("97137 Martinez Terrace", 139, 546, 472, 568),
    ("Schneider Ltd", 833, 510, 1026, 531),
    ("2279 Amy Shores", 832, 545, 1083, 572),
)


def test_two_column_labels_take_the_value_under_them():
    got = _get(TWO_COLUMN, "vendor", "customer")
    assert got["vendor"].value == "Wright, Martin and Carter"
    assert got["customer"].value == "Schneider Ltd"
    assert got["customer"].method == "label-below"


def test_client_value_is_not_taken_from_the_other_column():
    pages = _placed(
        ("Seller:", 133, 447, 255, 471),
        ("Proctor, Levy and Willis", 140, 510, 480, 536),
        ("Client:", 826, 446, 949, 472),
        ("IBAN: GB89NZLM61247862676381", 143, 688, 632, 709),
        ("Roth, Morris and Schultz", 833, 510, 1180, 536),
    )
    assert _get(pages, "customer")["customer"].value == "Roth, Morris and Schultz"


SUMMARY = _placed(
    ("VAT [%]", 641, 1283, 743, 1302),
    ("Net worth", 930, 1283, 1056, 1300),
    ("VAT", 1188, 1283, 1240, 1300),
    ("Gross worth", 1353, 1283, 1505, 1300),
    ("10%", 669, 1343, 717, 1360),
    ("14 709,00", 942, 1343, 1054, 1362),
    ("1 470,90", 1141, 1343, 1240, 1362),
    ("16 179,90", 1390, 1343, 1505, 1363),
    ("Total", 501, 1402, 565, 1418),
    ("$ 14 709,00", 908, 1402, 1057, 1422),
    ("$ 1 470,90", 1107, 1402, 1240, 1421),
    ("$ 16 179,90", 1356, 1402, 1505, 1422),
)


def test_summary_row_values_resolved_by_column_title():
    got = _get(SUMMARY, "subtotal", "tax", "total")
    assert (got["subtotal"].value, got["tax"].value, got["total"].value) == (14709.0, 1470.9, 16179.9)
    assert got["total"].method == "label-row-column"
    assert got["total"].verified  # subtotal + tax = total


def test_row_with_several_values_and_no_titles_is_flagged():
    pages = _placed(
        ("Total", 501, 1402, 565, 1418),
        ("$ 14 709,00", 908, 1402, 1057, 1422),
        ("$ 16 179,90", 1356, 1402, 1505, 1422),
    )
    value = _get(pages, "total")["total"]
    assert value.value == 16179.9
    assert "no column title" in value.warning and value.confidence < 0.7


def test_slanted_receipt_value_before_its_label_in_reading_order():
    pages = _placed(
        ("Jumlah Item", 326, 2231, 772, 2306),
        ("16,363", 1548, 2301, 1800, 2393),
        ("Sub Total", 326, 2332, 693, 2410),
        ("Pajak Resto", 318, 2436, 768, 2524),
        ("1,636", 1564, 2401, 1785, 2495),
        ("17,999", 1541, 2501, 1802, 2598),
        ("Grand Total", 328, 2538, 767, 2616),
    )
    got = _get(pages, "subtotal", "tax", "total")
    assert (got["subtotal"].value, got["tax"].value, got["total"].value) == (16363.0, 1636.0, 17999.0)


def test_far_right_text_is_not_a_names_value():
    pages = _placed(("Seller:", 100, 100, 180, 120), ("Page 1 of 2", 1400, 100, 1500, 120))
    assert _get(pages, "vendor")["vendor"].value is None


def test_currency_led_space_groups_and_grouped_integers():
    assert parse_money("$ 2 425,87") == (Decimal("2425.87"), "USD")
    assert parse_money("Rp. 28.636") == (Decimal("28636"), "IDR")
    assert parse_money("16,363") == (Decimal("16363"), None)
    assert parse_money("2 150.00") == (Decimal("150.00"), None)  # unchanged: no currency, could be qty + price
    assert parse_money("Invoice 2041") is None
