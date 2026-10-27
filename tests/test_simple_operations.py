"""The direct operations need no question, plan or model choice: text, tables, named fields."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from inklight import DocumentAgent
from inklight.cli import app as cli_app
from inklight.errors import InputRejected
from inklight.exports import RAW_NOTE

from .conftest import make_settings

runner = CliRunner()


def test_text_is_the_raw_reading_page_by_page(tmp_path, docs_dir):
    with DocumentAgent(make_settings(tmp_path / "home")) as agent:
        body = agent.text(docs_dir / "invoice_acme.pdf")
    assert body.startswith(f"# {RAW_NOTE}")
    assert "===== page 1 =====" in body and "INV-2041" in body


def test_tables_say_what_they_need_when_structure_is_off(tmp_path, docs_dir):
    with DocumentAgent(make_settings(tmp_path / "home")) as agent, pytest.raises(InputRejected, match="structure"):
        agent.tables(docs_dir / "invoice_acme.pdf")


def test_an_unreadable_file_is_reported_by_name(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4\nnot really a pdf")
    with DocumentAgent(make_settings(tmp_path / "home")) as agent, pytest.raises(InputRejected, match="broken.pdf"):
        agent.text(broken)


def test_cli_text_and_fields(tmp_path, docs_dir, monkeypatch):
    monkeypatch.setenv("INKLIGHT_HOME", str(tmp_path / "home"))
    r = runner.invoke(cli_app, ["text", str(docs_dir / "invoice_acme.pdf")])
    assert r.exit_code == 0, r.output
    assert "INV-2041" in r.output
    out = tmp_path / "acme.txt"
    assert runner.invoke(cli_app, ["text", str(docs_dir / "invoice_acme.pdf"), "-o", str(out)]).exit_code == 0
    assert RAW_NOTE in out.read_text(encoding="utf-8")
    r = runner.invoke(cli_app, ["extract", str(docs_dir / "invoice_acme.pdf")])
    assert r.exit_code == 1 and "Name the fields" in r.output  # no invoice schema assumed
    r = runner.invoke(cli_app, ["extract", str(docs_dir / "invoice_acme.pdf"), "--fields", "total", "--format", "csv"])
    assert r.exit_code == 0 and "total" in r.output


def test_cli_tables_without_the_structure_install(tmp_path, docs_dir, monkeypatch):
    monkeypatch.setenv("INKLIGHT_HOME", str(tmp_path / "home"))
    monkeypatch.setattr("inklight.structure.run.available", lambda: False)
    r = runner.invoke(cli_app, ["tables", str(docs_dir / "invoice_acme.pdf")])
    assert r.exit_code == 1 and "inklight[structure]" in r.output
