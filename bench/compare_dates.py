"""Measure a change to date extraction: run the same documents through two builds and compare with labels.

    # 1. once per build, with that build's interpreter (fresh library each time, same OCR models):
    python -I bench/compare_dates.py extract --out old.json --models <frozen models dir> <files or folders>...
    # 2. compare (any interpreter with python-dateutil):
    python -I bench/compare_dates.py compare old.json new.json [--invcdip <annotation dir>] [--voxel51 <truth.json>]

Labels: INV-CDIP ``Invoice_date`` / ``due_date`` strings, parsed here independently of Inklight's parser; Voxel51
``date``. A label this script cannot parse is reported as unscored, never guessed. Documents without a label
(e.g. CORD receipts) are compared old vs new only: every changed value is listed for inspection.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections import Counter
from datetime import date, datetime
from pathlib import Path

FIELDS = ["date", "due_date"]
SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
MONTHS = {
    m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])
}


def extract(out: Path, models: Path, inputs: list[Path]) -> None:
    import inklight
    from inklight import DocumentAgent
    from inklight.config import ModelSettings, OCRSettings, Settings

    files = sorted(p for i in inputs for p in ([i] if i.is_file() else i.iterdir()) if p.suffix.lower() in SUFFIXES)
    with tempfile.TemporaryDirectory() as home:
        settings = Settings(
            home=home, ocr=OCRSettings(model_dir=str(models / "indra")), models=ModelSettings(brain="rules")
        )
        with DocumentAgent(settings) as agent:
            records = agent.extract(files, fields=FIELDS)
            result = {
                Path(r.path).stem: {f: (r.fields[f].value if f in r.fields else None) for f in FIELDS} for r in records
            }
    out.write_text(json.dumps({"inklight": inklight.__file__, "values": result}, indent=1), encoding="utf-8")
    print(f"{len(result)} documents -> {out}")


def parse_label(text: str) -> date | None:
    """Independent label parser: explicit formats only."""
    s = text.strip().strip(".")
    m = re.fullmatch(r"([A-Za-z]{3})[\s.]*(\d{1,2})[/\-\s,]+(\d{2}|\d{4})", s)  # JAN04/00
    if m and m.group(1).lower() in MONTHS:
        y = int(m.group(3))
        y = y + 2000 if y < 70 else (y + 1900 if y < 100 else y)
        try:
            return date(y, MONTHS[m.group(1).lower()], int(m.group(2)))
        except ValueError:
            return None
    for fmt in (
        "%m/%d/%Y",
        "%m/%d/%y",
        "%m-%d-%y",
        "%m-%d-%Y",
        "%m.%d.%y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%B %d %Y",
        "%d %B %Y",
        "%d %b %Y",
        "%Y-%m-%d",
        "%b. %d, %Y",
        "%d-%b-%y",
        "%d-%b-%Y",
    ):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def invcdip_labels(folder: Path, ids: set[str]) -> dict[str, dict[str, str]]:
    names = {"Invoice_date": "date", "due_date": "due_date"}
    out: dict[str, dict[str, str]] = {}
    for doc_id in ids:
        path = folder / f"{doc_id}.json"
        if not path.exists():
            continue
        for f in json.loads(path.read_text(encoding="utf-8"))["Fields"]:
            label, tag = f["value"].get("label"), f["value"].get("tag")
            if tag not in names:
                label, tag = tag, label
            if tag in names and label:
                out.setdefault(doc_id, {})[names[tag]] = label
    return out


def score(values: dict, labels: dict[str, dict[str, str]]) -> tuple[Counter, list[str]]:
    c: Counter = Counter()
    unscored = []
    for doc_id, fields in labels.items():
        for field, raw in fields.items():
            truth = parse_label(raw)
            if truth is None:
                unscored.append(f"{doc_id}.{field}={raw!r}")
                continue
            got = (values.get(doc_id) or {}).get(field)
            c["labelled"] += 1
            c["correct" if got == truth.isoformat() else ("missing" if got is None else "wrong")] += 1
    return c, unscored


def compare(old_path: Path, new_path: Path, invcdip: Path | None, voxel51: Path | None) -> None:
    old = json.loads(old_path.read_text(encoding="utf-8"))
    new = json.loads(new_path.read_text(encoding="utf-8"))
    print(f"old: {old['inklight']}\nnew: {new['inklight']}")
    labels: dict[str, dict[str, str]] = {}
    if invcdip:
        labels.update(invcdip_labels(invcdip, set(old["values"])))
    if voxel51:
        truth = json.loads(voxel51.read_text(encoding="utf-8"))
        labels.update({Path(k).stem: {"date": v["date"]} for k, v in truth.items() if v.get("date")})
    labels = {k: v for k, v in labels.items() if k in old["values"]}
    for name, build in (("old", old), ("new", new)):
        counts, unscored = score(build["values"], labels)
        print(f"{name}: {dict(counts)}")
    print(f"unscored labels ({len(unscored)}): {unscored[:12]}")
    changed = [
        (d, f, old["values"][d][f], new["values"].get(d, {}).get(f))
        for d in sorted(old["values"])
        for f in FIELDS
        if old["values"][d][f] != new["values"].get(d, {}).get(f)
    ]
    print(f"changed values ({len(changed)}):")
    for d, f, a, b in changed:
        raw = labels.get(d, {}).get(f)
        verdict = (
            ""
            if raw is None or parse_label(raw) is None
            else (" RIGHT" if b == parse_label(raw).isoformat() else " WRONG")
        )
        print(f"  {d}.{f}: {a} -> {b}   label={raw!r}{verdict}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--out", type=Path, required=True)
    e.add_argument("--models", type=Path, required=True)
    e.add_argument("inputs", type=Path, nargs="+")
    c = sub.add_parser("compare")
    c.add_argument("old", type=Path)
    c.add_argument("new", type=Path)
    c.add_argument("--invcdip", type=Path)
    c.add_argument("--voxel51", type=Path)
    args = ap.parse_args()
    if args.cmd == "extract":
        extract(args.out, args.models, args.inputs)
    else:
        compare(args.old, args.new, args.invcdip, args.voxel51)


if __name__ == "__main__":
    main()
