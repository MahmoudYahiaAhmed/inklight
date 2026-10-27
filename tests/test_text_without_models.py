"""Plain-text files are read, indexed, shown and searched without any model: no OCR weights, no optional models.

Every test runs with a fresh library and empty model caches, and fails if anything tries to download a model.
"""

import urllib.request
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from inklight import DocumentAgent, modelstore
from inklight.cli import app as cli_app
from inklight.config import OCRSettings
from inklight.ocr import register_engine
from inklight.ocr.engine import InklightOCR
from inklight.schemas import DocumentContent, PageContent, TextLine

from .conftest import make_settings

TEXT = "Company name: Cedar Lane Bakery\nRegistration number: 55120\nاسم الشركة: مخبز درب الأرز\nالمدينة: الإسكندرية\n"


class DownloadAttempted(AssertionError):
    pass


@pytest.fixture
def no_downloads(tmp_path, monkeypatch):
    """Empty model caches; any model download fails the test. Returns the list of attempts."""
    for var in ("INKLIGHT_MODEL_CACHE", "HF_HOME", "HF_HUB_CACHE"):
        monkeypatch.setenv(var, str(tmp_path / "empty-cache" / var.lower()))
    monkeypatch.setenv("INKLIGHT_HOME", str(tmp_path / "fresh-home"))
    monkeypatch.setenv("INKLIGHT_MODELS__BRAIN", "rules")  # optional small models off
    monkeypatch.setenv("INKLIGHT_STRUCTURE__ENGINE", "inklight")  # structure on: its models must not load for text
    attempts: list[str] = []

    def refuse(what):
        def call(*args, **kwargs):
            attempts.append(f"{what}{args[:1]}")
            raise DownloadAttempted(f"model download attempted: {what}")

        return call

    monkeypatch.setattr(modelstore, "_download", refuse("modelstore._download"))
    monkeypatch.setattr(urllib.request, "urlopen", refuse("urlopen"))
    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "hf_hub_download", refuse("hf_hub_download"))
    monkeypatch.setattr(huggingface_hub, "snapshot_download", refuse("snapshot_download"))
    monkeypatch.setattr("inklight.structure.run.preload", refuse("structure preload"))
    return attempts


@pytest.fixture
def note(tmp_path) -> Path:
    path = tmp_path / "note.txt"
    path.write_text(TEXT, encoding="utf-8")
    return path


def test_cli_reads_shows_and_searches_text_without_models(no_downloads, note):
    runner = CliRunner()
    processed = runner.invoke(cli_app, ["process", str(note)])
    assert processed.exit_code == 0, processed.output
    assert "1 new" in processed.output and "plain text" in processed.output
    shown = runner.invoke(cli_app, ["text", str(note)])
    assert shown.exit_code == 0 and "Cedar Lane Bakery" in shown.output and "مخبز درب الأرز" in shown.output
    for query in ("Cedar Lane", "الإسكندرية"):
        found = runner.invoke(cli_app, ["search", query])
        assert found.exit_code == 0 and "note.txt" in found.output, found.output
    docs = runner.invoke(cli_app, ["docs"])
    assert "plain text" in docs.output
    assert no_downloads == []
    for folder in ("inklight_model_cache", "hf_home", "hf_hub_cache"):
        cache = note.parent / "empty-cache" / folder
        assert not cache.exists() or not any(cache.rglob("*.*")), f"something was written to {cache}"


def test_agent_never_creates_an_ocr_engine_for_text(no_downloads, note, tmp_path):
    with DocumentAgent(make_settings(tmp_path / "home", structure={"engine": "inklight"})) as agent:
        report = agent.add([note])
        assert not report.failed and len(report.documents) == 1
        assert "Cedar Lane Bakery" in agent.text(note) and "الإسكندرية" in agent.text(note)
        assert [h.source.name for h in agent.search("Cedar Lane")] == ["note.txt"]
        doc_id = report.documents[0].id
        assert agent.library.store.page_sources()[doc_id] == {"plain": 1}
        assert agent.library._engine is None, "the OCR engine was created for a text file"
    assert no_downloads == []


@pytest.fixture
def counting_engine(monkeypatch):
    """A test double registered as an OCR engine: counts how often it is created and read, loads nothing."""
    calls = {"created": 0, "read": 0}

    class Counting:
        name = "counting"

        def __init__(self, settings):
            calls["created"] += 1

        def supports(self, kind):
            return kind == "png"

        def read(self, path, *, max_pages, password=None):
            calls["read"] += 1
            line = TextLine(text="Scanned page: Cedar Lane Bakery", conf=0.9)
            page = PageContent(number=1, source="ocr", markdown=line.text, lines=(line,))
            return DocumentContent(path=str(path), pages=(page,), total_pages=1, engine=self.name)

    register_engine("counting", Counting)
    return calls


def test_the_ocr_engine_is_created_when_a_scan_needs_it(no_downloads, note, tmp_path, counting_engine):
    scan = tmp_path / "scan.png"
    Image.new("RGB", (40, 20), "white").save(scan)
    with DocumentAgent(
        make_settings(tmp_path / "home", ocr={"engine": "counting"}, structure={"engine": "none"})
    ) as agent:
        agent.add([note])
        assert counting_engine == {"created": 0, "read": 0}
        report = agent.add([scan])
        assert not report.failed, report.failed
        assert counting_engine == {"created": 1, "read": 1}
        assert agent.library.store.page_sources()[report.documents[0].id] == {"ocr": 1}
    assert no_downloads == []


def test_cli_fetches_models_first_only_for_files_that_need_them(no_downloads, note, tmp_path, monkeypatch):
    fetched: list[int] = []
    monkeypatch.setattr("inklight.cli._ensure_models", lambda settings: fetched.append(1))
    monkeypatch.setenv("INKLIGHT_OCR__ENGINE", "counting")
    register_engine("counting", lambda settings: _Never())
    runner = CliRunner()
    assert runner.invoke(cli_app, ["process", str(note)]).exit_code == 0
    assert fetched == []
    scan = tmp_path / "scan.png"
    Image.new("RGB", (40, 20), "white").save(scan)
    runner.invoke(cli_app, ["process", str(scan)])
    assert fetched == [1]


class _Never:
    name = "never"

    def supports(self, kind):
        return True

    def read(self, path, *, max_pages, password=None):
        raise AssertionError("not read in this test")


def test_inklight_ocr_loads_its_models_on_first_use_only(monkeypatch, tmp_path):
    loaded: list[str] = []
    monkeypatch.setattr(
        modelstore, "ensure", lambda model, local=None, progress=None: loaded.append("ensure") or tmp_path
    )
    monkeypatch.setattr("inklight.backends.ocr.load", lambda folder, **kw: loaded.append("load") or object())
    engine = InklightOCR(OCRSettings())
    assert loaded == []  # creating the engine loads nothing
    first = engine.converter()
    assert engine.converter() is first and loaded == ["ensure", "load"]
