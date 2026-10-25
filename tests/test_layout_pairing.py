"""Labels and values paired by their position on the page, across columns OCR read separately.

Receipts, invoices and forms often print a label on the left and its value on the right (or the reverse in
Arabic), and OCR returns the labels as one block and the values as another. A value belongs to a label when it
sits on the label's visual row. Several candidate values on one row are reported as ambiguous instead of choosing
one. Geometry for the first case is the Costa receipt from bench/usecases (fresh3, development data).
"""

from pathlib import Path

import pytest

from inklight import DocumentAgent
from inklight.extract import extract_record, resolve_field, schema_from_dict
from inklight.library import Library
from inklight.schemas import Block, DocumentContent, DocumentInfo, PageContent, TextLine

from .conftest import make_settings

COSTA = [
    ((171, 2517, 942, 2586), "Baguette BBO Chicken"),
    ((1674, 2512, 1874, 2574), "70.00"),
    ((172, 2749, 1082, 2815), "SubTotal (VAT-Inclusive)"),
    ((171, 2819, 1380, 2888), "-VAT ضريبة القيمة المضافة 14"),
    ((165, 2908, 660, 2962), "Dine In Total"),
    ((1467, 2818, 1644, 2885), "8.60"),
    ((1673, 2747, 1883, 2814), "61.40"),
    ((1682, 2902, 1882, 2967), "70.00"),
]
# A membership form: English labels on the left, Arabic labels on the right, values in a middle column read as
# a separate block; one row has two competing amounts.
FORM = [
    ((40, 100, 300, 130), "Membership form / استمارة عضوية"),
    ((40, 200, 260, 230), "Date of issue:"),
    ((40, 260, 260, 290), "Membership fee:"),
    ((40, 320, 260, 350), "Deposit:"),
    ((620, 200, 760, 230), "تاريخ الإصدار"),
    ((620, 260, 760, 290), "رسوم العضوية"),
    ((330, 202, 520, 228), "12 March 2024"),
    ((330, 262, 450, 288), "25.00"),
    ((330, 322, 430, 348), "500.00"),
    ((460, 322, 580, 348), "1,500.00"),
]


def _page(lines) -> PageContent:  # noqa: ANN001
    return PageContent(number=1, lines=tuple(TextLine(text=t, bbox=tuple(map(float, b)), conf=0.97) for b, t in lines))


def _doc() -> DocumentInfo:
    return DocumentInfo(id="c" * 16, path="/x/r.jpg", name="r.jpg", sha256="0", size=1, mtime=0)


# ---------------------------------------------------------------- extraction


def test_values_read_as_a_separate_column_pair_with_their_labels_by_row():
    f = extract_record(_doc(), [_page(COSTA)], [resolve_field(n) for n in ("subtotal", "tax", "total")]).fields
    assert f["subtotal"].value == 61.4
    assert f["total"].value == 70.0
    assert f["tax"].value == 8.6  # a mixed Arabic/English label with its amount on the far side of the row
    assert f["tax"].source is not None and f["tax"].source.bbox == (1467.0, 2818.0, 1644.0, 2885.0)
    assert f["tax"].source.page == 1


def test_competing_values_on_one_row_are_flagged_not_guessed():
    specs = schema_from_dict({"fields": [{"name": "deposit", "type": "money", "labels": ["Deposit"]}]})
    v = extract_record(_doc(), [_page(FORM)], specs).fields["deposit"]
    assert v.confidence < 0.3 and v.warning and "values on the" in v.warning


def test_form_labels_in_both_directions_find_the_middle_column():
    specs = schema_from_dict(
        {
            "fields": [
                {"name": "issued", "type": "date", "labels": ["Date of issue"]},
                {"name": "issued_ar", "type": "date", "labels": ["تاريخ الإصدار"]},
                {"name": "fee", "type": "money", "labels": ["Membership fee"]},
                {"name": "fee_ar", "type": "money", "labels": ["رسوم العضوية"]},
            ]
        }
    )
    f = extract_record(_doc(), [_page(FORM)], specs).fields
    assert str(f["issued"].value) == "2024-03-12" and str(f["issued_ar"].value) == "2024-03-12"
    assert f["fee"].value == 25.0 and f["fee_ar"].value == 25.0


def test_a_heading_row_is_not_a_tax_amount():
    lines = [
        ((40, 40, 300, 80), "TAX INVOICE"),
        ((420, 42, 600, 78), "No. 2045"),
        ((40, 200, 200, 230), "Total"),
        ((420, 200, 560, 230), "115.00"),
    ]
    f = extract_record(_doc(), [_page(lines)], [resolve_field("tax"), resolve_field("total")]).fields
    assert f["tax"].value is None
    assert f["total"].value == 115.0


def test_a_wrapped_label_keeps_its_value_on_the_first_rows_line():
    lines = [
        ((40, 200, 300, 230), "Total amount due"),
        ((40, 232, 300, 262), "(incl. VAT)"),
        ((420, 202, 560, 228), "1,140.00"),
        ((40, 300, 200, 330), "VAT 14%"),
        ((420, 302, 560, 328), "140.00"),
    ]
    f = extract_record(_doc(), [_page(lines)], [resolve_field("total"), resolve_field("tax")]).fields
    assert f["total"].value == 1140.0
    assert f["tax"].value == 140.0


# ---------------------------------------------------------------- questions over a page with geometry


class BoxEngine:
    """An OCR stand-in that returns lines with the given boxes, in the given (OCR) order."""

    name = "boxes"

    def __init__(self, pages: dict[str, list]) -> None:
        self.pages = pages

    def supports(self, kind: str) -> bool:
        return kind in ("png", "jpeg")

    def read(self, path: Path, *, max_pages: int, password: str | None = None) -> DocumentContent:  # noqa: ARG002
        page = _page(self.pages[path.name])
        blocks = tuple(
            Block(index=k, label="Text", text=ln.text, bbox=ln.bbox, conf=0.97) for k, ln in enumerate(page.lines)
        )
        page = page.model_copy(
            update={
                "width": 2000.0,
                "height": 3500.0,
                "source": "ocr",
                "markdown": "\n".join(ln.text for ln in page.lines),
                "blocks": blocks,
            }
        )
        return DocumentContent(path=str(path), pages=(page,), total_pages=1, engine=self.name)


@pytest.fixture(scope="module")
def boxed(tmp_path_factory):
    import base64

    tmp = tmp_path_factory.mktemp("boxed")
    png = base64.b64decode(  # a 1x1 white PNG; the engine above supplies the page content
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
    )
    for k, name in enumerate(("costa.png", "form.png")):
        (tmp / name).write_bytes(png + bytes(k + 1))  # distinct bytes: the library reuses OCR for identical files
    settings = make_settings(tmp / "home")
    lib = Library(settings, engine=BoxEngine({"costa.png": COSTA, "form.png": FORM}))
    agent = DocumentAgent(settings, library=lib)
    agent.add([tmp / "costa.png", tmp / "form.png"])
    ids = {d.name: d.id for d in agent.library.documents()}
    yield agent, ids
    agent.close()
    lib.close()  # the agent does not close a library it was given


def test_a_question_pairs_a_label_with_its_value_and_cites_the_box(boxed):
    agent, ids = boxed
    res = agent.ask("What is the VAT amount?", doc_ids=[ids["costa.png"]], save=False)
    assert res.answer.split("\n")[0].endswith("8.60"), res.answer
    assert res.sources and res.sources[0].page == 1 and res.sources[0].bbox is not None


def test_a_form_value_outside_the_field_catalog_is_paired_by_row(boxed):
    agent, ids = boxed
    res = agent.ask("What is the membership fee?", doc_ids=[ids["form.png"]], save=False)
    assert "25.00" in res.answer.split("\n\nEvidence")[0], res.answer
    assert "500.00" not in res.answer.split("\n\nEvidence")[0]


def test_a_question_whose_row_holds_competing_values_is_flagged(boxed):
    agent, ids = boxed
    res = agent.ask("How much is the deposit?", doc_ids=[ids["form.png"]], save=False)
    head = res.answer.split("\n\nEvidence")[0]
    assert res.confidence < 0.3 or head.startswith("I couldn't find supporting evidence"), res.answer
