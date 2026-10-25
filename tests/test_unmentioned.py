"""A question about something no document in scope mentions is answered "not found", not with a nearby sentence.

Both directions are tested: questions the documents do answer must still be answered (paraphrased verbs,
generic words such as "number" or "date", English questions over Arabic labels), so that fewer silent errors
does not just mean declining everything.
"""

import pytest

from inklight import DocumentAgent

from .conftest import make_settings

LEASE = (
    "Lease agreement between Nile Properties (the landlord) and Omar Hassan (the tenant).\n"
    "The monthly rent is EGP 8,000, payable on the first day of each month.\n"
    "This agreement is governed by the laws of the Arab Republic of Egypt.\n"
    "Signed in Cairo on 3 March 2024."
)
LETTER = (
    "Letter dated 18 January 2023 from the Permanent Representative of Kenya addressed to the President of the "
    "Security Council.\nI have the honour to transmit the communiqué on the situation in North Kivu.\n"
    "(Signed) Martin Kimani, Ambassador"
)
RECEIPT_MIXED = "Abu Auf\nرقم العملية: 334713895836\nالمبلغ الإجمالي 160.00 جنيه\nCashier: Abdallah"


@pytest.fixture()
def library(tmp_path):
    for name, text in (("lease.txt", LEASE), ("letter.txt", LETTER), ("receipt.txt", RECEIPT_MIXED)):
        (tmp_path / name).write_text(text, encoding="utf-8")
    agent = DocumentAgent(make_settings(tmp_path / "home"))
    agent.add([tmp_path / n for n in ("lease.txt", "letter.txt", "receipt.txt")])
    ids = {d.name: d.id for d in agent.library.documents()}
    yield agent, ids
    agent.close()


def _not_found(res) -> bool:  # noqa: ANN001
    return res.answer.lower().startswith("not found")


@pytest.mark.parametrize(
    ("doc", "question", "absent"),
    [
        ("letter.txt", "What is the IBAN?", "iban"),
        ("letter.txt", "What is the invoice total?", "invoice"),
        ("lease.txt", "What is the VAT number?", "vat"),
        ("lease.txt", "Who is the employer?", "employer"),
        ("receipt.txt", "What is the governing law?", "governing"),
        ("receipt.txt", "Who is the landlord?", "landlord"),
    ],
)
def test_a_question_about_something_never_mentioned_is_not_found(library, doc, question, absent):
    agent, ids = library
    res = agent.ask(question, doc_ids=[ids[doc]], save=False)
    assert _not_found(res), res.answer
    assert absent in res.answer.lower()
    assert any("not found" in c for c in res.checks)


@pytest.mark.parametrize(
    ("doc", "question", "expect"),
    [
        ("lease.txt", "What is the monthly rent?", "8,000"),
        ("lease.txt", "Who is the landlord?", "Nile Properties"),
        ("lease.txt", "Which law governs the agreement?", "Egypt"),
        ("letter.txt", "Who sent the letter?", "Kenya"),  # "sent" never occurs: verbs are paraphrased
        ("letter.txt", "What is the date of the letter?", "2023"),  # "date" is generic
        ("letter.txt", "Which region does the communiqué concern?", "North Kivu"),
        ("receipt.txt", "What is the operation number?", "334713895836"),  # English question, Arabic label
    ],
)
def test_answerable_questions_are_still_answered(library, doc, question, expect):
    agent, ids = library
    res = agent.ask(question, doc_ids=[ids[doc]], save=False)
    assert not _not_found(res), res.answer
    assert expect in res.answer or any(expect in s.excerpt for s in res.sources)


def test_a_term_found_in_any_document_in_scope_is_not_declined(library):
    agent, ids = library
    res = agent.ask("Who is the landlord?", doc_ids=[ids["letter.txt"], ids["lease.txt"]], save=False)
    assert not _not_found(res)


def test_an_unknown_term_over_another_language_is_not_declined(library):
    """No equivalent is known for "barcode", and the receipt is partly Arabic: absence proves nothing."""
    agent, ids = library
    res = agent.ask("What is the barcode?", doc_ids=[ids["receipt.txt"]], save=False)
    assert not _not_found(res)


def test_arabic_question_about_an_unmentioned_subject(library):
    agent, ids = library
    res = agent.ask("ما هو رقم الآيبان؟", doc_ids=[ids["lease.txt"]], save=False)
    assert _not_found(res), res.answer


def test_a_question_whose_only_specific_word_is_a_verb_is_answered(library):
    """Verbs are paraphrased ("wrote", "sent", "issued"): their absence says nothing about the subject."""
    agent, ids = library
    res = agent.ask("Who wrote it?", doc_ids=[ids["letter.txt"]], save=False)
    assert not _not_found(res), res.answer


@pytest.mark.parametrize(
    "question",
    [
        "How much is the salary?",  # the offer says "pay": a synonym, so the subject is there
        "WHO SENT THIS LETTER?",  # a shouted question has no acronyms
        "When is the payment due?",  # everyday words never decide on their own
        "Is the paper A4?",  # "A4" is not an acronym
    ],
)
def test_paraphrases_and_everyday_words_are_not_declined(tmp_path, question):
    (tmp_path / "offer.txt").write_text(
        "Employment offer. Your monthly pay will be EGP 12,000, paid by 5 June each month. Sent by Human Resources.",
        encoding="utf-8",
    )
    agent = DocumentAgent(make_settings(tmp_path / "home"))
    try:
        agent.add([tmp_path / "offer.txt"])
        doc = agent.library.documents()[0]
        res = agent.ask(question, doc_ids=[doc.id], save=False)
        assert not _not_found(res), res.answer
    finally:
        agent.close()


def test_a_question_over_the_whole_library_only_declines_known_subjects(library):
    """Over the whole library the documents may be in either language: only listed subjects are looked up."""
    agent, _ = library
    assert _not_found(agent.ask("What is the IBAN?", save=False))
    assert not _not_found(agent.ask("What is the barcode?", save=False))
