"""Runner limits/permissions and library behaviour, with a fake OCR engine (no Indra needed)."""

import threading
import time
from pathlib import Path

import pytest

from inklight import DocumentAgent
from inklight.agent import Policy
from inklight.agent.plan import Intent, Plan, Step
from inklight.agent.tools import TOOLS, Tool, _Args
from inklight.errors import ToolError
from inklight.library import Library
from inklight.schemas import StepStatus, TaskState

from .conftest import FakeEngine, make_settings


@pytest.fixture
def fake_agent(tmp_path):
    settings = make_settings(tmp_path / "home")
    engine = FakeEngine(
        {
            "a.png": [["INVOICE #A-1", "Vendor: Foo Ltd.", "Total: $10.00"]],
            "b.png": [["INVOICE #B-2", "Vendor: Bar Inc.", "Total: $20.00"], ["Page two text"]],
        }
    )
    lib = Library(settings, engine=engine)
    for name in ("a.png", "b.png"):
        (tmp_path / name).write_bytes(b"\x89PNG\r\n\x1a\n" + name.encode())
    return DocumentAgent(settings, library=lib), engine, tmp_path


def test_ingest_dedupe_and_unchanged(fake_agent):
    agent, engine, folder = fake_agent
    first = agent.add(folder)
    assert len(first.added) == 2 and engine.calls == 2
    again = agent.add(folder)
    assert len(again.unchanged) == 2 and engine.calls == 2
    twin = folder / "copy" / "a.png"
    twin.parent.mkdir()
    twin.write_bytes((folder / "a.png").read_bytes())
    report = agent.add(twin)
    assert report.added and engine.calls == 2, "identical content must reuse the stored OCR"
    assert "Foo Ltd" in agent.library.text(report.added[0].id)


def test_changed_file_is_reprocessed_and_removed(fake_agent):
    agent, engine, folder = fake_agent
    agent.add(folder / "a.png")
    (folder / "a.png").write_bytes(b"\x89PNG\r\n\x1a\nchanged")
    assert agent.add(folder / "a.png").added and engine.calls == 2
    doc = agent.library.find("a.png")
    assert agent.library.remove(doc.id) and agent.library.find("a.png") is None


def test_ocr_failure_is_reported_not_raised(tmp_path):
    settings = make_settings(tmp_path / "home")
    agent = DocumentAgent(settings, library=Library(settings, engine=FakeEngine(fail=True)))
    (tmp_path / "x.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    report = agent.add(tmp_path / "x.png")
    assert report.failed and "exploded" in report.failed[0][1]
    assert agent.library.documents()[0].status.value == "failed"


def test_page_limit(tmp_path):
    settings = make_settings(tmp_path / "home", limits={"max_pages": 1})
    engine = FakeEngine({"m.png": [["p1"], ["p2"], ["p3"]]})
    lib = Library(settings, engine=engine)
    (tmp_path / "m.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    doc = lib.add(tmp_path / "m.png").added[0]
    assert doc.pages == 1 and doc.total_pages == 3


def _plan(*steps: Step) -> Plan:
    return Plan(intent=Intent.EXTRACT, query="t", fields=("total",), steps=steps)


def test_max_steps(fake_agent):
    agent, _, folder = fake_agent
    agent.add(folder)
    agent.runner.max_steps = 1
    plan = _plan(Step(tool="inspect_documents"), Step(tool="extract_fields", args={"fields": ["total"]}))
    result = agent.run_plan(plan, [d.id for d in agent.library.documents()])
    assert result.state == TaskState.PARTIAL and len(result.trace) == 1


def test_unknown_tool_and_bad_args_rejected(fake_agent):
    agent, _, folder = fake_agent
    agent.add(folder)
    ids = [d.id for d in agent.library.documents()]
    result = agent.run_plan(_plan(Step(tool="shell", args={"cmd": "rm -rf /"})), ids)
    assert result.trace[0].status == StepStatus.DENIED
    result = agent.run_plan(_plan(Step(tool="extract_fields", args={"fields": ["../../etc"]})), ids)
    assert result.trace[0].status == StepStatus.FAILED and "invalid" in result.trace[0].summary


def test_no_dangerous_tools_exist():
    assert not {"shell", "exec", "python", "delete", "http", "fetch"} & set(TOOLS)
    assert {t.name for t in TOOLS.values() if t.permission == "write"} == {"write_output"}


class _SlowArgs(_Args):
    pass


def test_step_timeout_and_cancel(fake_agent, monkeypatch):
    agent, _, folder = fake_agent
    agent.add(folder)

    def slow(ctx, _args):
        for _ in range(200):
            ctx.check()
            time.sleep(0.01)
        return "done"

    monkeypatch.setitem(TOOLS, "slow", Tool("slow", "test", _SlowArgs, slow))
    agent.runner.step_timeout = 0.2
    result = agent.run_plan(_plan(Step(tool="slow")), [])
    assert result.state == TaskState.CANCELLED and "budget" in result.trace[0].error
    cancel = threading.Event()
    cancel.set()
    result = agent.run_plan(_plan(Step(tool="slow")), [], cancel=cancel)
    assert result.state == TaskState.CANCELLED


def test_recoverable_retry(fake_agent, monkeypatch):
    agent, _, _ = fake_agent
    calls = {"n": 0}

    def flaky(_ctx, _args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ToolError("transient", recoverable=True)
        return "ok"

    monkeypatch.setitem(TOOLS, "flaky", Tool("flaky", "test", _SlowArgs, flaky))
    result = agent.run_plan(_plan(Step(tool="flaky")), [])
    assert result.trace[0].status == StepStatus.OK and result.trace[0].attempts == 2


def test_tool_crash_is_contained(fake_agent, monkeypatch):
    agent, _, _ = fake_agent
    monkeypatch.setitem(TOOLS, "boom", Tool("boom", "test", _SlowArgs, lambda c, a: 1 / 0))
    result = agent.run_plan(_plan(Step(tool="boom")), [])
    assert result.state == TaskState.FAILED and "ZeroDivisionError" in result.trace[0].error


def test_write_policy_and_csv_formula_neutralised(fake_agent, tmp_path):
    agent, engine, folder = fake_agent
    engine.pages["a.png"] = [['Vendor: =HYPERLINK("http://x")', "Total: $10.00"]]
    agent.add(folder)
    out = tmp_path / "out"
    result = agent.ask("export vendor and total as csv", policy=Policy(allow_write=True, output_dir=out))
    text = Path(result.files_written[0]).read_text(encoding="utf-8")
    assert "'=HYPERLINK" in text


def test_tool_timeout_error_is_retryable_not_cancel(fake_agent, monkeypatch):
    agent, _, _ = fake_agent
    calls = {"n": 0}

    def sock(_ctx, _args):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("socket timed out")
        return "ok"

    monkeypatch.setitem(TOOLS, "sock", Tool("sock", "test", _SlowArgs, sock))
    result = agent.run_plan(_plan(Step(tool="sock")), [])
    assert result.state != TaskState.CANCELLED and result.trace[0].attempts == 2


def test_timeout_does_not_block_and_result_is_stable(fake_agent, monkeypatch):
    agent, _, _ = fake_agent

    def stubborn(ctx, _args):
        time.sleep(1.0)  # ignores check(); then writes late
        ctx.scratch.answer = "late write"
        return "done"

    monkeypatch.setitem(TOOLS, "stubborn", Tool("stubborn", "test", _SlowArgs, stubborn))
    agent.runner.step_timeout = 0.1
    t = time.monotonic()
    result = agent.run_plan(_plan(Step(tool="stubborn")), [])
    assert time.monotonic() - t < 0.8 and result.state == TaskState.CANCELLED
    time.sleep(1.1)
    assert "late write" not in result.answer


def test_failed_reingest_clears_stale_content(tmp_path):
    settings = make_settings(tmp_path / "home")
    engine = FakeEngine({"s.png": [["Total: $10.00 uniqueterm"]]})
    lib = Library(settings, engine=engine)
    png = bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10])
    (tmp_path / "s.png").write_bytes(png + b"v1")
    lib.add(tmp_path / "s.png")
    assert lib.search("uniqueterm")
    engine.fail = True
    (tmp_path / "s.png").write_bytes(png + b"v2")
    assert lib.add(tmp_path / "s.png").failed
    assert lib.search("uniqueterm") == []
