from datetime import date
from decimal import Decimal

import pytest

from inklight.errors import InputRejected
from inklight.extract import classify, extract_record, resolve_field, schema_from_dict
from inklight.extract.values import parse_dates, parse_money, parse_number
from inklight.schemas import DocumentInfo, PageContent, TextLine


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1,234.56", Decimal("1234.56")),
        ("1.234,56", Decimal("1234.56")),
        ("1234", Decimal("1234")),
        ("5 616,00", Decimal("5616.00")),
        ("", None),
        ("abc", None),
    ],
)
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


@pytest.mark.parametrize(
    "text,amount,cur",
    [
        ("Total: $5,616.00", Decimal("5616.00"), "USD"),
        ("EUR 1.200,50", Decimal("1200.50"), "EUR"),
        ("(£40.00)", Decimal("-40.00"), "GBP"),
        ("Amount 99.95", Decimal("99.95"), None),
    ],
)
def test_parse_money(text, amount, cur):
    assert parse_money(text) == (amount, cur)


def test_parse_money_ignores_bare_integers():
    assert parse_money("Invoice 2041 dated 2026") is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2026-03-14", date(2026, 3, 14)),
        ("14/03/2026", date(2026, 3, 14)),
        ("03/14/2026", date(2026, 3, 14)),
        ("March 14, 2026", date(2026, 3, 14)),
        ("14 Mar 2026", date(2026, 3, 14)),
        ("June 30th, 2027", date(2027, 6, 30)),
    ],
)
def test_parse_dates(text, expected):
    assert parse_dates(text)[0][0] == expected


def test_parse_dates_rejects_impossible():
    assert parse_dates("2026-02-31") == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("INVOICE DATE JAN04/00", date(2000, 1, 4)),  # genuine invoice (INV-CDIP hjfp0094)
        ("DUE DATE JAN24/00", date(2000, 1, 24)),
        ("INVOICE DATE FEB12/03", date(2003, 2, 12)),
        ("Date: 04-JAN-00", date(2000, 1, 4)),
        ("04JAN2000", date(2000, 1, 4)),
        ("19Jun'22 09:48", date(2022, 6, 19)),  # Egyptian receipt (CORU)
        ("Jan. 4, 2000", date(2000, 1, 4)),
        ("Sept 30, 82", date(1982, 9, 30)),
        ("Date: Mar 14 2026", date(2026, 3, 14)),
    ],
)
def test_parse_dates_month_name_forms(text, expected):
    assert parse_dates(text)[0][0] == expected


@pytest.mark.parametrize(
    "text",
    [
        "QTY 2 MAY 15.00",  # an amount after a month word is not a year
        "MAY 5 10.50",
        "Prices may 30 change",
        "Mar 12",  # no year
        "JAN32/00",  # no such day
        "Item JAN04/005",
    ],
)
def test_parse_dates_month_name_forms_do_not_overreach(text):
    assert parse_dates(text) == []


def test_extract_invoice_style_month_dates():
    page = _page(["Bozell Worldwide, Inc.", "INVOICE DATE JAN04/00", "DUE DATE JAN24/00", "Invoice Amount 31,000.00"])
    rec = extract_record(_doc(), [page], [resolve_field("date"), resolve_field("due date")])
    assert rec.fields["date"].value == "2000-01-04"
    assert rec.fields["due_date"].value == "2000-01-24"


def _doc():
    return DocumentInfo(id="d" * 16, path="/x/inv.pdf", name="inv.pdf", sha256="0", size=1, mtime=0)


def _page(lines, conf=0.99):
    return PageContent(
        number=1,
        lines=tuple(TextLine(text=t, bbox=(0, i * 10, 100, i * 10 + 8), conf=conf) for i, t in enumerate(lines)),
    )


def test_extract_labels_and_crosscheck():
    page = _page(
        [
            "Acme Supplies Ltd.",
            "INVOICE #INV-2041",
            "Invoice Date: 2026-03-14   Due Date: 2026-04-13",
            "Subtotal: $5,200.00",
            "Tax: $416.00",
            "Total: $5,616.00",
        ]
    )
    specs = [resolve_field(f) for f in ["invoice number", "date", "due date", "vendor", "subtotal", "tax", "total"]]
    rec = extract_record(_doc(), [page], specs)
    f = rec.fields
    assert f["invoice_number"].value == "INV-2041"
    assert f["date"].value == "2026-03-14"
    assert f["due_date"].value == "2026-04-13"
    assert f["vendor"].value == "Acme Supplies Ltd." and f["vendor"].warning
    assert f["total"].value == 5616.0 and f["total"].verified
    assert f["total"].source.page == 1 and f["total"].source.bbox is not None


def test_total_crosscheck_flags_bad_arithmetic_even_when_not_requested():
    page = _page(["Subtotal: $100.00", "Tax: $10.00", "Total: $999.00"])
    rec = extract_record(_doc(), [page], [resolve_field("total")])
    assert set(rec.fields) == {"total"}
    assert "does not equal" in rec.fields["total"].warning


def test_date_label_not_confused_with_due_date():
    page = _page(["Due Date: 2026-04-13", "Date: 2026-03-14"])
    assert extract_record(_doc(), [page], [resolve_field("date")]).fields["date"].value == "2026-03-14"


def test_subtotal_not_read_as_total():
    page = _page(["Subtotal: $100.00", "Grand Total: $110.00"])
    assert extract_record(_doc(), [page], [resolve_field("total")]).fields["total"].value == 110.0


def test_label_on_previous_line():
    page = _page(["Amount Due", "$1,500.00"])
    value = extract_record(_doc(), [page], [resolve_field("total")]).fields["total"]
    assert value.value == 1500.0 and value.method == "label-below"


def test_label_on_previous_line_without_geometry():
    page = PageContent(number=1, lines=(TextLine(text="Amount Due"), TextLine(text="$1,500.00")))
    value = extract_record(_doc(), [page], [resolve_field("total")]).fields["total"]
    assert value.value == 1500.0 and value.method == "label-next-line"


def test_low_ocr_confidence_is_flagged():
    value = extract_record(_doc(), [_page(["Total: $5.00"], conf=0.5)], [resolve_field("total")]).fields["total"]
    assert "low OCR confidence" in value.warning and value.confidence < 0.6


def test_missing_required_field():
    spec = schema_from_dict({"fields": [{"name": "po_number", "type": "id", "required": True}]})
    assert extract_record(_doc(), [_page(["nothing here"])], spec).fields["po_number"].warning == "not found"


def test_schema_formats():
    js = schema_from_dict(
        {
            "properties": {
                "total": {"type": "number", "x-type": "money"},
                "issued": {"type": "string", "format": "date"},
            },
            "required": ["total"],
        }
    )
    assert [(s.name, s.type, s.required) for s in js] == [("total", "money", True), ("issued", "date", False)]
    assert [s.type for s in schema_from_dict({"a": "money", "b": "date"})] == ["money", "date"]
    with pytest.raises(InputRejected):
        schema_from_dict({"a": "colour"})
    with pytest.raises(InputRejected):
        schema_from_dict([1, 2])


def test_resolve_field_aliases():
    assert resolve_field("VAT").name == "tax"
    assert resolve_field("customer names").name == "customer"
    assert resolve_field("Shipping Method").name == "shipping_method"


@pytest.mark.parametrize(
    "text,kind",
    [
        ("INVOICE #1 Bill To: X Amount Due $5 Subtotal", "invoice"),
        ("This Agreement between the parties hereinafter ... governing law", "contract"),
        ("Quarterly report. Executive summary. Findings and analysis", "report"),
        ("hello there", "unknown"),
    ],
)
def test_classify(text, kind):
    assert classify(text)[0] == kind


def test_percent_is_not_money():
    assert parse_money("Tax (8.25%): $12.00") == (Decimal("12.00"), "USD")
    page = _page(["Tax Rate 8.25%", "Tax: $12.00"])
    assert extract_record(_doc(), [page], [resolve_field("tax")]).fields["tax"].value == 12.0


def test_plain_space_does_not_join_columns():
    assert parse_money("2 150.00") == (Decimal("150.00"), None)
    assert parse_money("2 150.00") == (Decimal("2150.00"), None)


def test_unclosed_paren_is_not_negative():
    assert parse_money("(see note) 40.00") == (Decimal("40.00"), None)


def test_next_line_fallback_skips_other_labels():
    rec = extract_record(_doc(), [_page(["Vendor:", "Invoice No: 123"])], [resolve_field("vendor")])
    assert rec.fields["vendor"].value != "Invoice No: 123"
    rec = extract_record(_doc(), [_page(["INVOICE", "123 Main Street"])], [resolve_field("invoice number")])
    assert rec.fields["invoice_number"].value is None


def test_single_char_invoice_id():
    rec = extract_record(_doc(), [_page(["Invoice #7"])], [resolve_field("invoice number")])
    assert rec.fields["invoice_number"].value == "7"


def test_issue_date_far_in_the_future_is_flagged():
    # OCR read "08-OCT-85" as "08-OCT-35" (INV-CDIP tngn0205): keep the value, flag the year.
    page = _page(["INVOICE", "Date of Inv: 08-OCT-35", "Due Date: 08-OCT-36"])
    rec = extract_record(_doc(), [page], [resolve_field("date"), resolve_field("due date")])
    assert rec.fields["date"].value == "2035-10-08"
    assert "future" in rec.fields["date"].warning
    assert "future" not in (rec.fields["due_date"].warning or "")  # due and expiry dates may lie ahead
