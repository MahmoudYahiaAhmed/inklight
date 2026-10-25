"""Use-case evaluation: full pipeline on original files, scored against expectations fixed in corpus.json.

    python -I bench/usecases/evaluate.py --split dev --docs <files> --models <models dir> --out <dir>
        [--brain rules|auto] [--ocr-mode auto|ocr] [--save-hits hits.json | --replay-hits hits.json]

* The split is selected BEFORE anything is read. ``--split reserved`` appends a line to
  ``<out>/../reserved-access.log`` (build, arguments, time) before the first reserved file is opened.
* Every run uses a fresh, empty library and the build that runs this script. Nothing is cached between builds.
* ``--save-hits`` records the passages every search returned; ``--replay-hits`` makes every search return
  exactly those passages (matched by document name and page), so two brains can be compared on the same
  evidence. ONNX Runtime calls are counted independently of Inklight's own counters.
* Outcomes are never dropped: every attempted case is kept with its outcome.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from capability_diag import answer_head, arabic_share, contains, norm  # noqa: E402

ORT: collections.Counter = collections.Counter()
NOT_FOUND = re.compile(
    r"could not find|no (?:relevant |matching )?(?:evidence|passage|document|value)"
    r"|not (?:found|available|stated|mentioned)"
    r"|لم (?:أجد|يتم|يرد|يذكر)|غير (?:موجود|متوفر|مذكور)",
    re.IGNORECASE,
)
SUMMARY_REQUEST = {"ar": "لخص هذه الوثيقة", "en": "Summarize this document", "mixed": "Summarize this document"}


def instrument() -> None:
    import onnxruntime as ort

    init0, run0 = ort.InferenceSession.__init__, ort.InferenceSession.run

    def init(self, path_or_bytes, *a, **k):  # type: ignore[no-untyped-def]
        p = Path(str(path_or_bytes))
        low = str(p).lower()
        self._role = (
            "reader"
            if "squad" in low or "distilbert" in low
            else "embedder"
            if "bge" in low or "e5" in low or "minilm" in low
            else "writer"
            if "smollm" in low
            else "ocr"
        )
        return init0(self, path_or_bytes, *a, **k)

    def run(self, *a, **k):  # type: ignore[no-untyped-def]
        ORT[getattr(self, "_role", "unknown")] += 1
        return run0(self, *a, **k)

    ort.InferenceSession.__init__, ort.InferenceSession.run = init, run


def delta(before: collections.Counter) -> dict[str, int]:
    return {k: v - before.get(k, 0) for k, v in ORT.items() if v - before.get(k, 0)}


def settings(home: Path, models: Path, brain: str, ocr_mode: str):  # type: ignore[no-untyped-def]
    from inklight.config import ModelSettings, OCRSettings, Settings

    return Settings(
        home=home,
        ocr=OCRSettings(mode=ocr_mode, model_dir=str(models / "indra")),
        models=ModelSettings(brain=brain, model_dir=str(models / "small"), allow_download=False),
    )


# ---------------------------------------------------------------- fixed evidence


class HitRecorder:
    """Wraps Library.search: record, or replay recorded hits so two brains see identical passages."""

    def __init__(self, library, mode: str | None, path: Path | None) -> None:  # type: ignore[no-untyped-def]
        self.library, self.mode, self.path = library, mode, path
        self.store: dict[str, list[dict]] = json.loads(path.read_text(encoding="utf-8")) if mode == "replay" else {}
        self.original = library.search
        self.misses = 0
        if mode:
            library.search = self.search

    def _key(self, query: str, doc_ids, k: int) -> str:  # type: ignore[no-untyped-def]
        names = sorted(self.library.get(i).name for i in (doc_ids or []) if self.library.get(i))
        return json.dumps([query, names, k], ensure_ascii=False)

    def search(self, query: str, doc_ids=None, k: int = 8):  # type: ignore[no-untyped-def]
        from inklight.schemas import SearchHit

        key = self._key(query, doc_ids, k)
        if self.mode == "replay":
            if key not in self.store:
                self.misses += 1
                return self.original(query, doc_ids, k)
            by_name = {d.name: d for d in self.library.documents()}
            hits = []
            for h in self.store[key]:
                doc = by_name.get(h["source"]["name"])
                if doc is None:
                    continue
                h = json.loads(json.dumps(h))
                h["source"].update(doc_id=doc.id, path=doc.path)
                hits.append(SearchHit.model_validate(h))
            return hits
        hits = self.original(query, doc_ids, k)
        self.store[key] = [h.model_dump(mode="json") for h in hits]
        return hits

    def save(self) -> None:
        if self.mode == "save" and self.path:
            self.path.write_text(json.dumps(self.store, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- per-document tasks


def outcome(correct: bool, flagged: bool, state: str) -> str:
    if state in ("unsupported", "failed"):
        return state
    if correct:
        return "correct_flagged" if flagged else "correct"
    return "wrong_flagged" if flagged else "silent_wrong"


def evidence(res) -> list[dict]:  # type: ignore[no-untyped-def]
    """Every cited passage in full, so a run can be rescored or audited without running it again."""
    return [{"doc": s.name, "page": s.page, "excerpt": s.excerpt} for s in res.sources]


def flagged_result(res) -> bool:  # type: ignore[no-untyped-def]
    low = any("Low confidence" in w for w in res.warnings)
    return low or res.confidence < 0.3 or str(res.state.value) == "partial"


def first_stage(accepts: list[str], text: str, intent: str, passages: list[str], answer: str) -> str | None:
    if not any(contains(text, [a]) for a in accepts):
        return "ingestion/OCR"
    if intent not in ("ask",):
        return "request parsing"
    if not any(contains(p, accepts) for p in passages):
        return "retrieval"
    return "answering"


def qa_cases(agent, doc: dict, doc_id: str, text: str) -> list[dict]:  # type: ignore[no-untyped-def]
    rows = []
    for item in doc["qa"]:
        before, t0 = collections.Counter(ORT), time.perf_counter()
        res = agent.ask(item["q"], doc_ids=[doc_id], save=False)
        seconds = round(time.perf_counter() - t0, 2)
        head = answer_head(res.answer)
        correct = contains(head, item["accept"])
        state = str(res.state.value)
        src = res.sources[0] if res.sources else None
        cited = bool(src and contains(src.excerpt, item["accept"]) and (item.get("page") in (None, src.page)))
        passages = [s.excerpt for s in res.sources]
        retrieved = [h.source.excerpt for h in agent.library.search(item["q"], [doc_id], k=8)]
        o = outcome(correct, flagged_result(res), state)
        rows.append(
            {
                "q": item["q"],
                "answer": head.strip(),
                "answer_full": res.answer,
                "evidence": evidence(res),
                "warnings": list(res.warnings),
                "state": state,
                "intent": str(res.intent),
                "outcome": o,
                "cited_passage_supports": cited,
                "cited_page": src.page if src else None,
                "retrieval_has_answer": any(contains(p, item["accept"]) for p in retrieved),
                "first_failing_stage": None
                if correct
                else first_stage(item["accept"], text, str(res.intent), retrieved + passages, head),
                "confidence": res.confidence,
                "brain": res.brain,
                "seconds": seconds,
                "onnx": delta(before),
                "excerpt_preserved": bool(src and src.excerpt.strip() and src.excerpt.strip()[:40] in text),
            }
        )
    return rows


def missing_cases(agent, doc: dict, doc_id: str) -> list[dict]:  # type: ignore[no-untyped-def]
    rows = []
    for item in doc.get("missing", []):
        q, kind = (item, None) if isinstance(item, str) else (item["q"], item.get("kind"))
        res = agent.ask(q, doc_ids=[doc_id], save=False)
        state = str(res.state.value)
        abstained = (
            state in ("partial", "failed", "unsupported") or bool(NOT_FOUND.search(res.answer)) or flagged_result(res)
        )
        rows.append(
            {
                "q": q,
                "kind": kind,
                "answer": answer_head(res.answer).strip(),
                "answer_full": res.answer,
                "evidence": evidence(res),
                "warnings": list(res.warnings),
                "confidence": res.confidence,
                "state": state,
                "declined": state in ("partial", "failed", "unsupported") or bool(NOT_FOUND.search(res.answer)),
                "outcome": "abstained_or_flagged" if abstained else "silent_answer",
            }
        )
    return rows


def summary_case(agent, doc: dict, doc_id: str, text: str) -> dict:  # type: ignore[no-untyped-def]
    before, t0 = collections.Counter(ORT), time.perf_counter()
    res = agent.ask(SUMMARY_REQUEST[doc["lang"]], doc_ids=[doc_id], save=False)
    quoted = [ln.strip(" -•").rsplit(" (", 1)[0] for ln in res.answer.splitlines() if ln.strip().startswith("-")]
    supported = [q for q in quoted if q and norm(q)[:60] in norm(text)]
    return {
        "request": SUMMARY_REQUEST[doc["lang"]],
        "intent": str(res.intent),
        "state": str(res.state.value),
        "key_facts_covered": sum(contains(res.answer, [k]) for k in doc["summary_keys"]),
        "key_facts": len(doc["summary_keys"]),
        "sentences": len(quoted),
        "sentences_found_in_document": len(supported),
        "language_matches": (arabic_share(res.answer) > 0.5) == (doc["lang"] == "ar") if res.answer.strip() else False,
        "seconds": round(time.perf_counter() - t0, 2),
        "onnx": delta(before),
        "answer": res.answer,
        "evidence": evidence(res),
    }


def field_value_ok(spec: dict, value: Any) -> bool:
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


def field_cases(agent, doc: dict, path: Path) -> list[dict]:  # type: ignore[no-untyped-def]
    schema = {"fields": [{k: v for k, v in f.items() if k in ("name", "type", "labels")} for f in doc["fields"]]}
    record = agent.extract([path], schema=schema)[0]
    rows = []
    for spec in doc["fields"]:
        v = record.fields.get(spec["name"])
        value = None if v is None else v.value
        flagged = bool(v and (v.warning or v.confidence < 0.7))
        ok = field_value_ok(spec, value)
        if spec.get("ambiguous") and ok and not (v and v.warning and "ambiguous" in v.warning):
            ok_label = "correct_but_ambiguity_not_flagged"
        else:
            ok_label = None
        o = "missing" if value is None else outcome(ok, flagged, "succeeded")
        rows.append(
            {
                "field": spec["name"],
                "value": None if value is None else str(value),
                "outcome": ok_label or o,
                "warning": v.warning if v else None,
            }
        )
    return rows


def review_case(agent, doc: dict, doc_id: str) -> dict:  # type: ignore[no-untyped-def]
    names = [f["name"] for f in doc["fields"]]
    try:
        r = agent.open_review(doc_id, names, reviewer="usecase-eval-script")
        for f in r.fields:
            agent.reviews.decide(
                r.id,
                f.field,
                reviewer="usecase-eval-script",
                action="accepted" if f.predicted is not None else "absent",
            )
        agent.reviews.approve(r.id, reviewer="usecase-eval-script")
        return {"ok": True, "fields": [f.field for f in r.fields], "review_id": r.id}
    except Exception as exc:  # noqa: BLE001 - recorded as an outcome
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------- library tasks


def library_case(agent, task: dict, ids: dict[str, str], names: dict[str, str], out: Path) -> dict:  # type: ignore[no-untyped-def]
    scope = [ids[d] for d in task.get("scope", []) if d in ids] or None
    t0 = time.perf_counter()
    policy = None
    if task["kind"] == "export":  # writing is off unless the user grants it, as "allow write" does in the UI
        from inklight.agent.context import Policy

        policy = Policy(allow_write=True, output_dir=out / "exports", overwrite=True)
    res = agent.ask(task["request"], doc_ids=scope, save=False, policy=policy)
    state, kind = str(res.state.value), task["kind"]
    row: dict[str, Any] = {
        "id": task["id"],
        "kind": kind,
        "request": task["request"],
        "state": state,
        "intent": str(res.intent),
        "answer": res.answer,
        "evidence": evidence(res),
        "seconds": round(time.perf_counter() - t0, 2),
    }
    by_id = {v: k for k, v in ids.items()}
    if kind == "find":
        first = by_id.get(res.sources[0].doc_id) if res.sources else None
        row["first_source"] = first
        row["correct"] = first in task["expect_docs"]
    elif kind == "compare":
        row["correct"] = all(
            contains(res.answer, [v])
            or any(str(r.fields.get(f).value) == v for r in res.records for f in r.fields if r.fields.get(f))
            for v in task["expect_values"].values()
        )
    elif kind in ("count", "sum"):
        calc = res.calculation or {}
        got = calc.get("result")
        row["calculation"] = calc
        nums = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.?\d*", answer_head(res.answer))]
        target = float(task["expect_number"])
        row["correct"] = (got is not None and abs(float(got) - target) < 0.01) or any(
            abs(n - target) < 0.01 for n in nums[:3]
        )
        row["partial_reported"] = state == "partial"
    elif kind == "filter":
        got = {by_id.get(r.doc_id) for r in res.records}
        row["records"] = sorted(x for x in got if x)
        row["correct"] = got == set(task["expect_docs"])
    elif kind == "export":
        row["files"] = list(res.files_written)
        row.update(check_export(res.files_written, task["expect_rows"], names))
    elif kind == "unsupported":
        row["correct"] = state in ("unsupported", "partial", "failed")
    return row


def check_export(files: tuple[str, ...], expect: dict[str, dict[str, str]], names: dict[str, str]) -> dict:
    csvs = [f for f in files if f.lower().endswith(".csv")]
    if not csvs:
        return {"correct": False, "cells": 0, "cells_correct": 0, "error": "no CSV written"}
    with open(csvs[0], encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    cells = good = 0
    for doc_id, fields in expect.items():
        row = next((r for r in rows if r.get("document") == names.get(doc_id)), None)
        for field, want in fields.items():
            cells += 1
            have = (row or {}).get(field)
            if have is None or have == "":
                continue
            try:
                ok = abs(float(have) - float(want)) < 0.005
            except ValueError:
                ok = str(have)[:10] == want or norm(have) == norm(want)
            good += ok
    return {"correct": good == cells, "cells": cells, "cells_correct": good, "rows": len(rows)}


# ---------------------------------------------------------------- run


def build_info() -> dict:
    import inklight

    root = Path(inklight.__file__).resolve().parents[2]
    commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    return {
        "inklight_file": inklight.__file__,
        "version": inklight.__version__,
        "git_commit_if_source_tree": commit or None,
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, default=Path(__file__).with_name("corpus.json"))
    ap.add_argument("--split", choices=["dev", "reserved", "fresh", "fresh2"], required=True)
    ap.add_argument("--docs", type=Path, required=True)
    ap.add_argument("--models", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--brain", choices=["rules", "auto"], default="auto")
    ap.add_argument("--ocr-mode", choices=["auto", "ocr"], default="auto")
    ap.add_argument("--save-hits", type=Path)
    ap.add_argument("--replay-hits", type=Path)
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    docs = [d for d in corpus["documents"] if d["split"] == args.split]  # select the split before any reading
    tasks = [t for t in corpus["library_tasks"] if t["split"] == args.split]
    args.out.mkdir(parents=True, exist_ok=True)
    if args.split in ("reserved", "fresh", "fresh2"):
        with open(args.out.parent / "reserved-access.log", "a", encoding="utf-8") as log:
            log.write(
                json.dumps({"at": datetime.now(UTC).isoformat(), "build": build_info(), "argv": sys.argv[1:]}) + "\n"
            )
    instrument()
    from inklight import DocumentAgent

    home = args.out / "home"
    if home.exists():
        sys.exit(f"{home} exists: use a fresh --out")
    result: dict[str, Any] = {
        "label": "AUTOMATED USE-CASE EVALUATION",
        "split": args.split,
        "brain": args.brain,
        "ocr_mode": args.ocr_mode,
        "build": build_info(),
        "run_label": args.label,
        "evidence": "replayed" if args.replay_hits else "live",
        "documents": {},
        "library_tasks": [],
    }
    with DocumentAgent(settings(home, args.models, args.brain, args.ocr_mode)) as agent:
        recorder = HitRecorder(
            agent.library,
            "save" if args.save_hits else ("replay" if args.replay_hits else None),
            args.save_hits or args.replay_hits,
        )
        t0 = time.perf_counter()
        before = collections.Counter(ORT)
        report = agent.add([args.docs / d["file"] for d in docs])
        result["ingest"] = {
            "seconds": round(time.perf_counter() - t0, 1),
            "failed": [[str(p), str(e)] for p, e in report.failed],
            "onnx": delta(before),
        }
        by_name = {Path(d.path).name: d for d in report.documents}
        ids = {d["id"]: by_name[d["file"]].id for d in docs if d["file"] in by_name}
        names = {d["id"]: d["file"] for d in docs}
        for doc in docs:
            info = by_name.get(doc["file"])
            row: dict[str, Any] = {k: doc[k] for k in ("lang", "modality", "type", "genuine", "group")}
            if info is None:
                row["error"] = "not ingested"
                result["documents"][doc["id"]] = row
                continue
            text = agent.library.text(info.id)
            pages = agent.library.pages(info.id)
            row["ingest"] = {
                "pages": info.pages,
                "doc_type": info.doc_type,
                "mean_conf": info.mean_conf,
                "sources": dict(collections.Counter(p.source for p in pages)),
                "notes": sorted({p.note.split(";")[0] for p in pages if p.note})[:4],
                "text_sha": __import__("hashlib").sha256(text.encode()).hexdigest()[:16],
            }
            row["text_has_answers"] = [any(contains(text, [a]) for a in q["accept"]) for q in doc["qa"]]
            row["qa"] = qa_cases(agent, doc, info.id, text)
            row["missing"] = missing_cases(agent, doc, info.id)
            row["summary"] = summary_case(agent, doc, info.id, text)
            row["fields"] = field_cases(agent, doc, args.docs / doc["file"])
            row["review"] = review_case(agent, doc, info.id)
            result["documents"][doc["id"]] = row
            print(f"[{args.split}/{args.brain}] {doc['id']}", flush=True)
        for task in tasks:
            result["library_tasks"].append(library_case(agent, task, ids, names, args.out))
        export = agent.reviews.export("csv", actor="usecase-eval-script")
        text_csv = export.decode("utf-8") if isinstance(export, bytes) else export
        rows = list(csv.DictReader(text_csv.splitlines()))
        result["review_export"] = {
            "rows": len(rows),
            "arabic_values": sum(bool(re.search("[؀-ۿ]", r.get("predicted") or "")) for r in rows),
            "documents": len({r["document"] for r in rows}),
        }
        result["brain_usage"] = agent.library.brain.usage()
        result["replay_misses"] = recorder.misses
        recorder.save()
    result["onnx_total"] = dict(ORT)
    (args.out / "usecases.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {args.out / 'usecases.json'}")


if __name__ == "__main__":
    main()
