"""Provenance and model-execution tables from bench/external.py result files.

Field and task results are tabulated by bench/rescore.py, which scores every file with the same
five-outcome definitions (bench/scoring.py).

python bench/summarize_external.py <results dir> [--prefix final]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ENV_NAMES = {
    "A": "PyPI 0.1.0",
    "B": "before fixes",
    "C": "fix 1",
    "D": "fix 2",
    "E": "pre-final",
    "F": "final",
    "G": "digit-loss check",
    "H": "amount check v2",
}


def pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.1f}%"


def load(directory: Path, prefix: str) -> list[dict]:
    out = []
    for f in sorted(directory.glob(f"{prefix}-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        d["_env"] = f.stem.split("-")[1]
        out.append(d)
    return out


def execution_table(runs: list[dict]) -> str:
    rows = ["| Build | Dataset | Split | Brain | OCR calls | Reader calls | Embedder calls | Writer | Brain usage |"]
    rows.append("|---|---|---|---|---|---|---|---|---|")
    for d in runs:
        m = d["model_execution"]
        c = m["onnxruntime_calls_by_component"]
        usage = m["brain_usage"]
        short = (
            ", ".join(f"{k}: loaded={v.get('loaded')}" for k, v in usage.items() if isinstance(v, dict))
            if "note" not in usage
            else usage["note"]
        )
        rows.append(
            f"| {ENV_NAMES.get(d['_env'], d['_env'])} | {d['dataset']} | {d['split']} | {d['brain_mode']} "
            f"| {c.get('ocr', 0)} | {c.get('reader', 0)} | {c.get('embedder', 0)} | {c.get('writer', 0)} | {short} |"
        )
    return "\n".join(rows)


def _install(method: str) -> str:
    return f"pip, local wheel {method.rsplit('/', 1)[-1]}" if "file:" in method else method


def provenance_table(runs: list[dict]) -> str:
    seen = {}
    for d in runs:
        seen.setdefault(d["_env"], d["provenance"])
    rows = [
        "| Build | Version | Commit | Wheel sha256 | Installed from | `inklight.__file__` |",
        "|---|---|---|---|---|---|",
    ]
    for env, p in seen.items():
        rows.append(
            f"| {ENV_NAMES.get(env, env)} | {p['inklight_version']} | {p['git_commit']} "
            f"| {p.get('harness_commit') or '–'} "
            f"| `{(p['wheel_sha256'] or '')[:16]}…` "
            f"| {_install(p['install_method'])} | `…{p['inklight_file'][-60:]}` |"
        )
    return "\n".join(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("directory", type=Path)
    ap.add_argument("--prefix", default="final")
    args = ap.parse_args()
    runs = load(args.directory, args.prefix)
    for title, fn in (
        ("Provenance", provenance_table),
        ("Model execution", execution_table),
    ):
        print(f"\n### {title}\n\n{fn(runs)}")


if __name__ == "__main__":
    main()
