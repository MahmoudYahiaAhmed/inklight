"""A label's qualifier and the person or section it belongs to are part of what a question asks.

"What is the shipping address?" is not answered from "Billing Address:", "What is the delivery date?" not from
"Invoice Date:", and "What is Alice's salary?" not from the "Salary:" printed under Bob. Repeated identical labels
are told apart by the person or section heading they sit under, or the answer says the question is ambiguous.
These go through the public ``DocumentAgent.ask`` with OCR geometry fixed by the test engine, so every answering
path (role, field shortcut, label, reader/rules and the typed check) is exercised.
"""

import base64
from pathlib import Path

import pytest

from inklight import DocumentAgent
from inklight.library import Library
from inklight.schemas import Block, DocumentContent, PageContent, TextLine

from .conftest import make_settings

BOTH_ADDRESSES = [
    ((40, 40, 300, 70), "ACME SUPPLIES LTD"),
    ((40, 120, 220, 140), "Billing Address:"),
    ((240, 120, 520, 140), "12 King Street, Leeds"),
    ((40, 160, 220, 180), "Shipping Address:"),
    ((240, 160, 520, 180), "7 Harbour Road, Hull"),
    ((40, 220, 220, 240), "Amount Due:"),
    ((240, 220, 340, 240), "420.00"),
]
BILLING_ONLY = [
    ((40, 40, 300, 70), "ACME SUPPLIES LTD"),
    ((40, 120, 220, 140), "Billing Address:"),
    ((240, 120, 520, 140), "12 King Street, Leeds"),
    ((40, 220, 220, 240), "Amount Due:"),
    ((240, 220, 340, 240), "420.00"),
]
BOTH_DATES = [
    ((40, 40, 300, 70), "ACME SUPPLIES LTD"),
    ((40, 120, 200, 140), "Invoice Date:"),
    ((220, 120, 400, 140), "3 March 2025"),
    ((40, 160, 200, 180), "Delivery Date:"),
    ((220, 160, 400, 180), "17 March 2025"),
    ((40, 220, 200, 240), "Amount Due:"),
    ((220, 220, 320, 240), "420.00"),
]
INVOICE_DATE_ONLY = [
    ((40, 40, 300, 70), "ACME SUPPLIES LTD"),
    ((40, 120, 200, 140), "Invoice Date:"),
    ((220, 120, 400, 140), "3 March 2025"),
    ((40, 220, 200, 240), "Amount Due:"),
    ((220, 220, 320, 240), "420.00"),
]
PAYROLL = [  # two employees, each with the same "Salary:" label under their own name
    ((40, 40, 300, 70), "PAYROLL SUMMARY"),
    ((40, 120, 180, 140), "Employee:"),
    ((200, 120, 400, 140), "Alice Martin"),
    ((40, 150, 180, 170), "Salary:"),
    ((200, 150, 320, 170), "52,000"),
    ((40, 230, 180, 250), "Employee:"),
    ((200, 230, 400, 250), "Bob Turner"),
    ((40, 260, 180, 280), "Salary:"),
    ((200, 260, 320, 280), "61,000"),
]
PAYROLL_COLUMNS = [  # the same, as two side-by-side sections headed by the person's name
    ((40, 40, 300, 70), "PAYROLL SUMMARY"),
    ((40, 120, 260, 140), "Alice Martin"),
    ((40, 150, 140, 170), "Salary:"),
    ((150, 150, 260, 170), "52,000"),
    ((520, 120, 740, 140), "Bob Turner"),
    ((520, 150, 620, 170), "Salary:"),
    ((630, 150, 740, 170), "61,000"),
]
BONUS = [  # a field printed once, in Bob's section only
    *PAYROLL,
    ((40, 290, 180, 310), "Bonus:"),
    ((200, 290, 320, 310), "500"),
]
DUE_DATE_ONLY = [
    ((40, 40, 300, 70), "ACME SUPPLIES LTD"),
    ((40, 120, 200, 140), "Due Date:"),
    ((220, 120, 400, 140), "3 March 2025"),
    ((40, 220, 200, 240), "Amount Due:"),
    ((220, 220, 320, 240), "420.00"),
]
ONE_ADDRESS = [
    ((40, 40, 300, 70), "ACME SUPPLIES LTD"),
    ((40, 120, 200, 140), "Address:"),
    ((220, 120, 520, 140), "12 King Street, Leeds"),
]
PAYROLL_AR = [  # Arabic: label on the right, value to its left
    ((600, 40, 760, 70), "كشف الرواتب"),
    ((680, 120, 760, 140), "الموظف:"),
    ((480, 120, 660, 140), "علي حسن"),
    ((680, 150, 760, 170), "الراتب:"),
    ((560, 150, 660, 170), "5000"),
    ((680, 230, 760, 250), "الموظف:"),
    ((480, 230, 660, 250), "سارة محمود"),
    ((680, 260, 760, 280), "الراتب:"),
    ((560, 260, 660, 280), "7000"),
]
PAGES = {
    "addresses.png": BOTH_ADDRESSES,
    "billing-only.png": BILLING_ONLY,
    "dates.png": BOTH_DATES,
    "invoice-date-only.png": INVOICE_DATE_ONLY,
    "payroll.png": PAYROLL,
    "payroll-columns.png": PAYROLL_COLUMNS,
    "bonus.png": BONUS,
    "due-date-only.png": DUE_DATE_ONLY,
    "one-address.png": ONE_ADDRESS,
    "payroll-ar.png": PAYROLL_AR,
}


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
    tmp = tmp_path_factory.mktemp("label-scope")
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
    )
    for k, name in enumerate(PAGES):
        (tmp / name).write_bytes(png + bytes(k + 20))
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


def _declined_or_flagged(res) -> bool:  # noqa: ANN001
    declined = res.answer.startswith(("I couldn't find", "I could not find", "The documents do not"))
    return declined or any(w.startswith("Low confidence") for w in res.warnings)


# ---------------------------------------------------------------- positive controls


@pytest.mark.parametrize(
    ("doc", "question", "expect", "absent"),
    [
        ("addresses.png", "What is the billing address?", "King Street", "Harbour"),
        ("addresses.png", "What is the shipping address?", "Harbour Road", "King"),
        ("billing-only.png", "What is the billing address?", "King Street", "Harbour"),
        ("dates.png", "What is the invoice date?", ("3 March 2025", "2025-03-03"), "17 March"),
        ("dates.png", "What is the delivery date?", "17 March 2025", "3 March"),
        ("invoice-date-only.png", "What is the invoice date?", ("3 March 2025", "2025-03-03"), "17 March"),
        ("payroll.png", "What is Alice's salary?", "52,000", "61,000"),
        ("payroll.png", "What is Bob's salary?", "61,000", "52,000"),
        ("payroll.png", "What is the salary of Bob Turner?", "61,000", "52,000"),
        ("payroll-columns.png", "What is Alice's salary?", "52,000", "61,000"),
        ("payroll-columns.png", "What is Bob's salary?", "61,000", "52,000"),
    ],
)
def test_the_qualified_or_scoped_label_answers(library, doc, question, expect, absent):
    res = _ask(library, doc, question)
    head = _head(res)
    expect = (expect,) if isinstance(expect, str) else expect
    assert any(e in head for e in expect) and absent not in head, res.answer
    assert not any(w.startswith("Low confidence") for w in res.warnings), res.warnings
    assert res.sources and res.sources[0].page == 1 and res.sources[0].bbox is not None
    assert absent not in res.sources[0].excerpt, res.sources[0].excerpt


# ---------------------------------------------------------------- the reproduced failures


@pytest.mark.parametrize(
    ("doc", "question", "label"),
    [
        ("billing-only.png", "What is the shipping address?", "Billing Address:"),
        ("invoice-date-only.png", "What is the delivery date?", "Invoice Date:"),
        ("invoice-date-only.png", "When is the delivery date?", "Invoice Date:"),
    ],
)
def test_a_label_with_a_different_qualifier_does_not_answer(library, doc, question, label):
    """Only "Billing Address:" or "Invoice Date:" is printed: the shipping address or delivery date is not given,
    so neither the other field's value nor its bare label is returned as the answer."""
    res = _ask(library, doc, question)
    assert res.answer.startswith("I couldn't find supporting evidence"), res.answer
    assert label not in res.answer and not res.sources, res.answer


def test_a_paraphrased_question_about_a_missing_field_is_not_answered_confidently(library):
    res = _ask(library, "billing-only.png", "Where will the goods be shipped?")
    assert _declined_or_flagged(res), (res.answer, res.warnings)


@pytest.mark.parametrize("question", ["What is the salary?", "How much is the salary?"])
@pytest.mark.parametrize("doc", ["payroll.png", "payroll-columns.png"])
def test_a_repeated_label_without_its_person_is_ambiguous(library, doc, question):
    res = _ask(library, doc, question)
    assert _declined_or_flagged(res), (res.answer, res.warnings)


@pytest.mark.parametrize("doc", ["payroll.png", "payroll-columns.png"])
def test_a_person_not_on_the_page_gets_no_salary(library, doc):
    res = _ask(library, doc, "What is Carol's salary?")
    head = _head(res)
    assert ("52,000" not in head and "61,000" not in head) or _declined_or_flagged(res), res.answer


def test_a_named_person_not_on_the_page_is_not_given_anyones_salary(library):
    res = _ask(library, "payroll.png", "What is Carol's salary?")
    assert res.warnings and res.confidence < 0.3, res.answer


# ---------------------------------------------------------------- fallbacks cannot get around the checks


class _SpanReader:
    """A reader stand-in that returns a fixed span, as the extractive model would, and counts its calls."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = 0

    def answer(self, question, passages, top=8, check=None):  # noqa: ANN001, ARG002
        from types import SimpleNamespace

        self.calls += 1
        for k, p in enumerate(passages):
            at = p.find(self.text)
            if at >= 0:
                return [SimpleNamespace(text=self.text, passage=k, start=at, end=at + len(self.text), score=0.9)]
        return []


def _ask_reader(library, monkeypatch, doc: str, question: str, span: str, *, no_labels: bool = False):  # noqa: ANN202
    agent, ids = library
    brain, reader = agent.library.brain, _SpanReader(span)
    monkeypatch.setattr(type(brain), "reader", property(lambda self: reader))
    monkeypatch.setattr(brain, "mode", "auto")
    if no_labels:  # as if the label path had missed the label: the fallbacks must hold on their own
        monkeypatch.setattr("inklight.agent.labels.label_answer", lambda ctx, q: None)
    res = agent.ask(question, doc_ids=[ids[doc]], save=False)
    assert reader.calls >= 1, "the reader was not asked: the test would not exercise its span"
    return res


@pytest.mark.parametrize(
    ("doc", "question", "span"),
    [
        ("billing-only.png", "What is the shipping address?", "12 King Street, Leeds"),
        ("addresses.png", "What is the shipping address?", "12 King Street, Leeds"),
        ("invoice-date-only.png", "What is the delivery date?", "3 March 2025"),
        ("dates.png", "What is the delivery date?", "3 March 2025"),
    ],
)
def test_a_reader_span_beside_a_different_label_is_declined(library, monkeypatch, doc, question, span):
    res = _ask_reader(library, monkeypatch, doc, question, span, no_labels=True)
    assert span not in _head(res), res.answer
    assert res.answer.startswith("I couldn't find supporting evidence"), res.answer


@pytest.mark.parametrize("doc", ["payroll.png", "payroll-columns.png"])
def test_a_reader_span_from_another_persons_section_is_flagged(library, monkeypatch, doc):
    res = _ask_reader(library, monkeypatch, doc, "What is Bob's salary?", "52,000", no_labels=True)
    assert "52,000" not in _head(res) or _declined_or_flagged(res), (res.answer, res.warnings)


@pytest.mark.parametrize("doc", ["payroll.png", "payroll-columns.png"])
def test_a_reader_span_for_an_unnamed_repeated_label_is_flagged(library, monkeypatch, doc):
    res = _ask_reader(library, monkeypatch, doc, "What is the salary?", "61,000", no_labels=True)
    assert _declined_or_flagged(res), (res.answer, res.warnings)


@pytest.mark.parametrize(
    ("doc", "question", "span"),
    [
        ("addresses.png", "What is the billing address?", "12 King Street, Leeds"),
        ("addresses.png", "What is the shipping address?", "7 Harbour Road, Hull"),
        ("dates.png", "What is the delivery date?", "17 March 2025"),
        ("payroll.png", "What is Alice's salary?", "52,000"),
        ("payroll.png", "What is Bob's salary?", "61,000"),
        ("payroll-columns.png", "What is Alice's salary?", "52,000"),
        ("payroll-columns.png", "What is Bob's salary?", "61,000"),
    ],
)
def test_a_correctly_scoped_reader_span_still_answers(library, monkeypatch, doc, question, span):
    res = _ask_reader(library, monkeypatch, doc, question, span, no_labels=True)
    assert span in _head(res), res.answer
    assert not any(w.startswith("Low confidence") for w in res.warnings), res.warnings


@pytest.mark.parametrize(
    ("doc", "question"),
    [
        ("billing-only.png", "What is the shipping address?"),
        ("invoice-date-only.png", "What is the delivery date?"),
    ],
)
def test_the_rules_fallback_is_checked_too(library, monkeypatch, doc, question):
    monkeypatch.setattr("inklight.agent.labels.label_answer", lambda ctx, q: None)
    res = _ask(library, doc, question)
    head = _head(res)
    assert not head.rstrip().endswith(":"), res.answer
    assert "King Street" not in head and "3 March" not in head, res.answer


# ---------------------------------------------------------------- from the review of the first version


@pytest.mark.parametrize(
    ("doc", "question", "expect", "absent"),
    [
        ("addresses.png", "What's the Shipping address?", "Harbour Road", "King"),
        ("addresses.png", "What is the Shipping Address?", "Harbour Road", "King"),
        ("payroll.png", "What is Bob's Salary?", "61,000", "52,000"),
        ("payroll.png", "What is the Salary of Alice Martin?", "52,000", "61,000"),
        ("bonus.png", "What is Bob's bonus?", "500", "52,000"),
        ("one-address.png", "What is the company's address?", "King Street", "Harbour"),
        ("one-address.png", "What is the customer's address?", "King Street", "Harbour"),
    ],
)
def test_case_and_generic_owners_keep_their_meaning(library, doc, question, expect, absent):
    res = _ask(library, doc, question)
    head = _head(res)
    assert expect in head and absent not in head, res.answer
    assert not any(w.startswith("Low confidence") for w in res.warnings), res.warnings


def test_a_capitalised_qualifier_still_conflicts(library):
    res = _ask(library, "billing-only.png", "What's the Shipping address?")
    assert "King Street" not in _head(res), res.answer


def test_a_lone_label_in_another_persons_section_is_flagged(library):
    """ "Bonus:" is printed once, in Bob's section: it is not Alice's bonus."""
    res = _ask(library, "bonus.png", "What is Alice's bonus?")
    assert "500" not in _head(res) or _declined_or_flagged(res), (res.answer, res.warnings)


def test_a_different_date_label_does_not_answer_the_invoice_date(library):
    res = _ask(library, "due-date-only.png", "What is the invoice date?")
    assert "3 March" not in _head(res) or _declined_or_flagged(res), (res.answer, res.warnings)


@pytest.mark.parametrize("question", ["ما الراتب؟", "كم الراتب؟"])
def test_arabic_copies_of_a_label_are_not_chosen_between_silently(library, question):
    res = _ask(library, "payroll-ar.png", question)
    assert _declined_or_flagged(res), (res.answer, res.warnings)


def test_a_name_absent_from_the_document_is_said_to_be_absent(library):
    res = _ask(library, "payroll.png", "What is Carol's salary?")
    assert "carol" in " ".join(res.warnings).lower() or "carol" in res.answer.lower(), (res.answer, res.warnings)


# Plain text has no boxes: the answers come from its sentences, and the same checks apply to them.
TEXTS = {
    "billing.txt": "ACME SUPPLIES LTD\nBilling Address: 12 King Street, Leeds\nAmount Due: 420.00\n",
    "invoice-date.txt": "ACME SUPPLIES LTD\nInvoice Date: 3 March 2025\nAmount Due: 420.00\n",
    "payroll.txt": ("PAYROLL SUMMARY\nEmployee: Alice Martin\nSalary: 52,000\nEmployee: Bob Turner\nSalary: 61,000\n"),
}


@pytest.fixture(scope="module")
def texts(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("label-scope-text")
    for name, body in TEXTS.items():
        (tmp / name).write_text(body, encoding="utf-8")
    agent = DocumentAgent(make_settings(tmp / "home"))
    agent.add([tmp / n for n in TEXTS])
    ids = {d.name: d.id for d in agent.library.documents()}
    yield agent, ids
    agent.close()


@pytest.mark.parametrize(
    ("doc", "question", "wrong"),
    [
        ("billing.txt", "What is the shipping address?", "King Street"),
        ("invoice-date.txt", "What is the delivery date?", "3 March"),
    ],
)
def test_text_documents_get_the_same_qualifier_check(texts, doc, question, wrong):
    res = _ask(texts, doc, question)
    assert wrong not in _head(res), res.answer


@pytest.mark.parametrize(
    ("doc", "question", "expect"),
    [
        ("billing.txt", "What is the billing address?", "King Street"),
        ("invoice-date.txt", "What is the invoice date?", ("3 March 2025", "2025-03-03")),
    ],
)
def test_text_documents_still_answer_the_qualified_label(texts, doc, question, expect):
    res = _ask(texts, doc, question)
    expect = (expect,) if isinstance(expect, str) else expect
    assert any(e in res.answer for e in expect), res.answer
    assert not any(w.startswith("Low confidence") for w in res.warnings), res.warnings


def test_text_documents_flag_an_unnamed_repeated_label(texts):
    res = _ask(texts, "payroll.txt", "What is the salary?")
    assert _declined_or_flagged(res), (res.answer, res.warnings)


def test_many_copies_of_a_label_stay_fast(tmp_path):
    """A page of 150 employees: a scoped question is answered from the right section in well under a second."""
    import time

    def name(k: int) -> str:  # letters only: "Baaa", "Baab", …
        return "B" + "".join("abcdefghijklmnopqrstuvwxyz"[k // 26**i % 26] for i in (2, 1, 0))

    rows = [((40, 40, 300, 70), "PAYROLL SUMMARY")]
    for k in range(150):
        y = 100 + 60 * k
        rows += [
            ((40, y, 180, y + 20), "Employee:"),
            ((200, y, 400, y + 20), f"{name(k)} Turner"),
            ((40, y + 30, 180, y + 50), "Salary:"),
            ((200, y + 30, 320, y + 50), f"{1000 + k},000"),
        ]
    pages = {"big.png": rows}
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
    )
    (tmp_path / "big.png").write_bytes(png + b"big")
    settings = make_settings(tmp_path / "home")
    lib = Library(settings, engine=BoxEngine(pages))
    with DocumentAgent(settings, library=lib) as agent:
        agent.add([tmp_path / "big.png"])
        doc_id = agent.library.documents()[0].id
        started = time.perf_counter()
        res = agent.ask(f"What is {name(120)}'s salary?", doc_ids=[doc_id], save=False)
        took = time.perf_counter() - started
    lib.close()
    assert "1120,000" in _head(res), res.answer
    assert took < 2.0, took


@pytest.mark.parametrize("question", ["What is Alice's salary?", "What is Bob's salary?"])
def test_text_documents_do_not_give_another_fields_value_silently(texts, question):
    """The sentence path may cite "Employee: Alice Martin" for a salary; the page prints "Salary:", so that is not
    returned as if it answered."""
    res = _ask(texts, "payroll.txt", question)
    head = _head(res)
    assert not head.startswith("Employee") or _declined_or_flagged(res), (res.answer, res.warnings)
