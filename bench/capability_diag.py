"""Capability diagnostic: OCR, search, QA with sources, summaries, custom fields, review and export, across
English, Arabic and mixed documents, digital and scanned.

THIS IS A SMALL AUTOMATED DIAGNOSTIC, NOT A BENCHMARK. Each cell has 1-6 documents. Questions and accepted
answers come from dataset annotations or were written by an AI from the original files (see the corpus).

    python -I bench/capability_diag.py --corpus bench/capability_corpus.json --docs <folder with the files>
        --models <frozen models dir> --out <results dir> [--mode auto|ocr ...]

Run it with the interpreter of the build under test. Every run uses a fresh library, the original files, the
real OCR engine and the local models (brain = auto, no download). ONNX Runtime calls are counted
independently of Inklight's own counters. Scores are kept separate by language, document type, modality and
task, and never averaged across them.
"""

from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

ORT_CALLS: collections.Counter = collections.Counter()
ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
SUMMARY_REQUEST = {"ar": "لخص هذه الوثيقة", "en": "Summarize this document", "mixed": "Summarize this document"}


def instrument_onnxruntime() -> None:
    import onnxruntime as ort

    original_init, original_run = ort.InferenceSession.__init__, ort.InferenceSession.run

    def init(self, path_or_bytes, *args, **kwargs):  # type: ignore[no-untyped-def]
        p = Path(str(path_or_bytes))
        self._diag_name = f"{p.parent.name}/{p.name}"
        return original_init(self, path_or_bytes, *args, **kwargs)

    def run(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        ORT_CALLS[getattr(self, "_diag_name", "unknown")] += 1
        return original_run(self, *args, **kwargs)

    ort.InferenceSession.__init__ = init
    ort.InferenceSession.run = run


def norm(text: object) -> str:
    """Scoring normalisation: NFKC, casefold, Unicode digits to ASCII, Arabic letter variants unified, and
    harakat, tatweel and punctuation removed. Applied identically to answers and accepted strings."""
    s = unicodedata.normalize("NFKC", str(text)).casefold()
    out = []
    for ch in s:
        if ch.isdigit():
            out.append(str(unicodedata.digit(ch, 0)))
        elif ch in "أإآٱ":
            out.append("ا")
        elif ch == "ى":
            out.append("ي")
        elif ch == "ة":
            out.append("ه")
        elif ch == "ـ" or unicodedata.category(ch) == "Mn":
            continue
        elif ch.isalnum():
            out.append(ch)
        else:
            out.append(" ")
    return " ".join("".join(out).split())


def contains(haystack: object, accepts: list[str]) -> bool:
    h = f" {norm(haystack)} "
    return any(f" {norm(a)} " in h or (len(norm(a)) > 6 and norm(a) in h) for a in accepts)


# Arabic particles written attached to the next word: conjunctions, prepositions and the article, in norm() form.
_PARTICLES = ("وال", "بال", "فال", "كال", "لل", "ال", "و", "ف", "ب", "ل", "ك")


def _forms(token: str, depth: int = 2) -> set[str]:
    """A token and what is left when up to two attached Arabic particles are removed ("وبالامين" -> "امين"),
    keeping at least three letters. Latin and digit tokens are only themselves."""
    out = {token}
    if depth and token[:1] and "؀" <= token[0] <= "ۿ":
        for p in _PARTICLES:
            if token.startswith(p) and len(token) - len(p) >= 3:
                out |= _forms(token[len(p) :], depth - 1)
    return out


def contains_entity(haystack: object, accepts: list[str]) -> bool:
    """Like contains(), but an Arabic word may carry attached particles: "لتركيا" names "تركيا". Every letter of
    the word itself must still match, so an OCR misreading is not forgiven. Used beside contains(), never
    instead of it: the two scores answer different questions (entity identity, exact transcription)."""
    if contains(haystack, accepts):
        return True
    words = norm(haystack).split()
    forms = [_forms(w) for w in words]
    for accept in accepts:
        want = [{w} for w in norm(accept).split()]  # particles come off the answer's words, not the key's
        if not want:
            continue
        for i in range(len(words) - len(want) + 1):
            if all(forms[i + k] & want[k] for k in range(len(want))):
                return True
    return False


def answer_head(answer: str) -> str:
    """The answer itself, without the quoted evidence or a PARTIAL banner's interpretation lines: a correct
    string that appears only inside the evidence quote does not make a wrong answer right."""
    return answer.split("Evidence:")[0].split("Understood as:")[0]


def words(text: str) -> list[str]:
    return norm(text).split()


def word_recall(reference: str, text: str) -> float | None:
    ref = collections.Counter(words(reference))
    if not ref:
        return None
    got = collections.Counter(words(text))
    return round(sum(min(n, got[w]) for w, n in ref.items()) / sum(ref.values()), 3)


def arabic_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return round(sum(bool(ARABIC.match(c)) for c in letters) / len(letters), 3) if letters else 0.0


def text_layer(path: Path) -> str:
    import pypdfium2

    pdf = pypdfium2.PdfDocument(str(path))
    try:
        return "\n".join(pdf[i].get_textpage().get_text_range() for i in range(len(pdf)))
    finally:
        pdf.close()


def settings_for(mode: str, models: Path, home: Path):  # type: ignore[no-untyped-def]
    from inklight.config import ExtractionSettings, ModelSettings, OCRSettings, Settings

    return Settings(
        home=home,
        ocr=OCRSettings(mode=mode, model_dir=str(models / "indra")),
        models=ModelSettings(brain="auto", model_dir=str(models / "small"), allow_download=False),
        extraction=ExtractionSettings(),
    )


# ---------------------------------------------------------------- tasks


def ocr_task(doc: dict, text: str, docs_dir: Path, mode: str) -> dict:
    out: dict[str, Any] = {"chars": len(text), "arabic_share": arabic_share(text)}
    out["key_recall"] = round(sum(contains(text, [k]) for k in doc["keys"]) / len(doc["keys"]), 3)
    ref_name = doc.get("ocr_ref")
    if ref_name:
        out["word_recall"] = word_recall((docs_dir / ref_name).read_text(encoding="utf-8"), text)
        out["reference"] = "dataset transcription"
    elif doc["modality"] == "digital" and doc["lang"] == "en" and mode == "ocr":
        out["word_recall"] = word_recall(text_layer(docs_dir / doc["file"]), text)
        out["reference"] = "the PDF's own text layer"
    return out


def search_task(agent, doc: dict, doc_id: str) -> list[dict]:  # type: ignore[no-untyped-def]
    rows = []
    for q in doc["search"]:
        hits = agent.search(q, k=10)
        ranked = list(dict.fromkeys(h.source.doc_id for h in hits))
        rank = ranked.index(doc_id) + 1 if doc_id in ranked else None
        rows.append({"q": q, "rank": rank, "methods": sorted({h.method for h in hits}), "hits": len(hits)})
    return rows


def qa_task(agent, doc: dict, doc_id: str) -> list[dict]:  # type: ignore[no-untyped-def]
    rows = []
    for item in doc["qa"]:
        res = agent.ask(item["q"], doc_ids=[doc_id], save=False)
        correct = contains(answer_head(res.answer), item["accept"])
        sourced = correct and any(contains(s.excerpt, item["accept"]) for s in res.sources)
        rows.append(
            {
                "q": item["q"],
                "answer": res.answer[:300],
                "state": str(res.state.value),
                "intent": str(res.intent),
                "correct": correct,
                "correct_with_source": sourced,
                "sources": len(res.sources),
                "brain": res.brain,
            }
        )
    return rows


def summary_task(agent, doc: dict, doc_id: str, text: str) -> dict:  # type: ignore[no-untyped-def]
    res = agent.ask(SUMMARY_REQUEST[doc["lang"]], doc_ids=[doc_id], save=False)
    answer_words = words(res.answer)
    doc_words = set(words(text))
    return {
        "request": SUMMARY_REQUEST[doc["lang"]],
        "state": str(res.state.value),
        "intent": str(res.intent),
        "chars": len(res.answer),
        "arabic_share": arabic_share(res.answer),
        "language_matches": (arabic_share(res.answer) > 0.5) == (doc["lang"] == "ar") if res.answer else False,
        "from_document": round(sum(w in doc_words for w in answer_words) / len(answer_words), 3)
        if answer_words
        else 0.0,
        "mentions_a_key": contains(res.answer, doc["keys"]),
        "answer": res.answer[:400],
    }


def schema_for(doc: dict) -> dict:
    fields = []
    for f in doc["fields"]:
        spec = {"name": f["name"], "type": f.get("type", "id" if f["name"].endswith("number") else "text")}
        if f.get("labels"):
            spec["labels"] = f["labels"]
        fields.append(spec)
    return {"fields": fields}


def field_correct(spec: dict, value: Any) -> bool:
    if value is None:
        return False
    if spec.get("type") == "money":
        try:
            return any(abs(float(value) - float(a)) < 0.005 for a in spec["accept"])
        except (TypeError, ValueError):
            return False
    if spec.get("type") == "date":
        return str(value)[:10] in spec["accept"]
    return contains(value, spec["accept"])


def fields_task(agent, doc: dict, path: Path) -> list[dict]:  # type: ignore[no-untyped-def]
    record = agent.extract([path], schema=schema_for(doc))[0]
    rows = []
    for spec in doc["fields"]:
        v = record.fields.get(spec["name"])
        value = v.value if v else None
        rows.append(
            {
                "field": spec["name"],
                "labels": bool(spec.get("labels")),
                "value": None if value is None else str(value),
                "correct": field_correct(spec, value),
                "flagged": bool(v and (v.warning or v.confidence < 0.7)),
            }
        )
    return rows


def review_task(agent, doc: dict, doc_id: str) -> dict:  # type: ignore[no-untyped-def]
    names = [f["name"] for f in doc["fields"]]
    try:
        review = agent.open_review(doc_id, names, reviewer="capability-diag-script")
        for f in review.fields:
            action = "accepted" if f.predicted is not None else "absent"
            agent.reviews.decide(review.id, f.field, reviewer="capability-diag-script", action=action)
        agent.reviews.approve(review.id, reviewer="capability-diag-script")
        return {"opened": True, "fields_in_review": [f.field for f in review.fields], "error": None}
    except Exception as exc:  # noqa: BLE001 - the diagnostic records any failure
        return {"opened": False, "fields_in_review": [], "error": f"{type(exc).__name__}: {exc}"}


def export_check(agent, expected: dict[str, list[str]]) -> dict:  # type: ignore[no-untyped-def]
    content = agent.reviews.export("csv", actor="capability-diag-script")
    text = content.decode("utf-8") if isinstance(content, bytes) else content
    rows = list(csv.DictReader(io.StringIO(text)))
    got = collections.defaultdict(set)
    for r in rows:
        got[r["document"]].add(r["field"])
    return {
        "rows": len(rows),
        "columns": list(rows[0]) if rows else [],
        "all_custom_fields_exported": all(set(v) <= got.get(k, set()) for k, v in expected.items()),
        "arabic_values_exported": any(ARABIC.search(r.get("final") or "") for r in rows),
    }


# ---------------------------------------------------------------- run


def run_mode(corpus: dict, docs_dir: Path, models: Path, out: Path, mode: str) -> dict:
    from inklight import DocumentAgent

    home = out / f"home-{mode}"
    if home.exists():
        sys.exit(f"{home} exists: use a fresh --out")
    ORT_CALLS.clear()
    results: dict[str, Any] = {"mode": mode, "documents": {}}
    with DocumentAgent(settings_for(mode, models, home)) as agent:
        files = [docs_dir / d["file"] for d in corpus["documents"]]
        t0 = time.perf_counter()
        report = agent.add(files)
        results["ingest_seconds"] = round(time.perf_counter() - t0, 1)
        results["ingest_failed"] = [[str(p), str(e)] for p, e in report.failed]
        by_name = {Path(d.path).name: d for d in report.documents}
        expected_review: dict[str, list[str]] = {}
        for doc in corpus["documents"]:
            info = by_name.get(doc["file"])
            row: dict[str, Any] = {k: doc[k] for k in ("lang", "modality", "type")}
            if info is None:
                row["error"] = "not ingested"
                results["documents"][doc["id"]] = row
                continue
            text = agent.library.text(info.id)
            row["ingest"] = {
                "engine": info.engine,
                "pages": info.pages,
                "mean_conf": info.mean_conf,
                "doc_type": info.doc_type,
                "type_correct": info.doc_type == doc["type"],
            }
            row["ocr"] = ocr_task(doc, text, docs_dir, mode)
            row["search"] = search_task(agent, doc, info.id)
            row["qa"] = qa_task(agent, doc, info.id)
            row["summary"] = summary_task(agent, doc, info.id, text)
            row["fields"] = fields_task(agent, doc, docs_dir / doc["file"])
            row["review"] = review_task(agent, doc, info.id)
            if row["review"]["opened"]:
                expected_review[info.name] = row["review"]["fields_in_review"]
            results["documents"][doc["id"]] = row
            print(f"[{mode}] {doc['id']}: done", flush=True)
        results["export"] = export_check(agent, expected_review)
        results["brain_usage"] = agent.library.brain.usage()
    results["onnx_calls"] = dict(ORT_CALLS)
    return results


def provenance() -> dict:
    import inklight

    return {"inklight_version": inklight.__version__, "inklight_file": inklight.__file__, "python": sys.version}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--docs", type=Path, required=True)
    ap.add_argument("--models", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--mode", action="append", choices=["auto", "ocr"])
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    args.out.mkdir(parents=True, exist_ok=True)
    instrument_onnxruntime()
    runs = {m: run_mode(corpus, args.docs, args.models, args.out, m) for m in (args.mode or ["auto", "ocr"])}
    result = {
        "label": "AUTOMATED DIAGNOSTIC, not a benchmark",
        "provenance": provenance(),
        "runs": runs,
        "gaps": corpus["gaps"],
    }
    (args.out / "capability-diag.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {args.out / 'capability-diag.json'}")


if __name__ == "__main__":
    main()
