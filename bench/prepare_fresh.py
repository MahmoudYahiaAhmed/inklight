"""Prepare a fresh evaluation split that has not guided any development (run once).

    python -I bench/prepare_fresh.py --root <data dir> [--n 60]

* voxel51: the next annotated samples after dev and holdout, in the same sha1 order.
* cord: the *train* split (shard 0, downloaded to <root>/cord/train-00000.parquet), never used before.

Every candidate is checked against dev, holdout and the fresh documents already taken, and rejected if it
is an exact byte copy (sha256), a near copy of the pixels (64-bit difference hash, Hamming distance <= 4),
or has the same annotation (Voxel51: invoice number, or seller + client + total; CORD: identical parse).
The report goes to <root>/<dataset>/fresh/duplicates.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_external import VOXEL, _date, _key, _money  # noqa: E402

NEAR = 4


def dhash(data: bytes) -> int | None:
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    small = cv2.resize(img, (9, 8), interpolation=cv2.INTER_AREA).astype(np.int16)
    bits = (small[:, 1:] > small[:, :-1]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2)


class Seen:
    def __init__(self) -> None:
        self.sha: dict[str, str] = {}
        self.hashes: list[tuple[int, str]] = []
        self.notes: dict[str, str] = {}

    def add(self, name: str, data: bytes, note: str) -> None:
        self.sha[hashlib.sha256(data).hexdigest()] = name
        h = dhash(data)
        if h is not None:
            self.hashes.append((h, name))
        if note:
            self.notes[note] = name

    def duplicate_of(self, data: bytes, note: str) -> str | None:
        sha = hashlib.sha256(data).hexdigest()
        if sha in self.sha:
            return f"identical bytes to {self.sha[sha]}"
        h = dhash(data)
        if h is not None:
            for other, name in self.hashes:
                if bin(h ^ other).count("1") <= NEAR:
                    return f"near-identical pixels to {name} (dHash distance {bin(h ^ other).count('1')})"
        if note and note in self.notes:
            return f"same annotation as {self.notes[note]}"
        return None


def _voxel_note(ann: dict) -> str:
    inv, sub = ann.get("invoice", {}), ann.get("subtotal", {})
    return f"{inv.get('invoice_number')}|{inv.get('seller_name')}|{inv.get('client_name')}|{sub.get('total')}"


def fresh_voxel51(root: Path, n: int) -> dict:
    samples = json.loads((root / "voxel51" / "samples.json").read_text(encoding="utf-8"))["samples"]
    annotated = sorted((s for s in samples if s.get("json_annotation")), key=lambda s: _key(s["filepath"]))
    by_name = {Path(s["filepath"]).name: s for s in annotated}
    seen = Seen()
    for split in ("dev", "holdout"):
        for doc in sorted((root / "voxel51" / split / "docs").iterdir()):
            seen.add(
                f"{split}/{doc.name}", doc.read_bytes(), _voxel_note(json.loads(by_name[doc.name]["json_annotation"]))
            )
    out = root / "voxel51" / "fresh"
    (out / "docs").mkdir(parents=True, exist_ok=True)
    truth, rejected, checked = {}, [], 0
    for s in annotated[2 * n :]:
        if len(truth) == n:
            break
        name = Path(s["filepath"]).name
        target = out / "docs" / name
        if not target.exists():
            urllib.request.urlretrieve(VOXEL + s["filepath"], target)  # noqa: S310 - fixed https host
        data = target.read_bytes()
        ann = json.loads(s["json_annotation"])
        checked += 1
        dup = seen.duplicate_of(data, _voxel_note(ann))
        if dup:
            rejected.append({"candidate": name, "reason": dup})
            target.unlink()
            continue
        seen.add(f"fresh/{name}", data, _voxel_note(ann))
        inv, sub = ann.get("invoice", {}), ann.get("subtotal", {})
        truth[name] = {
            "vendor": inv.get("seller_name") or None,
            "customer": inv.get("client_name") or None,
            "invoice_number": inv.get("invoice_number") or None,
            "date": _date(inv.get("invoice_date")),
            "tax": _money(sub.get("tax")),
            "total": _money(sub.get("total")),
        }
    return _write(out, truth, rejected, checked, "voxel51 annotated samples after dev + holdout (sha1 order)")


def fresh_cord(root: Path, n: int) -> dict:
    import pyarrow.parquet as pq

    seen = Seen()
    for parquet in ("validation.parquet", "test.parquet"):  # dev and holdout come from these
        table = pq.read_table(root / "cord" / parquet).to_pylist()
        for idx, row in enumerate(table):  # the whole source splits, not only the sampled documents
            data = row["image"]["bytes"] if isinstance(row["image"], dict) else row["image"]
            seen.add(
                f"{parquet}:{idx}",
                data,
                json.dumps(json.loads(row["ground_truth"]).get("gt_parse", {}), sort_keys=True),
            )
    shard = "train-00000.parquet"
    table = pq.read_table(root / "cord" / shard).to_pylist()
    rows = sorted(enumerate(table), key=lambda r: _key(f"{shard}:{r[0]}"))
    out = root / "cord" / "fresh"
    (out / "docs").mkdir(parents=True, exist_ok=True)
    truth, rejected, checked = {}, [], 0
    for idx, row in rows:
        if len(truth) == n:
            break
        data = row["image"]["bytes"] if isinstance(row["image"], dict) else row["image"]
        gt = json.loads(row["ground_truth"]).get("gt_parse", {})
        note = json.dumps(gt, sort_keys=True)
        checked += 1
        dup = seen.duplicate_of(data, note)
        name = f"cord_fresh_{idx:03d}{'.png' if data[:4] == bytes([0x89, 0x50, 0x4E, 0x47]) else '.jpg'}"
        if dup:
            rejected.append({"candidate": name, "reason": dup})
            continue
        seen.add(f"fresh/{name}", data, note)
        (out / "docs" / name).write_bytes(data)
        total = gt.get("total", {}) if isinstance(gt.get("total"), dict) else {}
        sub = gt.get("sub_total", {}) if isinstance(gt.get("sub_total"), dict) else {}
        truth[name] = {
            "total": _money(total.get("total_price")),
            "subtotal": _money(sub.get("subtotal_price")),
            "tax": _money(sub.get("tax_price")),
        }
    return _write(out, truth, rejected, checked, f"CORD train split, {shard} (sha1 order)")


def _write(out: Path, truth: dict, rejected: list, checked: int, source: str) -> dict:
    (out / "truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    report = {
        "source": source,
        "taken": len(truth),
        "candidates_checked": checked,
        "rejected_as_duplicates": rejected,
        "checks": ["sha256 of bytes", f"dHash 64-bit, Hamming <= {NEAR}", "identical annotation"],
        "compared_against": "dev, holdout and the fresh documents already taken",
    }
    (out / "duplicates.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"{out}: {len(truth)} taken, {checked} checked, {len(rejected)} rejected as duplicates")
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--only", choices=["voxel51", "cord"], default=None)
    args = ap.parse_args()
    for name, fn in (("voxel51", fresh_voxel51), ("cord", fresh_cord)):
        if args.only in (None, name):
            if (args.root / name / "fresh" / "truth.json").exists():
                sys.exit(f"{name}/fresh already exists: the fresh split is prepared once")
            fn(args.root, args.n)


if __name__ == "__main__":
    main()
