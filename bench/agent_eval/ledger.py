"""The canonical per-run ledger of an agent-run evaluation, and every count in the report derived from it.

    python bench/agent_eval/ledger.py EVAL_DIR OUT_DIR [--runs RUNS_SUBDIR] [--judging JUDGING_SUBDIR] [--label NAME]

One row per run (one arm x one task, whatever produced it): what kind of run it was, whether it is scored, how many
actions it used, whether the person could see the original pages, the judge's outcome as recorded and as amended
(amendment/amendment.json), and the derived flags the report counts: completed by the tool (first action or after
follow-ups), manual rescue, correct or wrong abstention, silent wrong. Deterministic value checks are recomputed
against the original and the corrected references, side by side. Nothing frozen is modified.

Writes OUT_DIR/ledger.jsonl (no document text: ids, labels and numbers only) and OUT_DIR/summary.md.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from check import found, norm  # noqa: E402

BY_TOOL = {"correct_complete", "correct_after_clarification", "correct_abstention", "correct_clarification_request"}
CONTROL_PAIR = {"C-01", "C-02", "C-03", "C-04"}


def load(p: Path) -> object:
    return json.loads(p.read_text(encoding="utf-8"))


def arg(name: str, default: str) -> str:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def value_hits(ref: dict, answer: str) -> dict:
    text = norm(answer)
    out = {}
    for name, item in (ref.get("answer") or {}).items():
        if isinstance(item, dict) and item.get("value"):
            out[name] = any(found(o, text) for o in [item["value"], *item.get("alternatives", [])])
    return out


def main() -> None:
    eval_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    runs_dir = eval_dir / arg("--runs", "runs")
    judging = eval_dir / arg("--judging", "judging")
    out.mkdir(parents=True, exist_ok=True)
    tasks, refs = {}, {}
    for f in (eval_dir / "frozen").glob("tasks_*.json"):
        tasks.update({t["task_id"]: t for t in load(f)})
    for f in (eval_dir / "frozen").glob("refs_*.json"):
        refs.update({r["task_id"]: r for r in load(f)})
    split = load(eval_dir / "frozen" / "split.json")
    amend_file = eval_dir / "amendment" / "amendment.json"
    amend = load(amend_file)["items"] if amend_file.exists() else []
    corrected = {i["task"]: i["corrected"] for i in amend if i["kind"] == "reference"}
    judge_fix = {i["case"]: i for i in amend if i["kind"] == "judgment"}
    mapping = load(judging / "_map.json") if (judging / "_map.json").exists() else {}
    case_of = {(v["arm"], v["task"]): k for k, v in mapping.items()}
    pair_scores = {}
    for f in runs_dir.glob("controls-*.json"):
        pair_scores.update({(f.stem[9:], s["task"]): s["pass"] for s in load(f)})

    rows = []
    for transcript in sorted(runs_dir.glob("arm-*/*/transcript.jsonl")):
        arm, task = transcript.parent.parent.name[4:], transcript.parent.name
        entries = [json.loads(x) for x in transcript.read_text(encoding="utf-8").splitlines()]
        actions = [e for e in entries if "refused" not in e]
        results = [e.get("result") or {} for e in actions]
        final_file = transcript.parent / "final.json"
        final = load(final_file) if final_file.exists() else None
        if task in CONTROL_PAIR:
            kind, scope = "single_shot_scored", "control"
        elif task.startswith("CTRL"):
            kind, scope = "single_shot_judged", "control"
        elif final is None:
            kind, scope = "single_shot_subset", "subset"
        else:
            kind = "user_agent"
            scope = "dev" if task in split["dev_tasks"] else "reserved"
        row = {
            "run": f"{arm}:{task}",
            "arm": arm,
            "task": task,
            "kind": kind,
            "scope": scope,
            "scored": kind == "user_agent",
            "actions": len(actions),
            "refused_actions": len(entries) - len(actions),
            "tool_errors": sum(1 for e in actions if e.get("exit")),
            "tool_states": [r.get("state") for r in results],
            "page_images_available": kind == "user_agent",
            "seconds": [e["seconds"] for e in actions],
            "inklight_ms": [r["duration_ms"] for r in results if r.get("duration_ms") is not None],
            "brains": sorted({str(r.get("brain")) for r in results if r}),
            "tool_files": sum(len(r.get("files_written") or []) for r in results)
            + sum(1 for e in actions if e["command"][0] == "extract" and not e.get("exit")),
        }
        t = tasks.get(task)
        if t:
            langs = {t["request_language"], *t["doc_languages"]}
            row |= {
                "language": langs.pop() if len(langs) == 1 else "mixed",
                "request_language": t["request_language"],
                "task_type": t["task_type"],
                "deliverable": t["deliverable"],
            }
        if final is not None:
            handed = final.get("export_file")
            row["export_handed_over"] = bool(handed)
            row["export_from_tool"] = bool(handed) and "/outputs/" in str(handed).replace("\\", "/")
        case = case_of.get((arm, task))
        if case and (judging / case / "judgment.json").exists():
            j = load(judging / case / "judgment.json")
            amended = judge_fix.get(case, {}).get("corrected", {}).get("outcome", j["outcome"])
            row |= {
                "case": case,
                "outcome_recorded": j["outcome"],
                "outcome": amended,
                "judgment_amended": case in judge_fix,
                "first_attempt": j["first_attempt"],
                "answer_correct": j.get("answer_correct"),
                "citations": j.get("citations_support_claims"),
                "warnings": j.get("warnings_accurate"),
                "export_judged": j.get("export_correct"),
                "reference_disputed": bool(j.get("reference_disputed")),
                "uncertain": bool(j.get("uncertain")),
            }
            o, fa = amended, j["first_attempt"]
            first_done = fa == "correct" or (o == "correct_abstention" and fa == "abstained")
            row |= {
                "tool_completed": o in BY_TOOL,
                "completed_at": ("first" if first_done else "follow_up") if o in BY_TOOL else None,
                "manual_rescue": o == "correct_after_manual_correction",
                "wrong_abstention": o == "wrong_abstention",
                "silent_wrong": o == "silent_wrong",
                "overstated": o == "overstated_completion",
            }
        if kind == "single_shot_scored":
            row["control_pass"] = pair_scores.get((arm, task))
        if kind == "single_shot_subset":
            base = runs_dir / "arm-B" / task / "transcript.jsonl"
            first_b = json.loads(base.read_text(encoding="utf-8").splitlines()[0]).get("result") or {}
            row["identical_to_B_first_answer"] = (results[0].get("answer") if results else None) == first_b.get(
                "answer"
            )
        if task in refs and final is not None:
            row["checks_original"] = value_hits(refs[task], final.get("final_answer", ""))
            if task in corrected:
                row["checks_corrected"] = value_hits(corrected[task], final.get("final_answer", ""))
        rows.append(row)

    (out / "ledger.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", "utf-8")
    (out / "summary.md").write_text(summary(rows, arg("--label", "")), encoding="utf-8")
    print(f"{len(rows)} runs -> {out / 'ledger.jsonl'}")


def pct(n: int, d: int) -> str:
    return f"{n}/{d}"


def summary(rows: list[dict], label: str) -> str:
    kinds = Counter(r["kind"] for r in rows)
    scored = [r for r in rows if r["scored"]]
    arms = sorted({r["arm"] for r in scored})
    lines = [f"# Ledger summary {label}".rstrip(), "", "## Runs", "", "| kind | runs |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in sorted(kinds.items())]
    lines += [f"| **total** | {len(rows)} |", ""]
    lines += ["## Scored runs", "", "| | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]

    def row(name: str, fn) -> None:  # noqa: ANN001
        cells = []
        for a in arms:
            rs = [r for r in scored if r["arm"] == a]
            cells.append(pct(sum(1 for r in rs if fn(r)), len(rs)))
        lines.append(f"| {name} | " + " | ".join(cells) + " |")

    row("completed by the tool on the first action", lambda r: r.get("completed_at") == "first")
    row("completed by the tool after follow-up (incl. clarification)", lambda r: r.get("completed_at") == "follow_up")
    row("correct only after the person read the pages (manual rescue)", lambda r: r.get("manual_rescue"))
    row("correct abstention by the tool", lambda r: r.get("outcome") == "correct_abstention")
    row("wrong abstention", lambda r: r.get("wrong_abstention"))
    row("silent wrong (as handed over)", lambda r: r.get("silent_wrong"))
    row("overstated completion", lambda r: r.get("overstated"))
    row(
        "honest partial / wrong with relevant warning",
        lambda r: r.get("outcome") in ("honest_partial", "wrong_with_relevant_warning"),
    )
    row("technical failure", lambda r: r.get("outcome") == "technical_failure")
    row("first answer judged correct", lambda r: r.get("first_attempt") == "correct")
    row("first answer wrong", lambda r: r.get("first_attempt") == "wrong")
    row("first answer abstained", lambda r: r.get("first_attempt") == "abstained")
    row("first answer failed (error/empty)", lambda r: r.get("first_attempt") == "failed")
    row("citations fully support the claim", lambda r: r.get("citations") == "yes")
    row("citations partly support", lambda r: r.get("citations") == "partly")
    row("warnings describe the actual problem", lambda r: r.get("warnings") == "yes")
    row(
        "export tasks with a usable tool-written file",
        lambda r: r.get("deliverable") == "export" and r.get("export_from_tool") and r.get("export_judged") == "yes",
    )
    row("judgment amended", lambda r: r.get("judgment_amended"))
    lines.append("")
    for a in arms:
        rs = [r for r in scored if r["arm"] == a]
        secs = [s for r in rs for s in r["seconds"]]
        ms = [m for r in rs for m in r["inklight_ms"]]
        lines.append(
            f"- {a}: {sum(r['actions'] for r in rs)} actions, mean {statistics.mean(r['actions'] for r in rs):.2f}"
            f" per run; CLI seconds median {statistics.median(secs):.2f};"
            f" Inklight ms median {statistics.median(ms):.0f};"
            f" brains {sorted({b for r in rs for b in r['brains']})}"
        )
    lines += ["", "## By slice (completed by the tool / manual rescue / n)", ""]
    for key in ("language", "task_type"):
        groups = defaultdict(list)
        for r in scored:
            groups[(r[key], r["arm"])].append(r)
        lines += [f"| {key} | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
        for val in sorted({k[0] for k in groups}):
            cells = []
            for a in arms:
                g = groups.get((val, a), [])
                cells.append(f"{sum(r['tool_completed'] for r in g)} / {sum(r['manual_rescue'] for r in g)} / {len(g)}")
            lines.append(f"| {val} | " + " | ".join(cells) + " |")
        lines.append("")
    controls = [r for r in rows if r["scope"] == "control"]
    if controls:
        lines += ["## Controls (outside the score)", ""]
        for a in sorted({r["arm"] for r in controls}):
            cs = [r for r in controls if r["arm"] == a]
            pair = [r for r in cs if r["kind"] == "single_shot_scored"]
            judged = Counter(r.get("outcome") for r in cs if r["kind"] == "single_shot_judged")
            lines.append(
                f"- {a}: pair control {sum(bool(r['control_pass']) for r in pair)}/{len(pair)} pass;"
                f" known control {dict(judged)}"
            )
        lines.append("")
    subset = [r for r in rows if r["kind"] == "single_shot_subset"]
    if subset:
        lines.append(
            f"Small-models subset: {sum(r['identical_to_B_first_answer'] for r in subset)}/{len(subset)}"
            " first answers identical to arm B."
        )
    checks = [r for r in rows if "checks_corrected" in r]
    if checks:
        lines += [
            "",
            "## Deterministic checks under original vs corrected references",
            "",
            "| run | original | corrected |",
            "|---|---|---|",
        ]
        for r in checks:
            o, c = r["checks_original"], r["checks_corrected"]
            lines.append(f"| {r['run']} | {sum(o.values())}/{len(o)} | {sum(c.values())}/{len(c)} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
