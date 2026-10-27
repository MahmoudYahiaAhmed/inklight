"""How a document was read is named for what happened: a .txt file is plain text, never "read by OCR".

Reproduced on 8e860e6: an Arabic .txt file was labelled "read by OCR" in the workspace, which called every page
that was not a PDF text layer OCR. Pages record their source; the label now comes from it, the same in the
workspace (/api/documents read_as), the CLI (`inklight docs`) and read_as.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from inklight import DocumentAgent
from inklight.cli import app as cli_app
from inklight.read_as import method, read_as
from inklight.server import create_app

from .conftest import make_settings
from .factory import _image, _pdf

H = {"X-Inklight": "1"}
ARABIC = "شركة النور للتجارة\nرقم السجل التجاري: 12345\n"


def test_labels():
    assert read_as({"plain": 1}) == "plain text"
    assert read_as({"text": 3}) == "PDF text layer"
    assert read_as({"ocr": 2}) == "OCR"
    assert read_as({"hybrid": 1}) == "PDF text layer and OCR"
    assert read_as({"text": 2, "ocr": 1}) == "mixed: 2 pages PDF text layer, 1 page OCR"
    assert read_as({"error": 1}) == "page failed" and read_as({}) == ""
    assert read_as({"text": 1, "error": 1}) == "PDF text layer"
    assert method("something-new") == "something-new"  # an unknown source is never assumed to be OCR


def _library(tmp_path, scanned: bool = False):  # noqa: ANN202
    txt = tmp_path / "سجل.txt"
    txt.write_text(ARABIC, encoding="utf-8")
    pdf = _pdf(tmp_path / "digital.pdf", [[("ACME Ltd", 12), ("Registration Number: 12345", 11)]])
    files = [txt, pdf]
    if scanned:
        files.append(_image(pdf, tmp_path / "scan.png"))
    agent = DocumentAgent(make_settings(tmp_path / "home"))
    agent.add(files)
    return agent


def test_text_file_and_digital_pdf_are_labelled_by_their_source(tmp_path, monkeypatch):
    with _library(tmp_path) as agent:
        monkeypatch.setenv("INKLIGHT_ALLOWED_HOSTS", "testserver")
        docs = TestClient(create_app(agent.settings, agent=agent)).get("/api/documents", headers=H).json()
        by_name = {d["name"]: d for d in docs}
        assert by_name["سجل.txt"]["read_as"] == {"plain": 1}, by_name["سجل.txt"]
        assert by_name["digital.pdf"]["read_as"] == {"text": 1}, by_name["digital.pdf"]
        assert {"id", "name", "status", "pages"} <= by_name["digital.pdf"].keys()  # the existing fields are kept


def test_cli_docs_lists_how_each_document_was_read(tmp_path, monkeypatch):
    monkeypatch.setenv("INKLIGHT_HOME", str(tmp_path / "home"))
    txt = tmp_path / "note.txt"
    txt.write_text(ARABIC, encoding="utf-8")
    runner = CliRunner()
    processed = runner.invoke(cli_app, ["process", str(txt)])
    assert processed.exit_code == 0 and "plain text" in processed.output, processed.output
    out = runner.invoke(cli_app, ["docs"]).output
    assert "read as" in out and "plain text" in out and "OCR\n" not in out, out


@pytest.mark.ocr
def test_scanned_image_is_labelled_ocr(tmp_path):
    with _library(tmp_path, scanned=True) as agent:
        sources = agent.library.store.page_sources()
        scan = next(d for d in agent.library.documents() if d.name == "scan.png")
        assert sources[scan.id] == {"ocr": 1}, sources[scan.id]
        assert read_as(sources[scan.id]) == "OCR"
