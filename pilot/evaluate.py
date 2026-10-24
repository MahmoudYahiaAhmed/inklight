"""Pilot evaluation from approved human reviews.

    python -I pilot/evaluate.py --config <pilot-config.toml> --intake <data>/intake.json \
        --cohort genuine-invoice --split dev --out <results dir>

    # the reserved group: only to evaluate a finished improvement, and every access is logged
    python -I pilot/evaluate.py ... --split reserved --reason "evaluate build <commit> after fixes X, Y"

Ground truth is the reviewer's approved final value. Each predicted field is one of the five outcomes in
bench/scoring.py (correct/wrong x flagged/unflagged, missing), plus ``both_absent`` when neither the document
nor the prediction has a value (kept out of the rates, reported as a count). Reported per cohort and split,
never merged:

* field accuracy, coverage without review, precision among unflagged values, silent-error rate, each with
  a 95% Wilson interval (small pilots have wide intervals; read them);
* review burden: share of predicted values flagged, share corrected, active and wall seconds per document;
* manual entry: seconds per document with predictions hidden, and, on documents entered both ways, the
  agreement of the two final values (a check on the ground truth and on anchoring to predictions);
* the baselines the reviews were made with (a mixed set is refused unless --allow-mixed-baselines).

For the dev split, failures.csv lists every wrong or missing value with its warning, for development. For the
reserved split, only aggregates are written, so the reserved documents cannot drive changes.
"""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

OUTCOMES = ("correct_unflagged", "correct_flagged", "wrong_unflagged", "wrong_flagged", "missing")
MONEY = {"subtotal", "tax", "total", "contract_value"}


def same(field: str, a: Any, b: Any) -> bool:
    if field in MONEY:
        try:
            return abs(float(a) - float(b)) < 0.011
        except (TypeError, ValueError):
            return False
    if field.endswith("date") or field == "date":
        return str(a) == str(b)
    norm = lambda v: re.sub(r"[^a-z0-9]", "", str(v).lower())  # noqa: E731
    return norm(a) == norm(b)


def outcome(field: dict) -> str:
    pred, truth = field["predicted"], field["final"]
    if pred is None and truth is None:
        return "both_absent"
    if pred is None:
        return "missing"
    right = truth is not None and same(field["field"], pred, truth)
    return f"{'correct' if right else 'wrong'}_{'flagged' if field['flagged'] else 'unflagged'}"


def wilson(k: int, n: int) -> list[float] | None:
    if not n:
        return None
    z, p = 1.96, k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def rates(c: Counter) -> dict[str, Any]:
    n = sum(c[o] for o in OUTCOMES)
    cu, cf, wu, _wf, _m = (c[o] for o in OUTCOMES)

    def r(k: int, d: int) -> dict[str, Any]:
        return {"value": round(k / d, 3) if d else None, "ci95": wilson(k, d), "k": k, "n": d}

    return {
        "n": n,
        "counts": {o: c[o] for o in (*OUTCOMES, "both_absent")},
        "field_accuracy": r(cu + cf, n),
        "coverage_without_review": r(cu, n),
        "precision_unflagged": r(cu, cu + wu),
        "silent_error_rate": r(wu, n),
    }


def seconds(values: list[float]) -> dict[str, Any]:
    vals = [v for v in values if v is not None]
    if not vals:
        return {"n": 0}
    return {"n": len(vals), "median": round(statistics.median(vals), 1), "mean": round(statistics.mean(vals), 1)}


def evaluate(reviews: list[dict], intake: dict, cohort: str, split: str) -> tuple[dict, list[dict]]:
    by_sha = {d["sha256"]: d for d in intake["documents"]}
    chosen, outside = [], 0
    for r in reviews:
        doc = by_sha.get(r["doc_sha256"])
        if doc is None:
            outside += 1
            continue
        if doc["cohort"] == cohort and doc["split"] == split:
            chosen.append((r, doc))
    review_mode = [(r, d) for r, d in chosen if r["mode"] == "review"]
    manual_mode = [(r, d) for r, d in chosen if r["mode"] == "manual"]
    overall: Counter = Counter()
    per_field: dict[str, Counter] = defaultdict(Counter)
    flagged = corrected = predicted = 0
    failures = []
    for r, d in review_mode:
        for f in r["fields"]:
            o = outcome(f)
            overall[o] += 1
            per_field[f["field"]][o] += 1
            predicted += f["predicted"] is not None
            flagged += bool(f["flagged"])
            corrected += f["action"] == "corrected" and f["predicted"] is not None
            if o in ("wrong_unflagged", "wrong_flagged", "missing"):
                failures.append(
                    {
                        "outcome": o,
                        "document": d["stored_as"],
                        "vendor_group": d["vendor_group"],
                        "layout": d.get("layout"),
                        "field": f["field"],
                        "predicted": f["predicted"],
                        "predicted_raw": f["raw"],
                        "final": f["final"],
                        "method": f["method"],
                        "confidence": f["confidence"],
                        "warning": f["warning"],
                        "review_id": r["id"],
                    }
                )
    paired = {r["doc_sha256"] for r, _ in review_mode} & {r["doc_sha256"] for r, _ in manual_mode}
    agreement: Counter = Counter()
    for sha in paired:
        rv = next(r for r, _ in review_mode if r["doc_sha256"] == sha)
        mn = next(r for r, _ in manual_mode if r["doc_sha256"] == sha)
        manual_final = {f["field"]: f["final"] for f in mn["fields"]}
        for f in rv["fields"]:
            if f["field"] not in manual_final:
                continue  # only fields entered both ways are compared
            m = manual_final[f["field"]]
            agree = (m is None and f["final"] is None) or (
                m is not None and f["final"] is not None and same(f["field"], m, f["final"])
            )
            agreement["agree" if agree else "disagree"] += 1
            if not agree and f["action"] == "accepted":
                agreement["disagree_where_review_accepted_the_prediction"] += 1
    metrics = {
        "cohort": cohort,
        "split": split,
        "documents_reviewed": len(review_mode),
        "documents_manual_entry": len(manual_mode),
        "reviews_not_in_intake": outside,
        "baselines": sorted({r["baseline"] or "unrecorded" for r, _ in chosen}),
        "fields": rates(overall),
        "per_field": {k: rates(v) for k, v in sorted(per_field.items())},
        "review_burden": {
            "predicted_values": predicted,
            "flagged_share": round(flagged / predicted, 3) if predicted else None,
            "corrected_share": round(corrected / predicted, 3) if predicted else None,
            "active_seconds_per_document": seconds([r["active_seconds"] for r, _ in review_mode]),
            "wall_seconds_per_document": seconds([r["wall_seconds"] for r, _ in review_mode]),
        },
        "manual_entry": {
            "active_seconds_per_document": seconds([r["active_seconds"] for r, _ in manual_mode]),
            "wall_seconds_per_document": seconds([r["wall_seconds"] for r, _ in manual_mode]),
            "documents_entered_both_ways": len(paired),
            "agreement_on_those": dict(agreement),
        },
    }
    rv_t = metrics["review_burden"]["active_seconds_per_document"]
    mn_t = metrics["manual_entry"]["active_seconds_per_document"]
    metrics["time_ratio_review_vs_manual"] = (
        round(rv_t["median"] / mn_t["median"], 2) if rv_t.get("median") and mn_t.get("median") else None
    )
    return metrics, failures


def repredict(reviews: list[dict], config: Path) -> tuple[list[dict], dict]:
    """Predict every reviewed document again with the *installed* build; keep the approved final values.

    This is how a later improvement is evaluated: same documents, same human ground truth, new predictions.
    """
    import inklight
    from inklight import DocumentAgent
    from inklight.config import load_settings
    from inklight.review import is_flagged

    settings = load_settings(config)
    out = []
    with DocumentAgent(settings) as agent:
        by_sha = {d.sha256: d for d in agent.library.documents()}
        for r in reviews:
            doc = by_sha.get(r["doc_sha256"])
            if doc is None:
                raise SystemExit(f"document of review {r['id']} is no longer in the pilot library")
            names = [f["field"] for f in r["fields"]]
            record = agent.extract([doc.path], fields=names)[0]
            fields = []
            for f in r["fields"]:
                v = record.fields.get(f["field"])
                fields.append(
                    {
                        **f,
                        "predicted": None if v is None else v.value,
                        "raw": None if v is None else v.raw,
                        "confidence": None if v is None else v.confidence,
                        "method": None if v is None else v.method,
                        "warning": None if v is None else v.warning,
                        "flagged": bool(v is not None and v.value is not None and is_flagged(v)),
                    }
                )
            out.append({**r, "fields": fields, "baseline": f"re-predicted with {inklight.__version__}"})
    return out, {"inklight_version": inklight.__version__, "inklight_file": inklight.__file__}


def load_reviews(config: Path) -> list[dict]:
    from inklight.config import load_settings
    from inklight.review import ReviewStore
    from inklight.store import Store

    settings = load_settings(config)
    with Store(settings.db_path) as store:
        return [r.model_dump(mode="json") for r in ReviewStore(store).find(status="approved")]


def markdown(m: dict) -> str:
    f = m["fields"]

    def show(x: dict) -> str:
        if x["value"] is None:
            return "–"
        lo, hi = x["ci95"]
        return f"{100 * x['value']:.1f}% ({x['k']}/{x['n']}; 95% CI {100 * lo:.0f}–{100 * hi:.0f}%)"

    rb = m.get("review_burden") or {"flagged_share": "–", "corrected_share": "–", "active_seconds_per_document": "–"}
    me = m["manual_entry"]
    lines = [
        f"# Pilot evaluation: {m['cohort']} / {m['split']}",
        "",
        f"Documents reviewed: {m['documents_reviewed']} · manual entry: {m['documents_manual_entry']} · "
        f"baselines: {', '.join(m['baselines'])}",
        "",
        f"Predictions: {m.get('predictions', 'frozen when each review opened')}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Field accuracy | {show(f['field_accuracy'])} |",
        f"| Coverage without review | {show(f['coverage_without_review'])} |",
        f"| Precision, unflagged | {show(f['precision_unflagged'])} |",
        f"| Silent error rate | {show(f['silent_error_rate'])} |",
        f"| Predicted values flagged | {rb['flagged_share']} |",
        f"| Predicted values corrected | {rb['corrected_share']} |",
        f"| Active seconds per document, review | {rb['active_seconds_per_document']} |",
        f"| Active seconds per document, manual entry | {me['active_seconds_per_document']} |",
        f"| Time ratio review / manual (medians) | {m.get('time_ratio_review_vs_manual', '–')} |",
        f"| Documents entered both ways · agreement | {me['documents_entered_both_ways']} · "
        f"{me['agreement_on_those']} |",
        "",
        f"Counts: {f['counts']}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--intake", required=True, type=Path)
    ap.add_argument("--cohort", default="genuine-invoice", choices=["genuine-invoice", "synthetic-invoice", "receipt"])
    ap.add_argument("--split", default="dev", choices=["dev", "reserved"])
    ap.add_argument("--reason", default=None, help="Required for --split reserved; recorded in the access log.")
    ap.add_argument("--allow-mixed-baselines", action="store_true")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument(
        "--repredict",
        action="store_true",
        help="Score the installed build's new predictions against the approved values (later improvements).",
    )
    args = ap.parse_args()
    intake = json.loads(args.intake.read_text(encoding="utf-8"))
    if args.split == "reserved":
        if not args.reason or len(args.reason.strip()) < 10:
            sys.exit("--split reserved needs --reason: which finished build is being evaluated, and why now")
        log = args.intake.parent / "reserved_access.log"
        with log.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "at": datetime.now(UTC).isoformat(timespec="seconds"),
                        "by": getpass.getuser(),
                        "cohort": args.cohort,
                        "reason": args.reason,
                    }
                )
                + "\n"
            )
        print(f"Reserved access recorded in {log}. Only aggregate results are written.")
    reviews = load_reviews(args.config)
    predicted_by = "predictions frozen when each review opened"
    if args.repredict:
        reviews, build = repredict(reviews, args.config)
        predicted_by = f"re-predicted by the installed build {build}"
    metrics, failures = evaluate(reviews, intake, args.cohort, args.split)
    metrics["predictions"] = predicted_by
    if args.repredict:  # review timings belong to the original predictions, not to the new ones
        metrics.pop("review_burden", None)
        metrics.pop("time_ratio_review_vs_manual", None)
    if len(metrics["baselines"]) > 1 and not args.allow_mixed_baselines:
        sys.exit(f"reviews come from several baselines {metrics['baselines']}: evaluate one baseline at a time")
    args.out.mkdir(parents=True, exist_ok=True)
    stem = f"{args.cohort}-{args.split}"
    (args.out / f"{stem}.json").write_text(json.dumps(metrics, indent=1), encoding="utf-8")
    (args.out / f"{stem}.md").write_text(markdown(metrics), encoding="utf-8")
    if args.split == "dev":
        with (args.out / f"{stem}-failures.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(failures[0]) if failures else ["outcome"])
            writer.writeheader()
            writer.writerows(failures)
    print(markdown(metrics))


if __name__ == "__main__":
    main()
