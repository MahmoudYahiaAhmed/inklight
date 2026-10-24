"""Explicit, idempotent cleanup: connections and models are released, ownership is respected."""

from __future__ import annotations

import gc
import sys
import threading
import time
import warnings

import pytest
from fastapi.testclient import TestClient

from inklight import DocumentAgent, InklightError, Library
from inklight.agent.plan import Intent, Plan, Step
from inklight.agent.tools import TOOLS, Tool, _Args
from inklight.errors import StoreClosed
from inklight.schemas import TaskState
from inklight.server import create_app
from inklight.store import Store

from .conftest import make_settings


def _write(folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "a.txt").write_text("INVOICE #1\nVendor: Acme Ltd.\nTotal: USD 10.00\n", encoding="utf-8")
    return folder


def _resource_warnings(fn) -> list[str]:
    """Run ``fn`` and collect ResourceWarnings raised while its garbage is collected (local, not global)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        fn()
        gc.collect()
    return [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)]


def test_repeated_create_use_close_cycles_leave_nothing_open(tmp_path):
    docs = _write(tmp_path / "docs")

    def cycles():
        for i in range(5):
            with DocumentAgent(make_settings(tmp_path / f"home{i}")) as agent:
                agent.add(docs)
                assert agent.ask("how many invoices are there?", save=False).ok

    assert _resource_warnings(cycles) == []


@pytest.mark.skipif(sys.version_info < (3, 13), reason="sqlite3 warns about unclosed connections only from Python 3.13")
def test_unclosed_agent_is_what_the_warning_check_detects(tmp_path):
    """The check above is meaningful: forgetting close() is visible."""
    docs = _write(tmp_path / "docs")

    def leak():
        agent = DocumentAgent(make_settings(tmp_path / "leak"))
        agent.add(docs)
        del agent

    assert any("unclosed database" in w for w in _resource_warnings(leak))


def test_close_is_idempotent_and_use_after_close_is_a_clear_error(tmp_path):
    agent = DocumentAgent(make_settings(tmp_path / "home"))
    agent.close()
    agent.close()
    assert agent.closed and agent.library.closed and agent.library.store.closed
    with pytest.raises(InklightError, match="closed"):
        agent.ask("how many invoices are there?")
    with pytest.raises(StoreClosed):
        agent.library.documents()


def test_supplied_library_is_not_closed_by_the_agent(tmp_path):
    with Library(make_settings(tmp_path / "home")) as library:
        with DocumentAgent(library.settings, library=library) as agent:
            agent.add(_write(tmp_path / "docs"))
        assert not library.closed and library.documents()  # still usable by its owner
    assert library.closed


def test_supplied_store_is_not_closed_by_the_library(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    with Library(make_settings(tmp_path / "home"), store=store):
        pass
    assert not store.closed
    store.close()


class _NoArgs(_Args):
    pass


def test_close_cancels_running_work_before_releasing_the_database(tmp_path, monkeypatch):
    agent = DocumentAgent(make_settings(tmp_path / "home"))
    started = threading.Event()

    def slow(ctx, _args):
        started.set()
        for _ in range(500):
            ctx.check()  # raises once close() cancels the task
            time.sleep(0.01)
        return "done"

    monkeypatch.setitem(TOOLS, "slow", Tool("slow", "test", _NoArgs, slow))
    plan = Plan(intent=Intent.EXTRACT, query="x", steps=(Step(tool="slow"),))
    results = []
    worker = threading.Thread(target=lambda: results.append(agent.run_plan(plan, [], save=False)))
    worker.start()
    assert started.wait(5)
    t0 = time.monotonic()
    agent.close()
    worker.join(5)
    assert time.monotonic() - t0 < 3
    assert results and results[0].state == TaskState.CANCELLED
    assert agent.library.store.closed


def test_server_closes_only_what_it_created(tmp_path, monkeypatch):
    monkeypatch.setenv("INKLIGHT_ALLOWED_HOSTS", "testserver")
    settings = make_settings(tmp_path / "home")
    app = create_app(settings)
    with TestClient(app) as client:  # the app owns its agent
        assert client.get("/api/status").status_code == 200
        assert client.post("/api/settings", headers={"X-Inklight": "1"}, json={"brain": "rules"}).status_code == 200
        current = app.state.inklight["agent"]
        assert not current.library.store.closed
    assert current.closed and current.library.store.closed  # shutdown released the swapped agent and the store
    with DocumentAgent(settings) as mine:
        with TestClient(create_app(settings, agent=mine)) as client:
            client.get("/api/status")
        assert not mine.closed  # the caller's agent survives app shutdown
