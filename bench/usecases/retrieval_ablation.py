"""Keyword-only versus hybrid retrieval on the same library: where does the right document rank?

    python -I bench/usecases/retrieval_ablation.py --library <home of an evaluate.py run with brain auto>
        --models <models dir> [--corpus bench/usecases/corpus.json]

For every corpus question, the library-wide search (no document scope) is run twice on a COPY of the
library: keyword only (BM25), and hybrid (BM25 fused with the embedder). Ranks are of the first passage from
the document the question is about. The embedder's calls are counted from ONNX Runtime.
"""

from __future__ import annotations

import argparse
import collections
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate import ORT, instrument, settings  # noqa: E402


def rank(hits, doc_id: str) -> int | None:  # type: ignore[no-untyped-def]
    docs = list(dict.fromkeys(h.source.doc_id for h in hits))
    return docs.index(doc_id) + 1 if doc_id in docs else None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", type=Path, required=True)
    ap.add_argument("--models", type=Path, required=True)
    ap.add_argument("--corpus", type=Path, default=Path(__file__).with_name("corpus.json"))
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    instrument()
    from inklight import DocumentAgent

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        shutil.copytree(args.library, home)
        rows = []
        with DocumentAgent(settings(home, args.models, "auto", "auto")) as agent:
            by_name = {d.name: d.id for d in agent.library.documents()}
            for doc in corpus["documents"]:
                doc_id = by_name.get(doc["file"])
                if doc_id is None:
                    continue
                for item in doc["qa"]:
                    kw = [s for _, s in agent.library.store.keyword_search(item["q"], None, 30)]
                    kw_docs = list(dict.fromkeys(s.doc_id for s in kw))
                    hy = agent.library.search(item["q"], None, k=10)
                    rows.append(
                        {
                            "doc": doc["id"],
                            "lang": doc["lang"],
                            "q": item["q"],
                            "keyword": kw_docs.index(doc_id) + 1 if doc_id in kw_docs else None,
                            "hybrid": rank(hy, doc_id),
                            "method": hy[0].method if hy else None,
                        }
                    )
            usage = agent.library.brain.usage()
    summary = {}
    for lang in ("en", "ar", "mixed"):
        rs = [r for r in rows if r["lang"] == lang]
        if not rs:
            continue
        summary[lang] = {
            "questions": len(rs),
            "keyword_at1": sum(r["keyword"] == 1 for r in rs),
            "hybrid_at1": sum(r["hybrid"] == 1 for r in rs),
            "keyword_at3": sum(bool(r["keyword"]) and r["keyword"] <= 3 for r in rs),
            "hybrid_at3": sum(bool(r["hybrid"]) and r["hybrid"] <= 3 for r in rs),
            "hybrid_better": sum((r["hybrid"] or 99) < (r["keyword"] or 99) for r in rs),
            "hybrid_worse": sum((r["hybrid"] or 99) > (r["keyword"] or 99) for r in rs),
        }
    result = {
        "summary": summary,
        "rows": rows,
        "onnx": dict(ORT),
        "brain_usage": usage,
        "documents_in_library": len(by_name),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("onnx", dict(ORT))
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    collections  # noqa: B018 - imported for readers extending the script
    main()
