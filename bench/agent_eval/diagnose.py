"""Stage diagnosis: where, in the pipeline, each task's reference values were lost.

    EVAL_PYTHON bench/agent_eval/diagnose.py EVAL_DIR ARM OUT.jsonl [--runs RUNS_SUBDIR] [--ingest INGEST.json]

Replays the first action of every scored task exactly as the user agent sent it (same request, same files), in
process, against the arm's existing library, and records for each reference value:
- ocr: whether the value is in the stored text of its reference page (exact after normalisation; close: difflib
  ratio >= 0.85 against a same-length window; or, for a composite reference of 4+ words, 80% of its words present),
  and anywhere in the document;
- page: the page's rotation and source, and (structure on) whether the structure step kept Indra's lines
  (`rotated_pages_kept`) or structured the page;
- scope: the documents passed vs the documents left after the plan's document selection;
- retrieval: whether the value is in the retrieved passages (full block text, not the excerpt), and whether any
  retrieved passage is on the reference page;
- answer: whether the value is in the answer.
The earliest stage at which a value is lost is reported per value and per task. The replayed answer is compared with
the logged one to confirm the replay is faithful. Output holds no document text.
"""

from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from check import found, norm  # noqa: E402

from inklight import DocumentAgent  # noqa: E402
from inklight.config import load_settings  # noqa: E402
from inklight.library import Library  # noqa: E402

CAPTURED: list = []
_search = Library.search


def _recording_search(self, query, doc_ids=None, k=8):  # noqa: ANN001, ANN202
    hits = _search(self, query, doc_ids, k)
    CAPTURED.append(hits)
    return hits


Library.search = _recording_search  # type: ignore[method-assign]


def close(value: str, text: str) -> bool:
    v, t = norm(value), norm(text)
    if not v or not t:
        return False
    if found(value, t):
        return True
    words = [w for w in v.split() if len(w) >= 3]
    if len(words) >= 4:  # a composite reference ("name (IMO), flag, type, area"): most of its words on the page
        tokens = set(t.split())
        if sum(w in tokens for w in words) / len(words) >= 0.8:
            return True
    n = len(v)
    if n < 6:
        return False
    step = max(1, n // 4)
    return any(
        difflib.SequenceMatcher(None, v, t[i : i + n]).ratio() >= 0.85 for i in range(0, max(1, len(t) - n + 1), step)
    )


def page_text(page) -> str:  # noqa: ANN001
    return "\n".join([page.markdown, *(ln.text for ln in page.lines), *(b.text for b in page.blocks)])


def main() -> None:
    eval_dir, arm, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    runs = eval_dir / (sys.argv[sys.argv.index("--runs") + 1] if "--runs" in sys.argv else "runs")
    ingest_file = Path(sys.argv[sys.argv.index("--ingest") + 1]) if "--ingest" in sys.argv else None
    structure = {}
    if ingest_file and ingest_file.exists():
        for name, d in json.loads(ingest_file.read_text(encoding="utf-8"))["documents"].items():
            structure[Path(name).stem] = d.get("structure") or {}
    refs, tasks = {}, {}
    for f in (eval_dir / "frozen").glob("refs_A*.json"):
        refs.update({r["task_id"]: r for r in json.loads(f.read_text(encoding="utf-8"))})
    for f in (eval_dir / "frozen").glob("tasks_A*.json"):
        tasks.update({t["task_id"]: t for t in json.loads(f.read_text(encoding="utf-8"))})
    amend = eval_dir / "amendment" / "refs_corrected.json"
    if amend.exists():
        refs.update({r["task_id"]: r for r in json.loads(amend.read_text(encoding="utf-8"))})
    agent = DocumentAgent(load_settings(eval_dir / "configs" / f"arm-{arm}.toml"))
    rows = []
    for task_id in sorted(tasks):
        log = runs / f"arm-{arm}" / task_id / "transcript.jsonl"
        if not log.exists():
            continue
        first = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
        cmd = first["command"]
        if cmd[0] != "ask":
            rows.append({"task": task_id, "arm": arm, "replayed": False, "reason": f"first action was {cmd[0]}"})
            continue
        files, request = [c for c in cmd[1:-1] if not c.startswith("-")], cmd[-1]
        CAPTURED.clear()
        result = agent.ask(request, files=files, save=False)
        logged = (first.get("result") or {}).get("answer")
        by_name = {d.name: d for d in agent.library.documents()}
        trace = [(s.tool, s.summary) for s in result.trace]
        selected = next((s for t, s in trace if t == "inspect_documents"), "")
        hits = [h for batch in CAPTURED for h in batch]
        values = []
        for name, item in (refs[task_id].get("answer") or {}).items():
            if not isinstance(item, dict) or not item.get("value") or not item.get("doc"):
                continue
            doc = next((d for n, d in by_name.items() if Path(n).stem == item["doc"]), None)
            pages = agent.library.pages(doc.id) if doc else []
            pg = next((p for p in pages if p.number == item.get("page")), None)
            options = [item["value"], *item.get("alternatives", [])]
            on_page = bool(pg) and any(close(o, page_text(pg)) for o in options)
            in_doc = any(close(o, page_text(p)) for p in pages for o in options)
            hit_texts = []
            for h in hits:
                if doc and h.source.doc_id == doc.id:
                    p = next((p for p in pages if p.number == h.source.page), None)
                    b = (
                        p.blocks[h.source.block]
                        if p and h.source.block is not None and h.source.block < len(p.blocks)
                        else None
                    )
                    hit_texts.append(b.text if b else h.source.excerpt)
            retrieved = any(close(o, t) for t in hit_texts for o in options)
            ref_page_retrieved = any(
                doc and h.source.doc_id == doc.id and h.source.page == item.get("page") for h in hits
            )
            answered = any(close(o, result.answer) for o in options)
            st = structure.get(item["doc"], {})
            v = {
                "field": name,
                "computed": str(item.get("region", "")).lower().startswith("computed"),
                "doc": item["doc"],
                "page": item.get("page"),
                "page_rotation": pg.rotation if pg else None,
                "page_source": pg.source if pg else None,
                "structure": (
                    None
                    if not st
                    else "kept_ocr_lines"
                    if item.get("page") in st.get("rotated_pages_kept", [])
                    else "structured"
                    if item.get("page") in st.get("pages_structured", [])
                    else "not_processed"
                ),
                "ocr_on_page": on_page,
                "ocr_in_doc": in_doc,
                "retrieved": retrieved,
                "ref_page_retrieved": ref_page_retrieved,
                "answered": answered,
            }
            v["lost_at"] = (
                "answered"
                if answered
                else "computed"
                if v["computed"]
                else "not_literal"
                if not (on_page or in_doc) and pg is not None and pg.source == "text"
                else "ocr"
                if not (on_page or in_doc)
                else "retrieval"
                if not retrieved and not ref_page_retrieved
                else "answer_selection"
            )
            values.append(v)
        passed = len(files)
        n_selected = int(selected.split()[0]) if selected[:1].isdigit() else None
        rows.append(
            {
                "task": task_id,
                "arm": arm,
                "replayed": True,
                "replay_matches_log": result.answer == logged,
                "task_type": tasks[task_id]["task_type"],
                "intent": result.plan.intent.value if getattr(result, "plan", None) else None,
                "interpretation": list(result.interpretation),
                "docs_passed": passed,
                "docs_selected": n_selected,
                "scope_narrowed": n_selected is not None and n_selected < passed,
                "trace": trace,
                "state": result.state.value if hasattr(result.state, "value") else str(result.state),
                "values": values,
            }
        )
        print(task_id, rows[-1]["replay_matches_log"], [v["lost_at"] for v in values])
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
