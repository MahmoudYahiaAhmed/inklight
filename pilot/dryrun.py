"""Rehearse the pilot end to end on synthetic invoices, with a scripted reviewer. NOT pilot results.

    python -I pilot/dryrun.py --data <evaldata root> --work <empty dir> --documents 20 [--config pilot-config.toml]

Runs intake -> ingest -> review (and manual entry on every 4th document) -> approve -> export -> evaluate, on
Voxel51 *development* invoices (synthetic), in the ``synthetic-invoice`` cohort. The scripted reviewer takes
each final value from the dataset annotation: it accepts a matching prediction, corrects a wrong one and
marks a missing one absent. Its timings are meaningless, and agreement between its two entries is perfect by
construction. What the rehearsal does show: the workflow runs, nothing is lost between prediction and export,
and the evaluator agrees with the benchmark harness scoring of the same documents.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "bench"))
import evaluate  # noqa: E402
import intake  # noqa: E402
import scoring  # noqa: E402

FIELDS = ["vendor", "customer", "invoice_number", "date", "tax", "total"]
REVIEWER = "dry-run-script"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, type=Path, help="evaldata root (bench/prepare_external.py)")
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--documents", type=int, default=20)
    ap.add_argument("--config", type=Path, default=None)
    args = ap.parse_args()
    if args.work.exists() and any(args.work.iterdir()):
        sys.exit(f"--work {args.work} is not empty")
    from inklight import DocumentAgent, load_settings

    split_dir = args.data / "voxel51" / "dev"
    truth = json.loads((split_dir / "truth.json").read_text(encoding="utf-8"))
    names = sorted(truth)[: args.documents]
    manifest = args.work / "manifest.csv"
    args.work.mkdir(parents=True, exist_ok=True)
    with manifest.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(intake.COLUMNS))
        w.writeheader()
        for n in names:
            w.writerow(
                {
                    "file": str((split_dir / "docs" / n).resolve()),
                    "cohort": "synthetic-invoice",
                    "vendor": truth[n]["vendor"] or "unknown",
                    "layout": "voxel51-template",
                    "source": "Voxel51/high-quality-invoice-images-for-ocr (ODbL), dev split",
                    "permission_ref": "public dataset licence (ODbL); dry run",
                    "permission_scope": "evaluation (dry run only)",
                    "personal_data": "no",
                    "redacted": "no",
                }
            )
    data = args.work / "pilot-data"
    taken = intake.intake(manifest, data, reserved_share=0.4, salt="dry-run")
    record = json.loads((data / "intake.json").read_text(encoding="utf-8"))
    by_sha = {d["sha256"]: d for d in record["documents"]}
    settings = (
        load_settings(args.config, home=str(args.work / "home"))
        if args.config
        else load_settings(None, home=str(args.work / "home"), models={"brain": "rules"})
    )
    with DocumentAgent(settings) as agent:
        agent.add(data / "synthetic-invoice" / "dev")
        docs = agent.library.documents()
        for i, doc in enumerate(sorted(docs, key=lambda d: d.name)):
            want = truth[by_sha[doc.sha256]["original_name"]]
            modes = ["review", "manual"] if i % 4 == 0 else ["review"]
            for mode in modes:
                r = agent.open_review(
                    doc.id, FIELDS, reviewer=REVIEWER, mode=mode, cohort="synthetic-invoice", baseline="dry-run"
                )
                full = agent.reviews.get(r.id)  # the script, unlike a person, reads the hidden predictions
                for f in full.fields:
                    value = want.get(f.field)
                    if value is None:
                        agent.reviews.decide(r.id, f.field, reviewer=REVIEWER, action="absent")
                    elif mode == "review" and f.predicted is not None and scoring.same(f.field, f.predicted, value):
                        agent.reviews.decide(r.id, f.field, reviewer=REVIEWER, action="accepted")
                    else:
                        action = "entered" if mode == "manual" else "corrected"
                        agent.reviews.decide(r.id, f.field, reviewer=REVIEWER, action=action, value=str(value))
                agent.reviews.approve(r.id, reviewer=REVIEWER, active_seconds=0.0)
        exported = list(
            csv.DictReader(io.StringIO(agent.reviews.export("csv", actor=REVIEWER, cohort="synthetic-invoice")))
        )
        reviews = [r.model_dump(mode="json") for r in agent.reviews.find(status="approved")]
    metrics, failures = evaluate.evaluate(reviews, record, "synthetic-invoice", "dev")
    # The benchmark harness's own scoring of the same predictions against the same annotations.
    harness = scoring.summarize(
        [
            {
                "field": f["field"],
                "outcome5": scoring.outcome(
                    f["field"],
                    f["predicted"],
                    truth[by_sha[r["doc_sha256"]]["original_name"]][f["field"]],
                    f["warning"],
                    f["confidence"],
                ),
            }
            for r in reviews
            if r["mode"] == "review"
            for f in r["fields"]
            if truth[by_sha[r["doc_sha256"]]["original_name"]][f["field"]] is not None
        ]
    )["overall"]
    out = {
        "label": "DRY RUN on synthetic invoices with a scripted reviewer: not pilot results; timings meaningless",
        "intake": {"taken": taken["taken"], "rejected": taken["rejected"]},
        "exported_rows": len(exported),
        "reviews": len(reviews),
        "evaluator": metrics,
        "harness_check": {
            "evaluator_field_accuracy": metrics["fields"]["field_accuracy"]["value"],
            "harness_value_accuracy": harness["value_accuracy"],
            "evaluator_silent_error_rate": metrics["fields"]["silent_error_rate"]["value"],
            "harness_silent_error_rate": harness["silent_error_rate"],
        },
        "failures_found": len(failures),
    }
    (args.work / "dryrun.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "evaluator"}, indent=1))
    print(evaluate.markdown(metrics))


if __name__ == "__main__":
    main()
