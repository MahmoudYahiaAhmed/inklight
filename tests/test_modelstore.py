"""Model files: found in a named folder, Inklight's cache or the Hugging Face cache, checked by hash, downloaded with
resume, and reported clearly when missing, corrupt or offline. Downloads go through a fake server."""

from __future__ import annotations

import hashlib
import io

import pytest

from inklight import modelstore
from inklight.errors import ModelUnavailable

ALPHA, BETA = b"alpha model weights" * 50, b'{"beta": true}'


def _spec(name: str, data: bytes) -> modelstore.ModelFile:
    return modelstore.ModelFile(name, len(data), hashlib.sha256(data).hexdigest())


SET = modelstore.ModelSet(
    key="test",
    title="Test models",
    repo="org/test-models",
    revision="0123456789abcdef",
    files=(_spec("a.onnx", ALPHA), _spec("sub/b.json", BETA)),
)


@pytest.fixture(autouse=True)
def caches(tmp_path, monkeypatch):
    monkeypatch.setenv("INKLIGHT_MODEL_CACHE", str(tmp_path / "inklight-cache"))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf"))
    monkeypatch.delenv("INKLIGHT_OFFLINE", raising=False)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    return tmp_path


class FakeServer:
    """Serves SET's files; ``cut`` stops a response after that many bytes (an interrupted download)."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.cut: int | None = None
        self.ranges: list[str | None] = []

    def __call__(self, request, timeout=None):  # noqa: ANN001, ANN204
        name = request.full_url.split(f"/resolve/{SET.revision}/", 1)[1]
        data = self.files[name]
        rng = request.get_header("Range")
        self.ranges.append(rng)
        start = int(rng.split("=")[1].rstrip("-")) if rng else 0
        body = data[start:]
        if self.cut is not None:
            body, self.cut = body[: self.cut], None
            response = _Response(body, 206 if rng else 200, fail=True)
        else:
            response = _Response(body, 206 if rng else 200)
        return response


class _Response(io.BytesIO):
    def __init__(self, body: bytes, status: int, fail: bool = False) -> None:
        super().__init__(body)
        self.status = status
        self.fail = fail

    def read(self, n: int = -1) -> bytes:
        chunk = super().read(n)
        if not chunk and self.fail:
            raise ConnectionResetError("connection dropped")
        return chunk

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *_):  # noqa: ANN002
        self.close()


def _install(folder, files):  # noqa: ANN001, ANN202
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)


def test_a_hugging_face_cache_copy_of_the_same_revision_is_used_in_place(caches):
    snapshot = caches / "hf" / "models--org--test-models" / "snapshots" / SET.revision
    _install(snapshot, {"a.onnx": ALPHA, "sub/b.json": BETA})
    assert modelstore.locate(SET) == snapshot
    assert modelstore.status(SET)["installed"] is True


def test_another_revision_in_the_cache_is_not_used(caches):
    _install(caches / "hf" / "models--org--test-models" / "snapshots" / "fedcba", {"a.onnx": ALPHA, "sub/b.json": BETA})
    assert modelstore.locate(SET) is None


def test_a_corrupt_cached_file_is_not_used(caches):
    snapshot = caches / "hf" / "models--org--test-models" / "snapshots" / SET.revision
    _install(snapshot, {"a.onnx": ALPHA[:-1] + b"X", "sub/b.json": BETA})
    assert modelstore.locate(SET) is None


def test_a_named_folder_that_is_incomplete_is_reported(tmp_path):
    _install(tmp_path / "mine", {"a.onnx": ALPHA})
    with pytest.raises(ModelUnavailable, match=r"sub/b.json: missing"):
        modelstore.locate(SET, tmp_path / "mine")


def test_download_verifies_and_installs(monkeypatch):
    server = FakeServer({"a.onnx": ALPHA, "sub/b.json": BETA})
    monkeypatch.setattr(modelstore.urllib.request, "urlopen", server)
    seen = []
    folder = modelstore.ensure(SET, progress=lambda what, done, total: seen.append((done, total)))
    assert (folder / "a.onnx").read_bytes() == ALPHA and (folder / "sub" / "b.json").read_bytes() == BETA
    assert seen[-1] == (SET.size, SET.size)
    assert not list(folder.rglob("*.part"))
    assert modelstore.locate(SET) == folder  # found again without the network


def test_an_interrupted_download_resumes_from_the_partial_file(monkeypatch):
    server = FakeServer({"a.onnx": ALPHA, "sub/b.json": BETA})
    monkeypatch.setattr(modelstore.urllib.request, "urlopen", server)
    server.cut = 300
    with pytest.raises(ModelUnavailable, match="partial file resumes"):
        modelstore.ensure(SET)
    assert modelstore.downloads()["test"]["state"] == "failed"
    folder = modelstore.ensure(SET)
    assert server.ranges[-2] == "bytes=300-"  # a.onnx resumed, b.json fetched whole
    assert (folder / "a.onnx").read_bytes() == ALPHA
    assert "test" not in modelstore.downloads()


def test_a_download_that_fails_its_hash_is_removed(monkeypatch):
    server = FakeServer({"a.onnx": ALPHA[:-1] + b"X", "sub/b.json": BETA})
    monkeypatch.setattr(modelstore.urllib.request, "urlopen", server)
    with pytest.raises(ModelUnavailable, match="hash check"):
        modelstore.ensure(SET)
    assert not list((modelstore.cache_root()).rglob("a.onnx*"))


def test_offline_mode_never_downloads(monkeypatch):
    monkeypatch.setenv("INKLIGHT_OFFLINE", "1")
    monkeypatch.setattr(modelstore.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network used offline"))
    with pytest.raises(ModelUnavailable, match="inklight models pull"):
        modelstore.ensure(SET)


def test_the_pinned_sets_name_exact_revisions():
    for model in modelstore.SETS.values():
        assert len(model.revision) == 40 and all(len(f.sha256) == 64 for f in model.files), model.key
