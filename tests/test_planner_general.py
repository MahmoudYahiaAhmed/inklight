"""The planner handles general documents and Arabic requests, not only invoice phrasing.

Each case here failed on a development document in the use-case evaluation (bench/usecases, split "dev").
"""

import pytest

from inklight.agent.plan import Intent
from inklight.agent.planner import rule_plan


@pytest.mark.parametrize(
    ("request_text", "intent"),
    [
        ("لخص هذه الوثيقة", Intent.SUMMARIZE),
        ("لخّص الرسالة", Intent.SUMMARIZE),
        ("أعطني ملخصا للتقرير", Intent.SUMMARIZE),
        ("ما النقاط الرئيسية في هذا العقد؟", Intent.SUMMARIZE),
        ("قارن بين تاريخي الرسالتين", Intent.COMPARE),
        ("ما الفرق بين العقدين؟", Intent.COMPARE),
        ("كم عدد الإيصالات؟", Intent.COUNT),
        ("كم عدد الوثائق؟", Intent.COUNT),
        ("استخرج رقم الفاتورة والتاريخ والإجمالي", Intent.EXTRACT),
        ("أين ورد ذكر عبادان؟", Intent.FIND),
        ("في أي صفحة ذُكر القرار 2379؟", Intent.FIND),
        ("ما تاريخ الرسالة؟", Intent.ASK),
        ("ما الإجمالي؟", Intent.ASK),
        ("من وقّع الرسالة؟", Intent.ASK),
    ],
)
def test_arabic_requests(request_text, intent):
    assert rule_plan(request_text).intent == intent


def test_arabic_document_nouns_scope_a_count():
    plan = rule_plan("كم عدد الإيصالات؟")
    assert plan.doc_type == "receipt"
    assert rule_plan("كم عدد الفواتير؟").doc_type == "invoice"
    assert rule_plan("كم عدد العقود؟").doc_type == "contract"


@pytest.mark.parametrize(
    "request_text",
    [
        "Translate this letter into French",
        "Please translate the contract to Arabic",
        "Sign this contract on my behalf",
        "Email this invoice to my manager",
        "Send the report to the board",
        "ترجم هذه الرسالة إلى الإنجليزية",
        "أرسل هذه الفاتورة بالبريد الإلكتروني إلى المحاسب",
        "وقّع هذا العقد نيابة عني",
    ],
)
def test_actions_inklight_cannot_do_are_unsupported(request_text):
    plan = rule_plan(request_text)
    assert plan.blocked and plan.steps[-1].tool == "inspect_documents"


@pytest.mark.parametrize(
    "request_text", ["Who sent the letter?", "Who signed the letter?", "من أرسل هذه الرسالة؟", "What was translated?"]
)
def test_questions_about_actions_are_not_blocked(request_text):
    plan = rule_plan(request_text)
    assert not plan.blocked and plan.intent == Intent.ASK


@pytest.mark.parametrize(
    "request_text",
    [
        "Which city was hit by artillery fire on 8 September?",
        "Which mission sent the letter?",
        "The report covers the implementation of which resolution?",
        "Who is the fax addressed to?",
        "Which law governs the agreement?",
        "What initiative do the Russian actions obstruct?",
    ],
)
def test_questions_about_content_are_answered_not_filtered(request_text):
    plan = rule_plan(request_text)
    assert plan.intent == Intent.ASK
    assert plan.where is None
    assert "invoice_number" not in plan.fields


@pytest.mark.parametrize(
    ("request_text", "intent"),
    [
        ("Which invoices are above $5,000?", Intent.FILTER),
        ("List the invoices from Acme", Intent.FILTER),
        ("Show the receipts with a total above 150", Intent.FILTER),
        ("What is the total of all receipts?", Intent.AGGREGATE),
        ("How many receipts are there?", Intent.COUNT),
    ],
)
def test_set_requests_keep_their_intent(request_text, intent):
    assert rule_plan(request_text).intent == intent


def test_extraction_without_a_document_type_does_not_default_to_invoice_fields():
    plan = rule_plan("Extract the key fields from these letters")
    assert "invoice_number" not in plan.fields


def test_an_export_of_columns_is_not_a_sum():
    plan = rule_plan("Export the invoice number, date and total of the invoices to CSV")
    assert plan.intent == Intent.EXTRACT
    assert list(plan.fields) == ["invoice_number", "date", "total"]
    assert plan.output == "csv"


@pytest.mark.parametrize(
    "text", ["What is the sum of the totals of all invoices?", "Add up the totals of the receipts"]
)
def test_explicit_sums_still_aggregate(text):
    assert rule_plan(text).intent == Intent.AGGREGATE


def test_comparing_named_fields_compares_those_fields():
    plan = rule_plan("Compare the letter dates of these documents")
    assert plan.intent == Intent.COMPARE
    assert "date" in plan.fields
