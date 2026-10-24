"""Right-to-left forms: an Arabic label's value sits to its LEFT on the row.

Geometry from the dev synthetic Arabic invoice."""

from inklight.extract import extract_record, schema_from_dict
from inklight.schemas import DocumentInfo, PageContent, TextLine

LINES = [
    ((1298.6, 187.1, 1528.8, 238.3), "فاتورة ضريبية"),
    ((1442.6, 289.1, 1509.4, 325.5), "البائع:"),
    ((704.8, 292.2, 1026.9, 320.4), "شركة الواحة للتجهيزات المكتبية"),
    ((1378.2, 474.9, 1509.3, 510.7), "رقم الفاتورة:"),
    ((894.8, 480.0, 1021.6, 501.7), "INV-7731"),
    ((1356.9, 536.5, 1509.1, 571.2), "تاريخ الفاتورة:"),
    ((864.7, 540.6, 1026.0, 562.6), "2024-05-12"),
    ((1300.0, 900.0, 1509.0, 930.0), "الإجمالي:"),
    ((800.0, 902.0, 1020.0, 928.0), "4,600.00 ر.س"),
]


def _page() -> PageContent:
    return PageContent(number=1, lines=tuple(TextLine(text=t, bbox=b, conf=0.99) for b, t in LINES))


def _doc() -> DocumentInfo:
    return DocumentInfo(id="r" * 16, path="/x/ar.pdf", name="ar.pdf", sha256="0", size=1, mtime=0)


def test_arabic_labels_take_the_value_on_their_left():
    specs = schema_from_dict(
        {
            "fields": [
                {"name": "invoice_number", "type": "id", "labels": ["رقم الفاتورة"]},
                {"name": "date", "type": "date", "labels": ["تاريخ الفاتورة"]},
                {"name": "seller", "type": "text", "labels": ["البائع"]},
                {"name": "total", "type": "money", "labels": ["الإجمالي"]},
            ]
        }
    )
    f = extract_record(_doc(), [_page()], specs).fields
    assert f["invoice_number"].value == "INV-7731"
    assert f["date"].value == "2024-05-12"
    assert f["seller"].value == "شركة الواحة للتجهيزات المكتبية"
    assert f["total"].value == 4600.0
    assert f["invoice_number"].method == "label-row"


def test_english_labels_still_read_to_the_right():
    page = PageContent(
        number=1,
        lines=(
            TextLine(text="Invoice No:", bbox=(50, 100, 160, 120), conf=0.99),
            TextLine(text="A-17", bbox=(200, 100, 260, 120), conf=0.99),
            TextLine(text="Ref:", bbox=(10, 100, 40, 120), conf=0.99),
        ),
    )
    specs = schema_from_dict({"fields": [{"name": "invoice_number", "type": "id", "labels": ["Invoice No"]}]})
    assert extract_record(_doc(), [page], specs).fields["invoice_number"].value == "A-17"


def test_the_invoice_preset_reads_arabic_labels():
    from inklight.extract import resolve_field

    specs = [resolve_field(f) for f in ("invoice_number", "date", "vendor", "total")]
    f = extract_record(_doc(), [_page()], specs).fields
    assert (f["invoice_number"].value, f["date"].value, f["total"].value) == ("INV-7731", "2024-05-12", 4600.0)
    assert f["vendor"].value == "شركة الواحة للتجهيزات المكتبية"


def test_a_letter_date_comes_from_letter_dated():
    from inklight.extract import resolve_field

    page = PageContent(
        number=1,
        lines=(
            TextLine(text="Distr.: General 23 January 2023", bbox=(10, 10, 300, 30), conf=0.99),
            TextLine(text="Letter dated 18 January 2023 from the Chargé d'affaires", bbox=(10, 60, 600, 80), conf=0.99),
            TextLine(text="the Luanda mini-summit held on 23 November 2022", bbox=(10, 300, 600, 320), conf=0.99),
        ),
    )
    letter = _doc().model_copy(update={"doc_type": "letter"})
    assert extract_record(letter, [page], [resolve_field("date")]).fields["date"].value == "2023-01-18"


def test_a_letter_cited_in_the_body_does_not_date_the_document():
    from inklight.extract import resolve_field

    lines = [
        TextLine(text=f"Paragraph {n} of the report text.", bbox=(10, 40 + 30 * n, 600, 60 + 30 * n), conf=0.99)
        for n in range(20)
    ]
    lines.insert(0, TextLine(text="Distr.: General 15 January 2024", bbox=(10, 5, 300, 25), conf=0.99))
    lines.append(
        TextLine(
            text="The Council welcomed the letter dated 14 August 2017 from Iraq", bbox=(10, 700, 600, 720), conf=0.99
        )
    )
    value = extract_record(_doc(), [PageContent(number=1, lines=tuple(lines))], [resolve_field("date")]).fields["date"]
    assert value.value == "2024-01-15"


def test_only_a_title_line_starting_letter_dated_dates_the_document():
    from inklight.extract import resolve_field

    page = PageContent(
        number=1,
        lines=(
            TextLine(text="Distr.: General 2 January 2024", bbox=(10, 5, 300, 25), conf=0.99),
            TextLine(
                text="Credentials of the alternate representative. Report of the Secretary-General",
                bbox=(10, 40, 600, 60),
                conf=0.99,
            ),
            TextLine(
                text="the Secretary-General has received a letter dated 13 February 2023 from",
                bbox=(10, 80, 600, 100),
                conf=0.99,
            ),
        ),
    )
    assert extract_record(_doc(), [page], [resolve_field("date")]).fields["date"].value == "2024-01-02"


def test_letter_dated_dates_only_a_letter():
    from inklight.extract import resolve_field

    lines = (
        TextLine(text="Distr.: General 2 January 2024", bbox=(10, 5, 300, 25), conf=0.99),
        TextLine(text="وثائق تفويض ممثلة البرازيل في مجلس الأمن", bbox=(10, 40, 600, 60), conf=0.99),
        TextLine(text="رسالة مؤرخة 29 آذار/مارس 2023 من القائم بالأعمال", bbox=(10, 80, 600, 100), conf=0.99),
    )
    page = PageContent(number=1, lines=lines)
    report = _doc().model_copy(update={"doc_type": "report"})
    letter = _doc().model_copy(update={"doc_type": "letter"})
    assert extract_record(report, [page], [resolve_field("date")]).fields["date"].value == "2024-01-02"
    assert extract_record(letter, [page], [resolve_field("date")]).fields["date"].value == "2023-03-29"
