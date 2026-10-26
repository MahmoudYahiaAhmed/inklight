"""The regression control for the known ambiguity failure (kept out of the fresh evaluation score).

    python bench/agent_eval/make_controls.py OUT_DIR

Writes control-two-companies.pdf: two separate tables with identical headers and different companies,

    Company name | Company type          Company name | Company type
    Alpha Ltd    | Limited company       Beta Ltd     | Limited company

"What is the company name?" must ask which company or present both clearly, never silently pick Alpha Ltd. Also
writes control-tasks.json with the control questions and their expected behaviour.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pymupdf

CSS = "body{font-family:sans-serif;font-size:12pt} table{border-collapse:collapse;width:100%} td,th{border:1px solid black;padding:6px} th{background:#ddd} h2{font-size:14pt}"
HTML = """
<h1>Supplier registration summary</h1>
<p>The following companies were registered in the supplier list.</p>
<h2>Supplier 1</h2>
<table><tr><th>Company name</th><th>Company type</th></tr><tr><td>Alpha Ltd</td><td>Limited company</td></tr></table>
<p>Registered by the procurement office.</p>
<h2>Supplier 2</h2>
<table><tr><th>Company name</th><th>Company type</th></tr><tr><td>Beta Ltd</td><td>Limited company</td></tr></table>
"""
TASKS = [
    {"task_id": "C-01", "request": "What is the company name?", "expected": "clarify_or_present_all",
     "must_mention": ["Alpha Ltd", "Beta Ltd"], "must_not": "answer Alpha Ltd alone without saying there are two"},
    {"task_id": "C-02", "request": "What type of company is Beta Ltd?", "expected": "answer", "answer": "Limited company"},
    {"task_id": "C-03", "request": "What is the name of the second supplier?", "expected": "answer", "answer": "Beta Ltd"},
    {"task_id": "C-04", "request": "What is Alpha Ltd's company type?", "expected": "answer", "answer": "Limited company"},
]


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    story = pymupdf.Story(html=HTML, user_css=CSS)
    pdf = out / "control-two-companies.pdf"
    writer = pymupdf.DocumentWriter(str(pdf))
    rect = pymupdf.paper_rect("a4")
    device = writer.begin_page(rect)
    story.place(rect + (50, 50, -50, -50))
    story.draw(device)
    writer.end_page()
    writer.close()
    (out / "control-tasks.json").write_text(json.dumps(TASKS, indent=1), encoding="utf-8")
    print("wrote", pdf)


if __name__ == "__main__":
    main()
