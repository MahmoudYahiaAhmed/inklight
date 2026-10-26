"""The user agent's only way to use Inklight: the installed CLI, logged.

    python ik.py --arm A --task A1-03 ask DOCS... "request"
    python ik.py --arm A --task A1-03 extract DOCS... --fields a,b --format csv --out FILE
    python ik.py --arm A --task A1-03 search "query"        (also: show DOC, docs)

Runs `inklight <command> ... -c <arm config>` from the evaluation environment (the installed wheel). For `ask` it asks
for the full JSON result, and prints what a person sees: the answer, its sources (document, page, excerpt), warnings,
the state and any files written. Every call is appended, complete, to <runs>/<arm>/<task>/transcript.jsonl.
A task gets at most 4 calls (the first attempt and three follow-ups); further calls are refused and logged.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

EVAL = Path(os.environ.get("INKLIGHT_EVAL_DIR", r"C:/Users/pc/inklight-eval-private"))
CLI = EVAL / "venv" / "Scripts" / "inklight.exe"
BUDGET = 4


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Arabic text on a cp1252 console
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--arm", required=True)
    ap.add_argument("--task", required=True)
    ns, rest = ap.parse_known_args()
    if not rest:
        sys.exit("usage: ik.py --arm A --task ID <ask|extract|search|show|docs> ...")
    folder = EVAL / "runs" / f"arm-{ns.arm}" / ns.task
    folder.mkdir(parents=True, exist_ok=True)
    log = folder / "transcript.jsonl"
    done = sum(1 for _ in log.open(encoding="utf-8")) if log.exists() else 0
    if done >= BUDGET:
        print(f"Refused: this task already used its {BUDGET} actions.")
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"refused": rest}, ensure_ascii=False) + "\n")
        return
    command = rest[0]
    config = EVAL / "configs" / f"arm-{ns.arm}.toml"
    args = [str(CLI), *rest, "-c", str(config)]
    if command == "ask":
        args.append("--json")
        out_dir = folder / "outputs"
        out_dir.mkdir(exist_ok=True)
        args += ["--out", str(out_dir), "--yes"]
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "TQDM_DISABLE": "1"}
    started = time.perf_counter()
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    seconds = round(time.perf_counter() - started, 2)
    entry = {"n": done + 1, "command": rest, "seconds": seconds, "exit": proc.returncode, "stderr": proc.stderr[-4000:]}
    if command == "ask":
        try:
            result = json.loads(proc.stdout[proc.stdout.index("{") :])
        except (ValueError, json.JSONDecodeError):
            result = None
        entry["result"] = result
        shown = _render(result) if result else proc.stdout + proc.stderr[-2000:]
    else:
        entry["stdout"] = proc.stdout
        shown = proc.stdout + (proc.stderr[-2000:] if proc.returncode else "")
    entry["shown"] = shown
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(shown)
    print(f"[action {done + 1} of {BUDGET} · {seconds} s]")


def _render(r: dict) -> str:
    lines = [r.get("answer", "").strip(), ""]
    for s in r.get("sources", [])[:6]:
        excerpt = " ".join(str(s.get("excerpt", "")).split())[:240]
        lines.append(f"Source: {s.get('name')} p.{s.get('page')} — “{excerpt}”")
    for w in r.get("warnings", []):
        lines.append(f"Warning: {w}")
    for nu in r.get("not_understood", []):
        lines.append(f"Not applied: {nu}")
    for f in r.get("files_written", []):
        lines.append(f"Wrote: {f}")
    lines.append(f"State: {r.get('state')} · confidence {r.get('confidence')}")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
