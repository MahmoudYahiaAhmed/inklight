"""Two processes sharing a model cache must not break each other's download.

Reproduced on 8e860e6 (see model_race_child.py; no network, a slow fake server): the download locks were thread
locks, so a second process (another server, the CLI) wrote to the same ``lm_cjk.npz.part``. Depending on timing
one process failed with PermissionError, a hash mismatch, or ``FileNotFoundError: ...lm_cjk.npz.part`` after the
other renamed the finished file into place, the error seen on a first import; a retry then found the model.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from inklight import modelstore
from inklight.errors import ModelUnavailable

from . import model_race_child as child

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def cache(tmp_path, monkeypatch):  # noqa: ANN201
    folder = tmp_path / "model-cache"
    monkeypatch.setenv("INKLIGHT_MODEL_CACHE", str(folder))
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "hf"))
    monkeypatch.delenv("INKLIGHT_OFFLINE", raising=False)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    return folder


def _spawn(cache: Path, *args: str) -> subprocess.Popen:
    env = {**os.environ, "INKLIGHT_MODEL_CACHE": str(cache), "PYTHONPATH": str(ROOT)}
    return subprocess.Popen(
        [sys.executable, "-m", "tests.model_race_child", *args],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _target(cache: Path) -> Path:
    return cache / "org--race" / child.SET.revision / child.SPEC.path


def _parts(cache: Path) -> list[Path]:
    return list(cache.rglob("*.part"))


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (("0",), ("0.3",)),  # both downloading at once: one .part, two writers
        (("0", "2.5"), ("1.6",)),  # the second arrives while the first hashes the finished file: it was renamed away
    ],
)
def test_two_processes_share_one_download(cache, first, second):
    a = _spawn(cache, *first)
    b = _spawn(cache, *second)
    out = [p.communicate(timeout=60)[0].strip().splitlines()[-1] for p in (a, b)]
    assert out == ["OK", "OK"], out
    assert hashlib.sha256(_target(cache).read_bytes()).hexdigest() == child.SPEC.sha256
    assert not _parts(cache)


def test_a_killed_download_resumes_in_the_next_process(cache, monkeypatch):
    holder = _spawn(cache, "0")
    part = _target(cache).with_name(child.SPEC.path + ".part")
    deadline = time.monotonic() + 30
    while not (part.exists() and part.stat().st_size > 20_000):
        assert time.monotonic() < deadline and holder.poll() is None, "the download never started"
        time.sleep(0.05)
    holder.kill()  # interrupted mid-file: the OS drops its lock, the partial file stays
    holder.wait(timeout=10)
    have = part.stat().st_size
    assert 0 < have < child.SPEC.size

    ranges: list[str | None] = []

    def fake(request, timeout=None):  # noqa: ANN001, ANN202
        ranges.append(request.get_header("Range"))
        return child._fake(request, timeout)

    monkeypatch.setattr("urllib.request.urlopen", fake)
    folder = modelstore.ensure(child.SET)  # not blocked by the dead process's lock
    assert ranges and ranges[0] is not None and ranges[0].startswith("bytes="), ranges  # resumed, not restarted
    assert hashlib.sha256((folder / child.SPEC.path).read_bytes()).hexdigest() == child.SPEC.sha256
    assert not _parts(cache)


def test_a_held_lock_is_waited_for_and_reported(cache, monkeypatch):
    lock = cache / ".locks" / f"org--race--{child.SET.revision}.lock"
    lock.parent.mkdir(parents=True)
    with lock.open("a+b") as other:  # another process's download of the same set
        assert modelstore._try_lock(other)
        monkeypatch.setattr(modelstore, "LOCK_WAIT", 0.3)
        monkeypatch.setattr(modelstore, "_POLL", 0.05)
        monkeypatch.setattr("urllib.request.urlopen", child._fake)
        with pytest.raises(ModelUnavailable, match="Another Inklight process has been downloading"):
            modelstore.ensure(child.SET)
        assert not _target(cache).exists() and not _parts(cache)  # nothing was touched while it held the lock
        modelstore._unlock(other)
    assert modelstore.ensure(child.SET) == _target(cache).parent
    assert "race" not in modelstore.downloads()


def test_a_valid_cached_model_is_not_downloaded_or_rewritten(cache, monkeypatch):
    target = _target(cache)
    target.parent.mkdir(parents=True)
    target.write_bytes(child.DATA)
    before = target.stat().st_mtime_ns

    def no_network(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("a verified cached model must not be downloaded")

    monkeypatch.setattr("urllib.request.urlopen", no_network)
    assert modelstore.ensure(child.SET) == target.parent
    assert target.stat().st_mtime_ns == before
