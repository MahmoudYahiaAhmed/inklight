"""Freeze the pilot baseline: exact code, dependencies and model files. Verify before every pilot session.

    python -I pilot/freeze.py freeze --models-out <dir outside the repo> [--brain rules]
    python -I pilot/freeze.py verify --models <same dir> --config <pilot config.toml>

Run both with the interpreter of the pilot's own virtual environment (the one with the pilot wheel installed).

``freeze`` records in pilot/baseline.json:

* the installed ``inklight`` version and a digest of every file of the installed package (so the check does
  not depend on how it was installed), plus the git commit and the tree hash of ``src/`` it was built from;
* the exact version of every package in the environment (pilot/requirements-lock.txt);
* the OCR models (Indra's pinned snapshot) and the small models, copied into ``--models-out`` with the sha256
  of every file and the Hugging Face revision they came from;
* the settings the pilot runs with, written to ``--models-out``/pilot-config.toml.

``verify`` recomputes all of it and exits non-zero on any difference. Nothing is ever downloaded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASELINE = HERE / "baseline.json"
LOCK = HERE / "requirements-lock.txt"
SMALL_MODELS = {"reader": "Xenova/distilbert-base-cased-distilled-squad", "embedder": "Xenova/bge-small-en-v1.5"}
SMALL_FILES = ["onnx/model_int8.onnx", "tokenizer.json", "config.json"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def package_digest() -> tuple[str, int]:
    import inklight

    root = Path(inklight.__file__).resolve().parent
    files = sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    h = hashlib.sha256()
    for p in files:
        h.update(f"{p.relative_to(root).as_posix()}\0{sha256(p)}\n".encode())
    return h.hexdigest(), len(files)


def lock_lines() -> list[str]:
    return sorted(f"{d.metadata['Name']}=={d.version}" for d in metadata.distributions() if d.metadata["Name"])


def git(*args: str) -> str | None:
    try:
        return subprocess.run(  # noqa: S603 - fixed git command
            ["git", "-C", str(HERE.parent), *args],  # noqa: S607 - git on PATH
            capture_output=True,
            text=True,
            check=True,  # noqa: S607
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def tree_files(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): sha256(p) for p in sorted(folder.rglob("*")) if p.is_file()}


def freeze(models_out: Path, brain: str) -> None:
    from huggingface_hub import try_to_load_from_cache

    import inklight
    from inklight import modelstore

    if git("status", "--porcelain", "--", "src") not in ("", None):
        sys.exit("src/ has uncommitted changes: commit them first, so the baseline names real code")
    if models_out.exists() and any(models_out.iterdir()):
        sys.exit(f"{models_out} is not empty: freeze into a new folder")
    ocr_src = modelstore.ensure(modelstore.OCR)  # the pinned OCR models, verified
    ocr_dst = models_out / "indra"
    shutil.copytree(ocr_src, ocr_dst)
    small: dict[str, dict] = {}
    for role, repo in SMALL_MODELS.items():
        dst = models_out / "small" / repo.replace("/", "--")
        revision = None
        for name in SMALL_FILES:
            cached = try_to_load_from_cache(repo, name)
            if not isinstance(cached, str):
                sys.exit(f"{repo}/{name} is not in the local cache: run `inklight models pull` first")
            parts = Path(cached).parts
            revision = parts[parts.index("snapshots") + 1]
            (dst / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached, dst / name)
        small[role] = {"repo": repo, "revision": revision}
    digest, n_files = package_digest()
    config = models_out / "pilot-config.toml"
    config.write_text(
        "# Written by pilot/freeze.py. `home` holds the pilot library and its reviews: keep it on a backed-up disk.\n"
        f'home = "{(models_out / "pilot-home").as_posix()}"\n\n'
        "[models]\n"
        f'brain = "{brain}"\n'
        f'model_dir = "{(models_out / "small").as_posix()}"\n'
        f'reader_revision = "{small["reader"]["revision"]}"\n'
        f'embedder_revision = "{small["embedder"]["revision"]}"\n'
        "allow_download = false\n\n"
        "[ocr]\n"
        f'model_dir = "{ocr_dst.as_posix()}"\n\n'
        "[extraction]\n"
        "second_reading = true\n",
        encoding="utf-8",
    )
    LOCK.write_text("\n".join(lock_lines()) + "\n", encoding="utf-8")
    baseline = {
        "frozen_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "inklight_version": inklight.__version__,
        "package_digest": digest,
        "package_files": n_files,
        "git_commit": git("rev-parse", "HEAD"),
        "src_tree": git("rev-parse", "HEAD:src"),
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
        "requirements_lock_sha256": sha256(LOCK),
        "brain": brain,
        "second_reading": True,
        "ocr_models_revision": modelstore.OCR.revision,
        "ocr_models": {"source": str(ocr_src.name), "files": tree_files(ocr_dst)},
        "small_models": {
            role: {**info, "files": tree_files(models_out / "small" / info["repo"].replace("/", "--"))}
            for role, info in small.items()
        },
    }
    BASELINE.write_text(json.dumps(baseline, indent=1) + "\n", encoding="utf-8")
    print(f"froze {inklight.__version__} ({digest[:12]}, {n_files} files) at {baseline['git_commit']}")
    print(f"models copied to {models_out}; settings in {config}")
    print("Commit pilot/baseline.json and pilot/requirements-lock.txt, then run `verify` before every session.")


def verify(models: Path, config: Path | None) -> int:
    import inklight

    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    problems: list[str] = []
    digest, _ = package_digest()
    if inklight.__version__ != base["inklight_version"] or digest != base["package_digest"]:
        problems.append(f"installed inklight differs from the baseline ({inklight.__version__}, {digest[:12]})")
    if "\n".join(lock_lines()) + "\n" != LOCK.read_text(encoding="utf-8"):
        problems.append("installed packages differ from pilot/requirements-lock.txt")
    if tree_files(models / "indra") != base["ocr_models"]["files"]:
        problems.append("OCR model files differ from the baseline")
    for role, info in base["small_models"].items():
        if tree_files(models / "small" / info["repo"].replace("/", "--")) != info["files"]:
            problems.append(f"{role} model files differ from the baseline")
    if config is not None:
        from inklight.config import load_settings

        s = load_settings(config)
        expected = {
            "models.brain": base["brain"],
            "models.reader_revision": base["small_models"]["reader"]["revision"],
            "models.embedder_revision": base["small_models"]["embedder"]["revision"],
            "models.allow_download": False,
            "extraction.second_reading": base["second_reading"],
            "ocr.model_dir": (models / "indra").as_posix(),
        }
        actual = {
            "models.brain": s.models.brain,
            "models.reader_revision": s.models.reader_revision,
            "models.embedder_revision": s.models.embedder_revision,
            "models.allow_download": s.models.allow_download,
            "extraction.second_reading": s.extraction.second_reading,
            "ocr.model_dir": Path(s.ocr.model_dir).as_posix() if s.ocr.model_dir else None,
        }
        problems += [f"setting {k} is {actual[k]!r}, baseline {v!r}" for k, v in expected.items() if actual[k] != v]
    for p in problems:
        print(f"FAIL {p}")
    if not problems:
        print(f"OK matches the pilot baseline: inklight {base['inklight_version']} at {base['git_commit'][:12]}")
    return 1 if problems else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--models-out", required=True, type=Path)
    f.add_argument("--brain", choices=["rules", "auto"], default="rules")
    v = sub.add_parser("verify")
    v.add_argument("--models", required=True, type=Path)
    v.add_argument("--config", type=Path, default=None)
    args = ap.parse_args()
    if args.cmd == "freeze":
        freeze(args.models_out.resolve(), args.brain)
    else:
        sys.exit(verify(args.models.resolve(), args.config))


if __name__ == "__main__":
    main()
