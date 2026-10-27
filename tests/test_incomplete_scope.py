"""A selection with a document that failed to import, or is still being read, is not answered as if complete.

Reproduced on 8e860e6: with a ready document and a failed one selected, "What is the registration number?" came
back succeeded with no warning, and a comparison listed the failed document as "not found at a printed label".
The unreadable document is now named, the result is partial, and nothing about it is concluded or retried.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from inklight import DocumentAgent
from inklight.cli import app as cli_app
from inklight.schemas import DocStatus
from inklight.server import create_app

from .conftest import make_settings
from .factory import _pdf

H = {"X-Inklight": "1"}
READY = "ACME Trading Ltd\nRegistration Number: 12345\nTotal: 500\n"
OTHER = "ACME Trading Ltd\nRegistration Number: 12345\nTotal: 700\n"


def _files(tmp_path):  # noqa: ANN202
    a = _pdf(tmp_path / "a.pdf", [[(line, 11) for line in READY.splitlines()]])
    c = _pdf(tmp_path / "c.pdf", [[(line, 11) for line in OTHER.splitlines()]])
    b = tmp_path / "b.pdf"
    b.write_bytes(b"%PDF-1.4 not really a pdf")
    return a, b, c


def _library(agent: DocumentAgent, tmp_path) -> dict[str, str]:
    """a.pdf and c.pdf ready, b.pdf failed, p.pdf still pending (as while an import runs)."""
    a, b, c = _files(tmp_path)
    agent.add([a, b, c])
    docs = {d.name: d for d in agent.library.documents()}
    pending = docs["a.pdf"].model_copy(
        update={"id": "pending0001", "name": "p.pdf", "path": str(tmp_path / "p.pdf"), "status": DocStatus.PENDING}
    )
    agent.library.store.upsert_document(pending)
    docs = {d.name: d for d in agent.library.documents()}
    assert docs["b.pdf"].status == DocStatus.FAILED and docs["p.pdf"].status == DocStatus.PENDING
    return {name: d.id for name, d in docs.items()}


@pytest.fixture
def lib(tmp_path):  # noqa: ANN201
    agent = DocumentAgent(make_settings(tmp_path / "home"))
    ids = _library(agent, tmp_path)
    yield agent, ids
    agent.close()


def test_answer_from_part_of_the_selection_is_partial_and_names_what_was_not_read(lib):
    agent, ids = lib
    res = agent.ask("What is the registration number?", doc_ids=[ids["a.pdf"], ids["b.pdf"]], save=False)
    assert res.outcome == "partial" and res.state.value == "partial", (res.outcome, res.answer)
    assert res.answer.startswith("INCOMPLETE SCOPE: this result covers 1 of the 2"), res.answer
    assert "12345" in res.answer  # the useful preview from the ready document is kept
    assert any(w.startswith("b.pdf was not used: its import failed") for w in res.warnings), res.warnings
    assert res.scope == {
        "requested": [ids["a.pdf"], ids["b.pdf"]],
        "used": [ids["a.pdf"]],
        "unavailable": [res.scope["unavailable"][0]],
    }
    assert res.scope["unavailable"][0] | {"error": None} == {
        "doc_id": ids["b.pdf"],
        "document": "b.pdf",
        "status": "failed",
        "error": None,
    }
    assert any(c.startswith("scope: 1 of 2") for c in res.checks)


def test_pending_document_is_reported_and_not_reprocessed(lib):
    agent, ids = lib
    res = agent.ask("What is the registration number?", doc_ids=[ids["p.pdf"], ids["a.pdf"]], save=False)
    assert res.outcome == "partial" and "p.pdf (it is still being read)" in res.answer, res.answer
    assert agent.library.get(ids["p.pdf"]).status == DocStatus.PENDING  # asking never retries an import
    assert agent.library.get(ids["b.pdf"]).status == DocStatus.FAILED


def test_no_readable_document_is_not_answered(lib):
    agent, ids = lib
    res = agent.ask("What is the registration number?", doc_ids=[ids["b.pdf"], ids["p.pdf"]], save=False)
    assert res.state.value == "failed" and res.outcome == "failed", (res.state, res.outcome)
    assert res.answer.startswith("NOT ANSWERED: none of the 2 selected document(s) can be read yet"), res.answer
    assert not res.sources


def test_unknown_id_is_reported_as_missing(lib):
    agent, ids = lib
    res = agent.ask("What is the registration number?", doc_ids=[ids["a.pdf"], "gone0000"], save=False)
    assert res.outcome == "partial" and res.scope["unavailable"][0]["status"] == "missing"


def test_comparison_cannot_conclude_without_every_document(lib):
    agent, ids = lib
    res = agent.ask("Compare the registration number", doc_ids=[ids["a.pdf"], ids["b.pdf"]], save=False)
    assert res.comparison is not None and res.comparison["verdict"] == "cannot determine", res.answer
    statuses = {v["document"]: v["status"] for v in res.comparison["values"]}
    assert statuses == {"a.pdf": "found", "b.pdf": "not available"}, statuses
    assert "b.pdf: not compared: its import failed" in res.answer
    assert res.outcome == "partial"


def test_comparison_of_ready_documents_is_unchanged(lib):
    agent, ids = lib
    res = agent.ask("Compare the registration number", doc_ids=[ids["a.pdf"], ids["c.pdf"]], save=False)
    assert res.comparison["verdict"] == "matches" and res.scope is None, res.answer
    assert not any("was not used" in w for w in res.warnings)


def test_total_states_its_coverage(lib):
    agent, ids = lib
    res = agent.ask(
        "What is the sum of all invoice totals?", doc_ids=[ids["a.pdf"], ids["c.pdf"], ids["b.pdf"]], save=False
    )
    assert res.outcome == "partial" and "covers 2 of the 3 selected" in res.answer, res.answer


def test_http_ask_reports_the_scope(lib, monkeypatch):
    agent, ids = lib
    monkeypatch.setenv("INKLIGHT_ALLOWED_HOSTS", "testserver")
    client = TestClient(create_app(agent.settings, agent=agent))
    body = {"request": "What is the registration number?", "doc_ids": [ids["a.pdf"], ids["b.pdf"]]}
    r = client.post("/api/ask", headers=H, json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["outcome"] == "partial" and out["scope"]["unavailable"][0]["document"] == "b.pdf", out
    assert out["scope"]["requested"] == body["doc_ids"]


def test_cli_ask_with_library_documents(tmp_path, monkeypatch):
    monkeypatch.setenv("INKLIGHT_HOME", str(tmp_path / "home"))
    a, b, _ = _files(tmp_path)
    runner = CliRunner()
    runner.invoke(cli_app, ["process", str(a), str(b)])
    r = runner.invoke(
        cli_app, ["ask", "What is the registration number?", "--doc", "a.pdf", "--doc", "b.pdf", "--json"]
    )
    out = json.loads(r.stdout)
    assert out["outcome"] == "partial" and out["scope"]["unavailable"][0]["status"] == "failed", out
    assert r.exit_code == 0  # a partial result is a result
    r = runner.invoke(cli_app, ["ask", "What is the registration number?", "--doc", "b.pdf", "--json"])
    assert json.loads(r.stdout)["outcome"] == "failed" and r.exit_code == 2
    r = runner.invoke(cli_app, ["ask", "What is it?", "--doc", "nope.pdf"])
    assert r.exit_code != 0 and "No library document" in r.output


def test_cli_files_that_fail_make_the_result_partial(tmp_path, monkeypatch):
    monkeypatch.setenv("INKLIGHT_HOME", str(tmp_path / "home"))
    a, b, _ = _files(tmp_path)
    r = CliRunner().invoke(cli_app, ["ask", str(a), str(b), "What is the registration number?", "--json"])
    out = json.loads(r.stdout)
    assert out["outcome"] == "partial" and any("Skipped b.pdf" in w for w in out["warnings"]), out
