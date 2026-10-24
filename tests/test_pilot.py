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
