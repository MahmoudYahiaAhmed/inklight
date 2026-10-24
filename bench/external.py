"""External evaluation: real OCR on original document files, scored against dataset annotations.

    python -I bench/external.py --data <root> --dataset voxel51 --split dev --brain auto \
        --home <fresh dir> --label head --out results.json [--reference-text]

Runs against whichever ``inklight`` the interpreter imports (PyPI 0.1.0 or a freshly built wheel), using
only the public API, and records exactly what ran: interpreter, ``inklight.__file__``, install method,
wheel hash (``INKLIGHT_EVAL_WHEEL_SHA256``) and git commit (``INKLIGHT_EVAL_COMMIT``).

Model execution is proven independently of Inklight's own counters: ``onnxruntime.InferenceSession.run``
is wrapped and every call is counted per model file (OCR, reader, embedder).

Fields are scored with the five outcomes in bench/scoring.py (correct/wrong x flagged/unflagged, missing).
Requests are scored by bench/tasks.py against numbers computed from the annotations: counts, sums,
currency, values left out, exported rows and values, and whether a refusal names what it refused.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import platform
import sys
import time
from datetime import date
from pathlib import Path

# The harness's own modules sit next to it; -I keeps the dataset and working directories off sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import scoring  # noqa: E402
import tasks  # noqa: E402

FIELDS = {
    "voxel51": ["vendor", "customer", "invoice_number", "date", "tax", "total"],
    "cord": ["total", "subtotal", "tax"],
}


# ---------------------------------------------------------------- provenance + model-call proof

ORT_CALLS: collections.Counter = collections.Counter()


def _instrument_onnxruntime() -> None:
    import onnxruntime as ort

    original_init = ort.InferenceSession.__init__
    original_run = ort.InferenceSession.run

    def init(self, path_or_bytes, *args, **kwargs):  # type: ignore[no-untyped-def]
        p = Path(str(path_or_bytes))
        repo = next((part for part in p.parts if part.startswith("models--")), p.parent.name)
        self._eval_name = f"{repo}/{p.name}" if p.suffix == ".onnx" else "bytes"
        return original_init(self, path_or_bytes, *args, **kwargs)

    def run(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        ORT_CALLS[getattr(self, "_eval_name", "unknown")] += 1
        return original_run(self, *args, **kwargs)

    ort.InferenceSession.__init__ = init
    ort.InferenceSession.run = run


def _component(model_path: str) -> str:
    low = model_path.lower()
    if "distilbert" in low or "squad" in low:
        return "reader"
    if "bge" in low:
        return "embedder"
    if "smollm" in low:
        return "writer"
    if "indra" in low or any(k in low for k in ("det.onnx", "rec", "order.onnx", "orient", "script")):
        return "ocr"
    return "other"


def _harness_commit() -> str | None:
    """The commit of this evaluation code, and whether it has uncommitted changes."""
    import subprocess

    here = Path(__file__).resolve().parent
    try:
        head = subprocess.run(  # noqa: S603, S607 - fixed git command
            ["git", "-C", str(here), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(  # noqa: S603, S607
            ["git", "-C", str(here), "status", "--porcelain", "--", "."], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return f"{head}{' (bench/ modified)' if dirty else ''}"


def provenance() -> dict:
    import inklight

    try:
        from importlib.metadata import distribution

        dist = distribution("inklight")
        direct = dist.read_text("direct_url.json")
        method = f"pip from {json.loads(direct).get('url')}" if direct else "pip from package index (PyPI)"
        dist_version = dist.version
    except Exception as exc:  # running from a source checkout
        method, dist_version = f"source checkout ({type(exc).__name__})", None
    return {
        "inklight_version": getattr(inklight, "__version__", None),
        "dist_version": dist_version,
        "inklight_file": inklight.__file__,
        "install_method": method,
        "wheel_sha256": os.environ.get("INKLIGHT_EVAL_WHEEL_SHA256"),
        "git_commit": os.environ.get("INKLIGHT_EVAL_COMMIT"),
        "harness_commit": _harness_commit(),
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "platform": f"{platform.system()} {platform.machine()}",
        "date": date.today().isoformat(),
    }


# ---------------------------------------------------------------- run


def run(args: argparse.Namespace) -> dict:
    os.environ["INKLIGHT_HOME"] = str(args.home)  # never read the user's own ~/.inklight config or library
    _instrument_onnxruntime()
    from inklight import DocumentAgent, load_settings

    split_dir = Path(args.data) / args.dataset / args.split
    truth = json.loads((split_dir / "truth.json").read_text(encoding="utf-8"))
    if args.reference_text:
        docs = split_dir / "reference_text"
        truth = {f"{Path(k).stem}.txt": v for k, v in truth.items()}
    else:
        docs = split_dir / "docs"
    settings = load_settings(home=args.home, models={"brain": args.brain})
    agent = DocumentAgent(settings, allow_write=True, output_dir=Path(args.home) / "outputs")
    started = time.perf_counter()
    report = agent.add(docs)
    ingest_s = time.perf_counter() - started
    paths = [p for p in sorted(docs.iterdir()) if p.name in truth]
    t0 = time.perf_counter()
    records = {r.name: r for r in agent.extract(paths, fields=FIELDS[args.dataset])}
    extract_s = time.perf_counter() - t0
    rows = []
    methods: collections.Counter = collections.Counter()
    for name, want in truth.items():
        rec = records.get(name)
        for field in FIELDS[args.dataset]:
            if want.get(field) is None:
                continue
            value = rec.fields.get(field) if rec else None
            got = None if value is None else value.value
            if got is not None:
                methods[value.method] += 1
            warning = None if value is None else value.warning
            confidence = None if value is None else value.confidence
            rows.append(
                {
                    "doc": name,
                    "field": field,
                    "want": want[field],
                    "got": got,
                    "raw": None if value is None else value.raw,
                    "method": None if value is None else value.method,
                    "warning": warning,
                    "confidence": confidence,
                    "outcome5": scoring.outcome(field, got, want[field], warning, confidence),
                }
            )
    task_rows = []
    if not args.reference_text:
        scope = [d.id for d in agent.library.documents() if d.name in truth and truth[d.name].get("total") is not None]
        for case in tasks.cases(args.dataset, truth):
            task_rows.append(tasks.run_case(agent, case, scope))
    brain = agent.library.brain
    usage = brain.usage() if hasattr(brain, "usage") else {"note": "Brain.usage() not available in this version"}
    components: collections.Counter = collections.Counter()
    for model, n in ORT_CALLS.items():
        components[_component(model)] += n
    result = {
        "schema": 2,
        "label": args.label,
        "dataset": args.dataset,
        "genuine": args.dataset == "cord",
        "split": args.split,
        "brain_mode": args.brain,
        "input": "reference_text (diagnostic, not the OCR pipeline)"
        if args.reference_text
        else "original files via OCR",
        "provenance": provenance(),
        "documents": len(truth),
        "ingest_failed": len(report.failed),
        "ingest_s": round(ingest_s, 2),
        "extract_s": round(extract_s, 2),
        "extraction": scoring.summarize(rows),
        "value_methods": dict(methods),
        "tasks": {
            "n": len(task_rows),
            "outcomes": dict(collections.Counter(r["outcome"] for r in task_rows)),
            "items": task_rows,
        },
        "model_execution": {
            "onnxruntime_calls_by_component": dict(components),
            "onnxruntime_calls_by_model": dict(ORT_CALLS),
            "brain_usage": usage,
            "brain_label": brain.label() if hasattr(brain, "label") else None,
        },
        "rows": rows,
    }
    if hasattr(agent, "close"):  # 0.1.0 has no close(); its connections end with the process
        agent.close()
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--dataset", choices=sorted(FIELDS), required=True)
    ap.add_argument("--split", choices=["dev", "holdout", "fresh"], required=True)
    ap.add_argument("--brain", choices=["rules", "auto"], required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--reference-text", action="store_true")
    args = ap.parse_args()
    if Path(args.home).exists() and any(Path(args.home).iterdir()):
        sys.exit(f"--home {args.home} is not empty: each run needs its own fresh library database")
    if Path(args.out).exists():
        sys.exit(f"--out {args.out} exists: result files are never overwritten")
    result = run(args)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    o = result["extraction"]["overall"]
    print(
        f"{args.label} {args.dataset}/{args.split} {args.brain}: accuracy {o['value_accuracy']} "
        f"coverage-without-review {o['coverage_without_review']} precision-unflagged {o['precision_unflagged']} "
        f"silent {o['silent_error_rate']} review {o['review_rate']} | tasks {result['tasks']['outcomes']}"
    )


if __name__ == "__main__":
    main()
