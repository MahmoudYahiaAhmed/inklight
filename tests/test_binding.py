"""An answer must be connected to what was asked, not merely near it.

A nearby date, amount or name does not answer a question just because it sits in the same passage: the sender is
not the addressee, a letter's own date is not the date of an event it mentions, a total that includes tax is not
the tax, and a receipt that says "prices include VAT" does not state a VAT amount. Answerable questions must keep
their answers, so each case is tested in both directions.
"""

import pytest

from inklight import DocumentAgent

from .conftest import make_settings

LETTER_EN = (
    "Letter dated 14 February 2025 from the Permanent Representative of Kenya to the United Nations addressed to "
    "the Secretary-General\n"
    "I have the honour to transmit the communiqué adopted at the summit held in Nairobi on 3 February 2025. "
    "The Security Council will hold an open debate on the situation.\n"
    "(Signed) Martin Kimani\nPermanent Representative"
)
LETTER_AR = (
    "رسالة مؤرخة 14 شباط/فبراير 2025 موجهة إلى الأمين العام من الممثل الدائم لكينيا لدى الأمم المتحدة\n"
    "يشرفني أن أحيل إليكم البيان الصادر عن القمة التي عقدت في نيروبي في 3 شباط/فبراير 2025. "
    "وسيعقد مجلس الأمن مناقشة مفتوحة بشأن الحالة.\n"
    "(توقيع) مارتن كيماني\nالممثل الدائم"
)
# OCR of a 1984 typewritten letter: "PERMANENT REPRESENTATIVE OF IRAQ TO THE UNITED NATIONS ADDRESSED TO THE
# SECRETARY-GENERAL", as Indra read it.
LETTER_OCR = (
    "LETTER DATED 8 MAFCH 1984 FROM 'BE PERMANENT REPNFSEIWATIVE OF IRAQ T'J THE. INITED NATIONS ADDRESSED 10 "
    "THE SECRElARY-GEKERAL\n"
    "I have the honour to transmit to you herewith a. letter dated 28 February 1984 addressed to you by "
    "Mr. Tariq Aziz, Minister for Foreign Affairs of the Republic of Iraq.\n"
    "(Siqnedd Riyadh M. S. AL-QAYSI\nPermanent Representative"
)
FAX = "FAX COVER SHEET\nTo: George Baroody\nFrom: Betty Montgomery, Attorney General\nPages including cover: 3\n"
RECEIPT = (
    "McDonald's Sohag\nORD #99 REG #2 02/08/2022\n"
    "1 Reg Van Shake 32.50\nفانيليا عادي ميلك شيك\n1 Reg Straw Shake 32.50\n"
    "Subtotal 57.02\nEat-In Total (incl Tax) 65.00\nCash Tendered 200.00\nChange 135.00\nTAX OF 14.00% 7.98\n"
)
RECEIPT_VAT_MENTIONED = (
    "Lulu Hypermarket, New Cairo\nEgyptian Pasta 8.85\nRice Thai 17.55\nTotal: 182.15\n"
    "الاسعار شاملة ضريبة القيمة المضافة\nPrices include VAT\nServed by: Heba Mohamed\n"
)
DOCS = {
    "letter-en.txt": LETTER_EN,
    "letter-ar.txt": LETTER_AR,
    "letter-ocr.txt": LETTER_OCR,
    "fax.txt": FAX,
    "receipt.txt": RECEIPT,
    "lulu.txt": RECEIPT_VAT_MENTIONED,
}


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("binding")
    for name, text in DOCS.items():
        (tmp / name).write_text(text, encoding="utf-8")
    agent = DocumentAgent(make_settings(tmp / "home"))
    agent.add([tmp / n for n in DOCS])
    ids = {d.name: d.id for d in agent.library.documents()}
    yield agent, ids
    agent.close()


def _ask(library, doc: str, question: str):  # noqa: ANN202
    agent, ids = library
    return agent.ask(question, doc_ids=[ids[doc]], save=False)


def _no_evidence(res) -> bool:  # noqa: ANN001
    return res.answer.startswith("I couldn't find supporting evidence")


def _head(res) -> str:  # noqa: ANN001
    return res.answer.split("\n\nEvidence:")[0]


@pytest.mark.parametrize(
    ("doc", "question", "expect", "not_expect"),
    [
        ("letter-en.txt", "Who sent the letter?", "Kenya", "Secretary-General"),
        ("letter-en.txt", "Which country's Permanent Representative wrote the letter?", "Kenya", "Secretary"),
        ("letter-en.txt", "To whom is the letter addressed?", "Secretary-General", "Kenya"),
        ("letter-ar.txt", "من أرسل الرسالة؟", "كينيا", "الأمين العام"),
        ("letter-ar.txt", "إلى من وجهت الرسالة؟", "الأمين العام", "كينيا"),
        ("letter-ocr.txt", "Who sent the letter?", "IRAQ", "SECRE"),
        ("fax.txt", "Who is the fax addressed to?", "Baroody", "Montgomery"),
        ("fax.txt", "Who is the fax from?", "Montgomery", "Baroody"),
    ],
)
def test_sender_and_recipient_are_not_confused(library, doc, question, expect, not_expect):
    res = _ask(library, doc, question)
    assert expect in _head(res), res.answer
    assert not_expect not in _head(res), res.answer


@pytest.mark.parametrize(
    ("doc", "question", "expect"),
    [
        ("letter-en.txt", "When was the summit held?", "3 February 2025"),
        ("letter-en.txt", "What is the date of the letter?", "2025-02-14"),
    ],
)
def test_event_and_document_dates_are_both_still_answered(library, doc, question, expect):
    res = _ask(library, doc, question)
    assert expect in res.answer, res.answer
    assert not _no_evidence(res)


@pytest.mark.parametrize(
    ("doc", "question", "wrong"),
    [
        ("letter-en.txt", "On what date will the open debate be held?", "14 February"),
        ("letter-ar.txt", "متى سيعقد مجلس الأمن المناقشة المفتوحة؟", "14 شباط"),
    ],
)
def test_the_letters_own_date_is_not_the_date_of_an_event(library, doc, question, wrong):
    res = _ask(library, doc, question)
    assert wrong not in _head(res), res.answer
    assert _no_evidence(res), res.answer


@pytest.mark.parametrize(
    ("question", "expect"),
    [
        ("What is the tax amount?", "7.98"),
        ("How much cash was tendered?", "200.00"),
        ("What is the subtotal?", "57.02"),
        ("What is the total?", "65.00"),
        ("ما قيمة الضريبة؟", "7.98"),
    ],
)
def test_receipt_amounts_follow_their_own_labels(library, question, expect):
    res = _ask(library, "receipt.txt", question)
    assert expect in _head(res), res.answer


def test_a_mentioned_tax_without_an_amount_is_not_answered_with_the_total(library):
    res = _ask(library, "lulu.txt", "What is the VAT amount?")
    assert "182.15" not in _head(res), res.answer
    assert _no_evidence(res), res.answer
    assert "182.15" in _head(_ask(library, "lulu.txt", "What is the total?"))


def test_answers_that_are_connected_stay_answered(library):
    """The check must not turn into declining: who signed, the cashier and the summit city are still answered."""
    assert "Kimani" in _ask(library, "letter-en.txt", "Who signed the letter?").answer
    assert "Heba" in _ask(library, "lulu.txt", "Who served the customer?").answer
    assert "Nairobi" in _ask(library, "letter-en.txt", "Where was the summit held?").answer


# Regression cases taken from failures on the evaluation documents (OCR text as Indra read it).
OCR_CASES = {
    # A receipt photo: values were read on the line above their labels, and "TAX OF 14.00%" as "As If 14.80%".
    "mcd.txt": "TAX INVOICE\npain total (incl Tax)\n65.00\n200.00\nCash Tendered\nChange\n135.00\nAs If 14.80%\n7.98\n",
    # A right-to-left signature line: OCR put "(توقيع)" after the name.
    "rtl-signed.txt": (
        "رسالة مؤرخة 3 آذار/مارس 2025 موجهة إلى الأمين العام\nيشرفني أن أحيل إليكم البيان.\nقصي الضحاك (توقيع)\n"
    ),
    # The letter's own signature was lost by OCR; only the annex is signed.
    "annex-signed.txt": "Letter dated 8 March 1984 addressed to the Secretary-General\nI have the honour to transmit.\n"
    "Annex\nLetter dated 28 February 1984\n(Signed) Tariq Aziz\n",
    # Prose wrapped over PDF lines: the date and the event are on different lines of one sentence.
    "wrapped.txt": "The Syrian Arab Republic condemns in the strongest terms the statements made by the\n"
    "Prime Minister on 23 February 2025, when he called for the southern governorates to be\n"
    "demilitarized. The Council will hold an open debate on the situation.\n",
}


@pytest.fixture(scope="module")
def ocr_library(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ocr-cases")
    for name, text in OCR_CASES.items():
        (tmp / name).write_text(text, encoding="utf-8")
    agent = DocumentAgent(make_settings(tmp / "home"))
    agent.add([tmp / n for n in OCR_CASES])
    ids = {d.name: d.id for d in agent.library.documents()}
    yield agent, ids
    agent.close()


def test_a_label_and_its_value_on_neighbouring_lines_are_paired(ocr_library):
    assert "200.00" in _head(_ask(ocr_library, "mcd.txt", "How much cash was tendered?"))


def test_a_total_that_includes_tax_is_not_the_tax_when_ocr_lost_the_tax_label(ocr_library):
    res = _ask(ocr_library, "mcd.txt", "What is the tax amount?")
    assert "65.00" not in _head(res), res.answer


def test_a_right_to_left_signature_line_is_read(ocr_library):
    assert "قصي الضحاك" in _head(_ask(ocr_library, "rtl-signed.txt", "من وقّع الرسالة؟"))


def test_the_annexs_signature_is_not_given_as_the_letters(ocr_library):
    res = _ask(ocr_library, "annex-signed.txt", "Who signed the letter?")
    assert "The letter's own signature was not found" in res.answer, res.answer
    assert res.confidence < 0.3 and any("Low confidence" in w for w in res.warnings)


def test_a_date_and_its_event_on_different_lines_of_one_sentence_are_connected(ocr_library):
    res = _ask(ocr_library, "wrapped.txt", "On what date did the Prime Minister make the statements?")
    assert "23 February 2025" in res.answer, res.answer
    res = _ask(ocr_library, "wrapped.txt", "On what date will the open debate be held?")
    assert _no_evidence(res), res.answer


def test_review_cases_do_not_misfire(tmp_path):
    """From the code review: ordinary "Sign…" lines, content questions with "sent", a whole-number fee."""
    from inklight.agent.binding import role_asked

    assert role_asked("Which country sent troops?") is None
    assert role_asked("Who sent the money to Ali?") is None
    assert role_asked("Who sent the letter?") == "sender"
    (tmp_path / "terms.txt").write_text(
        "Service terms\nSignature of the applicant is required on every page.\nRenewal fee: 500 per year.\n",
        encoding="utf-8",
    )
    agent = DocumentAgent(make_settings(tmp_path / "home"))
    try:
        agent.add([tmp_path / "terms.txt"])
        doc = agent.library.documents()[0].id
        assert "500" in agent.ask("What is the renewal fee?", doc_ids=[doc], save=False).answer
        res = agent.ask("Who signed the form?", doc_ids=[doc], save=False)
        assert not res.answer.startswith("of the applicant")
        assert not any("answer: the signer" in c for c in res.checks)  # no signer was read from that line
    finally:
        agent.close()


# Regression cases from fresh3 (development data since its first run), as the documents read.
FRESH3_CASES = {
    # The question names the bus and the attack; the answer sentence, the next one, only says "injured".
    "bus.txt": (
        "On the morning of 23 April 2025, the Russian Federation launched a drone strike on the city of Marhanets,\n"
        "directly targeting a civilian bus transporting workers of a local plant. At least nine civilians were\n"
        "killed, and 54 others were injured, most of them women. Such attacks have become commonplace.\n"
    ),
    # Costa receipt: "VAT-Inclusive" qualifies the subtotal; the VAT amount is on its own line.
    "costa.txt": (
        "Baguette BBQ Chicken 70.00\nSubTotal (VAT-Inclusive)\n61.40\n14 % ضريبة القيمة المضافة VAT 8.60\n"
        "Dine In Total\n70.00\nVISA L.E70.00\n"
    ),
    # A body line that wraps "(see annex)." is not the annex heading; the letter is signed before the annex.
    "see-annex.txt": (
        "Letter dated 23 April 2025 from the Chargé d'affaires a.i. of the Permanent Mission of Ukraine to the\n"
        "United Nations addressed to the Secretary-General\n"
        "I am writing to inform you of the ongoing attacks against civilians in Ukraine (see\n"
        "annex).\n(Signed) Khrystyna Hayovyshyn\nAnnex to the letter dated 23 April 2025\n"
    ),
    # 1984 Arabic scan: the body starts with OCR's "أتشرِف", so the title ends before it.
    "ar-scan.txt": (
        "رسالة مؤرخة في ٢٣ نيسان /ابريل ١٩٨٤ وموجهة الى الأمين العام من الممثل\n"
        "الدائم لتركيا لدى الأمم المتحدة\nأتشرِف بأن أرفق طيه رسالة مؤرخة في ٢٣ نيسان /ابريل ١٩٨٤\n"
    ),
}


@pytest.fixture(scope="module")
def fresh3_library(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("fresh3-cases")
    for name, text in FRESH3_CASES.items():
        (tmp / name).write_text(text, encoding="utf-8")
    agent = DocumentAgent(make_settings(tmp / "home"))
    agent.add([tmp / n for n in FRESH3_CASES])
    ids = {d.name: d.id for d in agent.library.documents()}
    yield agent, ids
    agent.close()


def test_context_named_in_the_previous_sentence_still_connects(fresh3_library):
    res = _ask(fresh3_library, "bus.txt", "How many people were injured in the attack on the bus?")
    assert "54" in _head(res), res.answer


def test_a_qualifier_written_after_the_word_is_not_the_amount(fresh3_library):
    res = _ask(fresh3_library, "costa.txt", "What is the VAT amount?")
    assert "8.60" in _head(res), res.answer
    assert "61.40" not in _head(res).split("\n")[0], res.answer


def test_a_wrapped_see_annex_line_is_not_the_annex_heading(fresh3_library):
    res = _ask(fresh3_library, "see-annex.txt", "Who signed the letter?")
    assert "Hayovyshyn" in _head(res) and not res.answer.startswith("The letter's own signature"), res.answer
    assert res.confidence >= 0.3


def test_an_ocr_arabic_title_stops_at_the_body(fresh3_library):
    res = _ask(fresh3_library, "ar-scan.txt", "من أرسل الرسالة؟")
    head = _head(res)
    assert "تركيا" in head and "أتشرِف" not in head, res.answer


def test_qualifiers_before_or_after_the_word_do_not_count_as_the_subject():
    from inklight.agent.binding import _QUALIFIED_WORD, _keys

    for text in (
        "SubTotal (VAT-Inclusive) 61.40",
        "Total VAT inclusive 70.00",
        "Total (incl. VAT) 70.00",
        "Price incl tax 12.00",
        "الإجمالي شامل الضريبة 70.00",
    ):
        assert not ({"vat", "tax"} & _keys(_QUALIFIED_WORD.sub(" ", text))), text
    assert "vat" in _keys(_QUALIFIED_WORD.sub(" ", "14 % VAT 8.60"))


def test_a_reader_span_that_crosses_lines_is_matched_by_its_first_line():
    from inklight.agent.binding import _needles

    assert _needles("8.60\n61.40") == ["8.60 61.40", "8.60"]
    assert _needles("2 February\n2023") == ["2 February 2023", "2 February"]
