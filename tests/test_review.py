"""Human review: frozen predictions, decisions, approval, append-only history, export of approved reviews."""

import csv
import io
import json
import sqlite3
from pathlib import Path

import pytest

from inklight import DocumentAgent
from inklight.errors import InputRejected

from .conftest import make_settings

FIELDS = ["vendor", "invoice_number", "date", "total"]


def _invoice(folder: Path, name: str, body: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.txt").write_text(body, encoding="utf-8")


@pytest.fixture
def agent(tmp_path):
    docs = tmp_path / "docs"
    _invoice(
        docs, "acme", "INVOICE #INV-0001\nVendor: Acme Supplies Ltd.\nInvoice Date: 2026-03-14\nTotal: USD 1,250.00\n"
    )
    _invoice(docs, "globex", "INVOICE #INV-0002\nVendor: Globex Corporation\nInvoice Date: 2026-04-01\n")
    with DocumentAgent(make_settings(tmp_path / "home")) as a:
        a.add(docs)
        yield a


def _doc(agent, stem):
    return next(d for d in agent.library.documents() if d.name.startswith(stem))


def test_opening_a_review_freezes_the_predictions(agent):
    review = agent.open_review(_doc(agent, "acme").id, FIELDS, reviewer="ana", cohort="genuine-invoice")
    got = {f.field: f for f in review.fields}
    assert got["vendor"].predicted == "Acme Supplies Ltd."
    assert got["total"].predicted == 1250.0 and got["total"].raw and got["total"].source["page"] == 1
    assert review.status == "open" and review.cohort == "genuine-invoice" and review.doc_sha256
    assert all(f.action is None for f in review.fields)


def test_accept_correct_and_absent_keep_the_prediction(agent):
    store = agent.reviews
    r = agent.open_review(_doc(agent, "acme").id, FIELDS, reviewer="ana")
    store.decide(r.id, "vendor", reviewer="ana", action="accepted")
    store.decide(r.id, "total", reviewer="ana", action="corrected", value="1,520.00")
    store.decide(r.id, "date", reviewer="ana", action="corrected", value="03/15/2026")
    r = store.decide(r.id, "invoice_number", reviewer="ana", action="absent")
    got = {f.field: f for f in r.fields}
    assert got["vendor"].final == "Acme Supplies Ltd." and got["vendor"].action == "accepted"
    assert got["total"].final == 1520.0 and got["total"].predicted == 1250.0  # prediction preserved
    assert got["date"].final == "2026-03-15"
    assert got["invoice_number"].final is None and got["invoice_number"].action == "absent"


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("total", "1234", 1234.0),
        ("total", "Rp 63.000", 63000.0),
        ("total", "-45.00", -45.0),
        ("date", "2026-01-31", "2026-01-31"),
    ],
)
def test_typed_values(agent, field, value, expected):
    r = agent.open_review(_doc(agent, "acme").id, [field], reviewer="ana")
    r = agent.reviews.decide(r.id, field, reviewer="ana", action="corrected", value=value)
    assert r.fields[0].final == expected


@pytest.mark.parametrize(("field", "value"), [("total", "about ten"), ("date", "soon"), ("vendor", "   ")])
def test_invalid_values_are_rejected(agent, field, value):
    r = agent.open_review(_doc(agent, "acme").id, [field], reviewer="ana")
    with pytest.raises(InputRejected):
        agent.reviews.decide(r.id, field, reviewer="ana", action="corrected", value=value)


def test_nothing_to_accept_when_nothing_was_predicted(agent):
    r = agent.open_review(_doc(agent, "globex").id, ["total"], reviewer="ana")
    assert r.fields[0].predicted is None
    with pytest.raises(InputRejected, match="Nothing was predicted"):
        agent.reviews.decide(r.id, "total", reviewer="ana", action="accepted")


def test_predictions_and_history_cannot_be_rewritten(agent):
    r = agent.open_review(_doc(agent, "acme").id, FIELDS, reviewer="ana")
    db = agent.library.store._conn()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute("UPDATE review_fields SET predicted = '1' WHERE review_id = ?", (r.id,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("UPDATE review_events SET kind = 'x' WHERE review_id = ?", (r.id,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        db.execute("DELETE FROM review_events WHERE review_id = ?", (r.id,))


def _decide_all(agent, review_id):
    for f in agent.reviews.get(review_id).fields:
        action = "accepted" if f.predicted is not None else "absent"
        agent.reviews.decide(review_id, f.field, reviewer="ana", action=action)


def test_approval_needs_every_field_decided_and_records_time(agent):
    store = agent.reviews
    r = agent.open_review(_doc(agent, "acme").id, FIELDS, reviewer="ana")
    with pytest.raises(InputRejected, match="Decide every field"):
        store.approve(r.id, reviewer="ben")
    _decide_all(agent, r.id)
    with pytest.raises(InputRejected, match="active_seconds"):
        store.approve(r.id, reviewer="ben", active_seconds=10_000)
    r = store.approve(r.id, reviewer="ben", active_seconds=0.5)
    assert r.status == "approved" and r.approved_by == "ben" and r.active_seconds == 0.5 and r.wall_seconds >= 0
    with pytest.raises(InputRejected, match="reopen"):
        store.decide(r.id, "vendor", reviewer="ana", action="absent")


def test_reopen_needs_a_reason_and_is_logged(agent):
    store = agent.reviews
    r = agent.open_review(_doc(agent, "acme").id, FIELDS, reviewer="ana")
    _decide_all(agent, r.id)
    store.approve(r.id, reviewer="ana")
    with pytest.raises(InputRejected):
        store.reopen(r.id, reviewer="ana", reason=" ")
    r = store.reopen(r.id, reviewer="ana", reason="total was misread")
    assert r.status == "open" and r.approved_at is None
    kinds = [e["kind"] for e in store.events(r.id)]
    assert kinds[0] == "opened" and kinds[-2:] == ["approved", "reopened"] and kinds.count("set") == len(FIELDS)


def test_export_contains_only_approved_reviews_with_prediction_warning_and_decision(agent):
    store = agent.reviews
    approved = agent.open_review(_doc(agent, "acme").id, FIELDS, reviewer="ana")
    _decide_all(agent, approved.id)
    store.decide(approved.id, "total", reviewer="ana", action="corrected", value="1,520.00")
    store.approve(approved.id, reviewer="ben")
    agent.open_review(_doc(agent, "globex").id, FIELDS, reviewer="ana")  # left open: not exported
    rows = list(csv.DictReader(io.StringIO(store.export("csv", actor="ben"))))
    assert {r["review_id"] for r in rows} == {approved.id} and len(rows) == len(FIELDS)
    total = next(r for r in rows if r["field"] == "total")
    assert total["predicted"] == "1250.0" and total["action"] == "corrected" and total["approved_by"] == "ben"
    assert json.loads(store.export("json", actor="ben"))[0]["review_id"] == approved.id
    assert "exported" in [e["kind"] for e in store.events(approved.id)]


def test_formula_like_document_text_is_neutralised_in_csv(agent, tmp_path):
    _invoice(tmp_path / "more", "evil", 'INVOICE #INV-0009\nVendor: =HYPERLINK("x")\nTotal: USD 5.00\n')
    agent.add(tmp_path / "more")
    r = agent.open_review(_doc(agent, "evil").id, ["vendor"], reviewer="ana")
    agent.reviews.decide(r.id, "vendor", reviewer="ana", action="accepted")
    agent.reviews.approve(r.id, reviewer="ana")
    row = next(csv.DictReader(io.StringIO(agent.reviews.export("csv", actor="ana"))))
    assert row["predicted"].startswith("'=") and row["final"].startswith("'=")


def test_manual_mode_hides_predictions_until_approved(agent):
    r = agent.open_review(_doc(agent, "acme").id, FIELDS, reviewer="ana", mode="manual")
    shown = r.visible()["fields"]
    assert all(f["predicted"] is None and f["warning"] is None and f["source"] is None for f in shown)
    assert agent.reviews.get(r.id).fields[0].predicted == "Acme Supplies Ltd."  # still captured
    with pytest.raises(InputRejected, match="Manual entry"):
        agent.reviews.decide(r.id, "vendor", reviewer="ana", action="accepted")
    for f in FIELDS:
        agent.reviews.decide(r.id, f, reviewer="ana", action="absent")
    approved = agent.reviews.approve(r.id, reviewer="ana")
    assert approved.visible()["fields"][0]["predicted"] == "Acme Supplies Ltd."


def test_reviews_survive_reopening_the_library(tmp_path):
    docs = tmp_path / "docs"
    _invoice(docs, "acme", "INVOICE #INV-0001\nVendor: Acme Supplies Ltd.\nTotal: USD 10.00\n")
    with DocumentAgent(make_settings(tmp_path / "home")) as a:
        a.add(docs)
        review_id = a.open_review(a.library.documents()[0].id, ["vendor"], reviewer="ana").id
    with DocumentAgent(make_settings(tmp_path / "home")) as b:
        assert b.reviews.get(review_id).fields[0].predicted == "Acme Supplies Ltd."


@pytest.mark.parametrize("name", ["", "  ", "x" * 101])
def test_reviewer_name_is_required(agent, name):
    with pytest.raises(InputRejected, match="reviewer"):
        agent.open_review(_doc(agent, "acme").id, FIELDS, reviewer=name)


def test_unknown_document_field_and_review(agent):
    with pytest.raises(InputRejected):
        agent.open_review("nope", FIELDS, reviewer="ana")
    r = agent.open_review(_doc(agent, "acme").id, FIELDS, reviewer="ana")
    with pytest.raises(InputRejected):
        agent.reviews.decide(r.id, "iban", reviewer="ana", action="absent")
    with pytest.raises(InputRejected):
        agent.reviews.get("missing")


# ---------------------------------------------------------------- HTTP API

H = {"X-Inklight": "1"}


@pytest.fixture
def client(agent, monkeypatch):
    from fastapi.testclient import TestClient

    from inklight.server import create_app

    monkeypatch.setenv("INKLIGHT_ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("INKLIGHT_PILOT_BASELINE", "pilot-test")
    with TestClient(create_app(agent.settings, agent=agent)) as c:
        yield c


def test_review_over_http(client, agent):
    doc_id = _doc(agent, "acme").id
    r = client.post("/api/reviews", json={"doc_id": doc_id, "reviewer": "ana", "cohort": "dry-run"}, headers=H)
    assert r.status_code == 200, r.text
    review = r.json()
    assert review["baseline"] == "pilot-test" and len(review["fields"]) == 8
    rid = review["id"]
    for f in review["fields"]:
        action = "accepted" if f["predicted"] is not None else "absent"
        body = {"field": f["field"], "action": action, "reviewer": "ana"}
        assert client.post(f"/api/reviews/{rid}/decide", json=body, headers=H).status_code == 200
    bad = client.post(
        f"/api/reviews/{rid}/decide",
        json={"field": "total", "action": "corrected", "value": "x", "reviewer": "ana"},
        headers=H,
    )
    assert bad.status_code == 400 and "not a plain amount" in bad.json()["detail"]
    ok = client.post(f"/api/reviews/{rid}/approve", json={"reviewer": "ben", "active_seconds": 0}, headers=H)
    assert ok.json()["status"] == "approved"
    assert [e["kind"] for e in client.get(f"/api/reviews/{rid}").json()["events"]][-1] == "approved"
    exported = client.post("/api/reviews/export", json={"actor": "ben", "cohort": "dry-run"}, headers=H)
    assert exported.status_code == 200 and "attachment" in exported.headers["content-disposition"]
    assert rid in exported.text
    assert len(client.get("/api/reviews", params={"status": "approved"}).json()) == 1


def test_review_writes_need_the_csrf_header(client, agent):
    r = client.post("/api/reviews", json={"doc_id": _doc(agent, "acme").id, "reviewer": "ana"})
    assert r.status_code == 403


def test_manual_review_over_http_hides_predictions(client, agent):
    body = {"doc_id": _doc(agent, "acme").id, "reviewer": "ana", "mode": "manual", "fields": ["total"]}
    review = client.post("/api/reviews", json=body, headers=H).json()
    assert review["fields"][0]["predicted"] is None
    assert client.get(f"/api/reviews/{review['id']}").json()["fields"][0]["predicted"] is None


# ---------------------------------------------------------------- CLI


def test_review_cli_lists_and_exports_approved_reviews(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from inklight.cli import app as cli_app

    home = tmp_path / "cli-home"
    monkeypatch.setenv("INKLIGHT_HOME", str(home))
    docs = tmp_path / "docs"
    _invoice(docs, "acme", "INVOICE #INV-0001\nVendor: Acme Supplies Ltd.\nTotal: USD 10.00\n")
    with DocumentAgent(make_settings(home)) as a:
        a.add(docs)
        r = a.open_review(a.library.documents()[0].id, ["vendor"], reviewer="ana", cohort="dry-run")
        a.reviews.decide(r.id, "vendor", reviewer="ana", action="accepted")
        a.reviews.approve(r.id, reviewer="ana")
    runner = CliRunner()
    listed = runner.invoke(cli_app, ["review", "list", "--status", "approved"])
    assert listed.exit_code == 0 and r.id in listed.output and "dry-run" in listed.output
    out = tmp_path / "reviews.csv"
    exported = runner.invoke(cli_app, ["review", "export", "--out", str(out), "--actor", "ben"])
    assert exported.exit_code == 0, exported.output
    assert r.id in out.read_text(encoding="utf-8")
    again = runner.invoke(cli_app, ["review", "export", "--out", str(out), "--actor", "ben"])
    assert again.exit_code != 0  # never overwrites an export
    with DocumentAgent(make_settings(home)) as a:
        assert [e["kind"] for e in a.reviews.events(r.id)].count("exported") == 1  # the refused one is not logged
