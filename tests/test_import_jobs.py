"""Background imports report what actually happens to each file, can be followed after a reload, and can be stopped
between files."""

from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from inklight import DocumentAgent
from inklight.library import Library
from inklight.server import create_app

from .conftest import FakeEngine, make_settings

H = {"X-Inklight": "1"}


class SlowEngine(FakeEngine):
    """Reads two pages per file, reporting each like the real engine, and can be held between files."""

    def __init__(self) -> None:
        super().__init__({"a.png": [["one"], ["two"]], "b.png": [["three"]], "c.png": [["four"]]})
        self.on_page = None
        self.gate = threading.Event()
        self.gate.set()

    def read(self, path, *, max_pages, password=None):  # noqa: ANN001, ANN201
        self.gate.wait(10)
        content = super().read(path, max_pages=max_pages, password=password)
        for page in content.pages:
            if self.on_page:
                self.on_page(page.number, len(content.pages))
        return content


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("INKLIGHT_ALLOWED_HOSTS", "testserver")
    settings = make_settings(tmp_path / "home")
    engine = SlowEngine()
    agent = DocumentAgent(settings, library=Library(settings, engine=engine))
    client = TestClient(create_app(settings, agent=agent))
    yield client, engine
    agent.close()
    agent.library.close()


def _png(name: str) -> tuple[str, tuple[str, bytes, str]]:
    return ("files", (name, b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png"))


def _wait(client: TestClient, job_id: str, states: set[str], timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["state"] in states:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job stayed {job['state']}")


def test_a_background_import_reports_each_file_and_page(setup):
    client, _ = setup
    r = client.post("/api/documents?background=true", headers=H, files=[_png("a.png"), _png("b.png")]).json()
    job = r["job"]
    assert job["kind"] == "import" and [f["name"] for f in job["files"]] == ["a.png", "b.png"]
    done = _wait(client, job["id"], {"completed", "partial", "failed"})
    assert done["state"] == "completed"
    a, b = done["files"]
    assert (a["state"], a["page"], a["pages"]) == ("done", 2, 2)  # the pages the engine reported
    assert b["state"] == "done" and a["doc_id"] and b["doc_id"]
    assert [d["name"] for d in done["result"]["documents"]] == ["a.png", "b.png"]
    assert client.get("/api/jobs").json()[0]["id"] == job["id"]  # found again after a reload


def test_the_event_stream_ends_with_the_final_state(setup):
    client, _ = setup
    job = client.post("/api/documents?background=true", headers=H, files=[_png("a.png")]).json()["job"]
    with client.stream("GET", f"/api/jobs/{job['id']}/events") as stream:
        events = [json.loads(line[6:]) for line in stream.iter_lines() if line.startswith("data: ")]
    assert events[-1]["state"] == "completed"
    versions = [e["version"] for e in events]
    assert versions == sorted(versions)


def test_stopping_an_import_skips_the_files_not_yet_started(setup):
    client, engine = setup
    engine.gate.clear()  # hold the first file
    job = client.post(
        "/api/documents?background=true", headers=H, files=[_png("a.png"), _png("b.png"), _png("c.png")]
    ).json()["job"]
    _wait(client, job["id"], {"running"})
    assert client.post(f"/api/jobs/{job['id']}/cancel", headers=H).json() == {"cancelled": True}
    engine.gate.set()
    done = _wait(client, job["id"], {"cancelled", "completed"})
    assert done["state"] == "cancelled"
    assert [f["state"] for f in done["files"]] == ["done", "cancelled", "cancelled"]
    assert done["result"]["cancelled"] == ["b.png", "c.png"]
    assert client.post(f"/api/jobs/{job['id']}/cancel", headers=H).json() == {"cancelled": False}  # it has ended


def test_a_rejected_file_is_part_of_the_job(setup):
    client, _ = setup
    job = client.post(
        "/api/documents?background=true",
        headers=H,
        files=[_png("a.png"), ("files", ("evil.exe", b"MZ", "application/octet-stream"))],
    ).json()["job"]
    done = _wait(client, job["id"], {"completed", "partial", "failed"})
    assert done["state"] == "partial"
    rejected = done["files"][1]
    assert (rejected["name"], rejected["state"], rejected["error"]) == ("evil.exe", "failed", "unsupported file type")


def test_unknown_jobs(setup):
    client, _ = setup
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/api/jobs/nope/events").status_code == 404
    assert client.get("/api/jobs/nope/files/0/preview").status_code == 404


def test_reading_again_with_structure_needs_the_install(setup, monkeypatch):
    client, _ = setup
    job = client.post("/api/documents?background=true", headers=H, files=[_png("a.png")]).json()["job"]
    doc_id = _wait(client, job["id"], {"completed"})["files"][0]["doc_id"]
    monkeypatch.setattr("inklight.structure.run.available", lambda: False)
    r = client.post(f"/api/documents/{doc_id}/structure", headers=H)
    assert r.status_code == 409 and "inklight[structure]" in r.json()["detail"]
