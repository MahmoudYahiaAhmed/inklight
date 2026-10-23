"""Small models (skipped when not installed), mocked remote model, and the folder watcher."""

import json
from types import SimpleNamespace

import pytest

from inklight import DocumentAgent
from inklight.agent.answer import grounded
from inklight.brains import Brain, hub
from inklight.brains.remote import RemoteModel
from inklight.errors import ModelUnavailable
from inklight.library import Library
from inklight.watch import FolderWatcher

from .conftest import FakeEngine, make_settings

READER = "Xenova/distilbert-base-cased-distilled-squad"
have_models = hub.installed(READER, hub.FILES["reader"], None)


def test_rules_brain_never_loads(tmp_path):
    brain = Brain(make_settings(tmp_path))
    assert brain.reader is None and brain.embedder is None and brain.label() == "rules"


def test_local_brain_fails_clearly_without_models(tmp_path):
    settings = make_settings(tmp_path, models={"brain": "local", "reader": "nobody/missing-model"})
    with pytest.raises(ModelUnavailable, match="models pull"):
        _ = Brain(settings).reader


def test_grounding_check():
    ev = "Revenue for Q2 was $4.9 million, a growth of 17% over the prior quarter."
    assert grounded("Revenue grew 17% in Q2.", ev)
    assert not grounded("Revenue grew 25% in Q2.", ev)
    assert not grounded("Microsoft reported growth of 17%.", ev)


@pytest.mark.models
@pytest.mark.skipif(not have_models, reason="run `inklight models pull` to enable")
def test_reader_and_embedder(tmp_path):
    brain = Brain(make_settings(tmp_path, models={"brain": "auto"}))
    spans = brain.reader.answer(
        "When does the contract expire?",
        ["Fees are due monthly.", "The contract expires on June 30, 2027 unless renewed."],
    )
    assert spans[0].text == "June 30, 2027" and spans[0].passage == 1
    vec = brain.embedder.embed(["hello", "world"])
    assert vec.shape == (2, 384) and abs(float((vec[0] ** 2).sum()) - 1) < 1e-3


@pytest.mark.models
@pytest.mark.ocr
@pytest.mark.skipif(not have_models, reason="run `inklight models pull` to enable")
def test_agent_with_models(tmp_path, docs_dir, closer):
    agent = closer(DocumentAgent(make_settings(tmp_path, models={"brain": "auto"})))
    agent.add(docs_dir)
    result = agent.ask("What was revenue growth in Q2?")
    assert result.answer.startswith("17%") and "reader" in result.brain
    assert result.sources[0].name == "report_q2.pdf"


class _Resp:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": json.dumps(self.payload)}}]}


def _remote_settings(tmp_path, mode="always"):
    return make_settings(
        tmp_path, models={"remote_base_url": "https://llm.invalid/v1", "remote_model": "big", "remote_for": mode}
    )


def test_remote_answer_accepted_only_with_real_quote(tmp_path, monkeypatch, closer):
    httpx = pytest.importorskip("httpx")
    settings = _remote_settings(tmp_path)
    lib = closer(Library(settings, engine=FakeEngine({"r.png": [["Revenue grew 17% in Q2.", "Costs were flat."]]})))
    (tmp_path / "r.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    agent = DocumentAgent(settings, library=lib)
    agent.add(tmp_path / "r.png")
    sent = []

    def fake_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        sent.append(json)
        if "plan" in json["messages"][0]["content"]:
            return _Resp({"intent": "ask"})
        return _Resp({"answer": "17 percent", "quote": "Revenue grew 17% in Q2.", "evidence": 1})

    monkeypatch.setattr(httpx, "post", fake_post)
    result = agent.ask("How fast did revenue grow?")
    assert "Revenue grew 17% in Q2." in result.answer and "17 percent" in result.answer
    assert "unverified wording" in result.answer and "remote:big" in result.brain
    assert "Ignore" not in json.dumps(sent)

    def lying_post(url, json=None, headers=None, timeout=None):  # noqa: A002
        if "plan" in json["messages"][0]["content"]:
            return _Resp({"intent": "ask"})
        return _Resp({"answer": "99%", "quote": "Revenue grew 99%.", "evidence": 1})

    monkeypatch.setattr(httpx, "post", lying_post)
    result = agent.ask("How fast did revenue grow?")
    assert "99%" not in result.answer and any("rejected" in w for w in result.warnings)


def test_remote_errors_hide_secrets(tmp_path, monkeypatch):
    httpx = pytest.importorskip("httpx")
    monkeypatch.setenv("INKLIGHT_REMOTE_API_KEY", "sk-secret")

    def boom(*a, **k):
        raise httpx.ConnectError("sk-secret leaked?")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(ModelUnavailable) as info:
        RemoteModel(_remote_settings(tmp_path).models).chat("s", "u")
    assert "sk-secret" not in str(info.value)


def test_watcher_waits_for_stable_files(tmp_path, closer):
    settings = make_settings(tmp_path / "home")
    lib = closer(Library(settings, engine=FakeEngine({"in.png": [["Total: $5.00"]]})))
    agent = DocumentAgent(settings, library=lib)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    events = []
    w = FolderWatcher(agent=agent, folder=inbox, request="extract total", on_event=events.append)
    (inbox / "in.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    assert w.tick() == []  # first sighting: wait until stable
    got = w.tick()
    assert [e.kind for e in got] == ["indexed", "result"] and got[1].result.records[0].fields["total"].value == 5.0
    assert w.tick() == []  # unchanged: nothing to do
    _ = SimpleNamespace
