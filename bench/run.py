"""Reproducible benchmark suite. Every number in docs/BENCHMARKS.md comes from this script.

    python bench/run.py            # full run, writes bench/results.json and bench/results.md
    python bench/run.py --quick    # fewer documents

Measures OCR engine speed separately from end-to-end agent latency, plus
extraction accuracy on generated documents with known ground truth.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.factory import build  # noqa: E402

VENDORS = [
    "Acme Supplies Ltd.",
    "Globex Corporation",
    "Initech LLC",
    "Umbrella Holdings Inc.",
    "Stark Parts Co.",
    "Wayne Logistics Ltd.",
    "Hooli Services LLC",
    "Vandelay Imports Inc.",
]
TOTAL_LABELS = ["Total", "Total Due", "Amount Due", "Grand Total", "Balance Due"]
DATE_FORMATS = ["%Y-%m-%d", "%B %d, %Y", "%d %b %Y", "%m/%d/%Y"]


def peak_rss_mb() -> float | None:
    try:
        import psutil  # optional

        info = psutil.Process().memory_info()
        return round(getattr(info, "peak_wset", info.rss) / 2**20, 1)
    except ImportError:
        pass
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb)
        return round(pmc.PeakWorkingSetSize / 2**20, 1)
    import resource

    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


# ---------------------------------------------------------------- synthetic invoices with ground truth


def synth_invoices(folder: Path, n: int, seed: int = 7) -> list[dict]:
    import cv2
    import numpy as np
    import pymupdf

    rng = random.Random(seed)
    truth = []
    for i in range(n):
        vendor = rng.choice(VENDORS)
        issued = date(2026, 1, 1) + timedelta(days=rng.randint(0, 280))
        subtotal = round(rng.uniform(80, 12000), 2)
        tax = round(subtotal * rng.choice([0.05, 0.08, 0.1, 0.13]), 2)
        total = round(subtotal + tax, 2)
        number = f"{rng.choice(['INV', 'IN', 'GX', 'A'])}-{rng.randint(1000, 99999)}"
        label = rng.choice(TOTAL_LABELS)
        dfmt = rng.choice(DATE_FORMATS)
        doc = pymupdf.open()
        page = doc.new_page()
        y = 72.0
        layout = "ABC"[i % 3]  # three different templates, so the set is not one layout
        rate = round(tax / subtotal * 100)
        if layout == "A":
            lines = [
                (vendor, 15),
                ("42 Industrial Way", 9),
                (f"Invoice Number: {number}", 11),
                (f"Invoice Date: {issued.strftime(dfmt)}", 11),
                ("Bill To: Northwind Traders", 11),
                ("Item                         Amount", 10),
                (f"Services rendered        ${subtotal:,.2f}", 10),
                (f"Subtotal: ${subtotal:,.2f}", 11),
                (f"Tax: ${tax:,.2f}", 11),
                (f"{label}: ${total:,.2f}", 12),
            ]
        elif layout == "B":  # no currency symbols, "Dated" instead of a date label, vendor after "From:"
            lines = [
                ("INVOICE", 18),
                (f"From: {vendor}", 11),
                (f"Invoice No. {number}", 11),
                (f"Dated {issued.strftime('%B %d, %Y')}", 11),
                ("Billed To: Northwind Traders", 11),
                (f"Net amount     {subtotal:,.2f}", 11),
                (f"Sales tax      {tax:,.2f}", 11),
                (f"TOTAL DUE (USD)     {total:,.2f}", 12),
            ]
        else:  # day-first dates, a VAT line with a percentage, a trailing currency code
            lines = [
                (vendor.upper(), 14),
                ("Tax Invoice", 13),
                (f"Inv #: {number}", 11),
                (f"Date: {issued.strftime('%d/%m/%Y')}", 11),
                ("Customer: Northwind Traders", 11),
                (f"Sub-total: {subtotal:,.2f} USD", 11),
                (f"VAT ({rate}%): {tax:,.2f} USD", 11),
                (f"Amount payable: {total:,.2f} USD", 12),
            ]
        for text, size in lines:
            page.insert_text((72, y), text, fontsize=size)
            y += size * 1.8
        scanned = i % 2 == 1
        if scanned:
            pix = page.get_pixmap(dpi=rng.choice([110, 150, 200]), colorspace=pymupdf.csGRAY)
            img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width).copy()
            angle = rng.uniform(-2.5, 2.5)
            m = cv2.getRotationMatrix2D((img.shape[1] / 2, img.shape[0] / 2), angle, 1.0)
            img = cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), borderValue=255)
            noise = np.random.default_rng(i).normal(0, 12, img.shape)
            img = np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)
            path = folder / f"synth_{i:03d}.png"
            cv2.imwrite(str(path), img)
        else:
            path = folder / f"synth_{i:03d}.pdf"
            doc.save(str(path))
        truth.append(
            {
                "file": path.name,
                "scanned": scanned,
                "layout": layout,
                "invoice_number": number,
                "vendor": vendor,
                "date": issued.isoformat(),
                "subtotal": subtotal,
                "tax": tax,
                "total": total,
            }
        )
    return truth


# ---------------------------------------------------------------- request fidelity


def request_fidelity(agent, truth: list[dict], by_name: dict) -> dict:  # type: ignore[no-untyped-def]
    """Does the agent return exactly the documents the request asks for, end to end from OCR?

    Expected sets come from ground truth, so an extraction error also costs a point here. Requests the
    agent cannot apply must come back `partial` with the unapplied words listed.
    """
    files = {r["file"]: r for r in truth}
    ids = [d.id for d in agent.library.documents() if d.name in files]
    vendor = truth[0]["vendor"]
    short = vendor.split()[0]
    other = next(r["vendor"] for r in truth if r["vendor"] != vendor)
    other_short = other.split()[0]
    cases = [
        ("Find invoices above $5,000", lambda r: r["total"] > 5000),
        (f"Find invoices from {short} above $2,000", lambda r: r["vendor"] == vendor and r["total"] > 2000),
        ("Find invoices below $1,000 or above $10,000", lambda r: r["total"] < 1000 or r["total"] > 10000),
        ("invoices between $1,000 and $3,000", lambda r: 1000 <= r["total"] <= 3000),
        (f"invoices not from {short}", lambda r: r["vendor"] != vendor),
        ("how many invoices are above $8,000?", lambda r: r["total"] > 8000),
        # Added after the second external review (conditions on extraction, grouping, vendor lists):
        (f"Extract totals from {short}", lambda r: r["vendor"] == vendor),
        (
            "Find invoices between $1,000 and $3,000 or above $10,000",
            lambda r: 1000 <= r["total"] <= 3000 or r["total"] > 10000,
        ),
        (f"Find invoices from {short} or {other_short}", lambda r: r["vendor"] in (vendor, other)),
    ]
    items = []
    for request, want in cases:
        res = agent.run_plan(agent.plan(request), ids, save=False)
        got = {r.name for r in res.records}
        expected = {f for f, r in files.items() if want(r)}
        items.append(
            {
                "request": request,
                "exact": got == expected,
                "returned": len(got),
                "expected": len(expected),
                "state": res.state.value,
            }
        )
    unsupported = ["Find invoices that were paid late", "invoices from last month", "top 3 invoices by total"]
    flagged = []
    for request in unsupported:
        res = agent.run_plan(agent.plan(request), ids, save=False)
        flagged.append(
            {
                "request": request,
                "flagged": res.state.value != "succeeded" and bool(res.not_understood),
                "not_understood": list(res.not_understood),
            }
        )
    sum_res = agent.run_plan(agent.plan("What is the sum of all invoice totals?"), ids, save=False)
    true_sum = round(sum(r["total"] for r in truth), 2)
    return {
        "exact_set_accuracy": round(sum(i["exact"] for i in items) / len(items), 3),
        "unsupported_flagged": f"{sum(f['flagged'] for f in flagged)}/{len(flagged)}",
        "sum_matches_truth": f"{true_sum:,.2f}" in sum_res.answer,
        "items": items,
        "unsupported": flagged,
    }


# ---------------------------------------------------------------- labelled planner / QA sets

PLANNER_SET = [
    ("Read all these invoices and create a CSV of vendor, date, tax, and total", "extract"),
    ("Find every contract that expires within 90 days", "filter"),
    ("Find all invoices above $5,000", "filter"),
    ("Compare these reports and explain the differences", "compare"),
    ("Extract all customer names and flag inconsistent records", "inconsistencies"),
    ("Find the paragraph supporting this answer and show me its location", "find"),
    ("Convert this collection of PDFs into searchable, structured knowledge", "process"),
    ("Summarize the quarterly reports", "summarize"),
    ("Give me an overview of the contracts", "summarize"),
    ("What is the total of the Globex invoice?", "ask"),
    ("Who is the vendor on invoice INV-2041?", "ask"),
    ("When does the cloud agreement expire?", "ask"),
    ("How many employees were there in Q2?", "ask"),
    ("What was revenue growth in Q2?", "ask"),
    ("Is there a termination clause?", "ask"),
    ("What is the sum of all invoice totals?", "aggregate"),
    ("What is the average tax across invoices?", "aggregate"),
    ("Which invoice has the highest total?", "aggregate"),
    ("How many invoices are there?", "count"),
    ("Count the contracts", "count"),
    ("List all invoices with tax over 500", "filter"),
    ("Show contracts ending in the next 6 months", "filter"),
    ("Pull out the invoice numbers and due dates", "extract"),
    ("Export vendors and totals to json", "extract"),
    ("Tabulate the payment terms of each invoice", "extract"),
    ("What changed between the Q1 and Q2 report?", "compare"),
    ("Flag duplicate vendors", "inconsistencies"),
    ("Are there discrepancies between invoice totals and subtotals?", "inconsistencies"),
    ("Where does it say the contract can be terminated?", "find"),
    ("Which page mentions the governing law?", "find"),
    ("Index this folder", "process"),
    ("What does the memo say about onboarding?", "ask"),
    ("tl;dr of the memo", "summarize"),
    ("invoices under $1,000", "filter"),
    ("What's the effective date of the office lease?", "ask"),
    ("contracts that expire before January 1, 2027", "filter"),
    ("Extract the customer, total and due date", "extract"),
    ("Compare invoice_acme.pdf vs invoice_globex.pdf", "compare"),
    ("What is the minimum invoice total?", "aggregate"),
    ("Summarize every document in one paragraph each", "summarize"),
]

QA_SET = [  # (question, expected substring, expected document)
    ("What is the total of the Globex invoice?", "2,640.00", "invoice_globex.pdf"),
    ("What is the invoice number of the Acme invoice?", "INV-2041", "invoice_acme.pdf"),
    ("How many employees were there in Q2?", "134", "report_q2.pdf"),
    ("How many employees were there in Q1?", "120", "report_q1.pdf"),
    ("What was revenue growth in Q2?", "17%", "report_q2.pdf"),
    ("What was the revenue in Q1?", "4.2 million", "report_q1.pdf"),
    ("How much notice is needed to terminate?", "sixty days", None),
    ("Which state's law governs the agreement?", "New York", None),
    ("What does the memo say about onboarding?", "14 days", "memo_untrusted.pdf"),
    ("What is the contract value of the office lease?", "120,000.00", "contract_office.pdf"),
    ("Who is the provider in the cloud services agreement?", "Stratus Cloud", "contract_cloud.pdf"),
    ("What are the payment terms on the Acme invoice?", "Net 30", "invoice_acme.pdf"),
]


def run_cli(*args: str) -> float:
    exe = Path(sys.executable).with_name("inklight.exe" if os.name == "nt" else "inklight")
    t = time.perf_counter()
    subprocess.run([str(exe), *args], capture_output=True, check=True)  # noqa: S603
    return time.perf_counter() - t


def main() -> None:  # noqa: C901 - a linear script
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--n", type=int, default=40)
    args = ap.parse_args()
    n = 10 if args.quick else args.n
    results: dict = {
        "env": {
            "python": platform.python_version(),
            "platform": f"{platform.system()} {platform.machine()}",
            "cpu_count": os.cpu_count(),
            "processor": platform.processor()[:60],
            "date": date.today().isoformat(),
        }
    }

    t = time.perf_counter()
    import inklight  # noqa: F401

    results["import_s"] = round(time.perf_counter() - t, 3)
    results["cli_version_s"] = round(statistics.median(run_cli("--version") for _ in range(3)), 3)

    from inklight import DocumentAgent
    from inklight.config import load_settings
    from inklight.ocr.indra import IndraEngine

    work = Path(tempfile.mkdtemp(prefix="inklight-bench-"))
    demo, synth = work / "demo", work / "synth"
    synth.mkdir()
    build(demo)
    truth = synth_invoices(synth, n)

    # --- OCR engine alone ------------------------------------------------
    engine = IndraEngine(load_settings(home=str(work / "h0")).ocr)
    t = time.perf_counter()
    engine.converter()
    results["indra_load_s"] = round(time.perf_counter() - t, 2)
    per_kind: dict[str, list[float]] = {"digital_pdf_page": [], "scanned_image_page": []}
    for row in truth:
        path = synth / row["file"]
        t = time.perf_counter()
        content = engine.read(path, max_pages=10)
        per_kind["scanned_image_page" if row["scanned"] else "digital_pdf_page"].append(
            (time.perf_counter() - t) * 1000 / max(len(content.pages), 1)
        )
    results["ocr_ms_per_page"] = {
        k: {"median": round(statistics.median(v), 1), "p90": round(sorted(v)[int(len(v) * 0.9) - 1], 1), "n": len(v)}
        for k, v in per_kind.items()
        if v
    }

    # --- end-to-end ingest + extraction accuracy (rules brain) ------------
    for brain in ("rules", "auto"):
        home = work / f"home-{brain}"
        agent = DocumentAgent(load_settings(home=str(home), models={"brain": brain}))
        t = time.perf_counter()
        report = agent.add([synth])
        ingest_s = time.perf_counter() - t
        t = time.perf_counter()
        records = agent.extract([synth], fields=["invoice_number", "vendor", "date", "subtotal", "tax", "total"])
        extract_s = time.perf_counter() - t
        by_name = {r.name: r for r in records}
        correct: dict[str, list[bool]] = {}
        flagged_wrong = 0
        wrong = 0
        for row in truth:
            rec = by_name.get(row["file"])
            for f in ("invoice_number", "vendor", "date", "subtotal", "tax", "total"):
                got = rec.fields[f].value if rec else None
                ok = (
                    abs(float(got) - row[f]) < 0.01
                    if isinstance(got, (int, float))
                    else str(got).strip(" .").lower() == str(row[f]).strip(" .").lower()
                )
                correct.setdefault(f, []).append(ok)
                if not ok:
                    wrong += 1
                    if rec and (rec.fields[f].warning or rec.fields[f].confidence < 0.7 or got is None):
                        flagged_wrong += 1
        acc = {f: round(sum(v) / len(v), 3) for f, v in correct.items()}
        scanned_acc = round(
            sum(
                ok
                for row, oks in zip(truth, zip(*correct.values(), strict=True), strict=True)
                if row["scanned"]
                for ok in oks
            )
            / max(sum(r["scanned"] for r in truth) * 6, 1),
            3,
        )
        digital_acc = round(
            sum(
                ok
                for row, oks in zip(truth, zip(*correct.values(), strict=True), strict=True)
                if not row["scanned"]
                for ok in oks
            )
            / max(sum(not r["scanned"] for r in truth) * 6, 1),
            3,
        )
        by_layout = {
            lay: round(
                sum(
                    ok
                    for row, oks in zip(truth, zip(*correct.values(), strict=True), strict=True)
                    if row["layout"] == lay
                    for ok in oks
                )
                / max(sum(r["layout"] == lay for r in truth) * 6, 1),
                3,
            )
            for lay in "ABC"
        }
        results[f"fidelity_{brain}"] = request_fidelity(agent, truth, by_name)
        results[f"extraction_{brain}"] = {
            "by_layout": by_layout,
            "documents": len(truth),
            "failed": len(report.failed),
            "ingest_s": round(ingest_s, 2),
            "pages_per_s": round(report.pages / ingest_s, 2) if ingest_s else None,
            "extract_s": round(extract_s, 2),
            "field_accuracy": acc,
            "overall_accuracy": round(sum(sum(v) for v in correct.values()) / (6 * len(truth)), 3),
            "digital_accuracy": digital_acc,
            "scanned_accuracy": scanned_acc,
            "wrong_values": wrong,
            "wrong_values_flagged": flagged_wrong,
            "brain": agent.library.brain.label(),
        }

        # --- QA + citations on the demo set --------------------------------
        agent.add([demo])
        demo_ids = [d.id for d in agent.library.documents() if Path(d.path).parent == demo.resolve()]
        qa = []
        for question, expect, doc in QA_SET:
            t = time.perf_counter()
            res = agent.run_plan(agent.plan(question), demo_ids, save=False)
            ms = (time.perf_counter() - t) * 1000
            hit = expect.lower() in res.answer.lower()
            cite = (
                bool(res.sources)
                and (doc is None or res.sources[0].name == doc)
                and any(expect.lower() in s.excerpt.lower() for s in res.sources[:3])
            )
            qa.append({"q": question, "correct": hit, "citation_ok": cite, "ms": round(ms, 1), "brain": res.brain})
        results[f"qa_{brain}"] = {
            "accuracy": round(sum(q["correct"] for q in qa) / len(qa), 3),
            "citation_accuracy": round(sum(q["citation_ok"] for q in qa) / len(qa), 3),
            "median_ms": round(statistics.median(q["ms"] for q in qa), 1),
            "max_ms": round(max(q["ms"] for q in qa), 1),
            "items": qa,
        }

        # --- task latency per intent ---------------------------------------
        lat = {}
        for request in [
            "Find all invoices above $5,000",
            "Compare these reports and explain the differences",
            "What is the sum of all invoice totals?",
            "Summarize the reports",
            "Find every contract that expires within 90 days",
        ]:
            t = time.perf_counter()
            res = agent.run_plan(agent.plan(request), demo_ids, save=False)
            lat[res.intent] = round((time.perf_counter() - t) * 1000, 1)
        results[f"task_latency_ms_{brain}"] = lat
        agent.close()

    # --- planner accuracy: rules vs the 135M writer as a zero-shot classifier -----------------
    from inklight.agent.planner import rule_plan

    rules_ok = sum(rule_plan(q).intent.value == want for q, want in PLANNER_SET)
    results["planner_rules"] = {"accuracy": round(rules_ok / len(PLANNER_SET), 3), "n": len(PLANNER_SET)}
    try:
        from inklight.brains import Brain

        writer_brain = Brain(load_settings(home=str(work / "hw"), models={"brain": "auto", "use_writer": True}))
        writer = writer_brain.writer
        if writer is not None:
            labels = [
                "ask",
                "find",
                "extract",
                "filter",
                "aggregate",
                "compare",
                "inconsistencies",
                "summarize",
                "count",
                "process",
            ]
            ok = 0
            t = time.perf_counter()
            for q, want in PLANNER_SET:
                prompt = writer.chat(
                    "Classify the document task into one category: " + ", ".join(labels) + ".", f"Task: {q}\nCategory:"
                )
                scores = writer.score(prompt, [" " + x for x in labels])
                ok += labels[max(range(len(labels)), key=scores.__getitem__)] == want
            results["planner_writer_135m"] = {
                "accuracy": round(ok / len(PLANNER_SET), 3),
                "n": len(PLANNER_SET),
                "ms_per_request": round((time.perf_counter() - t) * 1000 / len(PLANNER_SET), 1),
            }
    except Exception as exc:  # writer not installed
        results["planner_writer_135m"] = {"skipped": str(exc)}

    # --- where does ingest time go? (decides whether Rust is worth it) ---------------------------
    import cProfile
    import pstats

    prof_home = work / "home-prof"
    agent = DocumentAgent(load_settings(home=str(prof_home), models={"brain": "rules"}))
    pr = cProfile.Profile()
    pr.enable()
    agent.add([synth])
    pr.disable()
    agent.close()
    stats = pstats.Stats(pr)
    total = stats.total_tt  # type: ignore[attr-defined]
    buckets = {"indra_ocr_python": 0.0, "inklight_python": 0.0, "native_c_calls": 0.0, "other_python": 0.0}
    for (file, _line, _fn), (_cc, _nc, tt, _ct, _callers) in stats.stats.items():  # type: ignore[attr-defined]
        f = file.replace("\\", "/")
        if "indra_ocr" in f or "onnxruntime" in f or "pypdfium" in f or "cv2" in f:
            buckets["indra_ocr_python"] += tt
        elif "/inklight/" in f:
            buckets["inklight_python"] += tt
        elif file == "~":  # C functions: ONNX Runtime inference, pdfium, OpenCV, sqlite, hashing
            buckets["native_c_calls"] += tt
        else:
            buckets["other_python"] += tt
    results["ingest_profile_share"] = {k: round(v / total, 3) for k, v in buckets.items()}
    results["peak_rss_mb"] = peak_rss_mb()

    out = ROOT / "bench"
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in results.items() if not k.startswith("qa_")}, indent=2))
    for brain in ("rules", "auto"):
        qa = results[f"qa_{brain}"]
        print(
            brain,
            "QA",
            qa["accuracy"],
            "cite",
            qa["citation_accuracy"],
            [q["q"] for q in qa["items"] if not q["correct"]],
        )


if __name__ == "__main__":
    main()
