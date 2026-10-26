"""Ingest the evaluation documents into one arm's library with the installed package, and time it.

    EVAL_PYTHON bench/agent_eval/ingest.py ARM_CONFIG DOCS_DIR OUT.json

Runs in a fresh process (models not in memory: "cold", with weights read from the local disk cache), adds every
document, then adds them all again with force=True in the same process ("warm": models already loaded). Records wall
time per document and in total, peak process memory, OCR time per page, and what the structure step recorded
(cells handed to Docling, foreign tokens, model load seconds). Nothing is downloaded: weights must already be cached.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import psutil

from inklight import DocumentAgent
from inklight.config import load_settings


def peak_mb() -> float:
    info = psutil.Process().memory_info()
    return round((getattr(info, "peak_wset", None) or info.rss) / 2**20, 1)


def run(agent: DocumentAgent, files: list[Path], force: bool) -> dict:
    per_doc = {}
    started = time.perf_counter()
    for f in files:
        t = time.perf_counter()
        report = agent.library.add([f], force=force)
        per_doc[f.name] = {"seconds": round(time.perf_counter() - t, 2), "failed": report.failed}
    return {"seconds": round(time.perf_counter() - started, 2), "documents": per_doc}


def main() -> None:
    config, docs, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    files = sorted(p for p in docs.iterdir() if p.is_file())
    settings = load_settings(config)
    with DocumentAgent(settings) as agent:
        cold = run(agent, files, force=False)
        cold["peak_mb"] = peak_mb()
        warm = run(agent, files, force=True)
        warm["peak_mb"] = peak_mb()
        details = {}
        for doc in agent.library.documents():
            pages = agent.library.pages(doc.id)
            stored = agent.library.structure(doc.id)
            details[doc.name] = {
                "pages": doc.pages,
                "doc_type": doc.doc_type,
                "status": doc.status.value,
                "page_sources": [p.source for p in pages],
                "ocr_ms": [p.ocr_ms for p in pages],
                "mean_conf": doc.mean_conf,
                "structure": stored[0] if stored else None,
            }
        status = agent.library.brain.usage() if hasattr(agent.library.brain, "usage") else {}
    out.write_text(
        json.dumps({"config": str(config), "cold": cold, "warm": warm, "documents": details, "brain": status},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(json.dumps({"cold_s": cold["seconds"], "warm_s": warm["seconds"], "peak_mb": warm["peak_mb"]}))


if __name__ == "__main__":
    main()
