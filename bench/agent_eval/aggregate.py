"""Aggregate the judged cases into counts with denominators, and the timing, memory and model-call figures.

    python bench/agent_eval/aggregate.py EVAL_DIR OUT_JSON [--md OUT_MD]

Reads EVAL_DIR/judging/<case>/judgment.json with _map.json (case -> arm, task), the frozen tasks, the split,
work/manifest.json, work/doc_types.json (doc id -> document type), runs/adjudication.json (outcome overrides),
every transcript (seconds per action, Inklight's own duration_ms, the brain used) and runs/ingest-*.json.
The output holds pseudonymous ids and numbers only, never document text, so it can be published.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

OUTCOMES = [
    "correct_complete",
    "correct_after_clarification",
    "correct_after_manual_correction",
    "honest_partial",
    "correct_abstention",
    "correct_clarification_request",
    "wrong_abstention",
    "wrong_with_relevant_warning",
    "silent_wrong",
    "overstated_completion",
    "technical_failure",
]
BY_TOOL = {"correct_complete", "correct_after_clarification", "correct_abstention", "correct_clarification_request"}


def load(p: Path) -> object:
    return json.loads(p.read_text(encoding="utf-8"))


def task_meta(eval_dir: Path) -> dict:
    tasks = {}
    for f in (eval_dir / "frozen").glob("tasks_*.json"):
        tasks.update({t["task_id"]: t for t in load(f)})
    types = load(eval_dir / "work" / "doc_types.json")
    digital = {
        d["doc_id"]: d["text_layer_chars"] >= 500 for d in load(eval_dir / "work" / "manifest.json")["documents"]
    }
    split = load(eval_dir / "frozen" / "split.json")
    for tid, t in tasks.items():
        langs = {t["request_language"], *t["doc_languages"]}
        t["language"] = langs.pop() if len(langs) == 1 else "mixed"
        kinds = {types.get(d, "?") for d in t["docs"]}
        t["doc_type"] = kinds.pop() if len(kinds) == 1 else "multi-type"
        t["source"] = "digital" if all(digital.get(d) for d in t["docs"]) else "scan/photo"
        t["group"] = "control" if tid.startswith("CTRL") else "dev" if tid in split["dev_tasks"] else "reserved"
    return tasks


def case_rows(eval_dir: Path, tasks: dict) -> list[dict]:
    judging = eval_dir / "judging"
    adjudication = eval_dir / "runs" / "adjudication.json"
    overrides = load(adjudication).get("overrides", {}) if adjudication.exists() else {}
    rows = []
    for case_id, info in load(judging / "_map.json").items():
        jf = judging / case_id / "judgment.json"
        if not jf.exists():
            continue
        j = load(jf)
        if case_id in overrides:
            j = {**j, "outcome": overrides[case_id]["to"], "adjudicated": True}
        transcript = eval_dir / "runs" / f"arm-{info['arm']}" / info["task"] / "transcript.jsonl"
        actions = (
            [json.loads(x) for x in transcript.read_text(encoding="utf-8").splitlines()] if transcript.exists() else []
        )
        actions = [a for a in actions if "refused" not in a]
        results = [a.get("result") or {} for a in actions]
        rows.append(
            {
                "case": case_id,
                "arm": info["arm"],
                "task": info["task"],
                **{
                    k: tasks[info["task"]][k]
                    for k in ("language", "doc_type", "task_type", "source", "group", "deliverable")
                },
                "outcome": j["outcome"],
                "first_attempt": j["first_attempt"],
                "citations": j.get("citations_support_claims"),
                "export": j.get("export_correct"),
                "warnings": j.get("warnings_accurate"),
                "uncertain": bool(j.get("uncertain")),
                "disputed": bool(j.get("reference_disputed")),
                "adjudicated": bool(j.get("adjudicated")),
                "actions": len(actions),
                "action_seconds": [a["seconds"] for a in actions],
                "inklight_ms": [r["duration_ms"] for r in results if r.get("duration_ms") is not None],
                "states": [r.get("state") for r in results if r],
                "brains": [str(r.get("brain")) for r in results if r],
                "failed_exit": sum(1 for a in actions if a.get("exit")),
            }
        )
    return rows


def summary(rows: list[dict]) -> dict:
    n = len(rows)
    c = Counter(r["outcome"] for r in rows)
    fa = Counter(r["first_attempt"] for r in rows)
    secs = [s for r in rows for s in r["action_seconds"]]
    ms = [m for r in rows for m in r["inklight_ms"]]
    return {
        "n": n,
        "outcomes": {o: c.get(o, 0) for o in OUTCOMES},
        "by_tool_after_followups": sum(c[o] for o in BY_TOOL),
        "first_attempt": dict(fa),
        "first_attempt_correct": fa.get("correct", 0),
        "silent_wrong": c.get("silent_wrong", 0),
        "overstated": c.get("overstated_completion", 0),
        "citations": dict(Counter(r["citations"] for r in rows)),
        "exports": dict(Counter(r["export"] for r in rows if r["export"] != "not_applicable")),
        "actions_mean": round(statistics.mean(r["actions"] for r in rows), 2) if rows else None,
        "action_seconds_median": round(statistics.median(secs), 2) if secs else None,
        "action_seconds_p90": round(sorted(secs)[int(0.9 * (len(secs) - 1))], 2) if secs else None,
        "inklight_ms_median": round(statistics.median(ms), 1) if ms else None,
        "uncertain": sum(r["uncertain"] for r in rows),
        "disputed": sum(r["disputed"] for r in rows),
    }


def breakdown(rows: list[dict], key: str) -> dict:
    groups = defaultdict(list)
    for r in rows:
        groups[(r["arm"], r[key])].append(r)
    return {f"{arm}|{val}": summary(g) for (arm, val), g in sorted(groups.items())}


def ingest(eval_dir: Path) -> dict:
    out = {}
    for f in sorted((eval_dir / "runs").glob("ingest-*.json")):
        d = load(f)
        out[f.stem] = {
            k: d.get(k, {}).get("seconds") if isinstance(d.get(k), dict) else d.get(k) for k in ("cold", "warm")
        } | {k: d[k] for k in d if k not in ("cold", "warm", "config")}
    return out


def markdown(agg: dict) -> str:
    lines = [
        "| arm · slice | n | by tool (after follow-ups) | first attempt correct | manual correction | "
        "honest partial | wrong abstention | silent wrong | overstated | tech. failure |",
        "|---|" + "---|" * 9,
    ]

    def row(label: str, s: dict) -> None:
        o = s["outcomes"]
        lines.append(
            f"| {label} | {s['n']} | {s['by_tool_after_followups']} | {s['first_attempt_correct']} | "
            f"{o['correct_after_manual_correction']} | {o['honest_partial']} | {o['wrong_abstention']} | "
            f"{o['silent_wrong']} | {o['overstated_completion']} | {o['technical_failure']} |"
        )

    for label, s in agg["overall"].items():
        row(label, s)
    for key in ("group", "language", "doc_type", "task_type", "source"):
        for label, s in agg["by"][key].items():
            row(f"{label.replace('|', ' · ')}", s)
    return "\n".join(lines)


def main() -> None:
    eval_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    tasks = task_meta(eval_dir)
    rows = case_rows(eval_dir, tasks)
    scored = [r for r in rows if r["group"] != "control"]
    agg = {
        "cases": rows,
        "overall": {arm: summary([r for r in scored if r["arm"] == arm]) for arm in sorted({r["arm"] for r in scored})},
        "controls": {
            arm: summary([r for r in rows if r["group"] == "control" and r["arm"] == arm])
            for arm in sorted({r["arm"] for r in rows if r["group"] == "control"})
        },
        "by": {k: breakdown(scored, k) for k in ("group", "language", "doc_type", "task_type", "source")},
        "ingest": ingest(eval_dir),
    }
    out.write_text(json.dumps(agg, ensure_ascii=False, indent=1), encoding="utf-8")
    if "--md" in sys.argv:
        Path(sys.argv[sys.argv.index("--md") + 1]).write_text(markdown(agg), encoding="utf-8")
    print(json.dumps(agg["overall"], indent=1))


if __name__ == "__main__":
    main()
