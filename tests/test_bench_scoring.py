"""The evaluation harness's own rules: five field outcomes and task grading."""

import collections
from types import SimpleNamespace

from bench import scoring, tasks


def test_five_field_outcomes():
    assert scoring.outcome("total", 10.0, 10.0, None, 0.95) == "correct_unflagged"
    assert scoring.outcome("total", 10.0, 10.0, "check me", 0.95) == "correct_flagged"
    assert scoring.outcome("total", 10.0, 10.0, None, 0.5) == "correct_flagged"
    assert scoring.outcome("total", 9.0, 10.0, None, 0.95) == "wrong_unflagged"
    assert scoring.outcome("total", 9.0, 10.0, "check me", 0.95) == "wrong_flagged"
    assert scoring.outcome("total", None, 10.0, None, None) == "missing"


def test_rates_match_the_reported_cord_recount():
    counts = collections.Counter(
        correct_unflagged=63, correct_flagged=22, wrong_unflagged=2, wrong_flagged=13, missing=24
    )
    r = scoring.rates(counts)
    assert r["n"] == 124
    assert r["value_accuracy"] == round(85 / 124, 3)
    assert r["coverage_without_review"] == 0.508
    assert r["precision_unflagged"] == 0.969


def _result(state="succeeded", files=(), records=(), answer="", warnings=(), not_understood=(), calculation=None):
    return SimpleNamespace(
        state=SimpleNamespace(value=state),
        files_written=tuple(files),
        records=tuple(records),
        answer=answer,
        warnings=tuple(warnings),
        not_understood=tuple(not_understood),
        calculation=calculation,
    )


class _Agent:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def plan(self, request):
        if self.error:
            raise self.error
        return request

    def run_plan(self, plan, ids, save=False):
        return self.result


def _csv(tmp_path, rows):
    path = tmp_path / "out.csv"
    lines = ["document,total,total_confidence,pages,warnings"] + [f"{n},{v},{c},1,{w}" for n, v, c, w in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


EXPORT = {"kind": "export", "form": "export-csv", "request": "Export", "rows": {"a.png": 100.0, "b.png": 200.0}}


def test_export_with_all_rows_and_values_is_correct(tmp_path):
    f = _csv(tmp_path, [("a.png", 100.0, 0.95, ""), ("b.png", 200.0, 0.95, "")])
    assert tasks.run_case(_Agent(_result(files=[f])), EXPORT, [])["outcome"] == "correct"


def test_empty_export_reported_as_success_is_silent(tmp_path):
    f = _csv(tmp_path, [])
    assert tasks.run_case(_Agent(_result(files=[f])), EXPORT, [])["outcome"] == "silent_wrong"


def test_wrong_value_unflagged_in_the_file_is_silent(tmp_path):
    f = _csv(tmp_path, [("a.png", 100.0, 0.95, ""), ("b.png", 20.0, 0.95, "")])
    assert tasks.run_case(_Agent(_result(files=[f])), EXPORT, [])["outcome"] == "silent_wrong"


def test_wrong_value_flagged_in_the_file_is_flagged(tmp_path):
    f = _csv(tmp_path, [("a.png", 100.0, 0.95, ""), ("b.png", 20.0, 0.4, "total: possible OCR misread")])
    out = tasks.run_case(_Agent(_result(files=[f])), EXPORT, [])
    assert out["outcome"] == "flagged" and out["wrong_values_flagged_in_file"] == 1


def test_sum_checks_the_number_and_the_values_left_out():
    case = {
        "kind": "sum",
        "form": "s",
        "request": "r",
        "expected_value": 300.0,
        "expected_count": 2,
        "expected_unit": "USD",
    }
    right = {"op": "sum", "result": 300.0, "unit": "USD", "count": 2, "missing": 0}
    assert tasks.run_case(_Agent(_result(calculation=right)), case, [])["outcome"] == "correct"
    wrong = {**right, "result": 299.0}
    assert tasks.run_case(_Agent(_result(calculation=wrong)), case, [])["outcome"] == "silent_wrong"
    other_currency = {**right, "unit": "EUR"}
    assert tasks.run_case(_Agent(_result(calculation=other_currency)), case, [])["outcome"] == "silent_wrong"
    gap = {**right, "result": 100.0, "count": 1, "missing": 1}
    out = tasks.run_case(_Agent(_result(state="partial", calculation=gap, warnings=["1 left out"])), case, [])
    assert out["outcome"] == "flagged" and out["missing_disclosed"]


def test_refusal_must_name_the_unsupported_part():
    case = {"kind": "unsupported", "form": "u", "request": "Find invoices paid late", "phrase": "paid late"}
    named = _result(state="partial", not_understood=["paid late"])
    assert tasks.run_case(_Agent(named), case, [])["outcome"] == "useful_abstention"
    unexplained = _result(state="failed")
    assert tasks.run_case(_Agent(unexplained), case, [])["outcome"] == "failed_refusal"
    assert tasks.run_case(_Agent(_result()), case, [])["outcome"] == "silent_wrong"


def test_a_crash_is_never_a_refusal():
    case = {"kind": "unsupported", "form": "u", "request": "Find invoices paid late", "phrase": "paid late"}
    out = tasks.run_case(_Agent(error=RuntimeError("boom")), case, [])
    assert out["outcome"] == "crash" and "boom" in out["error"]


def test_a_cancelled_run_is_a_timeout():
    case = {"kind": "unsupported", "form": "u", "request": "Find invoices paid late", "phrase": "paid late"}
    assert tasks.run_case(_Agent(_result(state="cancelled")), case, [])["outcome"] == "timeout"


def test_list_valued_annotations_are_not_concatenated():
    from bench.prepare_external import _money

    assert _money(["46.636", "46.636"]) == 46636.0
    assert _money(["55,834", "55,800"]) is None  # disagreeing values: unknown, not guessed
    assert _money(["30.273 200", "3.027"]) is None
    assert _money("60.000") == 60000.0 and _money("12.50") == 12.5
    assert _money("10%") is None  # a VAT rate annotated in the tax field
