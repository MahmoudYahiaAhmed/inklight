"""Public demo: two visitors never see each other's documents, jobs, reviews, questions or exports; the owner's
library is never used; sessions expire and their files are removed; uploads, the queue and request rates are bounded.
"""

import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from inklight import DocumentAgent
from inklight.ocr import register_engine
from inklight.schemas import DocumentContent, PageContent, TextLine
from inklight.server import create_app
from inklight.server.demo import DemoBusy
from inklight.server.hosting import DemoLimits, Hosting

from .conftest import make_settings

H = {"X-Inklight": "1"}


class _Scans:
    """Reads a PNG as one OCR page: its file name, so each visitor's document says whose it is. Loads no model."""

    name = "demo-scans"

    def __init__(self, settings):
        pass

    def supports(self, kind):
        return kind == "png"

    def read(self, path, *, max_pages, password=None):
        line = TextLine(text=f"Scanned page of {path.stem}", conf=0.95, bbox=(10, 10, 300, 30))
        page = PageContent(number=1, source="ocr", markdown=line.text, lines=(line,))
        return DocumentContent(path=str(path), pages=(page,), total_pages=1, engine=self.name)


register_engine("demo-scans", _Scans)


@pytest.fixture
def owner(tmp_path):
    """The owner's own library, with a private document in it: a demo must never reach it."""
    home = tmp_path / "owner-home"
    private = tmp_path / "owner-private.txt"
    private.write_text("Owner salary list: confidential\n", encoding="utf-8")
    with DocumentAgent(make_settings(home)) as agent:
        agent.add([private])
    return home


def _demo(tmp_path, owner, **limits):
    settings = make_settings(owner, ocr={"engine": "demo-scans"})
    hosting = Hosting(
        mode="demo",
        allowed_hosts=frozenset({"testserver"}),
        demo=DemoLimits(**limits),
        demo_dir=tmp_path / "demo-data",
    )
    return create_app(settings, hosting=hosting)


def _visitor(app):
    c = TestClient(app)
    assert c.get("/api/status").status_code == 200  # loading the workspace starts the session
    return c


def _upload(c, path, mime="text/plain"):
    with path.open("rb") as fh:
        r = c.post("/api/documents?background=true", headers=H, files={"files": (path.name, fh, mime)})
    assert r.status_code == 200, r.text
    job = r.json()["job"]
    for _ in range(200):
        snap = c.get(f"/api/jobs/{job['id']}").json()
        if snap["state"] in ("completed", "partial", "failed", "cancelled"):
            return snap
        time.sleep(0.05)
    raise AssertionError("import did not finish")


def _files(tmp_path):
    a = tmp_path / "alpha-notes.txt"
    a.write_text("Alpha visitor: Cedar Lane Bakery, رقم القيد 55120\n", encoding="utf-8")
    b = tmp_path / "beta-notes.txt"
    b.write_text("Beta visitor: Harbor Mills, المورد مطاحن الميناء\n", encoding="utf-8")
    scan = tmp_path / "alpha-scan.png"
    Image.new("RGB", (320, 60), "white").save(scan)
    return a, b, scan


def test_two_visitors_never_reach_each_others_data(tmp_path, owner):
    app = _demo(tmp_path, owner)
    a_file, b_file, scan = _files(tmp_path)
    with TestClient(app) as _:
        alice, bob = _visitor(app), _visitor(app)
        assert alice.cookies.get("inklight_demo") != bob.cookies.get("inklight_demo")
        a_job = _upload(alice, a_file)
        s_job = _upload(alice, scan, "image/png")
        b_job = _upload(bob, b_file)
        assert a_job["state"] == s_job["state"] == b_job["state"] == "completed"
        a_doc, scan_doc = a_job["files"][0]["doc_id"], s_job["files"][0]["doc_id"]

        assert {d["name"] for d in alice.get("/api/documents").json()} == {"alpha-notes.txt", "alpha-scan.png"}
        assert [d["name"] for d in bob.get("/api/documents").json()] == ["beta-notes.txt"]
        # the owner's library is not listed, searched or touched
        for c in (alice, bob):
            assert "owner-private.txt" not in c.get("/api/documents").text
            assert c.get("/api/search", params={"q": "salary"}).json() == []

        # every way to reach Alice's document, job, preview and export from Bob's session
        for path in (f"/api/documents/{a_doc}", f"/api/documents/{a_doc}/export?format=txt",
                     f"/api/documents/{a_doc}/tables", f"/api/documents/{scan_doc}/pages/1/image",
                     f"/api/documents/{a_doc}/structure?format=meta", f"/api/jobs/{a_job['id']}",
                     f"/api/jobs/{a_job['id']}/events", f"/api/jobs/{s_job['id']}/files/0/preview"):  # fmt: skip
            assert bob.get(path).status_code == 404, path
            assert alice.get(path).status_code in (200, 404 if "structure" in path or "preview" in path else 200), path
        assert alice.get(f"/api/documents/{scan_doc}/pages/1/image").headers["content-type"] == "image/png"
        assert bob.delete(f"/api/documents/{a_doc}", headers=H).status_code == 404
        assert bob.post(f"/api/jobs/{a_job['id']}/cancel", headers=H).json() == {"cancelled": False}
        assert bob.post("/api/extract", headers=H, json={"doc_ids": [a_doc], "fields": ["x"]}).status_code == 404
        assert bob.get("/api/jobs").json() and all(j["id"] == b_job["id"] for j in bob.get("/api/jobs").json())
        assert bob.get("/api/search", params={"q": "Cedar"}).json() == []
        assert alice.get("/api/search", params={"q": "Cedar"}).json()[0]["source"]["name"] == "alpha-notes.txt"

        # reviews and their export
        review = alice.post("/api/reviews", headers=H, json={"doc_id": a_doc, "reviewer": "Alice", "fields": ["x"]})
        assert review.status_code == 200, review.text
        rid = review.json()["id"]
        # another session's review answers exactly as an id that never existed
        unknown = {"detail": "Unknown review '0000000000000000'"}
        assert bob.get("/api/reviews/0000000000000000").json() == unknown
        assert bob.get(f"/api/reviews/{rid}").json() == {"detail": f"Unknown review '{rid}'"}
        attempts = [
            ("decide", {"field": "x", "action": "absent", "reviewer": "Bob"}),
            ("approve", {"reviewer": "Bob"}),
            ("reopen", {"reviewer": "Bob", "reason": "x"}),
        ]
        for action, body in attempts:
            r = bob.post(f"/api/reviews/{rid}/{action}", headers=H, json=body)
            assert r.status_code == 400 and r.json()["detail"].startswith("Unknown review"), (action, r.text)
        assert bob.post("/api/reviews", headers=H, json={"doc_id": a_doc, "reviewer": "Bob"}).status_code in (400, 404)
        assert bob.get("/api/reviews").json() == []
        alice.post(f"/api/reviews/{rid}/decide", headers=H,
                   json={"field": "x", "action": "absent", "reviewer": "Alice"})  # fmt: skip
        alice.post(f"/api/reviews/{rid}/approve", headers=H, json={"reviewer": "Alice"})
        exported = bob.post("/api/reviews/export", headers=H, json={"actor": "Bob", "format": "json"})
        assert exported.status_code == 200 and exported.json() == []

        # questions
        task = alice.post("/api/ask", headers=H, json={"request": "What is the company name?", "allow_write": True})
        assert task.status_code == 200
        assert not any((demo_dir := app.state.inklight["demo"].root).rglob("outputs/*")), demo_dir  # nothing saved
        tid = task.json()["task_id"]
        assert bob.get(f"/api/tasks/{tid}").status_code == 404 and bob.get("/api/tasks").json() == []
        assert alice.get(f"/api/tasks/{tid}").status_code == 200

        # the owner's settings and saved outputs are not reachable
        assert alice.post("/api/settings", headers=H, json={"brain": "auto"}).status_code == 403
        assert alice.get("/api/outputs/anything.csv").status_code == 403


def test_owner_library_is_never_opened(tmp_path, owner):
    before = (owner / "library.db").stat().st_mtime_ns
    app = _demo(tmp_path, owner)
    with TestClient(app) as _:
        c = _visitor(app)
        _upload(c, _files(tmp_path)[0])
        demo = app.state.inklight["demo"]
        assert app.state.inklight["agent"] is None
        assert owner not in demo.root.parents and demo.root != owner
    assert (owner / "library.db").stat().st_mtime_ns == before


def test_requests_without_a_session_are_refused(tmp_path, owner):
    app = _demo(tmp_path, owner)
    with TestClient(app) as anonymous:
        for path in ("/api/documents", "/api/jobs", "/api/reviews", "/api/tasks"):
            r = anonymous.get(path)
            assert r.status_code == 401 and "Reload the page" in r.json()["detail"], path
        anonymous.cookies.set("inklight_demo", "forged-value")
        assert anonymous.get("/api/documents").status_code == 401
        c = _visitor(app)
        cookie = next(k for k in c.cookies.jar if k.name == "inklight_demo")
        assert (
            cookie.has_nonstandard_attr("HttpOnly") and cookie.get_nonstandard_attr("SameSite", "").lower() == "strict"
        )
        status = c.get("/api/status").json()["hosting"]
        assert status["mode"] == "demo" and status["minutes"] == 60 and status["shared_library"] is False
        assert status["expires_at"] > time.time() + 59 * 60


def test_expired_sessions_are_refused_and_their_files_removed(tmp_path, owner):
    app = _demo(tmp_path, owner)
    with TestClient(app) as _:
        c = _visitor(app)
        _upload(c, _files(tmp_path)[0])
        demo = app.state.inklight["demo"]
        session = demo.get(c.cookies.get("inklight_demo"))
        folder = session.folder
        assert any(folder.rglob("alpha-notes.txt"))
        session.asking.acquire()  # a request still running: its files must stay
        session.expires = time.time() - 1
        assert c.get("/api/documents").status_code == 401  # ended for the visitor at once
        assert demo.sweep() == 0 and folder.exists()
        session.asking.release()
        assert demo.sweep() == 1 and not folder.exists()
        fresh = _visitor(app)  # reloading starts a new, empty session
        assert fresh.get("/api/documents").json() == []


def test_demo_folder_is_removed_when_the_server_stops(tmp_path, owner):
    settings = make_settings(owner, ocr={"engine": "demo-scans"})
    app = create_app(settings, hosting=Hosting(mode="demo", allowed_hosts=frozenset({"testserver"})))
    with TestClient(app) as _:
        c = _visitor(app)
        _upload(c, _files(tmp_path)[0])
        root = app.state.inklight["demo"].root
        assert root.exists() and "inklight-demo-" in root.name
    assert not root.exists()


def test_upload_limits(tmp_path, owner):
    app = _demo(tmp_path, owner, max_files_per_upload=2, max_documents=3, max_file_mb=0.01)
    a, b, _ = _files(tmp_path)
    big = tmp_path / "big.txt"
    big.write_text("x" * 15000, encoding="utf-8")  # over 10 KB, under the request limit
    exe = tmp_path / "tool.exe"
    exe.write_bytes(b"MZ")
    with TestClient(app) as _:
        c = _visitor(app)
        files = [("files", (p.name, p.read_bytes(), "text/plain")) for p in (a, b, big)]
        r = c.post("/api/documents?background=true", headers=H, files=files)
        assert r.status_code == 413 and "at most 2" in r.json()["detail"]
        assert c.post("/api/documents", headers=H, files=[files[0]]).status_code == 400  # background only
        snap = _upload(c, big)
        assert snap["state"] == "failed" and "MB" in snap["files"][0]["error"]
        snap = _upload(c, exe, "application/octet-stream")
        assert snap["files"][0]["error"] == "unsupported file type"
        _upload(c, a)
        _upload(c, b)
        third = tmp_path / "third.txt"
        third.write_text("third\n", encoding="utf-8")
        _upload(c, third)
        r = c.post("/api/documents?background=true", headers=H, files=[("files", ("more.txt", b"x", "text/plain"))])
        assert r.status_code == 413 and "at most 3 documents" in r.json()["detail"]


def test_queue_is_bounded_and_shared(tmp_path, owner):
    app = _demo(tmp_path, owner, queue=1)
    a, b, _ = _files(tmp_path)
    with TestClient(app) as _:
        alice, bob = _visitor(app), _visitor(app)
        demo = app.state.inklight["demo"]
        demo.runner.acquire()  # the OCR slot is busy: Alice's import waits in the queue
        try:
            with a.open("rb") as fh:
                r = alice.post("/api/documents?background=true", headers=H, files={"files": (a.name, fh, "text/plain")})
            assert r.json()["job"]["state"] == "queued"
            with b.open("rb") as fh:
                r = bob.post("/api/documents?background=true", headers=H, files={"files": (b.name, fh, "text/plain")})
            assert r.status_code == 429 and "The demo is busy" in r.json()["detail"]
        finally:
            demo.runner.release()
        for _ in range(200):
            if demo.pending() == 0:
                break
            time.sleep(0.05)
        assert _upload(bob, b)["state"] == "completed"


def test_request_rate_and_session_limits(tmp_path, owner):
    app = _demo(tmp_path, owner, requests_per_minute=3, max_sessions=2)
    with TestClient(app) as _:
        c = _visitor(app)
        codes = [c.post("/api/ask", headers=H, json={"request": "hello"}).status_code for _ in range(4)]
        assert codes[:3] == [200, 200, 200] and codes[3] == 429
        _visitor(app)
        third = TestClient(app).get("/api/status")
        assert third.status_code == 503 and "full" in third.json()["detail"]
    app = _demo(tmp_path, owner, sessions_per_address_per_hour=1)
    with TestClient(app) as _:
        _visitor(app)
        again = TestClient(app).get("/api/status")
        assert again.status_code == 429 and "this address" in again.json()["detail"]


def test_one_ocr_engine_is_shared_by_every_visitor(tmp_path, owner):
    app = _demo(tmp_path, owner)
    with TestClient(app) as _:
        alice, bob = _visitor(app), _visitor(app)
        demo = app.state.inklight["demo"]
        sa = demo.get(alice.cookies.get("inklight_demo"))
        sb = demo.get(bob.cookies.get("inklight_demo"))
        assert sa.agent.library.engine is sb.agent.library.engine is demo.engine
        assert sa.agent.library.store is not sb.agent.library.store and sa.folder != sb.folder
        assert sa.agent.settings.models.brain == "rules" and sa.agent.settings.models.remote_base_url is None


def test_a_body_without_a_declared_length_is_refused(tmp_path, owner):
    app = _demo(tmp_path, owner)
    with TestClient(app) as _:
        c = _visitor(app)

        def chunks():
            yield b"--x\r\nContent-Disposition: form-data; name=files; filename=a.txt\r\n\r\nhi\r\n--x--\r\n"

        r = c.post(
            "/api/documents?background=true",
            headers={**H, "Content-Type": "multipart/form-data; boundary=x"},
            content=chunks(),
        )
        assert r.status_code == 411


def test_queue_places_are_taken_in_one_step(tmp_path, owner):
    """Parallel uploads cannot all pass a queue check made before any of them is counted."""
    app = _demo(tmp_path, owner, queue=1)
    with TestClient(app) as _:
        alice, bob = _visitor(app), _visitor(app)
        demo = app.state.inklight["demo"]
        sa = demo.get(alice.cookies.get("inklight_demo"))
        sb = demo.get(bob.cookies.get("inklight_demo"))
        with demo.admit(sa, 1):  # Alice's upload is still arriving: not a job yet, but its place is taken
            with pytest.raises(DemoBusy) as busy, demo.admit(sb, 1):
                pass
            assert "The demo is busy" in str(busy.value)
        with demo.admit(sb, 1):  # released when Alice's upload was registered (or failed)
            pass


def test_one_import_at_a_time_per_visitor_and_waiting_files_count(tmp_path, owner):
    app = _demo(tmp_path, owner, max_documents=2)
    a, b, _ = _files(tmp_path)
    with TestClient(app) as _:
        c = _visitor(app)
        demo = app.state.inklight["demo"]
        demo.runner.acquire()  # the OCR slot is busy: the first import waits
        try:
            with a.open("rb") as fh:
                assert c.post("/api/documents?background=true", headers=H,
                              files={"files": (a.name, fh, "text/plain")}).status_code == 200  # fmt: skip
            with b.open("rb") as fh:
                r = c.post("/api/documents?background=true", headers=H, files={"files": (b.name, fh, "text/plain")})
            assert r.status_code == 429 and "previous import" in r.json()["detail"]
            session = demo.get(c.cookies.get("inklight_demo"))
            with pytest.raises(DemoBusy), demo.admit(session, 2):  # the waiting file counts against the limit
                pass
        finally:
            demo.runner.release()


def test_reads_are_rate_limited_too(tmp_path, owner):
    app = _demo(tmp_path, owner, reads_per_minute=5)
    with TestClient(app) as _:
        c = _visitor(app)
        codes = [c.get("/api/documents").status_code for _ in range(6)]
        assert codes[-1] == 429 and codes.count(200) == 4  # the status request that started the session counted


def test_a_session_answering_a_request_is_not_removed(tmp_path, owner):
    app = _demo(tmp_path, owner)
    with TestClient(app) as _:
        c = _visitor(app)
        demo = app.state.inklight["demo"]
        session = demo.get(c.cookies.get("inklight_demo"))
        with demo.serving(session):
            session.expires = time.time() - 1
            assert demo.sweep() == 0 and session.folder.exists()
        assert demo.sweep() == 1


def test_api_schema_needs_a_session(tmp_path, owner):
    app = _demo(tmp_path, owner)
    with TestClient(app) as anonymous:
        assert anonymous.get("/openapi.json").status_code in (404, 405)  # not served outside /api/
        assert anonymous.get("/api/openapi.json").status_code == 401
        c = _visitor(app)
        assert c.get("/api/openapi.json").status_code == 200


def test_ipv6_visitors_are_counted_by_their_network():
    from inklight.server.demo import _network

    assert _network("2001:db8:1:2::5") == _network("2001:db8:1:2:ffff::9") == "2001:db8:1:2::/64"
    assert _network("2001:db8:1:3::5") != _network("2001:db8:1:2::5")
    assert _network("203.0.113.7") == "203.0.113.7" and _network("::ffff:203.0.113.7") == "203.0.113.7"
