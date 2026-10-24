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
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench"))
from textnorm import fold  # noqa: E402

OUTCOMES = ("correct_unflagged", "correct_flagged", "wrong_unflagged", "wrong_flagged", "missing")
MONEY = {"subtotal", "tax", "total", "contract_value"}
PREDICTION_MODES = {
    "frozen": "as captured when each review opened",
    "cached": "re-extracted by the installed build from the OCR stored at review time",
    "full": "whole pipeline re-run by the candidate build in an isolated library",
}


def same(field: str, a: Any, b: Any) -> bool:
    if field in MONEY:
        try:
            return abs(float(a) - float(b)) < 0.011
        except (TypeError, ValueError):
            return False
    if field.endswith("date") or field == "date":
        return str(a) == str(b)
    return fold(a) == fold(b)  # every script kept: different Arabic vendors never compare equal


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
        f"Predictions: {(m.get('provenance') or {}).get('predictions', 'frozen')} "
        f"({PREDICTION_MODES[(m.get('provenance') or {}).get('predictions', 'frozen')]})",
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


def select(reviews: list[dict], intake: dict, cohort: str, split: str) -> list[tuple[dict, dict]]:
    """(review, intake entry) for the requested cohort and split only. Runs before any prediction."""
    by_sha = {d["sha256"]: d for d in intake["documents"]}
    out = []
    for r in reviews:
        doc = by_sha.get(r["doc_sha256"])
        if doc is not None and doc["cohort"] == cohort and doc["split"] == split:
            out.append((r, doc))
    return out


def _backup(source: Path, target: Path) -> None:
    """Copy a SQLite database consistently (the source is opened read-only); both connections are closed."""
    import sqlite3
    from contextlib import closing

    with (
        closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)) as src,
        closing(sqlite3.connect(target)) as dst,
    ):
        src.backup(dst)


def snapshot_reviews(config: Path, work: Path) -> list[dict]:
    """Approved reviews, read from a copy of the pilot database: evaluation never writes to the original."""

    from inklight.config import load_settings
    from inklight.review import ReviewStore
    from inklight.store import Store

    source = load_settings(config).db_path
    if not source.exists():
        sys.exit(f"no pilot library at {source}")
    work.mkdir(parents=True, exist_ok=True)
    copy = work / "reviews-snapshot.db"
    _backup(source, copy)
    with Store(copy) as store:
        return [r.model_dump(mode="json") for r in ReviewStore(store).find(status="approved")]


def ground_truth(selected: list[tuple[dict, dict]]) -> list[dict]:
    return [
        {
            "review_id": r["id"],
            "doc_sha256": r["doc_sha256"],
            "mode": r["mode"],
            "field": f["field"],
            "final": f["final"],
            "entered_input": f.get("entered"),
            "action": f["action"],
            "approved_by": r["approved_by"],
            "approved_at": r["approved_at"],
            "predictions_baseline": r["baseline"],
        }
        for r, _ in selected
        for f in r["fields"]
    ]


class Instrument:
    """Counts what actually ran: every ONNX Runtime inference per model file, and every crop re-read."""

    def __init__(self) -> None:
        import onnxruntime as ort

        from inklight.ocr.indra import IndraEngine

        self.calls: Counter = Counter()
        self.rereads = 0
        self.predicted_docs: list[str] = []
        calls, me = self.calls, self
        init, run, reread = ort.InferenceSession.__init__, ort.InferenceSession.run, IndraEngine.reread

        def _init(session, path_or_bytes, *a, **kw):  # type: ignore[no-untyped-def]
            p = Path(str(path_or_bytes))
            session._pilot_name = f"{p.parent.name}/{p.name}" if p.suffix == ".onnx" else "in-memory model"
            return init(session, path_or_bytes, *a, **kw)

        def _run(session, *a, **kw):  # type: ignore[no-untyped-def]
            calls[getattr(session, "_pilot_name", "unknown")] += 1
            return run(session, *a, **kw)

        def _reread(engine, *a, **kw):  # type: ignore[no-untyped-def]
            me.rereads += 1
            return reread(engine, *a, **kw)

        self._restore = (ort.InferenceSession, init, run, IndraEngine, reread)
        ort.InferenceSession.__init__ = _init  # type: ignore[method-assign]
        ort.InferenceSession.run = _run  # type: ignore[method-assign]
        IndraEngine.reread = _reread  # type: ignore[method-assign]

    def close(self) -> None:
        session, init, run, engine, reread = self._restore
        session.__init__ = init  # type: ignore[method-assign]
        session.run = run  # type: ignore[method-assign]
        engine.reread = reread  # type: ignore[method-assign]

    def report(self) -> dict[str, Any]:
        return {
            "onnxruntime_calls_by_model": dict(self.calls),
            "onnxruntime_calls_total": sum(self.calls.values()),
            "second_readings": self.rereads,
            "documents_predicted": len(self.predicted_docs),
        }


def _new_predictions(review: dict, record: Any) -> dict:
    from inklight.review import is_flagged

    fields = []
    for f in review["fields"]:
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
    return {**review, "fields": fields}


def predict(
    selected: list[tuple[dict, dict]],
    *,
    mode: str,
    config: Path,
    work: Path,
    data: Path,
    instrument: Instrument,
) -> list[tuple[dict, dict]]:
    """New predictions for the selected documents only.

    cached: re-extract from the OCR stored in a *copy* of the pilot library; the documents are not OCR'd again
            (a changed or missing file stops the run), though a second reading may OCR a crop.
    full:   ingest the original files into an isolated, empty database with the candidate settings, then extract:
            the whole pipeline, OCR included.
    """
    from inklight import DocumentAgent
    from inklight.config import load_settings

    home = work / f"{mode}-home"
    if home.exists() and any(home.iterdir()):
        sys.exit(f"{home} is not empty: every run needs its own isolated library")
    home.mkdir(parents=True, exist_ok=True)
    if mode == "cached":
        _backup(load_settings(config).db_path, home / "library.db")
    settings = load_settings(config, home=str(home))
    out = []
    done: dict[tuple[str, tuple[str, ...]], Any] = {}  # one prediction per document (and field set)
    with DocumentAgent(settings) as agent:
        by_sha = {d.sha256: d for d in agent.library.documents()}
        for review, entry in selected:
            names = tuple(f["field"] for f in review["fields"])
            key = (review["doc_sha256"], names)
            if key in done:  # the same document reviewed twice (review + manual entry)
                out.append((_new_predictions(review, done[key]), entry))
                continue
            if mode == "full":
                path = data / entry["stored_as"]
                report = agent.add([path])
                if report.failed:
                    sys.exit(f"could not ingest {entry['stored_as']}: {report.failed[0][1]}")
            else:
                doc = by_sha.get(review["doc_sha256"])
                if doc is None:
                    sys.exit(f"the document of review {review['id']} is not in the pilot library")
                path = Path(doc.path)
                report = agent.library.add([path])
                if report.added:  # a new or changed file would be OCR'd again: not a cached comparison
                    sys.exit(f"{path.name} changed or moved since review; use --predictions full")
            instrument.predicted_docs.append(review["doc_sha256"])
            done[key] = agent.extract([path], fields=list(names))[0]
            out.append((_new_predictions(review, done[key]), entry))
    return out


def provenance(config: Path, mode: str) -> dict[str, Any]:
    """Exact code, settings and model files behind the predictions."""
    import platform

    from freeze import git, package_digest, tree_files

    import inklight
    from inklight.config import load_settings

    settings = load_settings(config)
    digest, n_files = package_digest()
    out: dict[str, Any] = {
        "predictions": mode,
        "inklight_version": inklight.__version__,
        "inklight_file": inklight.__file__,
        "package_digest": digest,
        "package_files": n_files,
        "harness_commit": git("rev-parse", "HEAD"),
        "python": platform.python_version(),
        "settings": {k: v for k, v in settings.model_dump(mode="json").items() if k not in ("home", "output_dir")},
    }
    if mode != "frozen":
        import indra_ocr

        ocr_dir = Path(settings.ocr.model_dir) if settings.ocr.model_dir else Path(indra_ocr.model_dir())
        out["ocr_model_files"] = {"folder": ocr_dir.as_posix(), "sha256": tree_files(ocr_dir)}
        if settings.models.brain != "rules" and settings.model_cache:
            out["small_model_files"] = {
                repo: tree_files(settings.model_cache / repo.replace("/", "--"))
                for repo in (settings.models.reader, settings.models.embedder)
                if (settings.model_cache / repo.replace("/", "--")).exists()
            }
    return out


def log_reserved_access(intake_path: Path, cohort: str, reason: str | None, mode: str) -> None:
    if not reason or len(reason.strip()) < 10:
        sys.exit("--split reserved needs --reason: which finished build is being evaluated, and why now")
    log = intake_path.parent / "reserved_access.log"
    entry = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "by": getpass.getuser(),
        "cohort": cohort,
        "predictions": mode,
        "reason": reason,
    }
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    print(f"Reserved access recorded in {log} before any document was read. Only aggregate results are written.")


def run(args: argparse.Namespace) -> dict:
    intake = json.loads(args.intake.read_text(encoding="utf-8"))
    if args.split == "reserved":
        log_reserved_access(args.intake, args.cohort, args.reason, args.predictions)
    work = args.work or args.out / "work"
    instrument = Instrument() if args.predictions != "frozen" else None
    reviews = snapshot_reviews(args.config, work)
    selected = select(reviews, intake, args.cohort, args.split)  # before any prediction
    truth = ground_truth(selected)
    candidate = args.candidate_config or args.config
    if instrument is not None:
        try:
            selected = predict(
                selected,
                mode=args.predictions,
                config=candidate if args.predictions == "full" else args.config,
                work=work,
                data=args.intake.parent,
                instrument=instrument,
            )
        finally:
            instrument.close()
    metrics, failures = evaluate([r for r, _ in selected], intake, args.cohort, args.split)
    metrics["provenance"] = provenance(candidate if args.predictions == "full" else args.config, args.predictions)
    if instrument is not None:
        metrics["provenance"]["inference"] = instrument.report()
        metrics["baselines"] = [f"{args.predictions} re-prediction"]
        metrics.pop("review_burden", None)  # review timings belong to the original predictions
        metrics.pop("time_ratio_review_vs_manual", None)
    elif len(metrics["baselines"]) > 1 and not args.allow_mixed_baselines:
        sys.exit(f"reviews come from several baselines {metrics['baselines']}: evaluate one baseline at a time")
    args.out.mkdir(parents=True, exist_ok=True)
    stem = f"{args.cohort}-{args.split}-{args.predictions}"
    (args.out / f"{stem}.json").write_text(json.dumps(metrics, indent=1, default=str), encoding="utf-8")
    (args.out / f"{stem}.md").write_text(markdown(metrics), encoding="utf-8")
    (args.out / f"{stem}-ground-truth.json").write_text(json.dumps(truth, indent=1, default=str), encoding="utf-8")
    if args.split == "dev":
        with (args.out / f"{stem}-failures.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(failures[0]) if failures else ["outcome"])
            writer.writeheader()
            writer.writerows(failures)
    return metrics


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, type=Path, help="The pilot config: its library holds the reviews.")
    ap.add_argument("--intake", required=True, type=Path)
    ap.add_argument("--cohort", default="genuine-invoice", choices=["genuine-invoice", "synthetic-invoice", "receipt"])
    ap.add_argument("--split", default="dev", choices=["dev", "reserved"])
    ap.add_argument("--reason", default=None, help="Required for --split reserved; logged before any document is read.")
    ap.add_argument(
        "--predictions",
        default="frozen",
        choices=["frozen", "cached", "full"],
        help="frozen: as captured when each review opened. cached: re-extract with the installed build from the "
        "OCR stored in a copy of the pilot library. full: ingest the original files into an isolated empty "
        "library with --candidate-config and run the whole pipeline.",
    )
    ap.add_argument("--candidate-config", type=Path, default=None, help="Settings of the build under test (full).")
    ap.add_argument("--work", type=Path, default=None, help="Folder for the snapshot and isolated libraries.")
    ap.add_argument("--allow-mixed-baselines", action="store_true")
    ap.add_argument("--out", required=True, type=Path)
    print(markdown(run(ap.parse_args())))


if __name__ == "__main__":
    main()
