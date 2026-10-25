"""Tables from evaluate.py output, kept separate by language, document type, genuine/synthetic and task.

    python -I bench/usecases/summarize.py <usecases.json> [<another run> ...]

With several runs, each table has one column group per run, on the same cases.
"""

from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

QA_OUTCOMES = ["correct", "correct_flagged", "wrong_flagged", "silent_wrong", "unsupported", "failed"]
FIELD_OUTCOMES = [
    "correct",
    "correct_flagged",
    "correct_but_ambiguity_not_flagged",
    "missing",
    "wrong_flagged",
    "silent_wrong",
]


def key(doc: dict) -> tuple[str, str, str]:
    kind = "synthetic" if not doc["genuine"] else "genuine"
    typ = {
        "receipt": "invoice/receipt",
        "invoice": "invoice/receipt",
        "certificate": "form/certificate",
        "form": "form/certificate",
        "letter": "letter/contract",
        "contract": "letter/contract",
    }.get(doc["type"], doc["type"])
    return doc["lang"], typ, kind


def tally(run: dict, part: str, outcomes: list[str]) -> dict[tuple, collections.Counter]:
    out: dict[tuple, collections.Counter] = collections.defaultdict(collections.Counter)
    for d in run["documents"].values():
        for row in d.get(part, []):
            out[key(d)][row["outcome"]] += 1
            out[key(d)]["n"] += 1
    return out


def fmt(c: collections.Counter, names: list[str]) -> str:
    return " / ".join(str(c.get(n, 0)) for n in names) + f" (n={c['n']})"


def qa_table(runs: list[tuple[str, dict]]) -> str:
    names = ["correct", "correct_flagged", "wrong_flagged", "silent_wrong"]
    lines = [
        "| lang | type | data | "
        + " | ".join(f"{label}: correct / correct·flagged / wrong·flagged / silent wrong" for label, _ in runs)
        + " |",
        "|---|---|---|" + "---|" * len(runs),
    ]
    tallies = [tally(r, "qa", QA_OUTCOMES) for _, r in runs]
    for k in sorted(set().union(*[t.keys() for t in tallies])):
        lines.append(
            f"| {k[0]} | {k[1]} | {k[2]} | "
            + " | ".join(fmt(t.get(k, collections.Counter()), names) for t in tallies)
            + " |"
        )
    return "\n".join(lines)


def stages(run: dict) -> dict[tuple, collections.Counter]:
    out: dict[tuple, collections.Counter] = collections.defaultdict(collections.Counter)
    for d in run["documents"].values():
        for q in d.get("qa", []):
            if q["first_failing_stage"]:
                out[(d["lang"],)][q["first_failing_stage"]] += 1
    return out


def citation(run: dict) -> dict[str, str]:
    out = {}
    for lang in ("en", "ar", "mixed"):
        qs = [q for d in run["documents"].values() if d["lang"] == lang for q in d.get("qa", [])]
        ok = [q for q in qs if q["outcome"] in ("correct", "correct_flagged")]
        out[lang] = (
            f"answers {len(ok)}/{len(qs)}; cited passage supports the answer "
            f"{sum(q['cited_passage_supports'] for q in ok)}/{len(ok)};"
            f" retrieval had the answer {sum(q['retrieval_has_answer'] for q in qs)}/{len(qs)}"
        )
    return out


def summaries(run: dict) -> dict[str, str]:
    out = {}
    for lang in ("en", "ar", "mixed"):
        ss = [d["summary"] for d in run["documents"].values() if d["lang"] == lang and "summary" in d]
        if not ss:
            continue
        out[lang] = (
            f"{len(ss)} docs; recognised as a summary {sum(s['intent'].endswith('summarize') for s in ss)}; "
            f"key facts {sum(s['key_facts_covered'] for s in ss)}/{sum(s['key_facts'] for s in ss)}; "
            "quoted sentences found in the document "
            f"{sum(s['sentences_found_in_document'] for s in ss)}/{sum(s['sentences'] for s in ss)}"
        )
    return out


_DECLINED = re.compile(r"^not found|could not find|couldn't find supporting evidence", re.IGNORECASE)


def declined(row: dict) -> bool:
    """The answer says the documents do not contain it (older runs have no "declined" field)."""
    return bool(row.get("declined")) or bool(_DECLINED.search(row.get("answer", "").strip()))


def missing(run: dict) -> dict[str, str]:
    """Unanswerable questions: declined (says "not found"), only flagged, or answered silently; by kind when the
    corpus gives one. Answerable questions that were declined are reported beside them."""
    out = {}
    for lang in ("en", "ar", "mixed"):
        docs = [d for d in run["documents"].values() if d["lang"] == lang]
        ms = [m for d in docs for m in d.get("missing", [])]
        if not ms:
            continue
        parts = []
        for kind in sorted({m.get("kind", "all") for m in ms}):
            k = [m for m in ms if m.get("kind", "all") == kind]
            dec = sum(declined(m) for m in k)
            flag = sum(m["outcome"] == "abstained_or_flagged" and not declined(m) for m in k)
            parts.append(f"{kind}: declined {dec}, flagged {flag}, silent {len(k) - dec - flag} (n={len(k)})")
        qa = [q for d in docs for q in d.get("qa", [])]
        parts.append(f"answerable questions declined {sum(declined(q) for q in qa)}/{len(qa)}")
        out[lang] = "; ".join(parts)
    return out


def latency(run: dict) -> str:
    qa = [q["seconds"] for d in run["documents"].values() for q in d.get("qa", [])]
    qa.sort()
    calls = collections.Counter()
    for d in run["documents"].values():
        for q in d.get("qa", []):
            calls.update(q["onnx"])
    return (
        f"ingest {run['ingest']['seconds']} s; QA median {qa[len(qa) // 2]:.2f} s, max {qa[-1]:.2f} s; "
        f"ONNX calls during QA: {dict(calls)}; ingest ONNX: {run['ingest']['onnx']}"
    )


def rescore(run: dict, corpus: dict) -> None:
    """Re-check stored answers against the corpus as it is now (e.g. ISO dates accepted). The flag status of
    each answer is kept; only correct versus wrong can change. Applied to every run alike. Runs that stored
    complete answers ("answer_full") are rescored both ways; older, truncated runs can only be upgraded."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from capability_diag import contains

    accepts = {(d["id"], q["q"]): q["accept"] for d in corpus["documents"] for q in d["qa"]}
    for doc_id, d in run["documents"].items():
        for q in d.get("qa", []):
            accept = accepts.get((doc_id, q["q"]))
            if accept is None or q["outcome"] in ("unsupported", "failed"):
                continue
            flagged = q["outcome"] in ("correct_flagged", "wrong_flagged")
            if "answer_full" in q:  # complete answers are stored: score them again in either direction
                good = contains(q["answer"], accept)
            else:  # older runs cut answers at 300 characters: a match found on the full answer stands
                good = q["outcome"] in ("correct", "correct_flagged") or contains(q["answer"], accept)
            q["outcome"] = (
                ("correct_flagged" if flagged else "correct")
                if good
                else ("wrong_flagged" if flagged else "silent_wrong")
            )
            if good:
                q["first_failing_stage"] = None


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    runs = [(Path(p).parent.name, json.loads(Path(p).read_text(encoding="utf-8"))) for p in sys.argv[1:]]
    corpus = json.loads(Path(__file__).with_name("corpus.json").read_text(encoding="utf-8"))
    for _, r in runs:
        rescore(r, corpus)
    for label, r in runs:
        print(
            f"- **{label}**: split {r['split']}, brain {r['brain']}, OCR mode {r['ocr_mode']}, "
            f"evidence {r['evidence']}, "
            f"build {r['build']['git_commit_if_source_tree'] or r['build']['inklight_file']}"
        )
    print("\n### Questions with sources\n")
    print(qa_table(runs))
    for label, r in runs:
        print(f"\n**{label}**")
        print(f"- first failing stage of wrong answers: { {k[0]: dict(v) for k, v in stages(r).items()} }")
        for lang, s in citation(r).items():
            print(f"- {lang}: {s}")
        for lang, s in summaries(r).items():
            print(f"- summaries, {lang}: {s}")
        for lang, s in missing(r).items():
            print(f"- missing information, {lang}: {s}")
        ft = tally(r, "fields", FIELD_OUTCOMES)
        print(
            "- fields (correct / correct·flagged / ambiguity not flagged / missing / wrong·flagged / silent wrong): "
            + "; ".join(f"{k[0]} {k[1]} {k[2]}: {fmt(v, FIELD_OUTCOMES)}" for k, v in sorted(ft.items()))
        )
        print(
            "- library tasks: "
            + "; ".join(f"{t['id']} {'OK' if t.get('correct') else 'FAIL'} ({t['state']})" for t in r["library_tasks"])
        )
        print(f"- review export: {r['review_export']}")
        print(f"- latency and model activity: {latency(r)}")
        print(f"- brain usage: {r['brain_usage']}; replay misses: {r.get('replay_misses')}")


if __name__ == "__main__":
    main()
