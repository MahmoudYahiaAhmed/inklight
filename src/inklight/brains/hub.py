"""Locate small-model files: a local folder first, then the Hugging Face cache.

Nothing is downloaded unless ``allow_download`` is set (or the user runs
``inklight models pull``): network use is always an explicit choice.
"""

from __future__ import annotations

from pathlib import Path

from ..errors import ModelUnavailable

ONNX_FILE = "onnx/model_int8.onnx"
FILES = {
    "reader": [ONNX_FILE, "tokenizer.json", "config.json"],
    "embedder": [ONNX_FILE, "tokenizer.json", "config.json"],
    "writer": [ONNX_FILE, "tokenizer.json", "config.json"],
}


def resolve(
    repo: str, files: list[str], model_dir: Path | None, allow_download: bool, revision: str | None = None
) -> dict[str, Path]:
    """Return {relative name: local path} for every file, or raise ModelUnavailable.

    ``revision`` pins an exact Hugging Face commit; a cached copy of another revision is not used.
    """
    if model_dir is not None:
        base = model_dir / repo.replace("/", "--")
        found = {f: base / f for f in files}
        if all(p.is_file() for p in found.values()):
            return found
    try:
        from huggingface_hub import hf_hub_download, try_to_load_from_cache
    except ImportError as exc:  # pragma: no cover - indra-ocr depends on it
        raise ModelUnavailable("huggingface_hub is required to locate models") from exc
    out: dict[str, Path] = {}
    for name in files:
        cached = try_to_load_from_cache(repo, name, revision=revision)
        if isinstance(cached, str):
            out[name] = Path(cached)
            continue
        if not allow_download:
            raise ModelUnavailable(
                f"{repo} is not installed. Run `inklight models pull` (downloads once, then works offline)."
            )
        try:
            out[name] = Path(hf_hub_download(repo, name, revision=revision))
        except Exception as exc:
            raise ModelUnavailable(f"Could not download {repo}/{name}: {exc}") from exc
    return out


def pull(repo: str, files: list[str], model_dir: Path | None = None, revision: str | None = None) -> dict[str, Path]:
    """Download (or copy into ``model_dir``) the files of one model."""
    from huggingface_hub import hf_hub_download

    out = {}
    for name in files:
        if model_dir is not None:
            local = hf_hub_download(repo, name, revision=revision, local_dir=str(model_dir / repo.replace("/", "--")))
        else:
            local = hf_hub_download(repo, name, revision=revision)
        out[name] = Path(local)
    return out


def installed(repo: str, files: list[str], model_dir: Path | None, revision: str | None = None) -> bool:
    try:
        resolve(repo, files, model_dir, allow_download=False, revision=revision)
    except ModelUnavailable:
        return False
    return True
