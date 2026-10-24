"""Pilot tooling: intake rules, vendor-grouped split, evaluation outcomes and the reserved-group lock."""

import csv
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PILOT = Path(__file__).resolve().parents[1] / "pilot"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"pilot_{name}", PILOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


intake = _load("intake")
evaluate = _load("evaluate")

OK = {"permission_ref": "DPA-1", "permission_scope": "evaluation", "personal_data": "no", "redacted": "no"}


def _manifest(tmp_path, rows):
    for row in rows:
        p = tmp_path / row["file"]
        if not p.exists():
            p.write_bytes(row.pop("_bytes", row["file"].encode()))
        else:
            row.pop("_bytes", None)
    path = tmp_path / "manifest.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(intake.COLUMNS))
        w.writeheader()
        w.writerows(rows)
    return path


def test_vendor_names_are_grouped():
    assert intake.vendor_key("ACME Supplies, Ltd.") == intake.vendor_key("Acme Supplies Ltd") == "acme supplies"


def test_split_is_by_vendor_and_stable():
    a = intake.split_for("Acme Ltd", "salt", 0.4)
    assert all(intake.split_for(v, "salt", 0.4) == a for v in ("ACME LTD.", "Acme", "acme limited"))
    groups = [intake.split_for(f"vendor {i}", "salt", 0.4) for i in range(400)]
    assert 0.3 < groups.count("reserved") / 400 < 0.5


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        ({"permission_ref": ""}, "missing permission_ref"),
        ({"permission_scope": "marketing"}, "does not include evaluation"),
        ({"personal_data": "yes", "redacted": "no"}, "personal data"),
        ({"cohort": "mixed"}, "cohort must be"),
        ({"file": "notes.docx"}, "unsupported file type"),
    ],
)
def test_rows_that_break_a_rule_are_rejected(tmp_path, row, reason):
    base = {"file": "a.pdf", "cohort": "genuine-invoice", "vendor": "Acme", **OK}
    m = _manifest(tmp_path, [{**base, **row}])
    out = intake.intake(m, tmp_path / "data", 0.4, "s")
    assert out["taken"] == 0 and reason in out["rejected"][0]["reason"]


def test_intake_keeps_cohorts_apart_and_takes_duplicates_once(tmp_path):
    rows = [
        {"file": "a.pdf", "cohort": "genuine-invoice", "vendor": "Acme", **OK, "_bytes": b"A"},
        {"file": "b.pdf", "cohort": "receipt", "vendor": "Cafe", **OK, "_bytes": b"B"},
        {"file": "c.pdf", "cohort": "genuine-invoice", "vendor": "Acme", **OK, "_bytes": b"A"},  # same bytes as a.pdf
    ]
    out = intake.intake(_manifest(tmp_path, rows), tmp_path / "data", 0.4, "s")
    assert out["taken"] == 2 and "duplicate" in out["rejected"][0]["reason"]
    record = json.loads((tmp_path / "data" / "intake.json").read_text())
    cohorts = {d["cohort"]: d for d in record["documents"]}
    assert cohorts["receipt"]["split"] == "dev"  # only genuine invoices are split
    assert cohorts["genuine-invoice"]["stored_as"].startswith(f"genuine-invoice/{cohorts['genuine-invoice']['split']}/")
    assert "Acme" not in cohorts["genuine-invoice"]["stored_as"]  # stored by hash, not by name


def test_the_split_settings_cannot_change_later(tmp_path):
    m = _manifest(tmp_path, [{"file": "a.pdf", "cohort": "genuine-invoice", "vendor": "Acme", **OK}])
    intake.intake(m, tmp_path / "data", 0.4, "s")
    with pytest.raises(SystemExit):
        intake.intake(m, tmp_path / "data", 0.5, "s")
    with pytest.raises(SystemExit):
        intake.intake(m, tmp_path / "data", 0.4, "other")


def _review(sha, mode, fields, **extra):
    return {
        "id": f"{sha}-{mode}",
        "doc_sha256": sha,
        "mode": mode,
        "baseline": "b1",
        "active_seconds": extra.get("t", 10.0),
        "wall_seconds": 20.0,
        "fields": fields,
    }


def _field(name, predicted, final, flagged=False, action="accepted"):
    return {
        "field": name,
        "predicted": predicted,
        "final": final,
        "flagged": flagged,
        "action": action,
        "raw": None,
        "method": "label",
        "confidence": 0.9,
        "warning": "w" if flagged else None,
    }


def test_evaluation_outcomes_burden_and_paired_agreement():
    record = {
        "documents": [
            {"sha256": "s1", "cohort": "genuine-invoice", "split": "dev", "stored_as": "x", "vendor_group": "acme"}
        ]
    }
    review = _review(
        "s1",
        "review",
        [
            _field("total", 100.0, 100.0),
            _field("tax", 9.0, 10.0, action="corrected"),  # silent error
            _field("vendor", "Acme", "Acme Inc", flagged=True, action="corrected"),
            _field("date", None, "2026-01-01", action="corrected"),
            _field("po_number", None, None, action="absent"),
        ],
        t=30.0,
    )
    manual = _review(
        "s1",
        "manual",
        [_field("total", 100.0, 100.0, action="entered"), _field("tax", 9.0, 9.0, action="entered")],
        t=60.0,
    )
    metrics, failures = evaluate.evaluate([review, manual], record, "genuine-invoice", "dev")
    c = metrics["fields"]["counts"]
    assert (c["correct_unflagged"], c["wrong_unflagged"], c["wrong_flagged"], c["missing"], c["both_absent"]) == (
        1,
        1,
        1,
        1,
        1,
    )
    assert metrics["fields"]["silent_error_rate"]["k"] == 1 and metrics["fields"]["silent_error_rate"]["n"] == 4
    assert metrics["review_burden"]["corrected_share"] == round(2 / 3, 3)
    assert metrics["time_ratio_review_vs_manual"] == 0.5
    assert metrics["manual_entry"]["agreement_on_those"]["disagree"] == 1  # tax: 10 reviewed vs 9 typed
    assert {f["field"] for f in failures} == {"tax", "vendor", "date"}


def test_other_cohorts_and_splits_are_never_mixed_in():
    record = {
        "documents": [{"sha256": "s1", "cohort": "receipt", "split": "dev", "stored_as": "x", "vendor_group": "c"}]
    }
    metrics, _ = evaluate.evaluate(
        [_review("s1", "review", [_field("total", 1.0, 1.0)])], record, "genuine-invoice", "dev"
    )
    assert metrics["documents_reviewed"] == 0 and metrics["fields"]["n"] == 0


def test_wilson_interval_is_wide_for_small_samples():
    lo, hi = evaluate.wilson(9, 10)
    assert lo < 0.6 and hi > 0.97


def test_reserved_group_needs_a_reason(tmp_path):
    intake_file = tmp_path / "intake.json"
    intake_file.write_text(json.dumps({"documents": []}))
    cmd = [
        sys.executable,
        str(PILOT / "evaluate.py"),
        "--config",
        str(tmp_path / "c.toml"),
        "--intake",
        str(intake_file),
        "--split",
        "reserved",
        "--out",
        str(tmp_path / "o"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode != 0 and "--reason" in (result.stderr + result.stdout)
    assert not (tmp_path / "reserved_access.log").exists()


def test_reserved_access_with_a_reason_is_logged_and_writes_no_failures(tmp_path):
    config = tmp_path / "c.toml"
    config.write_text(f'home = "{(tmp_path / "home").as_posix()}"\n[models]\nbrain = "rules"\n', encoding="utf-8")
    from inklight.store import Store

    with Store(tmp_path / "home" / "library.db"):
        pass  # an empty pilot library
    intake_file = tmp_path / "intake.json"
    intake_file.write_text(json.dumps({"documents": []}))
    out = tmp_path / "o"
    cmd = [
        sys.executable,
        str(PILOT / "evaluate.py"),
        "--config",
        str(config),
        "--intake",
        str(intake_file),
        "--split",
        "reserved",
        "--reason",
        "evaluate build abc123 after the date fix",
        "--out",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    log = [json.loads(line) for line in (tmp_path / "reserved_access.log").read_text().splitlines()]
    assert log[0]["reason"] == "evaluate build abc123 after the date fix" and log[0]["cohort"] == "genuine-invoice"
    assert (out / "genuine-invoice-reserved-frozen.json").exists() and not list(out.glob("*failures*"))


# ---------------------------------------------------------------- reprediction: selection, isolation, provenance

import argparse  # noqa: E402
import hashlib  # noqa: E402

from inklight import DocumentAgent  # noqa: E402

from .conftest import make_settings  # noqa: E402

GROUPS = {"dev": ["Acme Supplies Ltd", "Globex Corporation"], "reserved": ["Initech LLC", "Umbrella GmbH"]}


@pytest.fixture
def workspace(tmp_path):
    """A pilot with approved reviews in both groups; its library ingested from the intake copies."""
    data = tmp_path / "data"
    entries = []
    for split, vendors in GROUPS.items():
        for i, vendor in enumerate(vendors):
            body = f"INVOICE #INV-{split}-{i}\nVendor: {vendor}\nTotal: USD {100 + i}.00\n"
            path = data / "genuine-invoice" / split / f"{split}{i}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
            entries.append(
                {
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "stored_as": path.relative_to(data).as_posix(),
                    "cohort": "genuine-invoice",
                    "split": split,
                    "vendor_group": vendor.lower(),
                    "layout": None,
                }
            )
    (data / "intake.json").write_text(json.dumps({"salt": "t", "documents": entries}), encoding="utf-8")
    home = tmp_path / "pilot-home"
    ocr_models = tmp_path / "ocr-models"
    ocr_models.mkdir()
    (ocr_models / "det.onnx").write_bytes(b"pinned model bytes")
    config = tmp_path / "pilot-config.toml"
    config.write_text(
        f'home = "{home.as_posix()}"\n[models]\nbrain = "rules"\n[ocr]\nmodel_dir = "{ocr_models.as_posix()}"\n',
        encoding="utf-8",
    )
    with DocumentAgent(make_settings(home)) as agent:
        agent.add([data / "genuine-invoice"])
        for doc in agent.library.documents():
            r = agent.open_review(doc.id, ["vendor", "total"], reviewer="ana", baseline="b1")
            for f in r.fields:
                agent.reviews.decide(r.id, f.field, reviewer="ana", action="accepted")
            agent.reviews.approve(r.id, reviewer="ana")
    shas = {split: {e["sha256"] for e in entries if e["split"] == split} for split in GROUPS}
    return {"data": data, "config": config, "home": home, "shas": shas, "tmp": tmp_path}


@pytest.fixture
def spy(monkeypatch):
    """Every document the agent extracts, and whether the reserved log existed at that moment."""
    calls = []
    original = DocumentAgent.extract

    def extract(self, files, *a, **kw):
        paths = [Path(f) for f in (files if isinstance(files, list) else [files])]
        log = paths[0].parents[2] / "reserved_access.log" if paths else None
        calls.append(
            {"sha": hashlib.sha256(paths[0].read_bytes()).hexdigest(), "log_existed": bool(log and log.exists())}
        )
        return original(self, files, *a, **kw)

    monkeypatch.setattr(DocumentAgent, "extract", extract)
    return calls


def _args(ws, **kw):
    base = {
        "config": ws["config"],
        "intake": ws["data"] / "intake.json",
        "cohort": "genuine-invoice",
        "split": "dev",
        "reason": None,
        "predictions": "frozen",
        "candidate_config": None,
        "work": ws["tmp"] / f"work-{kw.get('predictions', 'frozen')}-{kw.get('split', 'dev')}",
        "allow_mixed_baselines": False,
        "out": ws["tmp"] / "out",
    }
    return argparse.Namespace(**{**base, **kw})


def _sha_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("mode", ["cached", "full"])
def test_dev_reprediction_never_runs_inference_on_reserved_documents(workspace, spy, mode):
    metrics = evaluate.run(_args(workspace, predictions=mode))
    predicted = {c["sha"] for c in spy}
    assert predicted == workspace["shas"]["dev"]  # every dev document, no reserved one
    assert not predicted & workspace["shas"]["reserved"]
    assert metrics["provenance"]["inference"]["documents_predicted"] == len(workspace["shas"]["dev"])
    assert metrics["documents_reviewed"] == len(workspace["shas"]["dev"])


def test_reserved_reprediction_needs_a_reason_before_anything_is_read(workspace, spy):
    with pytest.raises(SystemExit):
        evaluate.run(_args(workspace, split="reserved", predictions="cached"))
    assert spy == [] and not (workspace["data"] / "reserved_access.log").exists()
    assert not (workspace["tmp"] / "work-cached-reserved").exists()  # no snapshot either


def test_reserved_access_is_logged_before_the_first_prediction(workspace, spy):
    evaluate.run(_args(workspace, split="reserved", predictions="cached", reason="evaluate build x after fix y"))
    assert {c["sha"] for c in spy} == workspace["shas"]["reserved"]
    assert all(c["log_existed"] for c in spy)


def test_full_pipeline_uses_an_isolated_library_and_records_provenance(workspace, spy):
    pilot_db = workspace["home"] / "library.db"
    before = _sha_file(pilot_db)
    metrics = evaluate.run(_args(workspace, predictions="full"))
    assert _sha_file(pilot_db) == before  # the pilot library, and its ground truth, are untouched
    isolated = workspace["tmp"] / "work-full-dev" / "full-home" / "library.db"
    with DocumentAgent(make_settings(isolated.parent)) as fresh:
        assert {d.sha256 for d in fresh.library.documents()} == workspace["shas"]["dev"]  # only what was asked
    prov = metrics["provenance"]
    assert prov["predictions"] == "full" and prov["package_digest"] and prov["settings"]["models"]["brain"] == "rules"
    assert prov["ocr_model_files"]["sha256"] == {"det.onnx": hashlib.sha256(b"pinned model bytes").hexdigest()}
    assert "onnxruntime_calls_total" in prov["inference"] and "second_readings" in prov["inference"]
    truth = json.loads((workspace["tmp"] / "out" / "genuine-invoice-dev-full-ground-truth.json").read_text())
    assert {t["doc_sha256"] for t in truth} == workspace["shas"]["dev"] and all(
        t["approved_by"] == "ana" for t in truth
    )


def test_cached_mode_does_not_write_to_the_pilot_library(workspace, spy):
    pilot_db = workspace["home"] / "library.db"
    before = _sha_file(pilot_db)
    evaluate.run(_args(workspace, predictions="cached"))
    assert _sha_file(pilot_db) == before


def test_cached_mode_refuses_a_document_changed_since_review(workspace, spy):
    changed = workspace["data"] / "genuine-invoice" / "dev" / "dev0.txt"
    changed.write_text(changed.read_text() + "Note: edited\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="changed or moved"):
        evaluate.run(_args(workspace, predictions="cached"))


def test_a_document_reviewed_twice_is_predicted_once(workspace, spy):
    with DocumentAgent(make_settings(workspace["home"])) as agent:
        doc = next(d for d in agent.library.documents() if d.sha256 in workspace["shas"]["dev"])
        r = agent.open_review(doc.id, ["vendor", "total"], reviewer="ben", mode="manual", baseline="b1")
        for f in r.fields:
            agent.reviews.decide(r.id, f.field, reviewer="ben", action="absent")
        agent.reviews.approve(r.id, reviewer="ben")
    before = len(spy)  # opening the manual review above extracted once too
    metrics = evaluate.run(_args(workspace, predictions="cached"))
    during = spy[before:]
    assert len(during) == len(workspace["shas"]["dev"]) == metrics["provenance"]["inference"]["documents_predicted"]
    assert "cached (re-extracted" in evaluate.markdown(metrics)


# ---------------------------------------------------------------- the human rehearsal checker

check_rehearsal = _load("check_rehearsal")


def _human_review(rid, reviewer, mode="review", active=40.0, wall=60.0, entered="1,520.00"):
    fields = [
        {
            "field": "total",
            "action": "corrected" if mode == "review" else "entered",
            "entered": entered,
            "final": 1520.0,
        },
        {"field": "vendor", "action": "absent", "entered": None, "final": None},
    ]
    return {
        "id": rid,
        "doc_sha256": f"sha-{rid}",
        "mode": mode,
        "opened_by": reviewer,
        "approved_by": reviewer,
        "baseline": "c49d506",
        "active_seconds": active,
        "wall_seconds": wall,
        "fields": fields,
    }


def _events(rid, reopen_reason=None):
    kinds = [{"kind": "opened", "note": None}, {"kind": "set", "note": None}, {"kind": "approved", "note": None}]
    if reopen_reason is not None:
        kinds += [{"kind": "reopened", "note": reopen_reason}, {"kind": "approved", "note": None}]
    return kinds


def _export(reviews):
    return [
        {"review_id": r["id"], "field": f["field"], "action": f["action"], "entered_input": f["entered"] or ""}
        for r in reviews
        for f in r["fields"]
    ]


def _good():
    reviews = [_human_review("r1", "ana"), _human_review("r2", "ben", mode="manual", active=90.0, wall=120.0)]
    events = {"r1": _events("r1", reopen_reason="total misread"), "r2": _events("r2")}
    return reviews, events, _export(reviews)


def test_a_complete_human_rehearsal_passes():
    result = check_rehearsal.check(*_good())
    assert result["passed"], result["problems"]
    assert result["coverage"] == {"reviewers": 2, "manual_entries": 1, "corrections": 1, "absent": 2, "reopenings": 1}
    assert result["timing"]["manual_active_s"]["median"] == 90.0


def test_scripted_reviews_never_count_as_human():
    reviews = [{**_human_review("r1", "dry-run-script"), "baseline": "dry-run"}]
    result = check_rehearsal.check(reviews, {"r1": _events("r1")}, _export(reviews))
    assert not result["passed"] and any("no human reviews" in p for p in result["problems"])


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (lambda rv, ev, ex: rv[0].update(active_seconds=0.0), "active time is 0 s"),
        (lambda rv, ev, ex: rv[0].update(active_seconds=500.0), "exceeds wall time"),
        (lambda rv, ev, ex: rv[0]["fields"][0].update(entered=None), "without the reviewer's input"),
        (lambda rv, ev, ex: ex.clear(), "missing from the export"),
        (lambda rv, ev, ex: ex[0].update(action="accepted"), "does not match the review"),
        (lambda rv, ev, ex: ex.append({"review_id": "zz", "field": "total", "action": "accepted"}), "not approved"),
        (lambda rv, ev, ex: ev.update(r1=[{"kind": "set", "note": None}]), "history does not run"),
        (lambda rv, ev, ex: ev.update(r1=_events("r1", reopen_reason=" ")), "without a reason"),
    ],
)
def test_rehearsal_problems_are_reported(change, problem):
    reviews, events, exported = _good()
    change(reviews, events, exported)
    result = check_rehearsal.check(reviews, events, exported)
    assert not result["passed"] and any(problem in p for p in result["problems"]), result["problems"]


def test_a_rehearsal_without_a_second_reviewer_or_manual_entry_is_incomplete():
    reviews = [_human_review("r1", "ana")]
    result = check_rehearsal.check(reviews, {"r1": _events("r1", reopen_reason="x y z")}, _export(reviews))
    assert any("2 reviewers" in p for p in result["problems"]) and any(
        "manual entries" in p for p in result["problems"]
    )


def test_rehearsal_check_reads_a_real_library_and_export(workspace, tmp_path):
    config = workspace["config"]
    with DocumentAgent(make_settings(workspace["home"])) as agent:
        docs = agent.library.documents()
        r = agent.open_review(docs[0].id, ["total"], reviewer="ben", mode="manual")
        agent.reviews.decide(r.id, "total", reviewer="ben", action="entered", value="(12.00)")
        agent.reviews.approve(r.id, reviewer="ben", active_seconds=1.0)
        export = tmp_path / "export.csv"
        export.write_text(agent.reviews.export("csv", actor="ben"), encoding="utf-8")
    out = tmp_path / "check"
    result = subprocess.run(
        [
            sys.executable,
            str(PILOT / "check_rehearsal.py"),
            "--config",
            str(config),
            "--export",
            str(export),
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    report = json.loads((out / "rehearsal-check.json").read_text())
    assert report["human_reviews"] == 5 and report["coverage"]["manual_entries"] == 1
    # the fixture's reviews were approved instantly with no active time: reported, so the check fails
    assert result.returncode == 1 and any("no active time" in p for p in report["problems"])
