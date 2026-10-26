"""Regressions from the agent-run evaluation (evaluation/AGENT_EVALUATION.md), reproduced on synthetic pages.

Each page copies the mechanism of a demonstrated failure, not its document: the geometry of a register's header
column of numbered labels, two supplier tables with identical headings, two documents of different types passed
together. Names and numbers are invented. Questions go through the public ``DocumentAgent.ask``.

- A form label is never returned as the value of another (or its own) label; when the value cannot be established
  the answer declines and says where the label is.
- When several entities, tables, pages or documents carry the field asked about, the answer lists them (or says
  which one it chose because the question named it); it does not silently take the first.
- Documents the user passed are not dropped because the request describes them with a type word.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from inklight import DocumentAgent
from inklight.library import Library
from inklight.schemas import Block, DocumentContent, PageContent, TextLine

from .conftest import make_settings

Box = tuple[float, float, float, float]

# A register's header column, right to left: numbered field names stacked in one cell, the column number under them,
# then the data row (geometry as Indra reads a scanned Egyptian commercial register; text invented).
REGISTER_AR = [
    ((786, 110, 1448, 140), "مستخرج من السجل التجارى رقم: ١٢٣٤٥ (شركة توصية بسيطة – مركز عام)"),
    ((1869, 244, 1976, 264), "١-الأسم التجارى"),
    ((1864, 271, 1999, 292), "(١) -السمة التجارية"),
    ((1074, 241, 1172, 263), "(١) نوع التجارة"),
    ((1874, 326, 1971, 347), "١- نوع الشركة"),
    ((1750, 356, 2003, 376), "(ب) ٢- عنوان الشركة أو اسمها او اسم"),
    ((1865, 382, 1976, 402), "الجمعية التعاونية"),
    ((1856, 412, 1971, 431), "٣- السمة التجارية"),
    ((1837, 499, 1866, 520), "(٢)"),
    ((1103, 496, 1133, 520), "(٤)"),
    ((1700, 567, 2004, 590), "النجمة الزرقاء للتوريدات"),
    ((878, 564, 1164, 588), "توريد أدوات مكتبية"),
]
# The same mechanism in English: a numbered list of field names with no values beside them, one filled field.
NUMBERED_EN = [
    ((100, 60, 600, 90), "APPLICATION FOR REGISTRATION"),
    ((100, 120, 330, 142), "1. Company name"),
    ((100, 150, 330, 172), "2. Company type"),
    ((100, 180, 330, 202), "3. Head office address"),
    ((100, 210, 600, 232), "4. Registration number: 31907"),
]
# Values that look like their labels are still values.
LOOKALIKE = [
    ((100, 120, 300, 142), "Company name:"),
    ((320, 120, 600, 142), "Name Holdings"),
    ((100, 150, 300, 172), "Company type:"),
    ((320, 150, 600, 172), "Limited company"),
    ((100, 180, 300, 202), "Registration"),
    ((100, 204, 300, 226), "number:"),
    ((320, 204, 600, 226), "77881"),
]
# Two supplier tables with identical headings, as plain lines (structure off).
SUPPLIERS = [
    ((50, 40, 600, 70), "Supplier registration summary"),
    ((50, 100, 200, 120), "Supplier 1"),
    ((50, 130, 240, 150), "Company name"),
    ((260, 130, 460, 150), "Company type"),
    ((50, 160, 240, 180), "Alpha Ltd"),
    ((260, 160, 460, 180), "Limited company"),
    ((50, 230, 200, 250), "Supplier 2"),
    ((50, 260, 240, 280), "Company name"),
    ((260, 260, 460, 280), "Company type"),
    ((50, 290, 240, 310), "Beta Ltd"),
    ((260, 290, 460, 310), "Partnership"),
]
CARD_ONE = [((100, 100, 300, 120), "Company name:"), ((320, 100, 600, 120), "Cedar Logistics")]
CARD_TWO = [((100, 100, 300, 120), "Company name:"), ((320, 100, 600, 120), "Nile Foods")]
CONTRACT = [
    ((100, 60, 600, 90), "SERVICE AGREEMENT"),
    ((100, 120, 900, 142), "This agreement is made on 3 March 2024 between Cedar Logistics and Nile Foods."),
    ((100, 150, 900, 172), "The parties agree that this contract is governed by the laws of Egypt."),
    ((100, 180, 900, 202), "Registration number: 760413"),
]
REGISTER_EN = [
    ((100, 60, 600, 90), "COMMERCIAL REGISTER EXTRACT"),
    ((100, 120, 400, 142), "Registration number: 760413"),
    ((100, 150, 400, 172), "Valid until: 3 April 2027"),
]
PAGES: dict[str, list[list[tuple[Box, str]]]] = {
    "register-ar.png": [REGISTER_AR],
    "numbered-en.png": [NUMBERED_EN],
    "lookalike.png": [LOOKALIKE],
    "suppliers.png": [SUPPLIERS],
    "card-one.png": [CARD_ONE],
    "card-two.png": [CARD_TWO],
    "two-pages.png": [CARD_ONE, CARD_TWO],
    "contract.png": [CONTRACT],
    "register-en.png": [REGISTER_EN],
}
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC")


class LinesEngine:
    """Stands in for Indra: fixed lines with boxes, one list per page."""

    name = "lines"

    def __init__(self, pages: dict[str, list[list[tuple[Box, str]]]]) -> None:
        self.pages = pages

    def supports(self, kind: str) -> bool:
        return kind in ("png", "jpeg")

    def read(self, path: Path, *, max_pages: int, password: str | None = None) -> DocumentContent:  # noqa: ARG002
        out = []
        for n, raw in enumerate(self.pages[path.name][:max_pages], 1):
            lines = tuple(TextLine(text=t, bbox=tuple(map(float, b)), conf=0.95) for b, t in raw)
            blocks = tuple(
                Block(index=k, label="Text", text=x.text, bbox=x.bbox, conf=0.95) for k, x in enumerate(lines)
            )
            out.append(
                PageContent(
                    number=n,
                    width=2338.0,
                    height=1653.0,
                    source="ocr",
                    lines=lines,
                    blocks=blocks,
                    markdown="\n".join(x.text for x in lines),
                )  # fmt: skip
            )
        return DocumentContent(path=str(path), pages=tuple(out), total_pages=len(out), engine=self.name)


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("regressions")
    for k, name in enumerate(PAGES):
        (tmp / name).write_bytes(PNG + bytes(k + 60))
    settings = make_settings(tmp / "home")
    lib = Library(settings, engine=LinesEngine(PAGES))
    agent = DocumentAgent(settings, library=lib)
    agent.add([tmp / n for n in PAGES])
    ids = {d.name: d.id for d in agent.library.documents()}
    yield agent, ids, tmp
    agent.close()
    lib.close()


def _ask(library, docs: list[str], q: str):  # noqa: ANN202
    agent, ids, _ = library
    return agent.ask(q, doc_ids=[ids[d] for d in docs], save=False)


def _head(res) -> str:  # noqa: ANN001
    return res.answer.split("\n\nEvidence:")[0]


def _declined(res) -> bool:  # noqa: ANN001
    return res.answer.startswith(("I couldn't find", "I could not find"))


# ---------------------------------------------------------------- A. a form label is not a value


@pytest.mark.parametrize(
    ("question", "labels"),
    [
        ("ما نوع الشركة؟", ["عنوان الشركة", "الجمعية التعاونية", "السمة التجارية"]),
        ("ما اسم الشركة؟", ["عنوان الشركة", "نوع الشركة", "السمة التجارية"]),
    ],
)
def test_a_numbered_form_label_is_not_returned_as_a_value_arabic(library, question, labels):
    res = _ask(library, ["register-ar.png"], question)
    head = _head(res)
    if _declined(res):  # it may name the field it could not read, and must say where it is
        assert "page 1" in res.answer, res.answer
        return
    assert not any(label in head for label in labels), res.answer
    assert "النجمة الزرقاء" in head or "توصية بسيطة" in head, res.answer


@pytest.mark.parametrize(
    "question", ["What is the company type?", "What is the company name?", "What is the head office address?"]
)
def test_a_numbered_form_label_is_not_returned_as_a_value_english(library, question):
    res = _ask(library, ["numbered-en.png"], question)
    assert _declined(res) and "page 1" in res.answer, res.answer
    assert "31907" not in res.answer, res.answer


def test_a_filled_field_in_a_numbered_list_is_still_answered(library):
    res = _ask(library, ["numbered-en.png"], "What is the registration number?")
    assert "31907" in _head(res), res.answer


@pytest.mark.parametrize(
    ("question", "expect"),
    [
        ("What is the company name?", "Name Holdings"),
        ("What is the company type?", "Limited company"),
        ("What is the registration number?", "77881"),  # a label wrapped over two lines
    ],
)
def test_a_value_that_resembles_its_label_is_kept(library, question, expect):
    res = _ask(library, ["lookalike.png"], question)
    assert expect in _head(res), res.answer


# ---------------------------------------------------------------- B. several candidates


def test_two_tables_with_the_same_headings_are_both_listed(library):
    res = _ask(library, ["suppliers.png"], "What is the company name?")
    assert "Alpha Ltd" in res.answer and "Beta Ltd" in res.answer, res.answer


@pytest.mark.parametrize(
    ("question", "expect", "not_expected"),
    [
        ("What type of company is Beta Ltd?", "Partnership", "Limited company"),
        ("What is Alpha Ltd's company type?", "Limited company", "Partnership"),
        ("What is the company name of Supplier 2?", "Beta Ltd", "Alpha Ltd"),  # the follow-up that names one
    ],
)
def test_a_question_naming_one_candidate_gets_that_one(library, question, expect, not_expected):
    head = _head(_ask(library, ["suppliers.png"], question))
    assert expect in head and not_expected not in head, head


def test_the_same_field_in_two_documents_is_listed_not_chosen(library):
    res = _ask(library, ["card-one.png", "card-two.png"], "What is the company name?")
    assert "Cedar Logistics" in res.answer and "Nile Foods" in res.answer, res.answer


def test_the_same_field_on_two_pages_is_listed_not_chosen(library):
    res = _ask(library, ["two-pages.png"], "What is the company name?")
    assert "Cedar Logistics" in res.answer and "Nile Foods" in res.answer, res.answer


# ---------------------------------------------------------------- C. the documents the user passed


@pytest.mark.parametrize(
    "request_text",
    [
        "Compare the registration number in the contract with the commercial register.",
        "قارن بين رقم السجل في العقد ومستخرج السجل التجاري",
        "Compare these two contracts",  # a type word that describes rather than restricts
    ],
)
def test_explicitly_passed_documents_are_not_dropped_by_a_type_word(library, request_text):
    res = _ask(library, ["contract.png", "register-en.png"], request_text)
    assert "at least two documents" not in res.answer, res.answer
    assert res.state.value != "failed", res.answer
    inspected = next(s for s in res.trace if s.tool == "inspect_documents")
    assert inspected.summary.startswith("2 documents"), inspected.summary


def test_an_explicit_restriction_still_narrows(library):
    res = _ask(library, ["contract.png", "register-en.png", "card-one.png"], "Summarize only the contracts")
    inspected = next(s for s in res.trace if s.tool == "inspect_documents")
    assert inspected.summary.startswith("1 documents"), inspected.summary


def test_files_given_on_the_command_line_are_the_users_choice(tmp_path, monkeypatch):
    """The CLI runs ``inklight ask FILE FILE "request"`` through run_plan, not ask: it must keep both files too."""
    import json

    from typer.testing import CliRunner

    from inklight.cli import app as cli_app

    monkeypatch.setenv("INKLIGHT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("INKLIGHT_MODELS__BRAIN", "rules")
    contract = tmp_path / "contract.txt"
    contract.write_text(
        "SERVICE AGREEMENT\nThis contract is made on 3 March 2024 between Cedar Logistics and Nile Foods.\n"
        "The parties agree that this agreement is governed by the laws of Egypt.\nRegistration number: 760413\n",
        encoding="utf-8",
    )
    register = tmp_path / "register.txt"
    register.write_text(
        "COMMERCIAL REGISTER EXTRACT\nRegistration number: 760413\nValid until: 3 April 2027\n", encoding="utf-8"
    )
    request = "Compare the registration number in the contract with the commercial register."
    r = CliRunner().invoke(cli_app, ["ask", str(contract), str(register), request, "--json"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.output[r.output.index("{") :])
    inspected = next(s for s in data["trace"] if s["tool"] == "inspect_documents")
    assert inspected["summary"].startswith("2 documents"), inspected
    assert "at least two documents" not in data["answer"], data["answer"]
