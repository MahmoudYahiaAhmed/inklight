"""HTTP API (FastAPI TestClient) and CLI (Typer CliRunner)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from inklight.cli import app as cli_app
from inklight.server import create_app

H = {"X-Inklight": "1"}
pytestmark = pytest.mark.ocr


@pytest.fixture
def client(shared_agent, monkeypatch):
    monkeypatch.setenv("INKLIGHT_ALLOWED_HOSTS", "testserver")  # TestClient's host; not allowed by default
    return TestClient(create_app(shared_agent.settings, agent=shared_agent))


def test_status_and_documents(client):
    status = client.get("/api/status").json()
    assert status["name"] == "Inklight" and status["stats"]["documents"] >= 8
    assert any(d["name"] == "invoice_acme.pdf" for d in client.get("/api/documents").json())
    assert client.get("/").status_code == 200 and "inklight" in client.get("/").text


def test_security_headers_and_guards(client):
    r = client.get("/api/status")
    assert r.headers["x-frame-options"] == "DENY" and "default-src 'self'" in r.headers["content-security-policy"]
    assert client.post("/api/ask", json={"request": "hi"}).status_code == 403, "CSRF header required"
    assert client.get("/api/status", headers={"host": "evil.example"}).status_code == 403, "DNS rebinding"


def test_token(monkeypatch, shared_agent):
    monkeypatch.setenv("INKLIGHT_SERVER_TOKEN", "t0k")
    monkeypatch.setenv("INKLIGHT_ALLOWED_HOSTS", "testserver")
    c = TestClient(create_app(shared_agent.settings, agent=shared_agent))
    assert c.get("/api/status").status_code == 401
    assert c.get("/api/status", headers={"X-Inklight-Token": "t0k"}).status_code == 200
    assert c.get("/api/status", params={"token": "tök"}).status_code == 401  # non-ASCII: 401 not 500


def test_testserver_host_not_allowed_by_default(shared_agent):
    c = TestClient(create_app(shared_agent.settings, agent=shared_agent))
    assert c.get("/api/status").status_code == 403


def test_oversized_body_rejected(client):
    r = client.post("/api/ask", headers={**H, "Content-Length": str(10**12)}, content=b"{}")
    assert r.status_code == 413


def test_ask_and_page_image(client):
    r = client.post("/api/ask", headers=H, json={"request": "Find all invoices above $5,000"}).json()
    assert r["state"] == "succeeded" and len(r["records"]) == 2
    src = r["sources"][0]
    img = client.get(f"/api/documents/{src['doc_id']}/pages/{src['page']}/image")
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    doc = client.get(f"/api/documents/{src['doc_id']}").json()
    assert doc["pages"][0]["blocks"]


def test_extract_search_tasks(client):
    ids = [d["id"] for d in client.get("/api/documents").json() if d["doc_type"] == "invoice"]
    rec = client.post("/api/extract", headers=H, json={"doc_ids": ids, "fields": ["total"]}).json()["records"]
    assert len(rec) == 3
    assert client.get("/api/search", params={"q": "termination notice"}).json()
    assert client.get("/api/tasks").json()


def test_bad_inputs(client):
    assert client.get("/api/documents/../../etc/passwd").status_code == 404
    assert client.get("/api/documents/zzz").status_code == 404
    assert client.get("/api/outputs/..%2F..%2Fsecrets.txt").status_code == 404
    assert client.post("/api/ask", headers=H, json={"request": ""}).status_code == 422
    assert client.get("/api/search", params={"q": " "}).status_code == 400


def test_upload_and_delete(client, tmp_path):
    files = [
        ("files", ("note.txt", b"Contract Value: $1,000.00\nExpiration Date: 2030-01-01", "text/plain")),
        ("files", ("evil.exe", b"MZ", "application/octet-stream")),
        ("files", ("empty.pdf", b"", "application/pdf")),
    ]
    r = client.post("/api/documents", headers=H, files=files).json()
    assert [d["name"] for d in r["documents"]] == ["note.txt"]  # the file's own name, no storage prefix
    assert {f["file"] for f in r["failed"]} == {"evil.exe", "empty.pdf"}
    doc_id = r["documents"][0]["id"]
    stored = Path(r["documents"][0]["path"])
    assert stored.exists()
    assert client.delete(f"/api/documents/{doc_id}", headers=H).status_code == 200
    assert client.get(f"/api/documents/{doc_id}").status_code == 404
    assert not stored.exists() and not stored.parent.exists()  # the upload and its own folder are gone


runner = CliRunner()


def test_cli_end_to_end(tmp_path, docs_dir, monkeypatch):
    monkeypatch.setenv("INKLIGHT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("INKLIGHT_MODELS__BRAIN", "rules")
    r = runner.invoke(cli_app, ["process", str(docs_dir)])
    assert r.exit_code == 0, r.output
    assert "8 new" in r.output
    r = runner.invoke(cli_app, ["ask", "Find all invoices above $5,000", "--json"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert data["intent"] == "filter" and len(data["records"]) == 2
    out = tmp_path / "out"
    r = runner.invoke(
        cli_app, ["ask", str(docs_dir / "invoice_acme.pdf"), "export the total as json", "--out", str(out)]
    )
    assert r.exit_code == 0 and list(out.glob("*.json"))
    schema = tmp_path / "s.json"
    schema.write_text(json.dumps({"invoice_number": "id", "total": "money"}))
    r = runner.invoke(
        cli_app, ["extract", str(docs_dir / "invoice_acme.pdf"), "--schema", str(schema), "--format", "csv"]
    )
    assert r.exit_code == 0 and "INV-2041" in r.output
    for cmd in (
        ["docs"],
        ["search", "termination"],
        ["history"],
        ["tools"],
        ["doctor"],
        ["models", "status"],
        ["show", "invoice_acme.pdf"],
        ["--version"],
    ):
        res = runner.invoke(cli_app, cmd)
        assert res.exit_code == 0, (cmd, res.output)
    assert runner.invoke(cli_app, ["remove", "invoice_acme.pdf"]).exit_code == 0
    assert runner.invoke(cli_app, ["remove", "nope.pdf"]).exit_code == 1
    assert runner.invoke(cli_app, ["process", str(tmp_path / "missing")]).exit_code == 0
