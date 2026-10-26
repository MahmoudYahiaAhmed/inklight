"""Deterministic checks for one judged case: exact values, export contents and cited pages.

    python bench/agent_eval/check.py CASE_DIR

Reads CASE_DIR/reference.json, final.json, transcript.jsonl and export/*. Writes CASE_DIR/checks.json:
- values: for each reference value, whether it (or an alternative) occurs in the final answer, normalised for
  digit forms (Arabic-Indic and Latin), Arabic letter variants, case and spacing;
- export: whether the handed-over file exists, has the expected columns, and contains each expected value;
- cited_pages: the pages the tool cited in its last answer, and whether they include each reference page.
These complement the judge; they never replace it (semantic tasks need judgment).
"""

from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

_AR = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ی": "ي", "ک": "ك"})


def norm(text: object) -> str:
    out = []
    for ch in unicodedata.normalize("NFKC", str(text)):
        if ch.isdigit():
            try:
                out.append(str(unicodedata.decimal(ch)))
                continue
            except ValueError:
                pass
        if unicodedata.category(ch).startswith("M") or ch == "ـ":
            continue
        out.append(ch)
    return re.sub(r"[\s,،]+", " ", "".join(out).translate(_AR).casefold()).strip()


def found(value: str, text: str) -> bool:
    v = norm(value)
    if not v:
        return False
    if v in text:
        return True
    digits = re.sub(r"\D", "", v)
    return len(digits) >= 5 and digits in re.sub(r"\D", "", text)  # identifiers printed with other separators


def main() -> None:
    case = Path(sys.argv[1])
    ref = json.loads((case / "reference.json").read_text(encoding="utf-8"))
    final = json.loads((case / "final.json").read_text(encoding="utf-8")) if (case / "final.json").exists() else {}
    answer = norm(final.get("final_answer", ""))
    values = {}
    for name, item in (ref.get("answer") or {}).items():
        if not isinstance(item, dict) or not item.get("value"):
            continue
        options = [item["value"], *item.get("alternatives", [])]
        values[name] = any(found(o, answer) for o in options)
    export = None
    files = sorted((case / "export").glob("*")) if (case / "export").exists() else []
    if ref.get("export_columns"):
        text, columns = "", []
        for f in files:
            raw = f.read_text(encoding="utf-8-sig", errors="replace")
            text += raw
            if f.suffix.lower() == ".csv":
                rows = list(csv.reader(raw.splitlines()))
                columns += rows[0] if rows else []
        export = {
            "files": [f.name for f in files],
            "columns_present": {c: any(norm(c) in norm(h) or norm(h) in norm(c) for h in columns) for c in ref["export_columns"]}
            if columns
            else None,
            "values_present": {
                n: any(found(o, norm(text)) for o in [i["value"], *i.get("alternatives", [])])
                for n, i in (ref.get("answer") or {}).items()
                if isinstance(i, dict) and i.get("value")
            },
        }
    cited = []
    transcript = case / "transcript.jsonl"
    if transcript.exists():
        for line in transcript.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            if entry.get("result"):
                cited = [(s.get("name"), s.get("page")) for s in entry["result"].get("sources", [])]
    ref_pages = {(i.get("doc"), i.get("page")) for i in (ref.get("answer") or {}).values() if isinstance(i, dict)}
    cited_ok = {
        f"{d} p{p}": any(str(name).startswith(str(d)) and page == p for name, page in cited) for d, p in ref_pages if d
    }
    out = {"values_in_answer": values, "export": export, "cited_pages": cited, "reference_pages_cited": cited_ok}
    (case / "checks.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
