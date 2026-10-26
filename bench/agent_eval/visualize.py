"""A folder of pictures of the evaluation, to look through: for every user-agent run, the cited pages with Inklight's
cited regions drawn on them, and an index.html with the request, what the tool answered (first and last action), its
warnings, what the person handed over, and the judge's verdict and explanation.

    EVAL_PYTHON bench/agent_eval/visualize.py EVAL_DIR OUT_DIR [--judging SUBDIR]

Inklight's boxes are in the page's stored (upright) frame; each is mapped onto the page as the file shows it with
inklight.frames.to_original (the page's rotation and size come from the arm's library) and scaled to the page image.
Run with an environment whose inklight has frames.py.
"""

from __future__ import annotations

import html
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from inklight import DocumentAgent
from inklight.config import load_settings
from inklight.frames import original_size, to_original

_GEOMETRY: dict[str, dict[tuple[str, int], tuple[int, float, float]]] = {}


def geometry(eval_dir: Path, arm: str) -> dict[tuple[str, int], tuple[int, float, float]]:
    """(document name, page) -> (rotation, stored width, stored height), from the arm's library."""
    if arm not in _GEOMETRY:
        config = eval_dir / "configs" / f"arm-{arm}.toml"
        found: dict[tuple[str, int], tuple[int, float, float]] = {}
        if config.exists():
            with DocumentAgent(load_settings(config)) as agent:
                for d in agent.library.documents():
                    for p in agent.library.pages(d.id):
                        found[(d.name, p.number)] = (p.rotation, float(p.width or 0), float(p.height or 0))
        _GEOMETRY[arm] = found
    return _GEOMETRY[arm]


def main() -> None:
    eval_dir, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    judging = eval_dir / (sys.argv[sys.argv.index("--judging") + 1] if "--judging" in sys.argv else "judging")
    mapping = (
        json.loads((judging / "_map.json").read_text(encoding="utf-8")) if (judging / "_map.json").exists() else {}
    )
    case_of = {(v["arm"], v["task"]): k for k, v in mapping.items()}
    tasks = {}
    for f in (eval_dir / "frozen").glob("tasks_*.json"):
        tasks.update({t["task_id"]: t for t in json.loads(f.read_text(encoding="utf-8"))})
    rows = []
    for run in sorted((eval_dir / "runs").glob("arm-*/*/transcript.jsonl")):
        info = {"arm": run.parent.parent.name[4:], "task": run.parent.name}
        case = judging / case_of.get((info["arm"], info["task"]), "-")
        judgment = (
            json.loads((case / "judgment.json").read_text(encoding="utf-8"))
            if (case / "judgment.json").exists()
            else {"outcome": "not judged yet", "explanation": ""}
        )
        task = tasks.get(info["task"], {"request": "?"})
        final_file = run.parent / "final.json"
        final = json.loads(final_file.read_text(encoding="utf-8")) if final_file.exists() else {}
        actions = [json.loads(x) for x in run.read_text(encoding="utf-8").splitlines()]
        actions = [a for a in actions if "refused" not in a]
        images = []
        boxes: dict[tuple[str, int], list] = {}
        for a in actions:
            for s in (a.get("result") or {}).get("sources") or []:
                boxes.setdefault((s.get("name"), s.get("page")), []).append(s.get("bbox"))
        for (name, page), bxs in list(boxes.items())[:4]:
            stem = Path(str(name)).stem
            png = eval_dir / "work" / "pages" / stem / f"p{page}.png"
            if not png.exists():
                continue
            img = Image.open(png).convert("RGB")
            draw = ImageDraw.Draw(img)
            rotation, w, h = geometry(eval_dir, info["arm"]).get((str(name), page), (0, 0.0, 0.0))
            ow, _ = original_size(rotation, w, h) if w else (img.width, img.height)
            scale = img.width / ow if ow else 1.0
            for b in bxs:
                if b:
                    shown = to_original(tuple(b), rotation, w, h) if w else tuple(b)
                    x0, y0, x1, y1 = (v * scale for v in shown)
                    draw.rectangle([x0, y0, x1, y1], outline=(220, 0, 0), width=4)
            target = out / f"{info['task']}-{info['arm']}-{stem}-p{page}.png"
            img.thumbnail((1100, 1500))
            img.save(target)
            images.append(target.name)
        first = (actions[0].get("shown") if actions else "") or ""
        last = (actions[-1].get("shown") if actions else "") or ""
        rows.append((info, task, judgment, final, first, last, images, len(actions)))
    parts = [
        "<!doctype html><meta charset='utf-8'><title>Inklight agent-run evaluation</title>",
        "<style>body{font-family:sans-serif;max-width:1200px;margin:auto;padding:16px} .case{border:1px solid #ccc;"
        "border-radius:8px;padding:12px;margin:16px 0} pre{white-space:pre-wrap;background:#f6f6f6;padding:8px} "
        "img{max-width:100%;border:1px solid #ddd;margin:4px 0} .ok{color:#0a7d2c} .bad{color:#b00020} "
        ".mid{color:#a65e00} [dir=auto]{unicode-bidi:plaintext}</style>",
        "<h1>Inklight agent-run evaluation — every user-agent run</h1>",
        "<p>Red boxes: the regions Inklight cited. Arms A/B: the evaluated build (3f1ec75); A2/B2: the corrected "
        "build (d9e0496). A and A2: structure off; B and B2: Docling structure. "
        "Private documents: do not share this folder.</p>",
    ]
    good = {"correct_complete", "correct_after_clarification", "correct_abstention", "correct_clarification_request"}
    mid = {"correct_after_manual_correction", "honest_partial", "wrong_with_relevant_warning"}
    for info, task, j, final, first, last, images, n in rows:
        cls = (
            "ok"
            if j["outcome"] in good
            else "mid"
            if j["outcome"] in mid or j["outcome"] == "not judged yet"
            else "bad"
        )
        parts.append(
            f"<div class='case'><h2>{info['task']} · arm {info['arm']} · "
            f"<span class='{cls}'>{html.escape(j['outcome'])}</span> (first attempt: "
            f"{html.escape(j.get('first_attempt', ''))}, {n} action(s))</h2>"
        )
        parts.append(f"<p dir='auto'><b>Request:</b> {html.escape(task['request'])}</p>")
        parts.append(f"<p><b>Tool, first action:</b></p><pre dir='auto'>{html.escape(first[:1500])}</pre>")
        if n > 1:
            parts.append(f"<p><b>Tool, last action:</b></p><pre dir='auto'>{html.escape(last[:1500])}</pre>")
        parts.append(f"<p dir='auto'><b>Handed over:</b> {html.escape(str(final.get('final_answer', ''))[:1200])}</p>")
        if final.get("manual_correction"):
            parts.append(
                f"<p dir='auto'><b>Manual correction:</b> {html.escape(str(final['manual_correction'])[:800])}</p>"
            )
        parts.append(f"<p dir='auto'><b>Judge:</b> {html.escape(j.get('explanation', ''))}</p>")
        for im in images:
            parts.append(f"<img src='{im}' loading='lazy'>")
        parts.append("</div>")
    (out / "index.html").write_text("\n".join(parts), encoding="utf-8")
    print(len(rows), "cases ->", out / "index.html")


if __name__ == "__main__":
    main()
