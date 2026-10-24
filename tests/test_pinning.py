"""Pilot baseline controls: pinned model revisions and the second-reading switch."""

from pathlib import Path

import pytest

from inklight import Library
from inklight.brains import Brain, hub
from inklight.errors import ModelUnavailable
from inklight.schemas import DocumentInfo

from .conftest import make_settings


def test_resolve_asks_the_cache_for_the_pinned_revision(monkeypatch):
    import huggingface_hub

    seen = []

    def fake_cache(repo, name, revision=None):
        seen.append(revision)
        return f"/cache/{repo}/{revision}/{name}"

    monkeypatch.setattr(huggingface_hub, "try_to_load_from_cache", fake_cache)
    files = hub.resolve("org/model", ["a.onnx"], None, allow_download=False, revision="abc123")
    assert seen == ["abc123"] and files["a.onnx"] == Path("/cache/org/model/abc123/a.onnx")


def test_a_pinned_revision_that_is_not_cached_is_not_replaced_by_another(monkeypatch):
    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "try_to_load_from_cache", lambda repo, name, revision=None: None)
    with pytest.raises(ModelUnavailable):
        hub.resolve("org/model", ["a.onnx"], None, allow_download=False, revision="abc123")


def test_brain_reports_the_pinned_revision(tmp_path):
    settings = make_settings(tmp_path, models={"reader_revision": "abc123"})
    assert Brain(settings).status()["reader"]["revision"] == "abc123"


class _ImageEngine:
    name = "fake-ocr"

    def supports(self, kind):
        return True

    def read(self, path, *, max_pages, password=None):  # pragma: no cover - not used here
        raise AssertionError

    def reread(self, path, page, bbox, rotation=0):
        return "63.000"


@pytest.mark.parametrize("enabled", [True, False])
def test_second_reading_can_be_switched_off(tmp_path, enabled):
    image = tmp_path / "r.png"
    image.write_bytes(b"not really an image")
    doc = DocumentInfo(id="d" * 16, path=str(image), name="r.png", sha256="0", size=1, mtime=0, engine="fake-ocr")
    settings = make_settings(tmp_path / "home", extraction={"second_reading": enabled})
    with Library(settings, engine=_ImageEngine()) as lib:
        again = lib.rereader(doc)
        assert (again is not None) is enabled
        if enabled:
            assert again(1, (0.0, 0.0, 10.0, 10.0)) == "63.000"
