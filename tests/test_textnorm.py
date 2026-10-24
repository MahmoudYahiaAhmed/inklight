"""Comparison keys keep every script: different Arabic (and other non-Latin) names never compare equal."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from inklight.agent.analysis import _key as inconsistency_key
from inklight.textnorm import fold

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bench"))
import scoring  # noqa: E402
import textnorm as bench_textnorm  # noqa: E402


def _pilot(name):
    spec = importlib.util.spec_from_file_location(f"pilot_{name}_tn", ROOT / "pilot" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ARABIC_A, ARABIC_B = "شركة النور للتجارة", "مؤسسة الأمل"

DIFFERENT = [
    (ARABIC_A, ARABIC_B),  # different Arabic vendors (the reproduced bug: both folded to "")
    ("شركة النور", "شركة النجوم"),
    ("कम", "काम"),  # Devanagari: the vowel sign is part of the letter
    ("東京商事", "大阪商事"),
    ("Ελληνικά Α.Ε.", "Κυπριακά Α.Ε."),
]
SAME = [
    ("مُحَمَّد", "محمد"),  # optional Arabic short vowels
    ("شركـــة النور", "شركة النور"),  # tatweel stretching
    ("INV-١٢٣", "INV-123"),  # Arabic-Indic digits
    ("ACME Supplies, Ltd.", "acme supplies ltd"),
    ("ＡＣＭＥ", "ACME"),  # full-width forms (NFKC)
]


@pytest.mark.parametrize(("a", "b"), DIFFERENT)
def test_different_names_stay_different(a, b):
    assert fold(a) != fold(b) and fold(a) and fold(b)
    assert not scoring.same("vendor", a, b)
    assert inconsistency_key(a) != inconsistency_key(b)


@pytest.mark.parametrize(("a", "b"), SAME)
def test_writing_variants_of_one_name_are_equal(a, b):
    assert fold(a) == fold(b)
    assert scoring.same("vendor", a, b)


def test_the_bench_copy_is_identical_to_the_product():
    for a, b in DIFFERENT + SAME:
        assert bench_textnorm.fold(a) == fold(a) and bench_textnorm.fold(b) == fold(b)
    body = lambda path: path.read_text(encoding="utf-8").split('"""', 2)[2]  # noqa: E731  (code after docstring)
    assert body(ROOT / "bench" / "textnorm.py") == body(ROOT / "src" / "inklight" / "textnorm.py")


def test_pilot_evaluation_and_vendor_groups_keep_arabic_names_apart():
    evaluate, intake = _pilot("evaluate"), _pilot("intake")
    assert not evaluate.same("vendor", ARABIC_A, ARABIC_B)
    assert evaluate.same("vendor", "مُحَمَّد للتجارة", "محمد للتجارة")
    assert intake.vendor_key(ARABIC_A) != intake.vendor_key(ARABIC_B)
    assert intake.vendor_key("ACME Supplies, Ltd.") == intake.vendor_key("Acme Supplies Ltd")


def test_historical_scores_are_unchanged_by_the_new_normalisation():
    """Every saved prediction rescored with the new comparison gives the stored outcome."""
    files = sorted((ROOT / "bench" / "results" / "external" / "rescored").glob("*.json"))
    assert files
    checked = 0
    for f in files:
        for row in json.loads(f.read_text(encoding="utf-8"))["rows"]:
            again = scoring.outcome(row["field"], row["got"], row["want"], row["warning"], row["confidence"])
            assert again == row["outcome5"], (f.name, row["doc"], row["field"])
            checked += 1
    assert checked > 10_000
