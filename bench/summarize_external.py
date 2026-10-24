"""Tables for docs/BENCHMARKS.md from bench/external.py result files.

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


def fields_table(runs: list[dict]) -> str:
    rows = [
        "| Build | Dataset | Split | Brain | Values | Correct (useful coverage) | Abstained | Wrong, flagged |"
        " Wrong, silent | Precision when unflagged |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for d in runs:
        o = d["extraction"]["overall"]
        kind = "receipts, genuine" if d["genuine"] else "invoices, synthetic"
        rows.append(
            f"| {ENV_NAMES.get(d['_env'], d['_env'])} | {d['dataset']} ({kind}) | {d['split']} | {d['brain_mode']} "
            f"| {o['n']} | {pct(o['correct'])} | {pct(o['abstained'])} | {pct(o['wrong_flagged'])} "
            f"| {pct(o['wrong_silent'])} | {pct(o['precision_unflagged'])} |"
        )
    return "\n".join(rows)


def per_field(runs: list[dict]) -> str:
    rows = ["| Build | Dataset | Split | Field | n | Correct | Abstained | Wrong, flagged | Wrong, silent |"]
    rows.append("|---|---|---|---|---|---|---|---|---|")
    for d in runs:
        if d["brain_mode"] != "rules":
            continue
        for name, f in d["extraction"]["fields"].items():
            rows.append(
                f"| {ENV_NAMES.get(d['_env'], d['_env'])} | {d['dataset']} | {d['split']} | {name} | {f['n']} "
                f"| {pct(f['correct'])} | {pct(f['abstained'])} | {pct(f['wrong_flagged'])} "
                f"| {pct(f['wrong_silent'])} |"
            )
    return "\n".join(rows)


def requests_table(runs: list[dict]) -> str:
    rows = [
        "| Build | Split | Brain | Supported: correct | Supported: flagged | Supported: silent wrong |"
        " Unsupported: useful abstention | Unsupported: silent wrong |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for d in runs:
        items = d["requests"]["items"]
        if not items:
            continue
        sup = [r for r in items if r.get("supported", True)]
        uns = [r for r in items if not r.get("supported", True)]

        def n(rs: list[dict], *outs: str) -> str:
            return f"{sum(r['outcome'] in outs for r in rs)}/{len(rs)}"

        rows.append(
            f"| {ENV_NAMES.get(d['_env'], d['_env'])} | {d['split']} | {d['brain_mode']} | {n(sup, 'correct')} "
            f"| {n(sup, 'unnecessary_abstention', 'flagged_wrong')} | {n(sup, 'silent_wrong')} "
            f"| {n(uns, 'useful_abstention')} | {n(uns, 'silent_wrong')} |"
        )
    return "\n".join(rows)


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
        ("Field extraction", fields_table),
        ("Per field (rules brain)", per_field),
        ("Requests", requests_table),
        ("Model execution", execution_table),
    ):
        print(f"\n### {title}\n\n{fn(runs)}")


if __name__ == "__main__":
    main()
