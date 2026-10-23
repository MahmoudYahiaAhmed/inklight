"""The agent must answer the question that was asked — or say clearly what it could not apply.

Regression tests for an external review of 478fc3d, which reproduced silently wrong answers with
`succeeded` and confidence 1.0.
"""

from __future__ import annotations

from datetime import date

import pytest

from inklight import DocumentAgent
from inklight.agent.answer import grounded
from inklight.agent.planner import rule_plan
from inklight.library import Library
from inklight.schemas import TaskState

from .conftest import FakeEngine, make_settings

PNG = bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10])

INVOICES = {
    "acme.png": ["Acme Supplies Ltd.", "INVOICE #A-100", "Invoice Date: 2026-03-01", "Total: $5,616.00"],
    "globex.png": ["Globex Corporation", "INVOICE #G-200", "Invoice Date: 2026-04-02", "Total: $6,200.00"],
    "initech.png": ["Initech LLC", "INVOICE #I-300", "Invoice Date: 2025-11-20", "Total: $50.00"],
    "euro.png": ["Umbrella GmbH", "INVOICE #E-400", "Invoice Date: 2026-05-05", "Total: €100.00"],
    "usd100.png": ["Hooli LLC", "INVOICE #H-500", "Invoice Date: 2026-05-06", "Total: $100.00"],
}


@pytest.fixture
def agent(tmp_path):
    settings = make_settings(tmp_path / "home")
    lib = Library(settings, engine=FakeEngine({k: [v] for k, v in INVOICES.items()}))
    for name in INVOICES:
        (tmp_path / name).write_bytes(PNG + name.encode())
    with lib, DocumentAgent(settings, library=lib) as a:
        a.add(tmp_path)
        yield a


def _scope(agent, *names):
    return [d.id for d in agent.library.documents() if d.name in names]


def _run(agent, request, *names):
    ids = _scope(agent, *names) if names else [d.id for d in agent.library.documents()]
    return agent.run_plan(agent.plan(request), ids, save=False)


def _docs(result):
    return sorted(r.name for r in result.records)


# ---------------------------------------------------------------- the three reproduced failures


def test_vendor_constraint_is_applied(agent):
    result = _run(agent, "Find invoices from Acme above $5,000", "acme.png", "globex.png", "initech.png")
    assert _docs(result) == ["acme.png"]
    assert any("Acme" in u for u in result.interpretation)


def test_or_conditions_match_any(agent):
    result = _run(agent, "Find invoices below $100 or above $5,000", "acme.png", "globex.png", "initech.png")
    assert _docs(result) == ["acme.png", "globex.png", "initech.png"]


def test_mixed_currency_sum_is_not_added_up(agent):
    result = _run(agent, "What is the sum of all invoice totals?", "euro.png", "usd100.png")
    assert "200.00" not in result.answer
    assert "USD" in result.answer and "EUR" in result.answer
    assert result.state == TaskState.PARTIAL
    assert any("currenc" in w.lower() for w in result.warnings)
    assert result.confidence < 1.0


# ---------------------------------------------------------------- related guard-rails


def test_between(agent):
    result = _run(agent, "invoices between $100 and $6,000", "acme.png", "globex.png", "initech.png")
    assert _docs(result) == ["acme.png"]


def test_negated_vendor(agent):
    result = _run(agent, "invoices not from Acme above $5,000", "acme.png", "globex.png", "initech.png")
    assert _docs(result) == ["globex.png"]


def test_currency_mismatch_in_filter_is_flagged(agent):
    result = _run(agent, "Find invoices above $50", "euro.png", "usd100.png")
    assert _docs(result) == ["usd100.png"]
    assert any("currenc" in w.lower() for w in result.warnings)


def test_unsupported_condition_is_reported_not_dropped(agent):
    result = _run(agent, "Find invoices from Acme that were paid late", "acme.png", "globex.png")
    assert result.state == TaskState.PARTIAL
    assert any("paid late" in x for x in result.not_understood)
    assert any("paid late" in w for w in result.warnings)
    assert result.interpretation_confidence < 0.6
    assert result.confidence <= result.interpretation_confidence


def test_unattached_amount_is_reported(agent):
    plan = rule_plan("list invoices with $5,000", date(2026, 10, 24))
    assert any("5,000" in x for x in plan.not_understood)


def test_year_condition(agent):
    result = _run(agent, "invoices in 2026 above $5,000", "acme.png", "globex.png", "initech.png")
    assert _docs(result) == ["acme.png", "globex.png"]


def test_interpretation_is_shown_and_confidences_are_separate(agent):
    result = _run(agent, "Find invoices from Acme above $5,000", "acme.png", "globex.png")
    assert result.state == TaskState.SUCCEEDED
    assert result.interpretation_confidence >= 0.8
    assert 0 < result.evidence_confidence <= 1
    assert result.confidence == min(result.interpretation_confidence, result.evidence_confidence)
    assert "Understood as" in result.answer


def test_planner_does_not_take_dates_or_doc_words_as_vendors():
    for text in ("invoices from March 1, 2026", "invoices from the last batch", "totals from these invoices"):
        assert all(c.field != "vendor" for c in rule_plan(text, date(2026, 10, 24)).conditions), text


def test_grounding_respects_who_did_what():
    evidence = "Bob owes Acme $100."
    assert not grounded("Acme owes Bob $100", evidence)
    assert grounded("Bob owes Acme $100", evidence)


def test_periods_are_not_vendors():
    for text in ("Summarize the reports from Q2", "totals from FY26 invoices", "invoices from H1"):
        assert all(c.field != "vendor" for c in rule_plan(text, date(2026, 10, 24)).conditions), text


def test_relative_dates_are_reported():
    for text in ("invoices from last month", "Find invoices from last month above $500"):
        assert "last month" in rule_plan(text, date(2026, 10, 24)).not_understood, text


def test_ambiguous_dates_are_flagged():
    from inklight.extract import extract_record, resolve_field
    from inklight.schemas import DocumentInfo, PageContent, TextLine

    doc = DocumentInfo(id="d" * 16, path="/x.pdf", name="x.pdf", sha256="0", size=1, mtime=0)
    page = PageContent(number=1, lines=(TextLine(text="Date: 03/04/2026", conf=0.99),))
    value = extract_record(doc, [page], [resolve_field("date")]).fields["date"]
    assert value.value == "2026-03-04" and "ambiguous" in value.warning and value.confidence < 0.7
    value = extract_record(doc, [page], [resolve_field("date")], day_first=True).fields["date"]
    assert value.value == "2026-04-03"


def test_currency_read_from_label_line(agent):
    from inklight.extract import extract_record, resolve_field
    from inklight.schemas import DocumentInfo, PageContent, TextLine

    doc = DocumentInfo(id="d" * 16, path="/x.pdf", name="x.pdf", sha256="0", size=1, mtime=0)
    page = PageContent(number=1, lines=(TextLine(text="TOTAL DUE (USD)   1,234.00", conf=0.99),))
    value = extract_record(doc, [page], [resolve_field("total")]).fields["total"]
    assert value.value == 1234.0 and value.unit == "USD"
