"""Questions that name a label are answered with the value printed beside or below that label.

Forms, infoboxes and receipts print "MANUFACTURER:  B & W", "Elevation  99 m", "Area code (+20) 97" or, in Arabic,
"المساحة 375 كيلومتر مربع". A question naming the label ("Who is the manufacturer?", "ما مساحة أسوان؟") is answered
from that label's row on the page, with page and box. A label with nothing beside it (a blank "LIST PRICE:") is
declined with that reason; prose lines are not labels. Cases follow fresh4 (development data since its first run).
"""

import base64
from pathlib import Path

import pytest

from inklight import DocumentAgent
from inklight.library import Library
from inklight.schemas import Block, DocumentContent, PageContent, TextLine

from .conftest import make_settings

FORM = [  # FUNSD-style form: labels on the left, typed values to their right, some fields blank
    ((280, 85, 520, 110), "NEW COMPETITIVE PRODUCTS"),
    ((90, 140, 220, 162), "REPORTED BY:"),
    ((235, 136, 580, 158), "BOBBY MILLS, REGIONAL SALES MGR."),
    ((130, 190, 185, 210), "DATE:"),
    ((190, 184, 240, 204), "8/10/90"),
    ((245, 190, 295, 210), "TIME:"),
    ((90, 280, 230, 300), "MANUFACTURER:"),
    ((245, 272, 300, 292), "B & W"),
    ((90, 325, 230, 345), "BRAND NAME:"),
    ((235, 322, 500, 342), "VICEROY KING BOX"),
    ((90, 470, 230, 490), "LIST PRICE:"),
    ((90, 520, 230, 540), "SIZE OR SIZES:"),
]
INFOBOX = [  # Wikipedia infobox (English) and a line of body prose
    ((40, 100, 160, 120), "Population (2024)"),
    ((40, 124, 260, 144), "• Total 370,000"),
    ((40, 150, 300, 170), "Elevation [1] 99 m (325 ft)"),
    ((40, 176, 240, 196), "Area code (+20) 97"),
    ((40, 202, 110, 222), "Area"),
    ((40, 226, 260, 246), "• Total 375.39 km2"),
    ((40, 400, 900, 420), "The population of the city grew quickly after the dam was completed in 1970 and"),
]
INFOBOX_AR = [  # Arabic infobox: label on the right, value to its left on the same line or row
    ((500, 100, 760, 120), "المساحة 375 كيلومتر مربع"),
    ((560, 130, 760, 150), "الرمز الهاتفي 20+ 97"),
    ((600, 160, 760, 180), "الكثافة السكانية"),
    ((420, 160, 560, 180), "1071 نسمة/كم²"),
]
RECEIPT = [
    ((40, 100, 200, 120), "Sub-Total"),
    ((300, 100, 360, 120), "133"),
    ((40, 140, 120, 160), "tax"),
    ((300, 140, 380, 160), "18.62"),
    ((40, 180, 160, 200), "12% Service:"),
    ((300, 180, 380, 200), "15.96"),
    ((40, 220, 140, 240), "Total"),
    ((300, 220, 390, 240), "167.58"),
]
PAGES = {"form.png": FORM, "infobox.png": INFOBOX, "infobox-ar.png": INFOBOX_AR, "receipt.png": RECEIPT}


class BoxEngine:
    name = "boxes"

    def __init__(self, pages: dict) -> None:
        self.pages = pages

    def supports(self, kind: str) -> bool:
        return kind in ("png", "jpeg")

    def read(self, path: Path, *, max_pages: int, password: str | None = None) -> DocumentContent:  # noqa: ARG002
        lines = tuple(TextLine(text=t, bbox=tuple(map(float, b)), conf=0.95) for b, t in self.pages[path.name])
        blocks = tuple(
            Block(index=k, label="Text", text=ln.text, bbox=ln.bbox, conf=0.95) for k, ln in enumerate(lines)
        )
        page = PageContent(
            number=1,
            width=1000.0,
            height=800.0,
            source="ocr",
            lines=lines,
            blocks=blocks,
            markdown="\n".join(ln.text for ln in lines),
        )
        return DocumentContent(path=str(path), pages=(page,), total_pages=1, engine=self.name)


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("labels")
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
    )
    for k, name in enumerate(PAGES):
        (tmp / name).write_bytes(png + bytes(k + 1))
    settings = make_settings(tmp / "home")
    lib = Library(settings, engine=BoxEngine(PAGES))
    agent = DocumentAgent(settings, library=lib)
    agent.add([tmp / n for n in PAGES])
    ids = {d.name: d.id for d in agent.library.documents()}
    yield agent, ids
    agent.close()
    lib.close()


def _ask(library, doc: str, q: str):  # noqa: ANN202
    agent, ids = library
    return agent.ask(q, doc_ids=[ids[doc]], save=False)


def _head(res) -> str:  # noqa: ANN001
    return res.answer.split("\n\nEvidence:")[0]


@pytest.mark.parametrize(
    ("doc", "question", "expect"),
    [
        ("form.png", "Who is the manufacturer?", "B & W"),
        ("form.png", "Who reported it?", "BOBBY MILLS"),
        ("form.png", "What is the brand name?", "VICEROY"),
        ("infobox.png", "What is the population of Aswan?", "370,000"),
        ("infobox.png", "What is the elevation of Aswan?", "99 m"),
        ("infobox.png", "What is the area code of Aswan?", "97"),
        ("infobox.png", "What is the total area of Aswan?", "375.39"),
        ("infobox-ar.png", "ما مساحة أسوان؟", "375"),
        ("infobox-ar.png", "ما الرمز الهاتفي لأسوان؟", "97"),
        ("infobox-ar.png", "ما الكثافة السكانية في أسوان؟", "1071"),
        ("receipt.png", "What is the subtotal?", "133"),
        ("receipt.png", "What is the service charge?", "15.96"),
    ],
)
def test_a_question_naming_a_label_gets_the_value_beside_it(library, doc, question, expect):
    res = _ask(library, doc, question)
    assert expect in _head(res), res.answer
    assert res.sources and res.sources[0].bbox is not None and res.sources[0].page == 1


def test_a_blank_field_is_declined_with_its_reason(library):
    res = _ask(library, "form.png", "What is the list price?")
    assert res.answer.startswith("I couldn't find supporting evidence"), res.answer
    assert any("blank" in c or "nothing beside" in c for c in res.checks), res.checks


def test_prose_is_not_a_label(library):
    """A body sentence that mentions "population" does not answer as a label; the infobox row does."""
    res = _ask(library, "infobox.png", "What is the population of Aswan?")
    assert "1970" not in _head(res)


# From the code review of the first version.
REVIEW = {
    # a dense receipt: the next row's price is closer in x than the label's own value
    "dense.png": [
        ((40, 100, 120, 118), "Total"),
        ((400, 101, 470, 119), "70.00"),
        ((40, 117, 160, 135), "Change"),
        ((300, 114, 360, 132), "5.00"),
    ],
    # a letter header: "To:", "Cc:" and "Date:" do not make it a form, so "Cc:" alone is not a blank field
    "letter.png": [
        ((40, 40, 120, 60), "To:"),
        ((130, 40, 400, 60), "Ministry of Finance"),
        ((40, 70, 120, 90), "Cc:"),
        ((40, 100, 120, 120), "Date:"),
        ((130, 100, 300, 120), "3 March 2025"),
    ],
    # a bullet before an inline label and value
    "bullet.png": [((40, 40, 300, 60), "• Elevation 99 m (325 ft)")],
}


@pytest.fixture(scope="module")
def review_library(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("labels-review")
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
    )
    for k, name in enumerate(REVIEW):
        (tmp / name).write_bytes(png + bytes(k + 10))
    settings = make_settings(tmp / "home")
    lib = Library(settings, engine=BoxEngine(REVIEW))
    agent = DocumentAgent(settings, library=lib)
    agent.add([tmp / n for n in REVIEW])
    ids = {d.name: d.id for d in agent.library.documents()}
    yield agent, ids
    agent.close()
    lib.close()


def test_the_value_on_the_labels_own_row_beats_a_closer_cell_of_the_next_row(review_library):
    res = _ask(review_library, "dense.png", "What is the total?")
    assert "70.00" in _head(res) and "5.00" not in _head(res), res.answer


def test_a_letter_header_label_alone_is_not_declined_as_a_blank_field(review_library):
    res = _ask(review_library, "letter.png", "Who is copied?")
    assert not res.answer.startswith("I couldn't find supporting evidence for a value"), res.answer


def test_a_bullet_does_not_hide_an_inline_value(review_library):
    assert "99 m" in _head(_ask(review_library, "bullet.png", "What is the elevation?"))
