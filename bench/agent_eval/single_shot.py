"""Single-action runs: the regression controls (outside the score) and the small-models subset.

    python bench/agent_eval/single_shot.py EVAL_DIR controls ARM[,ARM...]
    python bench/agent_eval/single_shot.py EVAL_DIR subset ARM TASK_ID[,TASK_ID...]

Each run is one `ask` through ik.py (so it is logged exactly like a user-agent action) with the request as written.
`controls` runs C-01..C-04 on control-two-companies.pdf and CTRL-01..05 on the known control document, then scores
C-01..C-04 against their stated expectations (mentions / answer present) into runs/controls-<ARM>.json. CTRL-* are
left for the judge. `subset` re-asks the first action of reserved tasks in another arm (e.g. B-models).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

IK = Path(__file__).with_name("ik.py")


def ask(eval_dir: Path, arm: str, task_id: str, docs: list[str], request: str) -> dict:
    subprocess.run(
        [sys.executable, str(IK), "--arm", arm, "--task", task_id, "ask", *docs, request],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    log = eval_dir / "runs" / f"arm-{arm}" / task_id / "transcript.jsonl"
    return json.loads(log.read_text(encoding="utf-8").splitlines()[-1])


def doc_path(eval_dir: Path, doc_id: str) -> str:
    return str(next((eval_dir / "work" / "docs").glob(f"{doc_id}.*"))).replace("\\", "/")


def controls(eval_dir: Path, arms: list[str]) -> None:
    pair = json.loads((eval_dir / "work" / "controls" / "control-tasks.json").read_text(encoding="utf-8"))
    known = json.loads((eval_dir / "frozen" / "tasks_CTRL.json").read_text(encoding="utf-8"))
    for arm in arms:
        scored = []
        for t in pair:
            e = ask(eval_dir, arm, t["task_id"], [doc_path(eval_dir, "control-two-companies")], t["request"])
            answer = (e.get("result") or {}).get("answer") or ""
            low = answer.casefold()
            if t["expected"] == "clarify_or_present_all":
                ok = all(m.casefold() in low for m in t["must_mention"])
            else:
                ok = t["answer"].casefold() in low
            scored.append(
                {
                    "task": t["task_id"],
                    "pass": ok,
                    "answer": answer[:300],
                    "state": (e.get("result") or {}).get("state"),
                    "seconds": e["seconds"],
                }
            )
        for t in known:
            ask(eval_dir, arm, t["task_id"], [doc_path(eval_dir, d) for d in t["docs"]], t["request"])
        out = eval_dir / "runs" / f"controls-{arm}.json"
        out.write_text(json.dumps(scored, ensure_ascii=False, indent=1), encoding="utf-8")
        print(arm, [(s["task"], s["pass"]) for s in scored])


def subset(eval_dir: Path, arm: str, task_ids: list[str]) -> None:
    tasks = {}
    for f in (eval_dir / "frozen").glob("tasks_A*.json"):
        tasks.update({t["task_id"]: t for t in json.loads(f.read_text(encoding="utf-8"))})
    for tid in task_ids:
        t = tasks[tid]
        e = ask(eval_dir, arm, tid, [doc_path(eval_dir, d) for d in t["docs"]], t["request"])
        r = e.get("result") or {}
        print(tid, e["seconds"], r.get("state"), str(r.get("brain")), (r.get("answer") or "")[:80].replace("\n", " "))


def main() -> None:
    eval_dir, mode = Path(sys.argv[1]), sys.argv[2]
    if mode == "controls":
        controls(eval_dir, sys.argv[3].split(","))
    else:
        subset(eval_dir, sys.argv[3], sys.argv[4].split(","))


if __name__ == "__main__":
    main()
