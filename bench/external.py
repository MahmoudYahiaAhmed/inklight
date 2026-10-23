"""External evaluation: real OCR on original document files, scored against dataset annotations.

    python -I bench/external.py --data <root> --dataset voxel51 --split dev --brain auto \
        --home <fresh dir> --label head --out results.json [--reference-text]

Runs against whichever ``inklight`` the interpreter imports (PyPI 0.1.0 or a freshly built wheel), using
only the public API, and records exactly what ran: interpreter, ``inklight.__file__``, install method,
wheel hash (``INKLIGHT_EVAL_WHEEL_SHA256``) and git commit (``INKLIGHT_EVAL_COMMIT``).

Model execution is proven independently of Inklight's own counters: ``onnxruntime.InferenceSession.run``
is wrapped and every call is counted per model file (OCR, reader, embedder).

Each field of each document is scored as one of:
  correct · abstained (no value) · wrong_flagged (warning or confidence < 0.7) · wrong_silent.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import platform
import re
import sys
import time
from datetime import date
from pathlib import Path

FIELDS = {
    "voxel51": ["vendor", "customer", "invoice_number", "date", "tax", "total"],
    "cord": ["total", "subtotal", "tax"],
}
MONEY = {"tax", "total", "subtotal"}


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
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "platform": f"{platform.system()} {platform.machine()}",
        "date": date.today().isoformat(),
    }


# ---------------------------------------------------------------- scoring


def _norm_text(v: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(v).lower())


def same(field: str, got: object, want: object) -> bool:
    if field in MONEY:
        try:
            return abs(float(got) - float(want)) < 0.011  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False
    if field == "date":
        return str(got) == str(want)
    return _norm_text(got) == _norm_text(want)


def outcome(field: str, value, want) -> str:  # type: ignore[no-untyped-def]
    if value is None or value.value is None:
        return "abstained"
    if same(field, value.value, want):
        return "correct"
    flagged = bool(value.warning) or (value.confidence or 0) < 0.7
    return "wrong_flagged" if flagged else "wrong_silent"


def summarize(rows: list[dict]) -> dict:
    by_field: dict = collections.defaultdict(collections.Counter)
    for r in rows:
        by_field[r["field"]][r["outcome"]] += 1
    total: collections.Counter = collections.Counter()
    for c in by_field.values():
        total.update(c)

    def rates(c: collections.Counter) -> dict:
        n = sum(c.values())
        answered = n - c["abstained"]
        unflagged = c["correct"] + c["wrong_silent"]
        return {
            "n": n,
            "correct": round(c["correct"] / n, 3) if n else None,  # = useful coverage
            "abstained": round(c["abstained"] / n, 3) if n else None,
            "wrong_flagged": round(c["wrong_flagged"] / n, 3) if n else None,
            "wrong_silent": round(c["wrong_silent"] / n, 3) if n else None,
            "precision_answered": round(c["correct"] / answered, 3) if answered else None,
            "precision_unflagged": round(c["correct"] / unflagged, 3) if unflagged else None,
            "counts": dict(c),
        }

    return {"overall": rates(total), "fields": {f: rates(c) for f, c in sorted(by_field.items())}}


# ---------------------------------------------------------------- requests over the dataset (end to end)


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def request_cases(truth: dict) -> list[dict]:
    """Request forms whose expected document sets come from the annotations.

    ``expected`` is None for requests Inklight does not support: the useful outcome is then an
    abstention (unsupported / partial / a reported not-understood part), never a confident answer.
    """
    rows = {n: t for n, t in truth.items() if t.get("total") is not None}
    totals = sorted(t["total"] for t in rows.values())
    if not totals:
        return []
    thr = round(totals[len(totals) // 2], -1) or totals[len(totals) // 2]
    lo, hi = round(totals[len(totals) // 4]), round(totals[3 * len(totals) // 4])
    above = {n for n, t in rows.items() if t["total"] > thr}

    def by_vendor(word: str) -> set[str]:
        return {n for n, t in truth.items() if t.get("vendor") and _key(word) in _key(t["vendor"])}

    # Single-word vendor names ("Jacobson-Wilson"), each matching only its own invoices.
    words = sorted(
        {t["vendor"] for t in truth.values() if t.get("vendor") and re.fullmatch(r"[A-Za-z-]+", t["vendor"])}
    )
    # v1 has an invoice above the threshold, so the combined forms expect a non-empty answer.
    v1 = next((w for w in words if by_vendor(w) & above), words[0] if words else "Nobody")
    v2 = next((w for w in words if w != v1), v1)
    years = sorted({t["date"][:4] for t in truth.values() if t.get("date")})
    y = years[len(years) // 2] if years else "2020"
    cases = [
        ("threshold", f"Find invoices above ${thr:,.0f}", above),
        ("threshold", f"Find invoices below ${thr:,.0f}", {n for n, t in rows.items() if t["total"] < thr}),
        ("range", f"Find invoices between ${lo:,} and ${hi:,}", {n for n, t in rows.items() if lo <= t["total"] <= hi}),
        ("count", f"how many invoices are above ${thr:,.0f}?", above),
        ("sum", f"What is the total of invoices above ${thr:,.0f}?", above),
        ("vendor", f"Find invoices from {v1}", by_vendor(v1)),
        ("vendor-or", f"Find invoices from {v1} or {v2}", by_vendor(v1) | by_vendor(v2)),
        ("vendor+threshold", f"Find invoices from {v1} above ${thr:,.0f}", by_vendor(v1) & above),
        ("possessive", f"Show {v1}'s invoices", by_vendor(v1)),
        ("possessive-lower", f"show {v1.lower()}'s invoices", by_vendor(v1)),
        ("possessive-curly", f"Show {v1}\u2019s invoices", by_vendor(v1)),
        ("possessive-start", f"{v1}'s invoices above ${thr:,.0f}", by_vendor(v1) & above),
        ("year", f"Find invoices in {y}", {n for n, t in truth.items() if (t.get("date") or "").startswith(y)}),
        ("unsupported", "Find invoices paid late", None),
        ("unsupported", "Find invoices from last month", None),
        ("unsupported", "Show the top 5 invoices by total", None),
        ("unsupported", "Find invoices from March", None),
    ]
    return [{"form": f, "request": r, "expected": e} for f, r, e in cases]


def request_outcome(expected: set[str] | None, got: set[str], state: str, not_understood: list) -> str:
    confident = state == "succeeded" and not not_understood
    if expected is None:
        return "silent_wrong" if confident else "useful_abstention"
    if got == expected:
        return "correct" if confident else "unnecessary_abstention"
    return "silent_wrong" if confident else "flagged_wrong"


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
    agent = DocumentAgent(settings)
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
            if value is not None and value.value is not None:
                methods[value.method] += 1
            rows.append(
                {
                    "doc": name,
                    "field": field,
                    "want": want[field],
                    "got": None if value is None else value.value,
                    "method": None if value is None else value.method,
                    "warning": None if value is None else value.warning,
                    "confidence": None if value is None else value.confidence,
                    "outcome": outcome(field, value, want[field]),
                }
            )
    request_rows = []
    if args.dataset == "voxel51" and not args.reference_text:
        ids = [d.id for d in agent.library.documents() if d.name in truth]
        for case in request_cases(truth):
            expected = case["expected"]
            res = agent.run_plan(agent.plan(case["request"]), ids, save=False)
            got = {r.name for r in res.records}
            state = res.state.value
            not_understood = list(getattr(res, "not_understood", ()) or ())
            request_rows.append(
                {
                    **{k: v for k, v in case.items() if k != "expected"},
                    "supported": expected is not None,
                    "state": state,
                    "returned": len(got),
                    "expected": None if expected is None else len(expected),
                    "missing": [] if expected is None else sorted(expected - got)[:10],
                    "extra": [] if expected is None else sorted(got - expected)[:10],
                    "not_understood": not_understood,
                    "outcome": request_outcome(expected, got, state, not_understood),
                }
            )
    brain = agent.library.brain
    usage = brain.usage() if hasattr(brain, "usage") else {"note": "Brain.usage() not available in this version"}
    components: collections.Counter = collections.Counter()
    for model, n in ORT_CALLS.items():
        components[_component(model)] += n
    result = {
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
        "extraction": summarize(rows),
        "value_methods": dict(methods),
        "requests": {
            "n": len(request_rows),
            "outcomes": dict(collections.Counter(r["outcome"] for r in request_rows)),
            "items": request_rows,
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
    ap.add_argument("--split", choices=["dev", "holdout"], required=True)
    ap.add_argument("--brain", choices=["rules", "auto"], required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--reference-text", action="store_true")
    args = ap.parse_args()
    if Path(args.home).exists() and any(Path(args.home).iterdir()):
        sys.exit(f"--home {args.home} is not empty: each run needs its own fresh library database")
    result = run(args)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
    o = result["extraction"]["overall"]
    print(
        f"{args.label} {args.dataset}/{args.split} {args.brain}: correct {o['correct']} abstained {o['abstained']} "
        f"flagged-wrong {o['wrong_flagged']} silent-wrong {o['wrong_silent']} | requests "
        f"{result['requests']['outcomes']} | ort {result['model_execution']['onnxruntime_calls_by_component']}"
    )


if __name__ == "__main__":
    main()
