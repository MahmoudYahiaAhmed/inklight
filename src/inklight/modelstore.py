"""The model files Inklight runs, pinned to exact revisions and checked by hash.

Each model set lists its files with their size and SHA-256. A set is found, in this order, in:

1. a folder the user named (``ocr.model_dir`` for the OCR models, ``structure.model_dir`` for the structure models);
2. Inklight's model cache (``INKLIGHT_MODEL_CACHE``, default ``~/.cache/inklight``);
3. the Hugging Face cache, when a copy of the same revision is already there (nothing is copied).

Otherwise it is downloaded once into Inklight's cache: each file to ``<name>.part``, resumed after an interruption,
checked against its hash, then moved into place. Only one process downloads a set at a time: a second server or CLI
asking for the same set waits for the first (an OS file lock, released even if that process dies), then uses its
copy, so two processes never write, delete or rename the same partial file. With ``INKLIGHT_OFFLINE=1`` (or
``HF_HUB_OFFLINE=1``) nothing is downloaded and a missing set is reported with the command that fetches it.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from .errors import ModelUnavailable

ENDPOINT = os.environ.get("INKLIGHT_MODEL_ENDPOINT", "https://huggingface.co")
_CHUNK = 1 << 20

Progress = Callable[[str, int, int], None]  # (what, bytes done, bytes total)


@dataclass(frozen=True)
class ModelFile:
    path: str  # relative to the set's folder
    size: int
    sha256: str


@dataclass(frozen=True)
class ModelSet:
    key: str
    title: str  # what the user sees
    repo: str
    revision: str  # an exact commit
    files: tuple[ModelFile, ...]
    root: str = ""  # sub-folder of the repo the set's files live in (the folder handed to the model)

    @property
    def size(self) -> int:
        return sum(f.size for f in self.files)


OCR = ModelSet(
    key="ocr",
    title="Inklight OCR",
    repo="datalab-to/indra-ocr",
    revision="bd02167fdf2005a19962cc15188f8496a2c87d3b",  # tag v1.1.0
    files=(
        ModelFile("det.onnx", 389948, "f2bd4cba23e9c328cf7ec824634e423e191a2c6aacbbf35c62bd79dd70f62f59"),
        ModelFile("rec.onnx", 5042161, "475972a2710be4a3cbfeb2bc7f3624ffd563de07de42476fc7a290d4e1ece484"),
        ModelFile("rec_rtl.onnx", 4812710, "468796bd684486a8388c30c8b4ed2a26e3eeb1f8ff02831c24c2e12c79a2a834"),
        ModelFile("rec_cjk.onnx", 10176018, "4a035516a17e62cdf33a4fe2d88077654cb8841cff024685cdef4e351694ef50"),
        ModelFile("rec_world.onnx", 5627990, "c8d1e59f21b04966f179d2d2d8e22b230d22110b3f89855bbbf2624a58c40043"),
        ModelFile("order.onnx", 2973138, "a42db2e8b536ad3d84045a4b7f9b0a72667cf8be4aa02d63f7b38004719fb180"),
        ModelFile("orient.onnx", 371802, "20eaf670f55a7cf9facfe1bdd6c7b8e40be75bbf4d48a3df43f66aa3bbd874fd"),
        ModelFile("script.onnx", 191630, "b6ce4e926e19c243faaf37bd46880398bf2cb4ae56a29e1177a3b017c1280e36"),
        ModelFile("meta.json", 211869, "4ce4c94b46f5d644033c02e718322014ff4081270f385038c571912b56696339"),
        ModelFile("lm.npz", 15695957, "6c0fb618a363a0acdd05d4f5b0edd9e8146d2d990541b87f6130bbfe17cea58d"),
        ModelFile("lm_cjk.npz", 18955160, "6d64f13f4f90f4e529bd63340c6df76238d007feaef2abb903d8cd28d92bc2f3"),
        ModelFile("lm_world.npz", 11641215, "34df5e74a2fcbb9cf5e7f360a559375ffa2e04d2d2943a42308c177bcb444d5d"),
    ),
)

LAYOUT = ModelSet(
    key="layout",
    title="Inklight document structure: layout",
    repo="docling-project/docling-layout-heron-onnx",
    revision="40bde044036bb181c130ddf6c51792187268748f",
    files=(
        ModelFile("model.onnx", 171220471, "59c81a3a2923042d85034ffc487f8f47e4854117e879aef89b2b9f728fb4922a"),
        ModelFile("config.json", 878, "c6e67b6cdf64fa245779d0409bb994aa96e8c1790e15ec07a65843628e232180"),
        ModelFile("preprocessor_config.json", 445, "54d086cf0d7d371f7fac36e5d3a0dae31e211298affc816106cc376506799d58"),
    ),
)

_TABLES_REPO = "docling-project/docling-models"
_TABLES_REV = "fc0f2d45e2218ea24bce5045f58a389aed16dc23"
TABLES = ModelSet(
    key="tables",
    title="Inklight document structure: tables",
    repo=_TABLES_REPO,
    revision=_TABLES_REV,
    root="model_artifacts/tableformer/accurate",
    files=(
        ModelFile(
            "model_artifacts/tableformer/accurate/tableformer_accurate.safetensors",
            212758388,
            "2a7d6c924b3cd12fb99a09280ca9c33a89c5d60b93253617d2e088c1a40374d9",
        ),
        ModelFile(
            "model_artifacts/tableformer/accurate/tm_config.json",
            7060,
            "984e122ceb8ccf84d84c9d2882f6f2302a44b4f1e577babd6289892c36f3cffd",
        ),
    ),
)
TABLES_FAST = ModelSet(
    key="tables-fast",
    title="Inklight document structure: tables (fast)",
    repo=_TABLES_REPO,
    revision=_TABLES_REV,
    root="model_artifacts/tableformer/fast",
    files=(
        ModelFile(
            "model_artifacts/tableformer/fast/tableformer_fast.safetensors",
            145453276,
            "3119563aab5a7c96fda4d621119b63fd8806272b86c30936d15507616422f718",
        ),
        ModelFile(
            "model_artifacts/tableformer/fast/tm_config.json",
            7060,
            "dca6762508dddfae6d57d6cb4ef822c6000119dff0f3b6489db7413118c2622a",
        ),
    ),
)

SETS = {s.key: s for s in (OCR, LAYOUT, TABLES, TABLES_FAST)}

_LOCK = threading.Lock()
_SET_LOCKS: dict[str, threading.Lock] = {}
_STATUS: dict[str, dict[str, int | str]] = {}  # set key -> {"state", "done", "total"}: shown while downloading


def cache_root() -> Path:
    env = os.environ.get("INKLIGHT_MODEL_CACHE")
    return Path(env).expanduser() if env else Path.home() / ".cache" / "inklight"


def offline() -> bool:
    return any(
        os.environ.get(k, "").strip().lower() in ("1", "true", "yes") for k in ("INKLIGHT_OFFLINE", "HF_HUB_OFFLINE")
    )


def downloads() -> dict[str, dict[str, int | str]]:
    """Downloads in progress or just failed, for a status display."""
    with _LOCK:
        return {k: dict(v) for k, v in _STATUS.items()}


def _own_folder(model: ModelSet) -> Path:
    return cache_root() / model.repo.replace("/", "--") / model.revision


def _hf_folder(model: ModelSet) -> Path:
    hub = os.environ.get("HF_HUB_CACHE") or os.path.join(
        os.environ.get("HF_HOME") or os.path.join(Path.home(), ".cache", "huggingface"), "hub"
    )
    return Path(hub) / f"models--{model.repo.replace('/', '--')}" / "snapshots" / model.revision


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(_CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def _verified_record() -> Path:
    return cache_root() / "verified.json"


def _load_verified() -> dict[str, list[float | int | str]]:
    try:
        return json.loads(_verified_record().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _check_file(path: Path, spec: ModelFile, verified: dict[str, list[float | int | str]]) -> str | None:
    """None when ``path`` is ``spec``'s file; else what is wrong. A file whose hash was checked before (same size
    and modification time) is not hashed again."""
    if not path.is_file():
        return "missing"
    stat = path.stat()
    if stat.st_size != spec.size:
        return f"wrong size ({stat.st_size} bytes, expected {spec.size})"
    key = str(path.resolve())
    if verified.get(key) == [stat.st_size, stat.st_mtime, spec.sha256]:
        return None
    if _sha256(path) != spec.sha256:
        return "corrupt (hash mismatch)"
    verified[key] = [stat.st_size, stat.st_mtime, spec.sha256]
    return None


def _check(folder: Path, model: ModelSet) -> list[str]:
    verified = _load_verified()
    problems = [f"{f.path}: {why}" for f in model.files if (why := _check_file(folder / f.path, f, verified))]
    if not problems:
        try:
            _verified_record().parent.mkdir(parents=True, exist_ok=True)
            _verified_record().write_text(json.dumps(verified), encoding="utf-8")
        except OSError:
            pass  # only a cache of hash checks
    return problems


def _in_folder(folder: Path, model: ModelSet) -> Path:
    return folder / model.root if model.root else folder


def locate(model: ModelSet, local_dir: str | Path | None = None) -> Path | None:
    """The folder of a complete, verified copy of ``model`` (its ``root``), or None. A user-named folder that is
    incomplete or corrupt raises ModelUnavailable: it was asked for explicitly."""
    if local_dir:
        folder = Path(local_dir).expanduser()
        problems = _check(folder, model)
        if problems:
            raise ModelUnavailable(f"The {model.title} model folder {folder} is not usable: {'; '.join(problems)}")
        return _in_folder(folder, model)
    for folder in (_own_folder(model), _hf_folder(model)):
        if folder.is_dir() and not _check(folder, model):
            return _in_folder(folder, model)
    return None


def status(model: ModelSet, local_dir: str | Path | None = None) -> dict[str, object]:
    """Where ``model`` is and whether it is usable, for diagnostics."""
    try:
        found = locate(model, local_dir)
    except ModelUnavailable as exc:
        return {"installed": False, "problem": str(exc), "revision": model.revision, "size": model.size}
    return {
        "installed": found is not None,
        "folder": str(found) if found else None,
        "revision": model.revision,
        "size": model.size,
    }


def ensure(model: ModelSet, local_dir: str | Path | None = None, progress: Progress | None = None) -> Path:
    """The folder of a verified copy of ``model``, downloading it first if needed."""
    found = locate(model, local_dir)
    if found is not None:
        return found
    if offline():
        raise ModelUnavailable(
            f"The {model.title} models are not installed and Inklight is offline. "
            "Run `inklight models pull` once with network access."
        )
    # One download of a set at a time: threads of this process (a preload and a request may both ask), then other
    # processes sharing the cache (a second server, the CLI). Whoever waited finds the finished copy.
    with _set_lock(model.key), _process_lock(model):
        found = locate(model, local_dir)
        return found if found is not None else _download(model, progress)


def _set_lock(key: str) -> threading.Lock:
    with _LOCK:
        return _SET_LOCKS.setdefault(key, threading.Lock())


LOCK_WAIT = 3600.0  # seconds to wait for another process's download of the same set before giving up
_POLL = 0.5


@contextmanager
def _process_lock(model: ModelSet) -> Iterator[None]:
    """Hold the cache's lock file for ``model`` while downloading it. The OS releases the lock when the holder
    exits, so a killed download never blocks the next one, and its partial file is resumed by whoever goes next."""
    path = cache_root() / ".locks" / f"{model.repo.replace('/', '--')}--{model.revision}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        deadline = time.monotonic() + LOCK_WAIT
        waiting = False
        while not _try_lock(handle):
            if not waiting:
                waiting = True
                _set_status(model.key, "waiting", 0, model.size)  # another process is downloading this set
            if time.monotonic() > deadline:
                _clear_status(model.key)
                raise ModelUnavailable(
                    f"Another Inklight process has been downloading the {model.title} models for over "
                    f"{LOCK_WAIT / 60:.0f} minutes. Let it finish, or stop it and run `inklight models pull`."
                )
            time.sleep(_POLL)
        try:
            yield
        finally:
            if waiting:
                _clear_status(model.key)
            _unlock(handle)


def _try_lock(handle: IO[bytes]) -> bool:
    """Take an exclusive lock on the first byte of ``handle`` without waiting; False if another process has it."""
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(handle: IO[bytes]) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass  # closing the handle releases it anyway


def _download(model: ModelSet, progress: Progress | None) -> Path:
    folder = _own_folder(model)
    total = model.size
    done = 0
    _set_status(model.key, "downloading", 0, total)
    try:
        for spec in model.files:
            target = folder / spec.path
            if not _check_file(target, spec, {}):
                done += spec.size
                continue
            done = _fetch(model, spec, target, done, total, progress)
        problems = _check(folder, model)
        if problems:
            raise ModelUnavailable(f"The {model.title} download is incomplete: {'; '.join(problems)}")
    except ModelUnavailable:
        _set_status(model.key, "failed", done, total)
        raise
    except Exception as exc:  # noqa: BLE001 - network, disk or protocol errors: one clear message
        _set_status(model.key, "failed", done, total)
        raise ModelUnavailable(
            f"Could not download the {model.title} models ({type(exc).__name__}: {exc}). Check the network "
            "connection and run `inklight models pull` again: finished files are kept and a partial file resumes."
        ) from exc
    _clear_status(model.key)
    return _in_folder(folder, model)


def _fetch(model: ModelSet, spec: ModelFile, target: Path, done: int, total: int, progress: Progress | None) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    if have > spec.size:
        part.unlink()
        have = 0
    url = f"{ENDPOINT}/{model.repo}/resolve/{model.revision}/{spec.path}"
    if not url.startswith("https://"):
        raise ModelUnavailable(f"Model downloads need an https endpoint, not {ENDPOINT!r}")
    request = urllib.request.Request(url, headers={"User-Agent": "inklight"})  # noqa: S310 - https checked above
    if have:
        request.add_header("Range", f"bytes={have}-")
    if have < spec.size:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - https checked above
            final = getattr(response, "geturl", lambda: url)()
            if not str(final).startswith("https://"):
                raise ModelUnavailable(f"A model download was redirected to a non-https address ({final})")
            if have and response.status != 206:  # the server ignored the range: start over
                have = 0
            with part.open("ab" if have else "wb") as out:
                while have < spec.size and (chunk := response.read(min(_CHUNK, spec.size - have))):
                    out.write(chunk)  # never more than the file's known size
                    have += len(chunk)
                    _set_status(model.key, "downloading", done + have, total)
                    if progress:
                        progress(model.title, done + have, total)
    if _sha256(part) != spec.sha256:
        part.unlink()
        raise ModelUnavailable(
            f"{spec.path} of {model.title} failed its hash check after download and was deleted; "
            "run `inklight models pull` again to fetch it anew"
        )
    os.replace(part, target)
    return done + spec.size


def _set_status(key: str, state: str, done: int, total: int) -> None:
    with _LOCK:
        _STATUS[key] = {"state": state, "done": done, "total": total}


def _clear_status(key: str) -> None:
    with _LOCK:
        _STATUS.pop(key, None)
