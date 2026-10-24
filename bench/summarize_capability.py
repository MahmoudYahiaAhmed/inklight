"""Tables from capability_diag.py output. One row per (language, document type, modality); never averaged
across languages, types or tasks. Counts are shown as k/n because n is tiny.

    python -I bench/summarize_capability.py <capability-diag.json> [<more runs to compare>...]
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capability_diag import answer_head, contains  # noqa: E402


def frac(k: int, n: int) -> str:
    return f"{k}/{n}" if n else "–"


def group_rows(run: dict) -> dict[tuple[str, str, str], list[dict]]:
    groups: dict[tuple[str, str, str], list[dict]] = collections.defaultdict(list)
    for doc_id, d in run["documents"].items():
        groups[(d["lang"], d["type"], d["modality"])].append({"id": doc_id, **d})
    return dict(sorted(groups.items()))


def rescore(run: dict, corpus: dict) -> None:
    """Score QA on the answer line only (older runs also counted the evidence quote)."""
    accepts = {d["id"]: {q["q"]: q["accept"] for q in d["qa"]} for d in corpus["documents"]}
    for doc_id, d in run["documents"].items():
        for q in d.get("qa", []):
            q["correct"] = contains(answer_head(q["answer"]), accepts[doc_id][q["q"]])
            q["correct_with_source"] = q["correct"] and q["correct_with_source"]


def cell(docs: list[dict]) -> dict[str, str]:
    ok = [d for d in docs if "ingest" in d]
    qa = [q for d in ok for q in d["qa"]]
    search = [s for d in ok for s in d["search"]]
    fields = [f for d in ok for f in d["fields"]]
    recalls = [d["ocr"]["word_recall"] for d in ok if d["ocr"].get("word_recall") is not None]
    keys = [d["ocr"]["key_recall"] for d in ok]
    return {
        "docs": str(len(docs)),
        "ingested": frac(len(ok), len(docs)),
        "type ok": frac(sum(d["ingest"]["type_correct"] for d in ok), len(ok)),
        "key strings": f"{sum(keys) / len(keys):.2f}" if keys else "–",
        "word recall": f"{sum(recalls) / len(recalls):.2f}" if recalls else "–",
        "search @1": frac(sum(s["rank"] == 1 for s in search), len(search)),
        "search @3": frac(sum(bool(s["rank"]) and s["rank"] <= 3 for s in search), len(search)),
        "QA": frac(sum(q["correct"] for q in qa), len(qa)),
        "QA + source": frac(sum(q["correct_with_source"] for q in qa), len(qa)),
        "summary in language": frac(sum(d["summary"]["language_matches"] for d in ok), len(ok)),
        "summary intent": frac(sum(d["summary"]["intent"].endswith("summarize") for d in ok), len(ok)),
        "fields": frac(sum(f["correct"] for f in fields), len(fields)),
        "review opened": frac(sum(d["review"]["opened"] for d in ok), len(ok)),
    }


def table(run: dict) -> str:
    groups = group_rows(run)
    cols = list(cell(next(iter(groups.values()))).keys())
    lines = ["| lang | type | modality | " + " | ".join(cols) + " |", "|" + "---|" * (len(cols) + 3)]
    for (lang, typ, mod), docs in groups.items():
        c = cell(docs)
        lines.append(f"| {lang} | {typ} | {mod} | " + " | ".join(c[k] for k in cols) + " |")
    return "\n".join(lines)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    corpus = json.loads((Path(__file__).resolve().parent / "capability_corpus.json").read_text(encoding="utf-8"))
    for path in sys.argv[1:]:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for run in data["runs"].values():
            rescore(run, corpus)
        print(f"# {path}\n\n{data['label']}; {data['provenance']['inklight_file']}\n")
        for mode, run in data["runs"].items():
            print(f"## OCR mode `{mode}`: ingest {run['ingest_seconds']} s, failed {len(run['ingest_failed'])}\n")
            print(table(run))
            print(f"\nexport: {json.dumps(run['export'], ensure_ascii=False)}")
            print(f"brain usage: {json.dumps(run['brain_usage'])}")
            print(f"ONNX calls: {json.dumps(run['onnx_calls'])}\n")


if __name__ == "__main__":
    main()
