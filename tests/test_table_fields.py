"""Field extraction reads a field in a table cell where a question would, through one shared routine.

Reproduced on 8e860e6 (the report's section 6.3, synthetic turned registration card, real OCR and structure
models): extract(fields=["registration number"]) returned nothing while "What is the registration number?"
answered 47319 from the table. A field the typed reader leaves empty is now read at its printed label or table cell
(agent/field_reader.py, the routine comparison already used), with that cell as its source, its OCR confidence, its
candidates when several match, and its type checked; never from a nearby passage.

Fixed OCR lines and fixed Docling structure (structure_fixtures.py): Docling's data model is real, its model
inference is not run. The same case on the real models is checked in the browser run, not here.
"""

from __future__ import annotations

import pytest

pytest.importorskip("docling_core")

from inklight import DocumentAgent  # noqa: E402
from inklight.library import Library  # noqa: E402

from . import structure_fixtures as fx  # noqa: E402
from .conftest import make_settings  # noqa: E402
from .test_structure import PNG, FixedOCR, _fixed_structure  # noqa: E402

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
FIXTURES = {
    "card-ar.png": fx.arabic_card,
    "partners-en.png": fx.english_partners,
    "fields-mixed.png": fx.mixed_fields,
    "suppliers.png": fx.suppliers,
    "key-value.png": lambda: fx.key_value(flag_first_row=False),
    "key-value-ar.png": fx.key_value_arabic,
}


@pytest.fixture(scope="module", autouse=True)
def _no_model_preload():
    mp = pytest.MonkeyPatch()
    mp.setattr("inklight.structure.run.preload", lambda settings: None)
    yield
    mp.undo()


@pytest.fixture(scope="module")
def lib(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("table-fields")
    pages = {name: build() for name, build in FIXTURES.items()}
    for k, name in enumerate(pages):
        (tmp / name).write_bytes(PNG + bytes(k + 60))
    settings = make_settings(tmp / "home", structure={"engine": "docling"})
    library = Library(settings, engine=FixedOCR(pages))
    mp = pytest.MonkeyPatch()
    mp.setattr("inklight.structure.structure_document", _fixed_structure(pages))
    agent = DocumentAgent(settings, library=library)
    agent.add([tmp / n for n in pages])
    yield agent, {d.name: d for d in agent.library.documents()}
    mp.undo()
    agent.close()
    library.close()


def _extract(lib, name: str, fields: list[str] | None = None, schema: dict | None = None):  # noqa: ANN202
    agent, docs = lib
    return agent.extract([docs[name].path], fields=fields, schema=schema)[0]


def _answer(lib, name: str, question: str) -> str:
    agent, docs = lib
    return agent.ask(question, doc_ids=[docs[name].id], save=False).answer.split("\n\nEvidence:")[0].strip()


@pytest.mark.parametrize(
    ("name", "field", "question", "expect"),
    [
        ("card-ar.png", "رقم القيد", "ما رقم القيد؟", "47319"),  # Arabic heading over an Arabic-Indic value
        ("fields-mixed.png", "registration number", "What is the registration number?", "47319"),  # mixed language
        ("key-value-ar.png", "رقم القيد", "ما رقم القيد؟", "47319"),  # right-to-left field | value rows
        ("key-value.png", "tax number", "What is the tax number?", "12345"),  # English field | value rows
    ],
)
def test_a_table_cell_is_extracted_as_a_question_reads_it(lib, name, field, question, expect):
    (value,) = _extract(lib, name, [field]).fields.values()
    assert str(value.value).translate(ARABIC_DIGITS) == expect, value  # as printed: Arabic-Indic digits stay
    assert value.method in ("table cell", "label") or value.method.startswith("label"), value.method
    assert value.source is not None and value.source.page == 1 and value.source.bbox is not None, value.source
    answer = _answer(lib, name, question)
    assert expect in answer.translate(ARABIC_DIGITS), answer


def test_the_cell_is_the_source_with_its_ocr_confidence(lib):
    v = _extract(lib, "fields-mixed.png", ["registration number"]).fields["registration_number"]
    assert v.method == "table cell" and v.raw == "47319" and v.verified, v
    assert 0 < v.confidence <= 0.95 and v.source.ocr_conf == pytest.approx(0.95), v  # the fixture's line confidence
    left, top, right, bottom = v.source.bbox
    assert (left, top, right, bottom) == pytest.approx((660, 200, 930, 240), abs=2)  # the "47319" cell, not its row


def test_several_entities_are_candidates_not_a_choice(lib):
    v = _extract(lib, "suppliers.png", ["company name"]).fields["company_name"]
    # Two supplier tables: the reading is one of the candidates, and both are named so the person can choose.
    assert v.value in (None, "Alpha Ltd", "Beta Ltd"), v
    assert "several candidates" in (v.warning or "") and "Alpha Ltd" in v.warning and "Beta Ltd" in v.warning, v
    assert v.value is None or v.confidence < 0.7, v  # shown as a value to check


def test_repeated_rows_for_people_are_candidates(lib):
    # The partners' shares, one per person. The line layout paired the heading with "مدير" from the next column;
    # the table says the heading's cells are 60% and 40%, so neither the wrong cell nor a guess is proposed.
    (value,) = _extract(lib, "card-ar.png", ["نسبة المشاركة"]).fields.values()
    assert value.value is None and "several candidates" in (value.warning or ""), value
    assert "٦٠٪" in value.warning and "٤٠٪" in value.warning and "مدير" in value.warning, value


def test_a_missing_field_stays_missing(lib):
    rec = _extract(lib, "key-value.png", ["expiry date", "invoice number"])
    for value in rec.fields.values():
        assert value.value is None, value  # never the first number nearby ("12345") or a passage


def test_a_value_of_the_wrong_type_is_not_proposed(lib):
    schema = {"fields": [{"name": "department_date", "type": "date", "labels": ["department"]}]}
    v = _extract(lib, "key-value.png", schema=schema).fields["department_date"]
    assert v.value is None and "is not a date" in (v.warning or ""), v


def test_a_typed_reading_that_differs_from_the_cell_is_flagged(lib):
    # The OCR wrapped "Golden Palm Trading / Co." over two lines; the cell holds the whole name.
    v = _extract(lib, "partners-en.png", ["company name"]).fields["company_name"]
    if v.method == "table cell":
        assert v.value == "Golden Palm Trading Co.", v
    else:
        assert "Golden Palm Trading Co." in (v.warning or "") and "check" in v.warning, v


def test_extraction_does_not_run_a_conversational_task(lib, monkeypatch):
    agent, docs = lib

    def no_ask(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("extraction must not call ask() per field")

    monkeypatch.setattr(agent, "ask", no_ask)
    monkeypatch.setattr(agent, "run_plan", no_ask)
    agent.extract([docs["fields-mixed.png"].path], fields=["registration number", "company name"])
    review = agent.open_review(docs["fields-mixed.png"].id, ["registration number"], reviewer="Test reviewer")
    assert review is not None
