"""End-to-end over real documents with the real Indra OCR engine (rules brain: deterministic)."""

from pathlib import Path

import pytest

from inklight import DocumentAgent, InputRejected
from inklight.agent import Policy
from inklight.schemas import StepStatus, TaskState

pytestmark = pytest.mark.ocr


def test_readme_python_example(shared_agent, docs_dir):
    result = shared_agent.ask("Extract the invoice number, date, and total", files=[docs_dir / "invoice_acme.pdf"])
    assert result.state == TaskState.SUCCEEDED
    row = result.table()[0]
    assert row["invoice_number"] == "INV-2041" and row["total"] == 5616.0
    assert result.sources and result.sources[0].name == "invoice_acme.pdf"


def test_csv_of_invoices_requires_permission(shared_agent):
    result = shared_agent.ask("Read all these invoices and create a CSV of vendor, date, tax, and total")
    assert result.state == TaskState.PARTIAL
    assert result.trace[-1].tool == "write_output" and result.trace[-1].status == StepStatus.DENIED
    assert {r["document"] for r in result.table()} == {
        "invoice_acme.pdf",
        "invoice_globex.pdf",
        "invoice_initech_scan.png",
    }


def test_csv_written_when_allowed(shared_agent, tmp_path):
    policy = Policy(allow_write=True, output_dir=tmp_path)
    result = shared_agent.ask("Create a CSV of vendor and total for all invoices", policy=policy)
    assert result.state == TaskState.SUCCEEDED and len(result.files_written) == 1
    text = Path(result.files_written[0]).read_text(encoding="utf-8")
    assert "Acme Supplies Ltd." in text and "5616.0" in text


def test_writes_never_overwrite(shared_agent, tmp_path):
    policy = Policy(allow_write=True, output_dir=tmp_path)
    a = shared_agent.ask("extract total from invoices to out.json", policy=policy)
    b = shared_agent.ask("extract total from invoices to out.json", policy=policy)
    assert a.files_written[0] != b.files_written[0]


def test_declined_confirmation(shared_agent, tmp_path):
    policy = Policy(allow_write=True, output_dir=tmp_path, confirm=lambda _msg: False)
    result = shared_agent.ask("export invoice totals as csv", policy=policy)
    assert not result.files_written and any("declined" in w for w in result.warnings)


def test_filter_contracts_expiring(shared_agent):
    result = shared_agent.ask("Find every contract that expires within 90 days")
    assert [r["document"] for r in result.table()] == ["contract_cloud.pdf"]
    assert result.sources[0].page == 1


def test_filter_invoices_above(shared_agent):
    result = shared_agent.ask("Find all invoices above $5,000")
    assert {r["document"] for r in result.table()} == {"invoice_acme.pdf", "invoice_initech_scan.png"}


def test_scanned_invoice_arithmetic_flagged(shared_agent):
    result = shared_agent.ask("Extract subtotal, tax and total from all invoices")
    scan = next(r for r in result.records if r.name == "invoice_initech_scan.png")
    assert "does not equal" in scan.fields["total"].warning
    acme = next(r for r in result.records if r.name == "invoice_acme.pdf")
    assert acme.fields["total"].verified


def test_aggregate_is_exact(shared_agent):
    result = shared_agent.ask("What is the sum of all invoice totals?")
    assert "16,186.00" in result.answer


def test_compare_reports(shared_agent):
    result = shared_agent.ask("Compare these reports and explain the differences")
    assert "6% → 17%" in result.answer and "120 → 134" in result.answer


def test_inconsistent_customers(shared_agent):
    result = shared_agent.ask("Extract all customer names from the invoices and flag inconsistent records")
    assert "3 spellings" in result.answer


def test_field_question_cites_source(shared_agent):
    result = shared_agent.ask("What is the total of the Globex invoice?")
    assert "2,640.00" in result.answer and result.sources[0].name == "invoice_globex.pdf"
    assert result.sources[0].bbox is not None


def test_rules_question_answer(shared_agent):
    result = shared_agent.ask("How many employees did the company have in Q2?")
    assert "134" in result.answer and result.sources[0].name == "report_q2.pdf"


def test_prompt_injection_is_data(shared_agent, tmp_path):
    policy = Policy(allow_write=True, output_dir=tmp_path)
    result = shared_agent.ask("What does the memo say about onboarding?", policy=policy)
    assert "14 days" in result.answer
    assert any("prompt injection" in w for w in result.warnings)
    assert not result.files_written and {s.tool for s in result.trace} <= {"inspect_documents", "search", "answer"}


def test_find_passage_location(shared_agent):
    result = shared_agent.ask("Find the paragraph about termination notice")
    top = result.sources[0]
    assert "sixty days" in top.excerpt and top.bbox is not None and len(top.excerpt) < 200


def test_summarize(shared_agent):
    result = shared_agent.ask("Summarize the reports")
    assert "report_q1.pdf" in result.answer and "(report_q1.pdf p.1)" in result.answer


def test_history_saved(shared_agent):
    result = shared_agent.ask("how many contracts are there?")
    assert "2 document(s)" in result.answer
    assert shared_agent.library.store.get_task(result.task_id).answer == result.answer


def test_extract_api(shared_agent, docs_dir):
    records = shared_agent.extract([docs_dir / "invoice_globex.pdf"], fields=["invoice_number", "total"])
    assert records[0].fields["invoice_number"].value == "GX-7781"
    records = shared_agent.extract(
        docs_dir / "contract_cloud.pdf", schema={"fields": [{"name": "expiry_date", "type": "date"}]}
    )
    assert records[0].fields["expiry_date"].value


def test_empty_request_rejected(shared_agent):
    with pytest.raises(InputRejected):
        shared_agent.ask("   ")


def test_unreadable_files_reported(agent: DocumentAgent, bad_dir):
    with pytest.raises(InputRejected, match="No readable documents"):
        agent.ask("what is the total?", files=[bad_dir])


def test_password_pdf(agent: DocumentAgent, bad_dir):
    report = agent.add(bad_dir / "locked.pdf")
    assert report.failed and "password" in report.failed[0][1].lower()
    report = agent.add(bad_dir / "locked.pdf", password="s3cret")
    assert report.added and "10.00" in agent.library.text(report.added[0].id)


def test_async_api(shared_agent):
    import asyncio

    result = asyncio.run(shared_agent.ask_async("how many invoices are there?"))
    assert "3 document(s)" in result.answer
