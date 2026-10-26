"""The beta's honest outcomes: every result says what it is, candidates come back to choose from, a named field is
compared document by document, and a run of field names is never an answer.

Fixed OCR lines stand in for Indra (no OCR model); the questions go through the public ``DocumentAgent.ask``.
Names and numbers are invented.
"""

from __future__ import annotations

import pytest

from inklight import DocumentAgent
from inklight.library import Library
from inklight.schemas import OUTCOME_LABELS

from .conftest import make_settings
from .test_eval_regressions import PNG, LinesEngine

PAGES = {
    "card.png": [[((100, 100, 300, 120), "Company name:"), ((320, 100, 600, 120), "Cedar Logistics"),
                  ((100, 130, 300, 150), "Registration number:"), ((320, 130, 600, 150), "760413")]],
    "register.png": [[((100, 60, 600, 90), "COMMERCIAL REGISTER EXTRACT"),
                      ((100, 120, 400, 142), "Registration number: 760413"),
                      ((100, 150, 400, 172), "Valid until: 3 April 2027")]],
    "register-other.png": [[((100, 60, 600, 90), "COMMERCIAL REGISTER EXTRACT"),
                            ((100, 120, 400, 142), "Registration number: 760999")]],
    "letter.png": [[((100, 60, 700, 90), "Letter dated 3 March 2024 from the Director"),
                    ((100, 120, 900, 142), "The committee will meet in Cairo to review the annual budget."),
                    ((100, 150, 900, 172), "The meeting is scheduled for the second week of April.")]],
    "two-cards.png": [[((100, 100, 300, 120), "Company name:"), ((320, 100, 600, 120), "Cedar Logistics")],
                      [((100, 100, 300, 120), "Company name:"), ((320, 100, 600, 120), "Nile Foods")]],
}  # fmt: skip


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("beta")
    for k, name in enumerate(PAGES):
        (tmp / name).write_bytes(PNG + bytes(k + 120))
    settings = make_settings(tmp / "home")
    lib = Library(settings, engine=LinesEngine(PAGES))
    agent = DocumentAgent(settings, library=lib)
    agent.add([tmp / n for n in PAGES])
    ids = {d.name: d.id for d in agent.library.documents()}
    yield agent, ids
    agent.close()
    lib.close()


def _ask(library, docs: list[str], q: str):  # noqa: ANN202
    agent, ids = library
    return agent.ask(q, doc_ids=[ids[d] for d in docs], save=False)


def test_every_outcome_has_a_label():
    assert set(OUTCOME_LABELS) == {
        "extracted", "proposed", "supported", "partial", "missing_evidence", "ambiguous", "unsupported", "failed",
    }  # fmt: skip


def test_a_value_at_its_printed_label_is_a_supported_answer(library):
    res = _ask(library, ["card.png"], "What is the company name?")
    assert "Cedar Logistics" in res.answer
    assert res.outcome == "supported" and res.sources


def test_a_missing_value_is_missing_evidence(library):
    res = _ask(library, ["card.png"], "What is the expiry date of the tax card?")
    assert res.outcome in ("missing_evidence", "proposed"), (res.outcome, res.answer)
    assert res.outcome != "supported"


def test_a_sentence_picked_from_prose_is_only_proposed(library):
    res = _ask(library, ["letter.png"], "Where will the committee meet?")
    assert res.outcome in ("proposed", "missing_evidence"), (res.outcome, res.answer)


def test_several_candidates_come_back_to_choose_from(library):
    res = _ask(library, ["two-cards.png"], "What is the company name?")
    assert res.outcome == "ambiguous", res.answer
    values = {c.value for c in res.candidates}
    assert values == {"Cedar Logistics", "Nile Foods"}, values
    assert all(c.source.page in (1, 2) and c.source.bbox for c in res.candidates)


def test_search_results_are_shown_as_extracted(library):
    res = _ask(library, ["letter.png", "card.png"], "Find the paragraph about the annual budget")
    assert res.outcome == "extracted", (res.outcome, res.intent)


@pytest.mark.parametrize(
    ("docs", "verdict"),
    [
        (["card.png", "register.png"], "matches"),
        (["register.png", "register-other.png"], "differs"),
        (["card.png", "letter.png"], "cannot determine"),
    ],
)
def test_a_named_field_is_compared_document_by_document(library, docs, verdict):
    res = _ask(library, docs, "Compare the registration number in these two documents")
    assert res.comparison is not None, res.answer
    assert res.comparison["verdict"] == verdict, res.answer
    assert len(res.comparison["values"]) == 2
    assert f"Result: {verdict}" in res.answer
    assert res.outcome == ("partial" if verdict == "cannot determine" else "proposed")
    for v in res.comparison["values"]:
        if v["status"] == "found":
            assert v["source"]["page"] == 1 and v["value"]


def test_an_arabic_field_comparison_names_the_field(library):
    res = _ask(library, ["card.png", "register.png"], "قارن رقم التسجيل في المستندين")
    assert res.comparison is not None and res.comparison["field"] == "رقم التسجيل", res.answer


def test_a_comparison_without_a_named_field_is_only_a_text_comparison(library):
    res = _ask(library, ["register.png", "register-other.png"], "Compare these two documents")
    assert res.comparison is None
    assert res.answer.startswith("Text comparison only"), res.answer
    assert res.outcome == "extracted"


MERGED_PAGE = {
    "merged.png": [[
        ((1700, 300, 2000, 320), "(ج) اسماء والقاب الشركاء"),
        ((1700, 330, 2000, 350), "(د) اسماء اعضاء مجلس الادارة"),
        ((1700, 360, 2000, 380), "(ه) اسم مدير الفرع الرئيسى"),
    ]]
}  # fmt: skip


def test_a_run_of_field_names_is_not_an_answer(tmp_path):
    """Docling merges a register's stacked header cells into one block; that block is not a value."""
    from inklight.schemas import Block, DocumentContent, PageContent, TextLine

    class MergedEngine(LinesEngine):
        def read(self, path, *, max_pages, password=None):  # noqa: ANN001, ANN202, ARG002
            raw = self.pages[path.name][0]
            lines = tuple(TextLine(text=t, bbox=tuple(map(float, b)), conf=0.95) for b, t in raw)
            merged = " ".join(x.text for x in lines)
            block = Block(index=0, label="Text", text=merged, bbox=(1700.0, 300.0, 2000.0, 380.0), conf=0.95)
            page = PageContent(number=1, width=2338.0, height=1653.0, source="ocr", lines=lines, blocks=(block,),
                               markdown=merged)  # fmt: skip
            return DocumentContent(path=str(path), pages=(page,), total_pages=1, engine=self.name)

    (tmp_path / "merged.png").write_bytes(PNG)
    settings = make_settings(tmp_path / "home")
    with DocumentAgent(settings, library=Library(settings, engine=MergedEngine(MERGED_PAGE))) as agent:
        agent.add([tmp_path / "merged.png"])
        doc = agent.library.documents()[0].id
        res = agent.ask("من هم الشركاء واعضاء مجلس الادارة؟", doc_ids=[doc], save=False)
    assert res.outcome == "missing_evidence", res.answer
    assert "run of field names" in res.answer and "page 1" in res.answer, res.answer
    assert res.sources and res.sources[0].page == 1  # the place is kept for review


def test_the_cli_shows_the_outcome_and_names_a_missing_file(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from inklight.cli import app as cli_app

    monkeypatch.setenv("INKLIGHT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("INKLIGHT_MODELS__BRAIN", "rules")
    runner = CliRunner()
    missing = runner.invoke(cli_app, ["ask", str(tmp_path / "nope.pdf"), "What is the company name?"])
    assert missing.exit_code != 0 and "File not found" in missing.output, missing.output
    card = tmp_path / "card.txt"
    card.write_text("Company name: Cedar Logistics\nRegistration number: 760413\n", encoding="utf-8")
    r = runner.invoke(cli_app, ["ask", str(card), "What is the registration number?"])
    assert r.exit_code == 0, r.output
    assert "Outcome:" in r.output and "760413" in r.output, r.output


# -- after the independent review of the beta: labels in review, missing values, doubtful comparisons, exports ------

BILINGUAL = {
    "bilingual.png": [[
        ((300, 290, 380, 315), "Field"), ((560, 290, 640, 325), "البيان"), ((990, 290, 1180, 322), "Value"),
        ((190, 367, 430, 399), "Company name"),
        ((530, 365, 1450, 401), "شركة النخيل الذهبي للتجارة / Golden Palm Trading Co. اسم الشركة"),
        ((190, 443, 494, 476), "Registration number"), ((520, 444, 645, 478), "رقم القيد"),
        ((700, 442, 800, 474), "47319"),
    ]],
    "register-low.png": [[((100, 60, 600, 90), "COMMERCIAL REGISTER EXTRACT"),
                          ((100, 120, 400, 142), "Registration number: 47819")]],
    "register-ok.png": [[((100, 60, 600, 90), "COMMERCIAL REGISTER EXTRACT"),
                         ((100, 120, 400, 142), "Registration number: 47319")]],
}  # fmt: skip


class _LowConfEngine(LinesEngine):
    """Indra's stand-in, with one document read at low confidence."""

    def read(self, path, *, max_pages, password=None):  # noqa: ANN001, ANN202
        content = super().read(path, max_pages=max_pages, password=password)
        if path.name != "register-low.png":
            return content
        pages = tuple(
            p.model_copy(update={"lines": tuple(x.model_copy(update={"conf": 0.55}) for x in p.lines)})
            for p in content.pages
        )
        return content.model_copy(update={"pages": pages})


@pytest.fixture(scope="module")
def bilingual(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("bilingual")
    for k, name in enumerate(BILINGUAL):
        (tmp / name).write_bytes(PNG + bytes(k + 200))
    settings = make_settings(tmp / "home")
    lib = Library(settings, engine=_LowConfEngine(BILINGUAL))
    agent = DocumentAgent(settings, library=lib)
    agent.add([tmp / n for n in BILINGUAL])
    yield agent, {d.name: d.id for d in agent.library.documents()}, tmp
    agent.close()
    lib.close()


def test_a_label_is_never_proposed_as_a_number_field_in_review(bilingual):
    agent, ids, _ = bilingual
    review = agent.open_review(ids["bilingual.png"], ["registration number", "company name"], reviewer="Tester")
    got = {f.field: f for f in review.fields}
    assert got["registration_number"].predicted != "رقم القيد", got["registration_number"]
    assert got["registration_number"].predicted in (None, "47319")
    # A value in a bilingual row may carry the label in the other language: it is flagged, not presented as clean.
    assert got["company_name"].flagged and "Arabic and Latin" in (got["company_name"].warning or "")


def test_an_arabic_field_name_can_be_extracted(bilingual):
    agent, ids, tmp = bilingual
    record = agent.extract([tmp / "bilingual.png"], fields=["رقم القيد"])[0]
    assert list(record.fields) == ["رقم_القيد"]


def test_a_number_question_answered_without_digits_is_missing_evidence(library):
    res = _ask(library, ["letter.png"], "What is the budget amount?")
    assert res.outcome == "missing_evidence", (res.outcome, res.answer)


def test_a_difference_resting_on_a_low_confidence_reading_cannot_be_determined(bilingual):
    agent, ids, _ = bilingual
    res = agent.ask(
        "Compare the registration number in these documents",
        doc_ids=[ids["register-low.png"], ids["register-ok.png"]],
        save=False,
    )
    assert res.comparison is not None, res.answer
    assert res.comparison["verdict"] == "cannot determine", res.answer
    assert res.warnings and any("register-low.png" in w for w in res.warnings), res.warnings
    assert "low confidence" in res.answer


def test_a_superseded_review_is_marked_in_the_export(bilingual):
    agent, ids, _ = bilingual
    doc = ids["register-ok.png"]
    for _ in range(2):
        r = agent.open_review(doc, ["registration number"], reviewer="Tester")
        agent.reviews.decide(r.id, "registration_number", reviewer="Tester", action="accepted")
        agent.reviews.approve(r.id, reviewer="Tester")
    import csv
    import io

    rows = [x for x in csv.DictReader(io.StringIO(agent.reviews.export("csv", actor="Tester")))
            if x["document"] == "register-ok.png"]  # fmt: skip
    assert sorted(x["superseded"] for x in rows) == ["False", "True"], rows
    assert all(x["source_bbox"] for x in rows)
