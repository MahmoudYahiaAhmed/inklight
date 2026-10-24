"""Field scoring shared by bench/external.py (new runs) and bench/rescore.py (saved predictions).

Every scored value is exactly one of five outcomes. "Flagged" means the value carries a warning or a
confidence below FLAG_CONFIDENCE, i.e. it asks for human review.

    correct_unflagged   matches the annotation, no review requested   <- the only outcome that saves work
    correct_flagged     matches, but review requested
    wrong_unflagged     does not match, no review requested           <- silent error
    wrong_flagged       does not match, review requested
    missing             no value returned
"""

from __future__ import annotations

import collections
import re
from typing import Any

FLAG_CONFIDENCE = 0.7
MONEY = {"tax", "total", "subtotal"}
OUTCOMES = ("correct_unflagged", "correct_flagged", "wrong_unflagged", "wrong_flagged", "missing")


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


def flagged(warning: str | None, confidence: float | None) -> bool:
    return bool(warning) or (confidence or 0.0) < FLAG_CONFIDENCE


def outcome(field: str, got: Any, want: Any, warning: str | None, confidence: float | None) -> str:
    if got is None:
        return "missing"
    match = "correct" if same(field, got, want) else "wrong"
    return f"{match}_{'flagged' if flagged(warning, confidence) else 'unflagged'}"


def rates(counts: collections.Counter) -> dict[str, Any]:
    n = sum(counts[o] for o in OUTCOMES)
    cu, cf, wu, wf, miss = (counts[o] for o in OUTCOMES)
    unflagged = cu + wu

    def r(x: int, d: int) -> float | None:
        return round(x / d, 3) if d else None

    return {
        "n": n,
        "counts": {o: counts[o] for o in OUTCOMES},
        "value_accuracy": r(cu + cf, n),  # matches, flagged or not
        "coverage_without_review": r(cu, n),  # matches nobody needs to check
        "precision_unflagged": r(cu, unflagged),  # how far an unflagged value can be trusted
        "silent_error_rate": r(wu, n),
        "review_rate": r(cf + wf, n),  # values a person is asked to check
        "missing_rate": r(miss, n),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_field: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for row in rows:
        by_field[row["field"]][row["outcome5"]] += 1
    total: collections.Counter = collections.Counter()
    for c in by_field.values():
        total.update(c)
    return {"overall": rates(total), "fields": {f: rates(c) for f, c in sorted(by_field.items())}}
