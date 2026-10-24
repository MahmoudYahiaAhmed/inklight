"""Task-level evaluation: does the request produce the right *result*, not just the right documents?

Expected values are computed independently from the dataset annotations, never from Inklight's output.

Kinds and what is checked:
    set          returned document set; execution state
    count        the number reported (records and the number stated in the answer); state
    sum          numeric result vs the annotated sum, currency, values left out (missing), state
    export       the written file exists, its rows are exactly the expected documents, every exported
                 amount equals the annotation; state
    unsupported  a useful abstention only if the run finished, the state is partial/unsupported and the
                 unsupported phrase is named in ``not_understood``. A crash, timeout or unexplained
                 failure is not a refusal.

Outcomes: correct · flagged (wrong or incomplete, and the result says so) · silent_wrong (wrong, reported as
complete success) · overstated (a sum or average that left documents out but reported succeeded, even with a
warning) · unnecessary_flag (right, but reported as partial) · useful_abstention · failed_refusal · crash ·
timeout.
"""

from __future__ import annotations

import csv
import re
import time
import traceback
from pathlib import Path
from typing import Any

TOLERANCE = 0.011


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def cases(dataset: str, truth: dict[str, dict]) -> list[dict[str, Any]]:
    """Request cases with independently computed expectations. Only documents with an annotated total
    are in scope, so every expectation is known."""
    rows = {n: t for n, t in truth.items() if t.get("total") is not None}
    totals = sorted(t["total"] for t in rows.values())
    if not totals:
        return []
    noun, cur, unit = ("receipts", "Rp ", "IDR") if dataset == "cord" else ("invoices", "$", "USD")
    step = 1000 if dataset == "cord" else 10
    thr = round(totals[len(totals) // 2] / step) * step or totals[len(totals) // 2]
    lo = round(totals[len(totals) // 4] / step) * step
    hi = round(totals[3 * len(totals) // 4] / step) * step
    above = {n for n, t in rows.items() if t["total"] > thr}
    between = {n for n, t in rows.items() if lo <= t["total"] <= hi}

    def money(x: float) -> str:
        return f"{cur}{x:,.0f}"

    out: list[dict[str, Any]] = [
        {"kind": "set", "form": "threshold", "request": f"Find {noun} above {money(thr)}", "docs": above},
        {
            "kind": "set",
            "form": "threshold-below",
            "request": f"Find {noun} below {money(thr)}",
            "docs": {n for n, t in rows.items() if t["total"] < thr},
        },
        {
            "kind": "set",
            "form": "range",
            "request": f"Find {noun} between {money(lo)} and {money(hi)}",
            "docs": between,
        },
        {
            "kind": "count",
            "form": "count",
            "request": f"how many {noun} are above {money(thr)}?",
            "expected_value": len(above),
        },
        {
            "kind": "sum",
            "form": "sum-threshold",
            "request": f"What is the total of {noun} above {money(thr)}?",
            "expected_value": round(sum(rows[n]["total"] for n in above), 2),
            "expected_count": len(above),
            "expected_unit": unit,
        },
        {
            "kind": "sum",
            "form": "sum-all",
            "request": f"What is the total of all {noun}?",
            "expected_value": round(sum(t["total"] for t in rows.values()), 2),
            "expected_count": len(rows),
            "expected_unit": unit,
        },
        {
            "kind": "export",
            "form": "export-csv",
            "request": f"Export {noun} above {money(thr)} to CSV",
            "rows": {n: rows[n]["total"] for n in above},
        },
        {"kind": "unsupported", "form": "paid-late", "request": f"Find {noun} paid late", "phrase": "paid late"},
        {
            "kind": "unsupported",
            "form": "last-month",
            "request": f"Find {noun} from last month",
            "phrase": "last month",
        },
        {"kind": "unsupported", "form": "top-n", "request": f"Show the top 5 {noun} by total", "phrase": "top 5"},
        {"kind": "unsupported", "form": "month-no-year", "request": f"Find {noun} from March", "phrase": "march"},
    ]
    if dataset == "voxel51":
        out += _vendor_cases(truth, rows, above, money(thr))
    return out


def _vendor_cases(truth: dict, rows: dict, above: set[str], thr_text: str) -> list[dict[str, Any]]:
    def by_vendor(word: str) -> set[str]:
        return {n for n, t in rows.items() if t.get("vendor") and _key(word) in _key(t["vendor"])}

    words = sorted(
        {t["vendor"] for t in truth.values() if t.get("vendor") and re.fullmatch(r"[A-Za-z-]+", t["vendor"])}
    )
    v1 = next((w for w in words if by_vendor(w) & above), words[0] if words else "Nobody")
    v2 = next((w for w in words if w != v1), v1)
    years = sorted({t["date"][:4] for t in rows.values() if t.get("date")})
    y = years[len(years) // 2] if years else "2020"
    in_year = {n for n, t in rows.items() if (t.get("date") or "").startswith(y)}
    return [
        {"kind": "set", "form": "vendor", "request": f"Find invoices from {v1}", "docs": by_vendor(v1)},
        {
            "kind": "set",
            "form": "vendor-or",
            "request": f"Find invoices from {v1} or {v2}",
            "docs": by_vendor(v1) | by_vendor(v2),
        },
        {
            "kind": "set",
            "form": "vendor+threshold",
            "request": f"Find invoices from {v1} above {thr_text}",
            "docs": by_vendor(v1) & above,
        },
        {"kind": "set", "form": "possessive", "request": f"Show {v1}'s invoices", "docs": by_vendor(v1)},
        {"kind": "set", "form": "possessive-lower", "request": f"show {v1.lower()}'s invoices", "docs": by_vendor(v1)},
        {"kind": "set", "form": "possessive-curly", "request": f"Show {v1}’s invoices", "docs": by_vendor(v1)},
        {
            "kind": "set",
            "form": "possessive-start",
            "request": f"{v1}'s invoices above {thr_text}",
            "docs": by_vendor(v1) & above,
        },
        {"kind": "set", "form": "year", "request": f"Find invoices in {y}", "docs": in_year},
        {
            "kind": "sum",
            "form": "average-year",
            "request": f"What is the average total of invoices from {y}?",
            "expected_value": round(sum(rows[n]["total"] for n in in_year) / len(in_year), 2) if in_year else None,
            "expected_count": len(in_year),
            "expected_unit": "USD",
        },
    ]


def _calc_from_text(answer: str) -> dict[str, Any] | None:
    """0.1.0 has no structured calculation: read "sum of total: 1,234.50 USD (over 7 ...)" from the answer."""
    m = re.search(r"\b(sum|avg|min|max) of (\w+): ([-\d,.]+)(?: ([A-Z]{3}))? \(over (\d+)", answer)
    if not m:
        return None
    return {
        "op": m.group(1),
        "field": m.group(2),
        "result": float(m.group(3).replace(",", "")),
        "unit": m.group(4),
        "count": int(m.group(5)),
        "missing": None,
        "source": "parsed from answer text (no structured calculation in this version)",
    }


def run_case(agent: Any, case: dict[str, Any], ids: list[str], time_budget_s: float = 60.0) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        res = agent.run_plan(agent.plan(case["request"]), ids, save=False)
    except Exception as exc:  # a crash is recorded, never counted as a refusal
        return {
            **_public(case),
            "outcome": "crash",
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc(limit=3),
        }
    elapsed = time.perf_counter() - started
    state = res.state.value
    not_understood = [str(x) for x in (getattr(res, "not_understood", ()) or ())]
    base = {
        **_public(case),
        "state": state,
        "seconds": round(elapsed, 2),
        "not_understood": not_understood,
        "warnings": [str(w) for w in res.warnings][:6],
    }
    if state == "cancelled" or elapsed > time_budget_s:
        return {**base, "outcome": "timeout"}
    complete = state == "succeeded" and not not_understood
    kind = case["kind"]
    if kind == "unsupported":
        named = any(case["phrase"] in x.lower() for x in not_understood)
        ok = state in ("partial", "unsupported") and named
        return {**base, "outcome": "useful_abstention" if ok else ("silent_wrong" if complete else "failed_refusal")}
    if kind == "set":
        got = {r.name for r in res.records}
        right = got == case["docs"]
        return {
            **base,
            "returned": len(got),
            "expected": len(case["docs"]),
            "missing_docs": sorted(case["docs"] - got)[:10],
            "extra_docs": sorted(got - case["docs"])[:10],
            "outcome": _grade(right, complete),
        }
    if kind == "count":
        stated = re.search(r"\b(\d+) of \d+ document", res.answer)
        n_records = len(res.records)
        n_stated = int(stated.group(1)) if stated else None
        right = n_records == case["expected_value"] and n_stated in (None, n_records)
        return {
            **base,
            "records": n_records,
            "stated": n_stated,
            "outcome": _grade(right, complete),
        }
    if kind == "sum":
        calc = getattr(res, "calculation", None) or _calc_from_text(res.answer)
        result = calc.get("result") if calc else None
        value_ok = (
            result is not None
            and case["expected_value"] is not None
            and abs(result - case["expected_value"]) < TOLERANCE
        )
        unit = calc.get("unit") if calc else None
        unit_ok = unit in (case["expected_unit"], None) and not (calc or {}).get("by_unit")
        missing = (calc or {}).get("missing")
        disclosed = not missing or any("left out" in w for w in res.warnings)
        return {
            **base,
            "result": result,
            "by_unit": (calc or {}).get("by_unit"),
            "unit": unit,
            "used": (calc or {}).get("count"),
            "missing": missing,
            "missing_disclosed": disclosed,
            "calculation_source": (calc or {}).get("source", "structured"),
            "outcome": sum_outcome(state, missing, value_ok and unit_ok, complete),
        }
    if kind == "export":
        return {**base, **_check_export(res, case, complete)}
    raise ValueError(kind)


def _check_export(res: Any, case: dict[str, Any], complete: bool) -> dict[str, Any]:
    """Rows and values of the written file, and whether each wrong value is flagged *in the file*
    (its ``total_confidence`` below 0.7 or a ``total:`` entry in the ``warnings`` column)."""
    files = [Path(f) for f in res.files_written]
    if not files:
        explained = bool(getattr(res, "not_understood", ())) or any("not saved" in w.lower() for w in res.warnings)
        return {"file": None, "outcome": "flagged" if explained else "silent_wrong" if complete else "flagged"}
    with files[0].open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    header = list(rows[0]) if rows else []
    name_col = next((c for c in ("document", "name", "file") if c in header), None)
    total_col = next((c for c in header if c.lower() == "total"), None)
    by_name = {r.get(name_col or "", ""): r for r in rows}
    expected = case["rows"]
    wrong, wrong_flagged, right_flagged = [], 0, 0
    for name, want in expected.items():
        row = by_name.get(name)
        if row is None:
            continue
        got = row.get(total_col or "", "")
        try:
            ok = got not in (None, "") and abs(float(str(got).replace(",", "")) - want) < TOLERANCE
        except ValueError:
            ok = False
        flagged = _flagged_in_file(row)
        if ok:
            right_flagged += flagged
        else:
            wrong.append((name, want, got, "flagged in file" if flagged else "NOT flagged in file"))
            wrong_flagged += flagged
    rows_right = set(by_name) == set(expected)
    right = rows_right and not wrong
    every_error_flagged = len(wrong) == wrong_flagged
    if right:
        outcome = "correct" if complete else "unnecessary_flag"
    elif complete and (not rows_right or not every_error_flagged):
        outcome = "silent_wrong"  # missing/extra rows, or a wrong value the file does not flag
    else:
        outcome = "flagged"
    return {
        "file": files[0].name,
        "columns": header,
        "rows_exported": len(by_name),
        "rows_expected": len(expected),
        "missing_rows": sorted(set(expected) - set(by_name))[:10],
        "extra_rows": sorted(set(by_name) - set(expected))[:10],
        "wrong_values": wrong[:10],
        "wrong_values_flagged_in_file": wrong_flagged,
        "correct_values_flagged_in_file": right_flagged,
        "outcome": outcome,
    }


def _flagged_in_file(row: dict[str, str]) -> bool:
    try:
        low = float(row.get("total_confidence") or 0) < 0.7
    except ValueError:
        low = True
    return low or "total:" in (row.get("warnings") or "")


def sum_outcome(state: str, missing: int | None, right: bool, complete: bool) -> str:
    """A sum that left documents out but still reports ``succeeded`` overstates its completeness, even when it
    warns: that is its own outcome, never "flagged"."""
    if state == "succeeded" and missing:
        return "overstated"
    return _grade(right, complete and not missing)


def regrade(item: dict[str, Any]) -> dict[str, Any]:
    """Apply the current rules to a stored task result (used by bench/rescore.py)."""
    if item.get("kind") == "sum" and item.get("state") == "succeeded" and item.get("missing"):
        return {**item, "outcome": "overstated"}
    return item


def _grade(right: bool, complete: bool) -> str:
    if right:
        return "correct" if complete else "unnecessary_flag"
    return "silent_wrong" if complete else "flagged"


def _public(case: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in case.items() if k not in ("docs", "rows")}
    if "docs" in case:
        out["expected_docs"] = len(case["docs"])
    if "rows" in case:
        out["expected_rows"] = len(case["rows"])
    return out
