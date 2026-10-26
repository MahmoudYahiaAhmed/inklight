"""Build blinded judging cases from user-agent runs, then run the deterministic checks on each.

    python bench/agent_eval/bundle.py EVAL_DIR ARM[,ARM...] TASKS_JSON [--seed N] [--judging SUBDIR] [--blind]
        [--corrected]   (--blind removes arm names from what judges read; --corrected uses the amended references)

For every (arm, task) with a run, creates EVAL_DIR/judging/<case_id>/ with task.json, reference.json, transcript.md
(every action and exactly what the tool showed), transcript.jsonl, final.json, export/ (the files the user handed over
and the files the tool wrote), and pages.txt (the original page images of the task's documents). Case ids are random;
the arm of each case is recorded only in EVAL_DIR/judging/_map.json, which judges do not read.
"""

from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

_ARM = re.compile(r"arm-[A-Za-z0-9-]+")


def render(transcript: Path) -> str:
    parts = []
    for line in transcript.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if "refused" in e:
            parts.append(f"### Refused action (budget used up): {e['refused']}\n")
            continue
        cmd = " ".join(e["command"])
        parts.append(f"### Action {e['n']} ({e['seconds']} s)\n\n`inklight {cmd}`\n\n```\n{e.get('shown', '')}\n```\n")
    return "\n".join(parts)


def main() -> None:
    eval_dir, arms, tasks_file = Path(sys.argv[1]), sys.argv[2].split(","), Path(sys.argv[3])
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 7
    rng = random.Random(seed)
    tasks = {t["task_id"]: t for t in json.loads(tasks_file.read_text(encoding="utf-8"))}
    refs = {}
    for f in (eval_dir / "frozen").glob("refs_*.json"):
        refs.update({r["task_id"]: r for r in json.loads(f.read_text(encoding="utf-8"))})
    corrected = eval_dir / "amendment" / "refs_corrected.json"
    if "--corrected" in sys.argv and corrected.exists():  # the amended references (amendment/amendment.json)
        refs.update({r["task_id"]: r for r in json.loads(corrected.read_text(encoding="utf-8"))})
    judging = eval_dir / (sys.argv[sys.argv.index("--judging") + 1] if "--judging" in sys.argv else "judging")
    judging.mkdir(exist_ok=True)
    mapping_file = judging / "_map.json"
    mapping = json.loads(mapping_file.read_text(encoding="utf-8")) if mapping_file.exists() else {}
    done = {(v["arm"], v["task"]) for v in mapping.values()}
    for task_id, task in tasks.items():
        for arm in arms:
            run = eval_dir / "runs" / f"arm-{arm}" / task_id
            if not run.exists() or (arm, task_id) in done:
                continue
            case_id = f"case-{rng.randrange(16**6):06x}"
            case = judging / case_id
            case.mkdir()
            (case / "task.json").write_text(json.dumps(task, ensure_ascii=False, indent=1), encoding="utf-8")
            (case / "reference.json").write_text(
                json.dumps(refs[task_id], ensure_ascii=False, indent=1), encoding="utf-8"
            )
            transcript = run / "transcript.jsonl"
            if transcript.exists():
                shutil.copyfile(transcript, case / "transcript.jsonl")
                (case / "transcript.md").write_text(render(transcript), encoding="utf-8")
            final = run / "final.json"
            if final.exists():
                shutil.copyfile(final, case / "final.json")
            export = case / "export"
            export.mkdir()
            handed = json.loads(final.read_text(encoding="utf-8")).get("export_file") if final.exists() else None
            for f in [Path(handed)] if handed else []:
                if f.exists():
                    shutil.copyfile(f, export / f.name)
            for f in (run / "outputs").glob("*") if (run / "outputs").exists() else []:
                shutil.copyfile(f, export / f"tool-{f.name}")
            pages = []
            for doc in task["documents"]:
                stem = Path(doc).stem
                pages += sorted(str(p).replace("\\", "/") for p in (eval_dir / "work" / "pages" / stem).glob("p*.png"))
            (case / "pages.txt").write_text("\n".join(pages), encoding="utf-8")
            if "--blind" in sys.argv:  # file paths name the arm ("runs/arm-B2/..."): judges must not see it
                for f in [case / "transcript.md", case / "transcript.jsonl", case / "final.json"]:
                    if f.exists():
                        f.write_text(_ARM.sub("arm-X", f.read_text(encoding="utf-8")), encoding="utf-8")
            mapping[case_id] = {"arm": arm, "task": task_id}
            subprocess.run([sys.executable, str(Path(__file__).with_name("check.py")), str(case)], capture_output=True)
    mapping_file.write_text(json.dumps(mapping, indent=1), encoding="utf-8")
    print(len(mapping), "cases")


if __name__ == "__main__":
    main()
