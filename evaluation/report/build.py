"""Build evaluation/REPORT.md and evaluation/REPORT.html from the stored results.

    python evaluation/report/build.py            # needs the `markdown` package for the HTML version

Every number in the report text comes from ``facts`` below, and every figure is drawn from the same values, so the
text, the figures and the result files cannot disagree. The sources are stored results in evaluation/results/ and
the examples written by evaluation/report/examples.py; ``external.json`` holds the externally reported numbers, each
with its source. Figures are standalone SVG files that follow the reader's light or dark setting.
"""

from __future__ import annotations

import collections
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent
RESULTS = EVAL / "results"
FIG = HERE / "figures"
sys.path.insert(0, str(EVAL.parent / "bench" / "usecases"))
import summarize  # noqa: E402  (the use-case harness's own tallies)

# ------------------------------------------------------------------ colours (validated: see report/README.md)

STYLE = """<style>
svg{font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;font-variant-numeric:tabular-nums}
.t1{fill:#17181a}.t2{fill:#55575c}.t3{fill:#7c7e83}.grid{stroke:#e4e4e1}.axis{stroke:#b9bab6}
.c-ok{fill:#2a78d6}.c-okf{fill:#1baf7a}.c-wf{fill:#eda100}.c-sw{fill:#e34948}.c-miss{fill:url(#hatch)}
.c-acc{fill:#0a8fb0}.c-mut{fill:#c9cac6}.hatch-l{stroke:#9b9c98}.hatch-b{fill:#f1f1ee}.gap{stroke:#fcfcfb}
.box{fill:#fcfcfb;stroke:#c9cac6}.box-acc{fill:#e6f5f9;stroke:#0a8fb0}.line{stroke:#9b9c98}.bg{fill:#fcfcfb}
@media (prefers-color-scheme:dark){
.t1{fill:#ecedea}.t2{fill:#b9bab4}.t3{fill:#8e8f8a}.grid{stroke:#2c2d2f}.axis{stroke:#4a4b4e}
.c-ok{fill:#3987e5}.c-okf{fill:#199e70}.c-wf{fill:#c98500}.c-sw{fill:#d55181}.c-acc{fill:#22b8d8}.c-mut{fill:#4a4b4e}
.hatch-l{stroke:#77786f}.hatch-b{fill:#232426}.gap{stroke:#17181a}.box{fill:#1d1e20;stroke:#3a3b3e}
.box-acc{fill:#0d2f38;stroke:#22b8d8}.line{stroke:#6b6c68}.bg{fill:#17181a}}
@media print{.bg{fill:#fff}}
</style>
<defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
<rect class="hatch-b" width="6" height="6"/><line class="hatch-l" x1="0" y1="0" x2="0" y2="6" stroke-width="2"/></pattern></defs>"""

OUTCOMES = [  # field and answer outcomes, in the order they are stacked
    ("correct_unflagged", "Correct", "c-ok"),
    ("correct_flagged", "Correct, flagged for review", "c-okf"),
    ("wrong_flagged", "Wrong, flagged for review", "c-wf"),
    ("wrong_unflagged", "Wrong, not flagged (silent)", "c-sw"),
    ("missing", "Missing / declined", "c-miss"),
]


def esc(s: Any) -> str:
    return html.escape(str(s), quote=True)


def svg(width: int, height: int, body: str, title: str, desc: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-labelledby="t d"><title id="t">{esc(title)}</title><desc id="d">{esc(desc)}</desc>'
        f'{STYLE}<rect class="bg" width="{width}" height="{height}"/>{body}</svg>'
    )


def legend(x: float, y: float, items: list[tuple[str, str]], max_x: float = 760) -> tuple[str, int]:
    """Swatches and labels in rows that wrap at ``max_x``; returns the SVG and the number of rows."""
    out, cx, rows = [], x, 1
    for label, cls in items:
        width = 15 + 6.4 * len(label) + 18
        if cx > x and cx + width > max_x:
            cx, y, rows = x, y + 18, rows + 1
        out.append(f'<rect class="{cls}" x="{cx}" y="{y - 9}" width="10" height="10" rx="2"/>')
        out.append(f'<text class="t2" x="{cx + 15}" y="{y}" font-size="12">{esc(label)}</text>')
        cx += width
    return "".join(out), rows


def stacked(rows: list[dict[str, Any]], keys: list[tuple[str, str, str]], title: str, desc: str, note: str) -> str:
    """100% stacked horizontal bars, one per row, each segment labelled with its count when it fits."""
    left, bar_w, bar_h, gap = 210, 560, 22, 16
    key_svg, key_rows = legend(20, 50, [(label, cls) for _, label, cls in keys], left + bar_w)
    top = 46 + 18 * key_rows
    height = top + len(rows) * (bar_h + gap) + 54
    out = [f'<text class="t1" x="20" y="28" font-size="15" font-weight="600">{esc(title)}</text>', key_svg]
    for i, row in enumerate(rows):
        y = top + i * (bar_h + gap)
        n = sum(row["counts"].get(k, 0) for k, _, _ in keys)
        out.append(
            f'<text class="t1" x="{left - 12}" y="{y + 11}" font-size="13" text-anchor="end">{esc(row["label"])}</text>'
        )
        out.append(
            f'<text class="t3" x="{left - 12}" y="{y + 25}" font-size="11" text-anchor="end">{esc(row["sub"])} · n = {n}</text>'
        )
        x = left
        for k, label, cls in keys:
            c = row["counts"].get(k, 0)
            if not c:
                continue
            w = bar_w * c / n
            out.append(
                f'<rect class="{cls}" x="{x:.1f}" y="{y}" width="{max(w - 2, 1):.1f}" height="{bar_h}" rx="3">'
                f"<title>{esc(row['label'])}: {esc(label)} {c} of {n}</title></rect>"
            )
            if w > 26:
                fill = "t1" if cls in ("c-miss", "c-wf", "c-okf") else "bg"
                out.append(
                    f'<text class="{fill}" x="{x + w / 2 - 1:.1f}" y="{y + 15}" font-size="12" text-anchor="middle" '
                    f'font-weight="600">{c}</text>'
                )
            x += w
    out.append(f'<text class="t3" x="20" y="{height - 18}" font-size="11">{esc(note)}</text>')
    return svg(left + bar_w + 30, height, "".join(out), title, desc)


def hbars(
    rows: list[tuple[str, float, str]], title: str, desc: str, note: str, unit: str = "", vmax: float | None = None
) -> str:
    """Plain horizontal bars from zero, value labels at the bar end; ``cls`` picks the mark colour."""
    left, bar_w, bar_h, gap, top = 210, 470, 20, 12, 52
    vmax = vmax or max(v for _, v, _ in rows) * 1.12
    height = top + len(rows) * (bar_h + gap) + 44
    out = [f'<text class="t1" x="20" y="28" font-size="15" font-weight="600">{esc(title)}</text>']
    out.append(f'<line class="axis" x1="{left}" y1="{top - 8}" x2="{left}" y2="{top + len(rows) * (bar_h + gap)}"/>')
    for i, (label, v, cls) in enumerate(rows):
        y = top + i * (bar_h + gap)
        w = bar_w * v / vmax
        out.append(
            f'<text class="t1" x="{left - 12}" y="{y + 14}" font-size="13" text-anchor="end">{esc(label)}</text>'
        )
        out.append(
            f'<rect class="{cls}" x="{left}" y="{y}" width="{max(w, 1):.1f}" height="{bar_h}" rx="3"><title>{esc(label)}: {v:g}{unit}</title></rect>'
        )
        out.append(f'<text class="t2" x="{left + w + 8:.1f}" y="{y + 14}" font-size="12">{v:g}{unit}</text>')
    out.append(f'<text class="t3" x="20" y="{height - 14}" font-size="11">{esc(note)}</text>')
    return svg(left + bar_w + 90, height, "".join(out), title, desc)


def architecture() -> str:
    """The pipeline: what runs where, which model files, which stages are deterministic code."""
    stages = [
        (
            "Read",
            "PDF text layer · pypdfium2",
            "code",
            "Pages rendered once; a PDF text layer is\nchecked and used where it is sound",
        ),
        (
            "OCR",
            "Indra OCR models · ONNX Runtime",
            "model",
            "Detection, recognition (Latin, Arabic, …),\norientation, reading order · ~76 MB",
        ),
        (
            "Structure",
            "Heron layout (ONNX) · TableFormer (PyTorch)",
            "model",
            "Optional [structure] extra: regions,\ntables, cells matched to OCR lines · ~380 MB",
        ),
        (
            "Store",
            "SQLite library · full-text index",
            "code",
            "Lines, boxes, confidences, blocks and\ntables kept per page, with provenance",
        ),
        (
            "Operations",
            "Rules and label readers",
            "code",
            "Text, tables, fields, search with\ncitations, review and export",
        ),
        (
            "Ask",
            "Experimental · optional small models",
            "exp",
            "Questions over the library; Arabic\nquestions skip the English-only models",
        ),
    ]
    w, bw, bh, top = 980, 146, 150, 70
    gap = (w - 40 - bw * len(stages)) / (len(stages) - 1)
    out = [
        '<text class="t1" x="20" y="30" font-size="15" font-weight="600">Inklight: one local process, '
        "three model sets, deterministic operations</text>"
    ]
    for i, (name, runtime, kind, detail) in enumerate(stages):
        x = 20 + i * (bw + gap)
        cls = "box-acc" if kind == "model" else "box"
        dash = ' stroke-dasharray="5 4"' if kind == "exp" else ""
        out.append(
            f'<rect class="{cls}" x="{x:.1f}" y="{top}" width="{bw}" height="{bh}" rx="10" stroke-width="1.5"{dash}/>'
        )
        out.append(
            f'<text class="t1" x="{x + 12:.1f}" y="{top + 26}" font-size="14" font-weight="600">{esc(name)}</text>'
        )
        for j, part in enumerate(_wrap(runtime, 22)):
            out.append(f'<text class="t2" x="{x + 12:.1f}" y="{top + 48 + j * 15}" font-size="11.5">{esc(part)}</text>')
        for j, part in enumerate(detail.split("\n")):
            for k, piece in enumerate(_wrap(part, 24)):
                out.append(
                    f'<text class="t3" x="{x + 12:.1f}" y="{top + 92 + (j * 2 + k) * 14}" font-size="10.5">{esc(piece)}</text>'
                )
        if i < len(stages) - 1:
            ax = x + bw
            out.append(
                f'<line class="line" x1="{ax + 4:.1f}" y1="{top + bh / 2}" x2="{ax + gap - 6:.1f}" y2="{top + bh / 2}" stroke-width="1.5"/>'
            )
            out.append(f'<path class="c-mut" d="M{ax + gap - 6:.1f},{top + bh / 2 - 4} l6,4 l-6,4z"/>')
    out.append(
        legend(
            20,
            top + bh + 36,
            [("model inference (CPU)", "box-acc"), ("deterministic code", "box"), ("experimental", "c-mut")],
        )[0]
    )
    out.append(
        f'<text class="t3" x="20" y="{top + bh + 62}" font-size="11">No document leaves the machine. Model files are '
        "downloaded once at pinned revisions and checked by SHA-256; INKLIGHT_OFFLINE=1 forbids downloads.</text>"
    )
    return svg(
        w,
        top + bh + 80,
        "".join(out),
        "Inklight architecture",
        "Six stages from reading a file to experimental questions",
    )


def _wrap(s: str, n: int) -> list[str]:
    words, lines, cur = s.split(), [], ""
    for wd in words:
        if len(cur) + len(wd) + 1 > n and cur:
            lines.append(cur)
            cur = wd
        else:
            cur = f"{cur} {wd}".strip()
    return lines + ([cur] if cur else [])


# ------------------------------------------------------------------ data


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def external_fields() -> list[dict[str, Any]]:
    rows = []
    for ds, sub in (("cord", "genuine receipt photos"), ("voxel51", "synthetic invoice images")):
        for split in ("dev", "holdout"):
            d = load(RESULTS / "external" / f"v030-{ds}-{split}-rules.json")
            c = d["extraction"]["overall"]["counts"]
            rows.append(
                {
                    "label": f"{'CORD' if ds == 'cord' else 'Voxel51'} {split}",
                    "sub": sub,
                    "counts": c,
                    "metrics": d["extraction"]["overall"],
                    "tasks": d["tasks"]["outcomes"],
                    "docs": d["documents"] if isinstance(d["documents"], int) else len(d["documents"]),
                    "ingest_s": d["ingest_s"],
                    "commit": d["provenance"]["git_commit"],
                }
            )
    return rows


def usecase_qa(path: Path) -> dict[str, collections.Counter]:
    run = load(path)
    by_lang: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for (lang, *_), counter in summarize.tally(run, "qa", summarize.QA_OUTCOMES).items():
        by_lang[lang].update({k: v for k, v in counter.items() if k != "n"})
    return by_lang


def agent_eval() -> dict[str, dict[str, int]]:
    text = (RESULTS / "agent_eval" / "amendment-1" / "summary-v2.md").read_text(encoding="utf-8")
    want = {
        "completed by the tool on the first action": "tool_first",
        "completed by the tool after follow-up (incl. clarification)": "tool_follow",
        "correct only after the person read the pages (manual rescue)": "rescue",
        "correct abstention by the tool": "abstain",
        "silent wrong (as handed over)": "silent",
        "first answer judged correct": "first_correct",
        "citations fully support the claim": "cite_full",
        "citations partly support": "cite_part",
    }
    out: dict[str, dict[str, int]] = {arm: {} for arm in ("A", "A2", "B", "B2")}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and cells[0] in want:
            for arm, cell in zip(("A", "A2", "B", "B2"), cells[1:5], strict=True):
                out[arm][want[cells[0]]] = int(cell.split("/")[0])
    return out


def facts() -> dict[str, Any]:
    ext = external_fields()
    mig = load(RESULTS / "migration-0.3" / "summary.json")["documents"]
    s02 = load(RESULTS / "migration-0.3" / "structure-synthetic-0.2.json")["summary"]
    s03 = load(RESULTS / "migration-0.3" / "structure-synthetic-0.3.json")["summary"]
    ae = agent_eval()
    now = usecase_qa(RESULTS / "usecases" / "fresh5-rerun-26445bf-rules.json")
    before = usecase_qa(RESULTS / "usecases" / "fresh5-first-access-915be7b-rules.json")
    ex = load(HERE / "examples" / "examples.json")
    f: dict[str, Any] = {"ext": ext, "agent": ae, "uc_now": now, "uc_before": before, "examples": ex}
    for r in ext:
        k = r["label"].lower().replace(" ", "_")
        m = r["metrics"]
        f[f"{k}_n"] = m["n"]
        f[f"{k}_cov"] = f"{100 * m['coverage_without_review']:.1f}%"
        f[f"{k}_acc"] = f"{100 * m['value_accuracy']:.1f}%"
        f[f"{k}_prec"] = f"{100 * m['precision_unflagged']:.1f}%"
        f[f"{k}_silent"] = r["counts"]["wrong_unflagged"]
        f[f"{k}_docs"] = r["docs"]
        f[f"{k}_tasks"] = ", ".join(f"{v} {k2.replace('_', ' ')}" for k2, v in sorted(r["tasks"].items()))
    pdfs = [d for d in mig if d["layout"] != "identical"]
    f["mig_n"] = len(mig)
    f["mig_private"] = sum(d["origin"] == "private" for d in mig)
    f["mig_tables"] = sum(d["tables_identical"] for d in mig)
    f["mig_e2e"] = sum(d["end_to_end_identical"] for d in mig)
    f["mig_pdf_changed"] = len(pdfs)
    f["mig_box_only"] = sum(d["layout"] == "box positions only" for d in mig)
    f["mig_blocks"] = sum(d["layout"] == "blocks changed" for d in mig)
    f["mig_box_max"] = max(d["max_box_deviation_px"] for d in mig)
    for tag, s in (("s02", s02), ("s03", s03)):
        f[f"{tag}_ingest"] = s["B"]["ingest_s"]
        f[f"{tag}_peak"] = round(s["B"]["peak_mb"])
    for arm in ("A", "B"):
        o = s03[arm]["outcomes"]
        for lang in ("ar", "en", "mixed"):
            c = o[f"{lang} answerable"]
            f[f"syn_{arm}_{lang}_correct"] = c.get("correct", 0) + c.get("correct_flagged", 0)
            f[f"syn_{arm}_{lang}_n"] = sum(c.values())
            f[f"syn_{arm}_{lang}_silent"] = c.get("silent_wrong", 0)
        f[f"syn_{arm}_silent"] = sum(o[f"{lg} answerable"].get("silent_wrong", 0) for lg in ("ar", "en", "mixed"))
        f[f"syn_{arm}_cite"] = s03[arm]["citation_holds_answer"]
    for tag, run in (("now", now), ("before", before)):
        for lang in ("en", "ar", "mixed"):
            c = run[lang]
            f[f"uc_{tag}_{lang}_ok"] = c["correct"] + c["correct_flagged"]
            f[f"uc_{tag}_{lang}_silent"] = c["silent_wrong"]
            f[f"uc_{tag}_{lang}_n"] = sum(c.values())
    for r in ext:
        f[r["label"].lower().replace(" ", "_") + "_ingest"] = r["ingest_s"]
    # the stored run before the type-scope fix (26445bf), and the independent historical CORD split (build H)
    pre = load(RESULTS / "external" / "v030-prefix-cord-dev-rules.json")["tasks"]["items"][0]
    f["pre_dev_returned"], f["pre_dev_expected"] = pre["returned"], pre["expected"]
    f["pre_hold_silent"] = load(RESULTS / "external" / "v030-prefix-cord-holdout-rules.json")["tasks"]["outcomes"][
        "silent_wrong"
    ]
    fr = load(RESULTS / "external" / "rescored" / "fresh1-H-cord-fresh-rules.json")["extraction"]["overall"]
    f["cord_fresh_n"], f["cord_fresh_silent"] = fr["n"], fr["counts"]["wrong_unflagged"]
    f["cord_fresh_cov"] = f"{100 * fr['coverage_without_review']:.1f}%"
    f["cord_fresh_prec"] = f"{100 * fr['precision_unflagged']:.1f}%"
    f["cord_fresh_acc"] = f"{100 * fr['value_accuracy']:.1f}%"
    f["mig_box_only_max"] = max(d["max_box_deviation_px"] for d in mig if d["layout"] == "box positions only")
    f["syn_missing_silent"] = s03["B"]["outcomes"].get("en missing", {}).get("silent", 0)
    f["uc_now_ok"] = sum(f[f"uc_now_{lg}_ok"] for lg in ("en", "ar", "mixed"))
    f["uc_before_ok"] = sum(f[f"uc_before_{lg}_ok"] for lg in ("en", "ar", "mixed"))
    f["uc_n"] = sum(f[f"uc_now_{lg}_n"] for lg in ("en", "ar", "mixed"))
    f.update(example_facts(ex))
    for arm in ("A2", "B2"):
        f[f"ae_{arm}_tool"] = ae[arm]["tool_first"] + ae[arm]["tool_follow"]
        f[f"ae_{arm}_rescue"] = ae[arm]["rescue"]
        f[f"ae_{arm}_silent"] = ae[arm]["silent"]
    return f


def example_facts(ex: dict[str, Any]) -> dict[str, Any]:
    """The examples' values as the report quotes them, straight from examples.json."""
    first = ex["arabic_signer"]["sources"][0]
    tables = ex["tables"]["tables"]
    inv = ex["invoices"]
    head = ex["limit_arabic_letterhead"]["line"]
    lim = ex["limit_turned_card_extract"]
    return {
        "ex_signer_answer": ex["arabic_signer"]["answer"].splitlines()[0],
        "ex_signer_box": ", ".join(f"{v:g}" for v in first["bbox"]),
        "ex_signer_excerpt": first["excerpt"],
        "ex_t1_name": tables[0]["rows"][1][0],
        "ex_t1_type": tables[0]["rows"][1][1],
        "ex_t2_name": tables[1]["rows"][1][0],
        "ex_t2_type": tables[1]["rows"][1][1],
        "ex_share_answer": ex["turned_share"]["answer"].splitlines()[0],
        **{
            f"ex_inv{i}_{k}": v
            for i, r in enumerate(inv, 1)
            for k, v in (
                ("file", r["file"]),
                ("number", r["invoice_number"]["value"]),
                ("total", f"{r['total']['value']:,.2f}"),
                ("src", f"“{r['total']['source']['excerpt']}”, page {r['total']['source']['page']}"),
            )
        },
        "ex_ambiguous_answer": _listed(ex["ambiguous"]["answer"]),
        "ex_review_pred": ex["review"]["predicted"]["company_name"],
        "ex_review_csv": _review_csv(),
        "ex_head_text": head["text"],
        "ex_head_conf": f"{head['conf']:.2f}",
        "ex_lim_name": lim["fields"]["company_name"],
        "ex_lim_regno": lim["registration_number_by_question"].splitlines()[0],
    }


def _listed(answer: str) -> str:
    """An answer's first line and its bullet list, as one sentence."""
    head, *items = answer.splitlines()
    return f"{head} " + "; ".join(i.lstrip("- ") for i in items if i.strip()) + "."


def _review_csv() -> str:
    """The export with the columns that show provenance and decisions (the file has all of them)."""
    import csv
    import io

    keep = ["document", "field", "predicted", "source_page", "source_bbox", "final", "action", "approved_by"]
    rows = list(csv.DictReader(io.StringIO((HERE / "examples" / "review-export.csv").read_text(encoding="utf-8"))))
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=keep, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return out.getvalue().strip()


# ------------------------------------------------------------------ figures


def figures(f: dict[str, Any]) -> dict[str, str]:
    figs: dict[str, str] = {"architecture": architecture()}
    figs["fields"] = stacked(
        f["ext"],
        OUTCOMES,
        "Field extraction on two public datasets, current build",
        "Outcome of every annotated value, per split",
        "Rules mode, CPU, structure off. CORD: total, subtotal, tax. Voxel51: vendor, customer, number, date, tax, total. "
        "Flagged = warning or confidence < 0.7.",
    )
    qa_keys = [
        ("correct", "Correct", "c-ok"),
        ("correct_flagged", "Correct, flagged", "c-okf"),
        ("wrong_flagged", "Wrong, flagged", "c-wf"),
        ("silent_wrong", "Wrong, not flagged", "c-sw"),
        ("declined", "Declined", "c-miss"),
    ]
    names = {"en": "English", "ar": "Arabic", "mixed": "Mixed"}
    rows = []
    for lang in ("en", "ar", "mixed"):
        for tag, sub in (("uc_before", "915be7b (Oct 25)"), ("uc_now", "0.3.0b1 rerun")):
            rows.append({"label": names[lang], "sub": sub, "counts": dict(f[tag][lang])})
    figs["questions"] = stacked(
        rows,
        qa_keys,
        "Answerable questions on 10 public documents (fresh5), rules mode",
        "Each question's outcome, before and after the 0.3 changes",
        "Development data since its first run: these documents guided later fixes. Same questions and expectations.",
    )
    ae = f["agent"]
    ae_keys = [
        ("tool", "Answered correctly by Inklight", "c-ok"),
        ("abstain", "Correct “not in the document”", "c-okf"),
        ("rescue", "Correct only after the person read the page", "c-miss"),
        ("silent", "Wrong as handed over", "c-sw"),
    ]
    figs["agent"] = stacked(
        [
            {
                "label": "Structure off",
                "sub": "build d9e0496",
                "counts": {
                    "tool": ae["A2"]["tool_first"] + ae["A2"]["tool_follow"] - ae["A2"]["abstain"],
                    "abstain": ae["A2"]["abstain"],
                    "rescue": ae["A2"]["rescue"],
                    "silent": ae["A2"]["silent"],
                },
            },
            {
                "label": "Structure on",
                "sub": "build d9e0496",
                "counts": {
                    "tool": ae["B2"]["tool_first"] + ae["B2"]["tool_follow"] - ae["B2"]["abstain"],
                    "abstain": ae["B2"]["abstain"],
                    "rescue": ae["B2"]["rescue"],
                    "silent": ae["B2"]["silent"],
                },
            },
        ],
        ae_keys,
        "Historical: 38 workflow tasks on mostly scanned Arabic business documents",
        "Who produced each correct deliverable in the agent-run evaluation",
        "October 2026, before 0.3. Agents as users, blinded AI judges, strict brief v2. 17 of 25 documents private.",
    )
    figs["migration"] = stacked(
        [
            {"label": "OCR lines", "sub": "text, box, confidence", "counts": {"same": f["mig_n"]}},
            {
                "label": "Tables",
                "sub": "rows, columns, cells",
                "counts": {"same": f["mig_tables"], "diff": f["mig_n"] - f["mig_tables"]},
            },
            {
                "label": "Layout blocks",
                "sub": "label, text, order, box",
                "counts": {
                    "same": f["mig_n"] - f["mig_pdf_changed"],
                    "box": f["mig_box_only"],
                    "diff": f["mig_blocks"],
                },
            },
        ],
        [
            ("same", "Identical", "c-ok"),
            ("box", f"Boxes moved ≤ {f['mig_box_only_max']:g} px", "c-wf"),
            ("diff", "Blocks changed", "c-sw"),
        ],
        "0.2 → 0.3: same model files run inside Inklight",
        "Documents identical per stage, out of 17",
        f"17 documents ({f['mig_private']} private, listed by kind only). Layout differs on every readable PDF: "
        "PDF pages are no longer drawn by docling-parse.",
    )
    figs["speed"] = hbars(
        [
            ("0.2 (docling runtime)", f["s02_ingest"], "c-mut"),
            ("0.3.0b1 (inside Inklight)", f["s03_ingest"], "c-acc"),
        ],
        "Internal improvement: structuring 6 synthetic documents",
        "Seconds to add 6 documents with structure, from stored OCR",
        f"Same CPU (Ryzen 7 8700F), same OCR replayed, same answers. Peak memory {f['s02_peak']} → {f['s03_peak']} MB. "
        "Not comparable with any GPU throughput.",
        unit=" s",
    )
    figs["parsebench"] = hbars(
        [(name, v, "c-mut") for name, v in ((r["system"], r["overall"]) for r in EXTERNAL["parsebench_leaderboard"])],
        "Externally reported: ParseBench leaderboard, overall",
        "Overall score as published by LlamaIndex, 0 to 100",
        "Source: run-llama/ParseBench leaderboard.csv, accessed 2026-10-27; run by the benchmark owner. "
        "Inklight: not evaluated.",
        vmax=100,
    )
    return figs


EXTERNAL = load(HERE / "external.json")

# ------------------------------------------------------------------ report


def fill(template: str, f: dict[str, Any]) -> str:
    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in f:
            raise KeyError(f"REPORT.template.md uses {{{{{key}}}}}, which build.py does not compute")
        v = f[key]
        return f"{v:g}" if isinstance(v, float) else str(v)

    return re.sub(r"\{\{([a-zA-Z0-9_]+)\}\}", sub, template)


def to_html(md_text: str, figs: dict[str, str]) -> str:
    import markdown

    body = markdown.markdown(md_text, extensions=["tables", "toc", "fenced_code", "attr_list"])

    def inline(m: re.Match[str]) -> str:
        name = Path(m.group(1)).stem
        return f'<span class="fig">{figs[name]}</span>' if name in figs else m.group(0)

    body = re.sub(r'<img alt="[^"]*" src="report/figures/([^"]+\.svg)"\s*/?>', inline, body)
    body = body.replace('src="report/examples/', 'src="report/examples/')
    return (HERE / "template.html").read_text(encoding="utf-8").replace("{{body}}", body)


def main() -> int:
    f = facts()
    FIG.mkdir(exist_ok=True)
    figs = figures(f)
    for name, content in figs.items():
        (FIG / f"{name}.svg").write_text(content, encoding="utf-8")
    md = fill((HERE / "REPORT.template.md").read_text(encoding="utf-8"), f)
    (EVAL / "REPORT.md").write_text(md, encoding="utf-8")
    try:
        (EVAL / "REPORT.html").write_text(to_html(md, figs), encoding="utf-8")
    except ImportError:
        print("REPORT.html not written: pip install markdown")
    print(f"wrote {EVAL / 'REPORT.md'}, {len(figs)} figures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
