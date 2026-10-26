"""Several tables (or documents) whose headings match the question: list them, or take the one the question names.

The evaluation's ambiguity control: two supplier tables with identical headings. Read through Docling's structure
(fixed DoclingDocuments, see structure_fixtures.py), "What is the company name?" took the first table's cell. The
answer now lists each candidate with where it is; a question naming one company gets that company's row.
"""

from __future__ import annotations

import pytest

pytest.importorskip("docling_core")

from inklight import DocumentAgent  # noqa: E402
from inklight.library import Library  # noqa: E402

from . import structure_fixtures as fx  # noqa: E402
from .conftest import make_settings  # noqa: E402
from .test_structure import PNG, FixedOCR, _fixed_structure  # noqa: E402

FIXTURES = {
    "suppliers.png": fx.suppliers,
    "one-company.png": lambda: fx.suppliers((("Cedar Logistics", "Limited company"),)),
    "other-company.png": lambda: fx.suppliers((("Nile Foods", "Partnership"),)),
}


@pytest.fixture(scope="module", autouse=True)
def _no_model_preload():
    mp = pytest.MonkeyPatch()
    mp.setattr("inklight.structure.docling_run.preload", lambda settings: None)
    yield
    mp.undo()


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("candidates")
    pages = {name: build() for name, build in FIXTURES.items()}
    for k, name in enumerate(pages):
        (tmp / name).write_bytes(PNG + bytes(k + 90))
    settings = make_settings(tmp / "home", structure={"engine": "docling"})
    lib = Library(settings, engine=FixedOCR(pages))
    mp = pytest.MonkeyPatch()
    mp.setattr("inklight.structure.structure_document", _fixed_structure(pages))
    agent = DocumentAgent(settings, library=lib)
    agent.add([tmp / n for n in pages])
    ids = {d.name: d.id for d in agent.library.documents()}
    yield agent, ids
    mp.undo()
    agent.close()
    lib.close()


def _ask(library, docs: list[str], q: str):  # noqa: ANN202
    agent, ids = library
    return agent.ask(q, doc_ids=[ids[d] for d in docs], save=False)


def test_two_tables_with_the_same_headings_are_listed(library):
    res = _ask(library, ["suppliers.png"], "What is the company name?")
    assert "Alpha Ltd" in res.answer and "Beta Ltd" in res.answer, res.answer
    assert len(res.sources) >= 2


@pytest.mark.parametrize(
    ("question", "expect", "not_expected"),
    [
        ("What type of company is Beta Ltd?", "Partnership", "Limited company"),
        ("What is Alpha Ltd's company type?", "Limited company", "Partnership"),
    ],
)
def test_the_named_company_gets_its_own_table(library, question, expect, not_expected):
    head = _ask(library, ["suppliers.png"], question).answer.split("\n\nEvidence:")[0]
    assert expect in head and not_expected not in head, head


def test_the_same_heading_in_two_documents_is_listed(library):
    res = _ask(library, ["one-company.png", "other-company.png"], "What is the company name?")
    assert "Cedar Logistics" in res.answer and "Nile Foods" in res.answer, res.answer
