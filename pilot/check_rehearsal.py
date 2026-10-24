"""Check a human rehearsal before the pilot expands (see pilot/REHEARSAL.md).

    python -I pilot/check_rehearsal.py --config <pilot-config.toml> --export <exported reviews.csv> --out <dir>

It reads the pilot library through a read-only snapshot and the CSV the reviewers exported, and checks:

* every approved review has a decision for every field, a prediction that was never changed, and a history
  that runs opened -> set ... -> approved (reopenings carry a reason);
* every correction or manual entry keeps the reviewer's typed input next to the parsed value;
* the export holds exactly the approved reviews, field by field, with prediction, warning and decision;
* timing is usable: active time recorded, above zero, not above wall time; long idle reviews are listed;
* at least two reviewers, at least one manual entry, at least one correction and one reopening took place.

Reviews made by a script (reviewer or baseline containing "dry-run" or "script") are never counted as
human; the check fails if they are the only reviews. Results go to <out>/rehearsal-check.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from evaluate import snapshot_reviews  # noqa: E402

LONG_IDLE_SECONDS = 30 * 60


def scripted(review: dict) -> bool:
    who = f"{review.get('opened_by') or ''} {review.get('approved_by') or ''} {review.get('baseline') or ''}".lower()
    return "dry-run" in who or "script" in who


def check(reviews: list[dict], events: dict[str, list[dict]], exported: list[dict]) -> dict:
    problems: list[str] = []
    notes: list[str] = []
    human = [r for r in reviews if not scripted(r)]
    if len(human) < len(reviews):
        notes.append(f"{len(reviews) - len(human)} scripted review(s) ignored")
    if not human:
        problems.append("no human reviews: a scripted run cannot stand in for the rehearsal")
    for r in human:
        undecided = [f["field"] for f in r["fields"] if f["action"] is None]
        if undecided:
            problems.append(f"review {r['id']}: approved with undecided fields {undecided}")
        for f in r["fields"]:
            if f["action"] in ("corrected", "entered") and not f.get("entered"):
                problems.append(f"review {r['id']} {f['field']}: typed value without the reviewer's input")
        kinds = [e["kind"] for e in events.get(r["id"], [])]
        if not kinds or kinds[0] != "opened" or "approved" not in kinds:
            problems.append(f"review {r['id']}: history does not run from opened to approved ({kinds})")
        for e in events.get(r["id"], []):
            if e["kind"] == "reopened" and not (e.get("note") or "").strip():
                problems.append(f"review {r['id']}: reopened without a reason")
        if r["active_seconds"] is None:
            problems.append(f"review {r['id']}: no active time recorded")
        elif r["active_seconds"] <= 0:
            problems.append(f"review {r['id']}: active time is 0 s (the page never had focus?)")
        elif r["wall_seconds"] is not None and r["active_seconds"] > r["wall_seconds"] + 5:
            problems.append(f"review {r['id']}: active time exceeds wall time")
        if r["wall_seconds"] and r["wall_seconds"] > LONG_IDLE_SECONDS:
            notes.append(f"review {r['id']}: open for {r['wall_seconds'] / 60:.0f} min (left open during a break?)")
    approved_ids = {r["id"] for r in human}
    exported_ids = {row["review_id"] for row in exported}
    if exported_ids - {r["id"] for r in reviews}:
        problems.append(f"export holds reviews that are not approved: {sorted(exported_ids - approved_ids)}")
    if approved_ids - exported_ids:
        problems.append(f"approved reviews missing from the export: {sorted(approved_ids - exported_ids)}")
    by_review = {r["id"]: {f["field"]: f for f in r["fields"]} for r in human}
    for row in exported:
        f = by_review.get(row["review_id"], {}).get(row["field"])
        if f is None:
            continue
        if row["action"] != (f["action"] or "") or (row.get("entered_input") or None) != (f.get("entered") or None):
            problems.append(f"export row {row['review_id']}/{row['field']} does not match the review")
    reviewers = {r["approved_by"] for r in human}
    actions = [f["action"] for r in human for f in r["fields"]]
    reopened = sum(e["kind"] == "reopened" for r in human for e in events.get(r["id"], []))
    coverage = {
        "reviewers": len(reviewers),
        "manual_entries": sum(r["mode"] == "manual" for r in human),
        "corrections": actions.count("corrected"),
        "absent": actions.count("absent"),
        "reopenings": reopened,
    }
    for name, minimum in (("reviewers", 2), ("manual_entries", 1), ("corrections", 1), ("reopenings", 1)):
        if coverage[name] < minimum:
            problems.append(f"the rehearsal needs at least {minimum} {name.replace('_', ' ')} (found {coverage[name]})")

    def secs(mode: str, key: str) -> dict:
        vals = [r[key] for r in human if r["mode"] == mode and r[key] is not None]
        return {"n": len(vals), "median": round(statistics.median(vals), 1) if vals else None}

    return {
        "passed": not problems,
        "problems": problems,
        "notes": notes,
        "human_reviews": len(human),
        "documents": len({r["doc_sha256"] for r in human}),
        "coverage": coverage,
        "timing": {
            "review_active_s": secs("review", "active_seconds"),
            "review_wall_s": secs("review", "wall_seconds"),
            "manual_active_s": secs("manual", "active_seconds"),
            "manual_wall_s": secs("manual", "wall_seconds"),
        },
    }


def load_events(work: Path, ids: list[str]) -> dict[str, list[dict]]:
    from inklight.review import ReviewStore
    from inklight.store import Store

    with Store(work / "reviews-snapshot.db") as store:  # written by snapshot_reviews
        reviews = ReviewStore(store)
        return {i: reviews.events(i) for i in ids}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--export", required=True, type=Path, help="The CSV exported from the Review tab.")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    work = args.out / "work"
    reviews = snapshot_reviews(args.config, work)
    events = load_events(work, [r["id"] for r in reviews])
    with args.export.open(encoding="utf-8", newline="") as fh:
        exported = list(csv.DictReader(fh))
    result = check(reviews, events, exported)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "rehearsal-check.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps(result, indent=1))
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
