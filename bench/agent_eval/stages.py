"""Summarise diagnose.py output: the earliest demonstrated failure stage per task, and structure coverage.

    python bench/agent_eval/stages.py STAGE_A.jsonl STAGE_B.jsonl LEDGER.jsonl OUT.md [OUT.json]

Stage order (earliest first): document selection (the plan dropped documents the user passed) -> request parsing
(a non-invoice request routed to the default invoice columns) -> OCR (a needed
value is not in the stored text of its page; split by page rotation) -> retrieval (in the text, not in any retrieved
passage, and no passage from its page; only when a search ran) -> answer selection (retrieved, or handled by an
extraction/summary/compare path, and not in the answer). Computed reference values and paraphrases of digital text
are not counted as losses. Tasks with no literal
reference value use the task type: absent facts answered anyway -> answer selection; ambiguous requests answered
without presenting the candidates -> ambiguity; export deliverables without a usable tool file -> export.
A task the tool completed (ledger) has no failure stage.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ORDER = [
    "document_selection",
    "request_parsing",
    "ocr_rotated_page",
    "ocr_upright_page",
    "retrieval",
    "answer_selection",
]
INVOICE_DEFAULT = "columns: invoice_number, vendor, date, total"
NON_INVOICE = {"field", "table", "search", "export"}


def load_jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def stage(row: dict, ledger_row: dict) -> tuple[str, dict]:
    if ledger_row.get("tool_completed"):
        return "completed", {}
    if row.get("scope_narrowed"):
        return "document_selection", {}
    if INVOICE_DEFAULT in row.get("interpretation", []) and row.get("task_type") in NON_INVOICE:
        return "request_parsing", {}  # a non-invoice request routed to the default invoice columns
    searched = any(t == "search" for t, _ in row.get("trace", []))
    lost = Counter()
    for v in row.get("values", []):
        if v["lost_at"] in ("answered", "computed", "not_literal"):
            continue
        key = v["lost_at"]
        if key == "retrieval" and not searched:
            key = "answer_selection"  # no search ran: the extraction/summary/compare path did not surface it
        if key == "ocr":
            key = "ocr_rotated_page" if (v.get("page_rotation") or 0) % 360 else "ocr_upright_page"
        lost[key] += 1
    if lost:
        return min(lost, key=ORDER.index), dict(lost)
    tt = row.get("task_type")
    if tt == "ambiguous":
        return "ambiguity", {}
    if ledger_row.get("deliverable") == "export":
        return "export", {}
    if tt == "absent":
        return "answer_selection", {}
    return "answer_selection_or_scope_of_answer", {}  # every value appears, but the judged answer was still wrong


def coverage(row: dict) -> str:
    kinds = {v.get("structure") for v in row.get("values", []) if v.get("structure")}
    if not kinds:
        return "no_reference_page"
    if kinds == {"structured"}:
        return "structured"
    if kinds == {"kept_ocr_lines"}:
        return "skipped_rotated"
    return "mixed"


def main() -> None:
    a, b, ledger_file, out = (Path(x) for x in sys.argv[1:5])
    ledger = {r["run"]: r for r in load_jsonl(ledger_file)}
    table, per = [], Counter()
    names = sys.argv[sys.argv.index("--arms") + 1].split(",") if "--arms" in sys.argv else ["A", "B"]
    for arm, f in ((names[0], a), (names[1], b)):
        for row in load_jsonl(f):
            if not row.get("replayed"):
                continue
            lr = ledger.get(f"{arm}:{row['task']}", {})
            s, detail = stage(row, lr)
            vals = row.get("values", [])
            table.append(
                {
                    "arm": arm,
                    "task": row["task"],
                    "task_type": row.get("task_type"),
                    "language": lr.get("language"),
                    "stage": s,
                    "lost": detail,
                    "values": len(vals),
                    "values_in_ocr": sum(v["ocr_on_page"] or v["ocr_in_doc"] for v in vals),
                    "values_retrieved": sum(v["retrieved"] for v in vals),
                    "values_answered": sum(v["lost_at"] == "answered" for v in vals),
                    "rotated_value_pages": sum(bool((v.get("page_rotation") or 0) % 360) for v in vals),
                    "structure": coverage(row) if arm == names[1] else None,
                    "scope_narrowed": row.get("scope_narrowed"),
                    "outcome": lr.get("outcome"),
                    "replay_matches_log": row.get("replay_matches_log"),
                }
            )
            per[(arm, s)] += 1
    lines = [f"| stage (earliest demonstrated) | {names[0]} | {names[1]} |", "|---|---|---|"]
    for s in sorted(
        {k[1] for k in per},
        key=lambda x: (ORDER + ["ambiguity", "export"]).index(x) if x in ORDER + ["ambiguity", "export"] else 99,
    ):
        lines.append(f"| {s} | {per[(names[0], s)]} | {per[(names[1], s)]} |")
    vals_a = [t for t in table if t["arm"] == names[0]]
    tot = sum(t["values"] for t in vals_a)
    lines += [
        "",
        f"Reference values ({names[0]} replay): {tot}; in the OCR text {sum(t['values_in_ocr'] for t in vals_a)}; "
        f"retrieved {sum(t['values_retrieved'] for t in vals_a)}; "
        f"in the first answer {sum(t['values_answered'] for t in vals_a)}.",
        "",
        f"| structure coverage of the supporting pages ({names[1]}) | tasks | completed by the tool |",
        "|---|---|---|",
    ]
    for c, n in Counter(t["structure"] for t in table if t["arm"] == names[1]).most_common():
        done = sum(1 for t in table if t["arm"] == names[1] and t["structure"] == c and t["stage"] == "completed")
        lines.append(f"| {c} | {n} | {done} |")
    Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    if len(sys.argv) > 5 and not sys.argv[5].startswith("--"):
        Path(sys.argv[5]).write_text(json.dumps(table, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
