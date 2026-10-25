"""English-only optional models are not used on Arabic (they degraded Arabic results in bench/usecases).

Spies stand in for the reader and the embedder, so the tests prove which model was called, not just the answer.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from inklight import DocumentAgent

from .conftest import make_settings

LETTER_AR = "رسالة مؤرخة 18 كانون الثاني/يناير 2023 موجهة إلى رئيس مجلس الأمن.\nوقعت الرسالة فيكتوريا ليولوشا ليتا."
LETTER_EN = (
    "Letter dated 18 January 2023 addressed to the President of the Security Council.\nSigned by Victoria Lieta."
)


class SpyReader:
    def __init__(self) -> None:
        self.calls = 0

    def answer(self, question, passages, top=8, check=None):  # noqa: ANN001, ARG002
        self.calls += 1
        return [SimpleNamespace(text="Victoria Lieta", passage=0, start=0, end=14, score=0.9)]


class SpyEmbedder:
    name = "spy-embedder"

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts, query=False):  # noqa: ANN001, ARG002
        self.calls += 1
        return np.ones((len(texts), 4), dtype=np.float32) / 2.0


@pytest.fixture()
def spied(tmp_path, monkeypatch):
    for name, text in (("ar.txt", LETTER_AR), ("en.txt", LETTER_EN)):
        (tmp_path / name).write_text(text, encoding="utf-8")
    agent = DocumentAgent(make_settings(tmp_path / "home"))
    reader, embedder = SpyReader(), SpyEmbedder()
    brain = agent.library.brain
    monkeypatch.setattr(type(brain), "reader", property(lambda self: reader))
    monkeypatch.setattr(type(brain), "embedder", property(lambda self: embedder))
    monkeypatch.setattr(brain, "mode", "auto")
    agent.add([tmp_path / "ar.txt", tmp_path / "en.txt"])
    yield agent, reader, embedder
    agent.close()


def test_arabic_question_skips_reader_and_embedder(spied):
    agent, reader, embedder = spied
    res = agent.ask("من وقع الرسالة؟")
    assert reader.calls == 0
    assert embedder.calls == 0 or all(h.method == "keyword" for h in agent.search("من وقع الرسالة؟"))
    assert any("reader not used" in c for c in res.checks)
    assert any("embedder not used" in c for c in res.checks)
    assert "ليولوشا" in res.answer


def test_english_question_still_uses_both_models(spied):
    agent, reader, embedder = spied
    res = agent.ask(
        "Which council is mentioned in the letter?"
    )  # not a sender/signer question: those are read from layout
    assert reader.calls >= 1 and embedder.calls >= 1
    assert not any("not used" in c for c in res.checks)


def test_arabic_search_is_keyword_only(spied):
    agent, _, embedder = spied
    before = embedder.calls
    hits = agent.search("مجلس الأمن")
    assert hits and all(h.method == "keyword" for h in hits)
    assert embedder.calls == before


def test_scoped_question_without_a_keyword_match_reads_the_document(spied):
    agent, _, _ = spied
    doc = next(d for d in agent.library.documents() if d.name == "ar.txt")
    hits = agent.library.search("ما الجهة المرسل إليها الخطاب؟", [doc.id])
    assert hits and hits[0].method in ("scope", "keyword")


def test_an_answer_with_little_overlap_is_flagged(tmp_path):
    # syn-salary (reserved): one of three question words matched, and the sentence was returned unflagged
    lines = [
        "Al-Madar Software LLC certifies that Omar Al-Khatib works as a senior engineer.",
        "This certificate was issued at the employee's request without any liability on the company.",
    ]
    path = tmp_path / "salary.txt"
    path.write_text(chr(10).join(lines), encoding="utf-8")
    with DocumentAgent(make_settings(tmp_path / "home")) as agent:
        res = agent.ask("What is the employee's passport number?", files=[path])
    assert res.confidence < 0.3 or res.state.value != "succeeded"
