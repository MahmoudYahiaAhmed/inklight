"""The workspace's document endpoints: structure status, tables, raw exports, and the build shown to the user.

The structure is fixed (structure_fixtures.py, docling-core's own data model; no Docling model runs) and so is the
OCR (fixed lines). Requests go through the FastAPI app as the browser sends them.
"""

from __future__ import annotations

import csv
import io
import json

import pytest

pytest.importorskip("docling_core")

from fastapi.testclient import TestClient  # noqa: E402

from inklight import DocumentAgent, __version__  # noqa: E402
from inklight.library import Library  # noqa: E402
from inklight.server import create_app  # noqa: E402

from . import structure_fixtures as fx  # noqa: E402
from .conftest import make_settings  # noqa: E402
from .test_structure import PNG, FixedOCR, _fixed_structure  # noqa: E402

H = {"X-Inklight": "1"}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("workspace")
    pages = {"card-ar.png": fx.arabic_card()}
    (tmp / "card-ar.png").write_bytes(PNG + b"workspace")
    settings = make_settings(tmp / "home", structure={"engine": "docling"})
    mp = pytest.MonkeyPatch()
    mp.setenv("INKLIGHT_ALLOWED_HOSTS", "testserver")  # TestClient's host; not allowed by default
    mp.setattr("inklight.structure.run.preload", lambda settings: None)
    mp.setattr("inklight.structure.structure_document", _fixed_structure(pages))
    agent = DocumentAgent(settings, library=Library(settings, engine=FixedOCR(pages)))
    agent.add([tmp / "card-ar.png"])
    with TestClient(create_app(settings, agent)) as c:
        yield c, agent.library.documents()[0].id
    mp.undo()
    agent.close()


def test_status_shows_version_and_commit(client):
    c, _ = client
    s = c.get("/api/status").json()
    assert s["version"] == __version__ and s["commit"]


def test_document_says_whether_structure_is_available(client):
    c, doc = client
    data = c.get(f"/api/documents/{doc}").json()
    assert data["structure"]["available"] is True
    assert data["structure"]["tables"] == 3
    assert data["structure"]["pages"]["1"].startswith("structured")


def test_tables_are_grids_with_their_header_rows(client):
    c, doc = client
    tables = c.get(f"/api/documents/{doc}/tables").json()
    assert len(tables) == 3
    first = tables[0]
    assert first["page"] == 1 and first["header_rows"] == [0]
    assert "اسم الشركة" in first["rows"][0] and "شركة النخيل الذهبي للتجارة" in first["rows"][1]


@pytest.mark.parametrize("fmt", ["txt", "json", "tables.csv"])
def test_raw_exports_say_they_are_not_reviewed(client, fmt):
    c, doc = client
    r = c.get(f"/api/documents/{doc}/export", params={"format": fmt})
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    body = r.content.decode("utf-8-sig")
    if fmt == "json":
        data = json.loads(body)
        assert data["note"].startswith("Raw extraction") and "not reviewed" in data["note"]
        assert data["pages"][0]["lines"][0]["bbox"] and len(data["tables"]) == 3
        assert "path" not in data["document"]  # no local path in a shared file
    if fmt == "tables.csv":
        rows = list(csv.reader(io.StringIO(body)))
        assert rows[0] == ["table", "page", "row", "column", "header", "text", "note"]  # a header spreadsheets read
        assert "not reviewed" in rows[1][6]
        assert any(row[5] == "٤٧٣١٩" for row in rows[1:])
    if fmt == "txt":
        assert "not reviewed" in body.splitlines()[0]
    if fmt == "txt":
        assert "شركة النخيل الذهبي للتجارة" in body


def test_an_unknown_export_format_is_refused(client):
    c, doc = client
    assert c.get(f"/api/documents/{doc}/export", params={"format": "docx"}).status_code == 400


def test_a_document_without_structure_says_why(tmp_path, monkeypatch):
    monkeypatch.setenv("INKLIGHT_ALLOWED_HOSTS", "testserver")
    (tmp_path / "note.txt").write_text("Registration number: 760413", encoding="utf-8")
    settings = make_settings(tmp_path / "home")
    with DocumentAgent(settings) as agent:
        agent.add([tmp_path / "note.txt"])
        doc = agent.library.documents()[0].id
        with TestClient(create_app(settings, agent)) as c:
            data = c.get(f"/api/documents/{doc}").json()
            assert data["structure"]["available"] is False and "off" in data["structure"]["reason"]
            assert c.get(f"/api/documents/{doc}/tables").json() == []
