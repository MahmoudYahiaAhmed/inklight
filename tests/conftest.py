from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from inklight import DocumentAgent
from inklight.config import Settings, load_settings
from inklight.schemas import Block, DocumentContent, PageContent, TextLine

from .factory import build, build_bad


def make_settings(home: Path, **overrides) -> Settings:
    base = {"home": str(home), "models": {"brain": "rules"}}
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = {**base[key], **value}
        else:
            base[key] = value
    return load_settings(None, **base)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path_factory):
    for key in list(__import__("os").environ):
        if key.startswith("INKLIGHT_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("INKLIGHT_HOME", str(tmp_path_factory.mktemp("default-home")))


@pytest.fixture(scope="session")
def docs_dir(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("documents")
    build(folder, today=date.today())
    return folder


@pytest.fixture(scope="session")
def bad_dir(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("bad")
    build_bad(folder)
    return folder


@pytest.fixture(scope="session")
def shared_agent(tmp_path_factory, docs_dir):
    """One OCR pass over the demo set, shared by read-only end-to-end tests."""
    home = tmp_path_factory.mktemp("home")
    with DocumentAgent(make_settings(home)) as agent:
        report = agent.add([docs_dir])
        assert not report.failed, report.failed
        yield agent


@pytest.fixture
def agent(tmp_path):
    with DocumentAgent(make_settings(tmp_path / "home")) as agent:
        yield agent


@pytest.fixture
def closer():
    """Register objects with ``close()``; they are closed when the test ends, even if it fails."""
    opened: list = []

    def register(obj):
        opened.append(obj)
        return obj

    yield register
    for obj in reversed(opened):
        obj.close()


class FakeEngine:
    """A deterministic OCR engine for unit tests that must not depend on Indra."""

    name = "fake"

    def __init__(self, pages: dict[str, list[list[str]]] | None = None, fail: bool = False) -> None:
        self.pages = pages or {}
        self.fail = fail
        self.calls = 0

    def supports(self, kind: str) -> bool:
        return kind in ("pdf", "png", "jpeg", "tiff", "bmp", "webp")

    def read(self, path: Path, *, max_pages: int, password: str | None = None) -> DocumentContent:
        from inklight.errors import OCRError

        self.calls += 1
        if self.fail:
            raise OCRError("engine exploded")
        raw = self.pages.get(path.name, [["Hello world"]])
        pages = []
        for n, lines in enumerate(raw[:max_pages], 1):
            tl = tuple(
                TextLine(text=t, bbox=(10.0, 20.0 * i, 200.0, 20.0 * i + 15), conf=0.97) for i, t in enumerate(lines)
            )
            blocks = tuple(
                Block(index=i, label="Text", text=t, bbox=line.bbox, conf=0.97)
                for i, (t, line) in enumerate(zip(lines, tl, strict=True))
            )
            pages.append(
                PageContent(
                    number=n,
                    width=600.0,
                    height=800.0,
                    source="ocr",
                    markdown="\n\n".join(lines),
                    lines=tl,
                    blocks=blocks,
                )
            )
        return DocumentContent(path=str(path), pages=tuple(pages), total_pages=len(raw), engine=self.name)
