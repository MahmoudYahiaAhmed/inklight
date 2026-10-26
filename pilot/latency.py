"""Latency with and without the second OCR reading, on development data only.

    python -I pilot/latency.py --data <evaldata root> --datasets voxel51 cord --split dev --repeats 3 \
        --out <results dir> [--config <pilot-config.toml>]

For each dataset the documents are ingested once (OCR, timed separately). Then every document is extracted
on its own, with ``extraction.second_reading`` on and off in alternating order (on/off, off/on, ...), so
warm-up does not favour either setting. Every crop re-read is counted and timed. Reported per setting:
median, p90, mean and total seconds per document, and the number and time of second readings.

Use development splits only: the latency of the second reading depends on how many amounts trigger it, and
a reserved or fresh split must not be opened for this.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from pathlib import Path

FIELDS = {
    "voxel51": ["vendor", "customer", "invoice_number", "date", "tax", "total"],
    "cord": ["total", "subtotal", "tax"],
}


class Counted:
    """Wraps IndraEngine.reread to count and time every second reading."""

    def __init__(self) -> None:
        from inklight.ocr.engine import InklightOCR as IndraEngine

        self.calls = 0
        self.seconds = 0.0
        original = IndraEngine.reread

        def reread(engine, *args, **kwargs):  # type: ignore[no-untyped-def]
            t = time.perf_counter()
            try:
                return original(engine, *args, **kwargs)
            finally:
                self.calls += 1
                self.seconds += time.perf_counter() - t

        IndraEngine.reread = reread  # type: ignore[method-assign]

    def take(self) -> tuple[int, float]:
        out = (self.calls, self.seconds)
        self.calls, self.seconds = 0, 0.0
        return out


def p90(values: list[float]) -> float:
    s = sorted(values)
    return s[max(0, int(round(0.9 * len(s))) - 1)]


def run_dataset(data: Path, dataset: str, split: str, repeats: int, work: Path, base: dict, counted: Counted) -> dict:
    from inklight import DocumentAgent, load_settings

    docs = data / dataset / split / "docs"
    home = work / f"home-{dataset}"
    settings = load_settings(None, **{**base, "home": str(home)})
    t0 = time.perf_counter()
    with DocumentAgent(settings) as agent:
        report = agent.add(docs)
    ingest = time.perf_counter() - t0
    paths = sorted(p for p in docs.iterdir() if p.is_file())
    timings: dict[bool, list[float]] = {True: [], False: []}
    rereads: dict[bool, list[int]] = {True: [], False: []}
    reread_seconds: dict[bool, float] = {True: 0.0, False: 0.0}
    for rep in range(repeats):
        order = (True, False) if rep % 2 == 0 else (False, True)
        for enabled in order:
            s = load_settings(None, **{**base, "home": str(home), "extraction": {"second_reading": enabled}})
            with DocumentAgent(s) as agent:
                counted.take()
                for p in paths:
                    t = time.perf_counter()
                    agent.extract([p], fields=FIELDS[dataset])
                    timings[enabled].append(time.perf_counter() - t)
                calls, secs = counted.take()
                rereads[enabled].append(calls)
                reread_seconds[enabled] += secs

    def summary(enabled: bool) -> dict:
        v = timings[enabled]
        return {
            "documents": len(paths),
            "measurements": len(v),
            "median_s": round(statistics.median(v), 4),
            "p90_s": round(p90(v), 4),
            "mean_s": round(statistics.mean(v), 4),
            "total_s_per_pass": round(sum(v) / repeats, 3),
            "second_readings_per_pass": rereads[enabled],
            "second_reading_s_per_pass": round(reread_seconds[enabled] / repeats, 3),
        }

    on, off = summary(True), summary(False)
    return {
        "dataset": dataset,
        "split": split,
        "documents": len(paths),
        "ingest_failed": len(report.failed),
        "ingest_s_total": round(ingest, 2),
        "ingest_s_per_document": round(ingest / max(len(paths), 1), 3),
        "second_reading_on": on,
        "second_reading_off": off,
        "added_per_document_median_s": round(on["median_s"] - off["median_s"], 4),
        "added_per_document_mean_s": round(on["mean_s"] - off["mean_s"], 4),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--datasets", nargs="+", default=["voxel51", "cord"], choices=sorted(FIELDS))
    ap.add_argument("--split", default="dev", choices=["dev"])
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--work", required=True, type=Path, help="An empty folder for the measurement libraries.")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--config", type=Path, default=None, help="Pilot config: models and OCR folders, brain.")
    args = ap.parse_args()
    if args.work.exists() and any(args.work.iterdir()):
        sys.exit(f"--work {args.work} is not empty")
    import inklight
    from inklight.config import load_settings

    base_settings = load_settings(args.config) if args.config else load_settings(None, models={"brain": "rules"})
    base = {k: v for k, v in base_settings.model_dump(mode="json").items() if k in ("models", "ocr", "limits")}
    counted = Counted()
    results = {
        "inklight_version": inklight.__version__,
        "inklight_file": inklight.__file__,
        "python": platform.python_version(),
        "machine": f"{platform.system()} {platform.machine()} ({platform.processor()})",
        "brain": base_settings.models.brain,
        "repeats": args.repeats,
        "datasets": [
            run_dataset(args.data, d, args.split, args.repeats, args.work, base, counted) for d in args.datasets
        ],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "latency.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    for d in results["datasets"]:
        on, off = d["second_reading_on"], d["second_reading_off"]
        print(
            f"{d['dataset']}/{d['split']} ({d['documents']} docs): "
            f"extract median on {on['median_s']}s / off {off['median_s']}s, "
            f"p90 {on['p90_s']}s / {off['p90_s']}s; second readings per pass {on['second_readings_per_pass']}; "
            f"OCR ingest {d['ingest_s_per_document']}s/doc"
        )


if __name__ == "__main__":
    main()
