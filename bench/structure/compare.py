"""Controlled comparison: Inklight without (A) and with (B) Docling's structure, on the same Indra OCR.

    python bench/structure/compare.py --docs DIR --models MODELS --out OUT.json [--brain rules]

1. Each document is read once by Indra (Inklight's engine) and that DocumentContent is kept.
2. A and B each run in a fresh process and library, ingesting the kept content through a replay engine, so the
   OCR is identical and every difference comes from structure. Peak memory is the process's own.
3. Every question of bench/structure/cases.json is asked; each answer is scored:
   correct / correct_flagged / declined (an answerable question declined) / wrong_flagged / silent_wrong, and for
   questions about something not printed: declined / flagged / silent. Also recorded: whether Indra's text holds
   the expected value at all ("ocr_has_answer", so OCR errors are not counted against structure), whether a cited
   source holds the answer ("citation_holds_answer"), the latency, and for B the export completeness (every OCR
   line found in Docling's Markdown export) and the structure meta (components, cells handed over, foreign tokens).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# A0 runs an older checkout's source (--baseline-src); A and B run this one.
sys.path.insert(0, os.environ.get("STRUCTURE_COMPARE_SRC") or str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "bench"))

from textnorm import fold  # noqa: E402  (the bench's frozen copy)

NOT_FOUND = re.compile(
    r"^(I couldn't find|I could not find|The documents do not|No passage|None of the)", re.IGNORECASE
)


def ocr_once(docs: Path, models: Path, cache: Path, files: list[str]) -> None:
    from inklight.config import OCRSettings
    from inklight.ocr.indra import IndraEngine

    engine = IndraEngine(OCRSettings(model_dir=str(models / "indra")))
    cache.mkdir(parents=True, exist_ok=True)
    for name in files:
        out = cache / f"{name}.json"
        if out.exists():
            continue
        started = time.perf_counter()
        content = engine.read(docs / name, max_pages=50)
        out.write_text(content.model_dump_json(), encoding="utf-8")
        print(f"OCR {name}: {time.perf_counter() - started:.1f}s", flush=True)


class ReplayEngine:
    """Hands the library the DocumentContent Indra produced earlier for the same file."""

    name = "indra"

    def __init__(self, cache: Path) -> None:
        self.cache = cache

    def supports(self, kind: str) -> bool:
        return True

    def read(self, path: Path, *, max_pages: int, password: str | None = None):  # noqa: ANN201, ARG002
        from inklight.schemas import DocumentContent

        return DocumentContent.model_validate_json((self.cache / f"{path.name}.json").read_text(encoding="utf-8"))


def peak_mb() -> float | None:
    try:
        import psutil

        info = psutil.Process().memory_info()
        peak = getattr(info, "peak_wset", None) or getattr(info, "peak_rss", None)
        if peak is None:
            import resource

            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        return peak / 2**20
    except ImportError:
        return None


def run_mode(mode: str, docs: Path, cache: Path, home: Path, cases: dict, brain: str, models: Path) -> dict:
    import inklight.config as config
    from inklight import DocumentAgent
    from inklight.config import ModelSettings, OCRSettings, Settings
    from inklight.library import Library

    StructureSettings = getattr(config, "StructureSettings", None)  # noqa: N806 (absent before structure support)

    extra = {"structure": StructureSettings(engine="docling" if mode == "B" else "none")} if StructureSettings else {}
    settings = Settings(
        home=home,
        ocr=OCRSettings(model_dir=str(models / "indra")),
        models=ModelSettings(brain=brain, model_dir=str(models / "small"), allow_download=False),
        **extra,
    )
    lib = Library(settings, engine=ReplayEngine(cache))
    rows: list[dict] = []
    ingest: dict[str, dict] = {}
    with DocumentAgent(settings, library=lib) as agent:
        for entry in cases["documents"]:
            for name in entry["files"]:
                started = time.perf_counter()
                report = agent.add([docs / name])
                info = agent.library.documents()
                doc = next(d for d in info if d.name == name)
                stored = agent.library.structure(doc.id) if hasattr(agent.library, "structure") else None
                pages = agent.library.pages(doc.id)
                ingest[name] = {
                    "seconds": round(time.perf_counter() - started, 2),
                    "doc_type": doc.doc_type,
                    "failed": report.failed,
                    "warnings": report.warnings,
                    "structure_meta": stored[0] if stored else None,
                    "export": _export_check(pages, stored[1]) if stored and stored[1] is not None else None,
                }
                ocr_text = fold(" ".join(ln.text for p in pages for ln in p.lines))
                for kind, items in (("answerable", entry["qa"]), ("missing", entry.get("missing", []))):
                    for item in items:
                        rows.append(_ask(agent, doc.id, name, entry["lang"], kind, item, ocr_text))
    lib.close()
    return {"mode": mode, "rows": rows, "ingest": ingest, "peak_mb": peak_mb()}


def _ask(agent, doc_id: str, name: str, lang: str, kind: str, item: dict, ocr_text: str) -> dict:  # noqa: ANN001
    started = time.perf_counter()
    res = agent.ask(item["q"], doc_ids=[doc_id], save=False)
    seconds = time.perf_counter() - started
    head = res.answer.split("\n\nEvidence:")[0]
    declined = bool(NOT_FOUND.search(res.answer.strip()))
    flagged = any(w.startswith("Low confidence") for w in res.warnings) or res.confidence < 0.3
    accept = item.get("accept", [])
    ok = any(fold(a) and fold(a) in fold(head) for a in accept)
    if kind == "answerable":
        outcome = "declined" if declined else ("correct" if ok else "wrong") + ("_flagged" if flagged else "")
        outcome = {"wrong": "silent_wrong"}.get(outcome, outcome)
    else:
        outcome = "declined" if declined else ("flagged" if flagged else "silent")
    return {
        "doc": name,
        "lang": lang,
        "kind": kind,
        "category": item.get("category"),
        "q": item["q"],
        "outcome": outcome,
        "answer": res.answer,
        "warnings": list(res.warnings),
        "confidence": res.confidence,
        "sources": [{"page": s.page, "bbox": s.bbox, "excerpt": s.excerpt[:200]} for s in res.sources[:3]],
        "citation_holds_answer": any(fold(a) in fold(s.excerpt) for a in accept for s in res.sources) if ok else None,
        "ocr_has_answer": any(fold(a) in ocr_text for a in accept) if accept else None,
        "path": [t.summary for t in res.trace][-1:] or [""],
        "seconds": round(seconds, 3),
    }


def _export_check(pages: list, document) -> dict:  # noqa: ANN001
    """Docling's own exports of the structure: does every OCR line appear in them?"""
    markdown = document.export_to_markdown(traverse_pictures=True)
    squashed = "".join(markdown.split())
    lines = [ln.text for p in pages for ln in p.lines if ln.text.strip()]
    missing = [t for t in lines if "".join(t.split()) not in squashed]
    data = json.dumps(document.export_to_dict(), ensure_ascii=False)
    return {
        "markdown_chars": len(markdown),
        "json_chars": len(data),
        "ocr_lines": len(lines),
        "ocr_lines_missing_from_markdown": missing,
        "tables": len(document.tables),
        "pictures": len(document.pictures),
    }


def summarize(results: list[dict]) -> dict:
    out = {}
    for res in results:
        counts: dict[str, dict[str, int]] = {}
        for row in res["rows"]:
            key = f"{row['lang']} {row['kind']}"
            counts.setdefault(key, {})
            counts[key][row["outcome"]] = counts[key].get(row["outcome"], 0) + 1
        cited = [r["citation_holds_answer"] for r in res["rows"] if r["citation_holds_answer"] is not None]
        out[res["mode"]] = {
            "outcomes": counts,
            "citation_holds_answer": f"{sum(cited)}/{len(cited)}",
            "median_question_s": sorted(r["seconds"] for r in res["rows"])[len(res["rows"]) // 2],
            "ingest_s": round(sum(v["seconds"] for v in res["ingest"].values()), 1),
            "peak_mb": res["peak_mb"],
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", type=Path, required=True)
    ap.add_argument("--models", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cases", type=Path, default=Path(__file__).with_name("cases.json"))
    ap.add_argument("--brain", default="rules")
    ap.add_argument("--baseline-src", type=Path, help="src/ of an unchanged checkout, run as A0")
    ap.add_argument("--mode", choices=["A0", "A", "B"], help=argparse.SUPPRESS)  # one side, in its own process
    ap.add_argument("--work", type=Path, help=argparse.SUPPRESS)
    args = ap.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    files = [f for entry in cases["documents"] for f in entry["files"]]
    work = args.work or args.out.with_suffix(".work")
    cache = work / "ocr"
    if args.mode:
        result = run_mode(args.mode, args.docs, cache, work / f"home-{args.mode}", cases, args.brain, args.models)
        (work / f"{args.mode}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        return
    ocr_once(args.docs, args.models, cache, files)
    results = []
    for mode in ("A0", "A", "B") if args.baseline_src else ("A", "B"):
        home = work / f"home-{mode}"
        if home.exists():
            import shutil

            shutil.rmtree(home)
        cmd = [sys.executable, __file__, *sys.argv[1:], "--mode", mode, "--work", str(work)]
        started = time.perf_counter()
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        if mode == "A0":
            env["STRUCTURE_COMPARE_SRC"] = str(args.baseline_src)
        subprocess.run(cmd, check=True, env=env)  # noqa: S603
        result = json.loads((work / f"{mode}.json").read_text(encoding="utf-8"))
        result["wall_s"] = round(time.perf_counter() - started, 1)
        results.append(result)
    from inklight.config import StructureSettings
    from inklight.structure.docling_run import components

    report = {
        "label": "STRUCTURE COMPARISON (synthetic documents, fixed Indra OCR)",
        "modes": {
            "A0": f"unchanged Inklight from {args.baseline_src}" if args.baseline_src else None,
            "A": "this build, structure off",
            "B": "this build, Docling structure on Indra's lines",
        },
        "brain": args.brain,
        "python": platform.python_version(),
        "components": components(StructureSettings(engine="docling")),
        "summary": summarize(results),
        "results": results,
    }
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
