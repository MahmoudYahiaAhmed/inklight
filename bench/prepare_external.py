"""Prepare external evaluation sets (run once, in the dev environment).

    python bench/prepare_external.py --root <data dir> [--n 60]

Writes, per dataset and split, original document images plus a ground-truth JSON:

* ``voxel51``: Voxel51/high-quality-invoice-images-for-ocr (ODbL), **synthetic** invoices.
  Ground truth = its JSON annotation. Its ``ocr_text`` is saved separately as a
  reference-text diagnostic, never mixed into pipeline results.
* ``cord``: naver-clova-ix/cord-v2 (CC-BY-4.0), **genuine** photographed receipts
  (Indonesia, IDR). validation -> dev, test -> holdout.

Splits are deterministic (sha1 of the source id), so the holdout never changes.
Downloaded files are untrusted data: images and JSON only, nothing is executed.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import urllib.request
from datetime import datetime
from pathlib import Path

VOXEL = "https://huggingface.co/datasets/Voxel51/high-quality-invoice-images-for-ocr/resolve/main/"


def _key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _money(raw: str | None) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip().replace(" ", "")
    if not s:
        return None
    digits = "".join(ch for ch in s if ch.isdigit() or ch in ".,")
    if not digits:
        return None
    # Two decimals after the last separator = cents; otherwise separators group thousands (IDR "60.000").
    last = max(digits.rfind("."), digits.rfind(","))
    if last >= 0 and len(digits) - last - 1 == 2:
        whole = digits[:last].replace(".", "").replace(",", "")
        return float(f"{whole}.{digits[last + 1 :]}")
    return float(digits.replace(".", "").replace(",", ""))


def _date(raw: str | None) -> str | None:
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def prepare_voxel51(root: Path, n: int) -> None:
    src = root / "voxel51" / "samples.json"
    samples = json.loads(src.read_text(encoding="utf-8"))["samples"]
    annotated = sorted((s for s in samples if s.get("json_annotation")), key=lambda s: _key(s["filepath"]))
    splits = {"dev": annotated[:n], "holdout": annotated[n : 2 * n]}
    for split, rows in splits.items():
        out = root / "voxel51" / split
        (out / "docs").mkdir(parents=True, exist_ok=True)
        (out / "reference_text").mkdir(exist_ok=True)
        truth = {}
        for s in rows:
            name = Path(s["filepath"]).name
            target = out / "docs" / name
            if not target.exists():
                urllib.request.urlretrieve(VOXEL + s["filepath"], target)  # noqa: S310 - fixed https host
            ann = json.loads(s["json_annotation"])
            inv, sub = ann.get("invoice", {}), ann.get("subtotal", {})
            truth[name] = {
                "vendor": inv.get("seller_name") or None,
                "customer": inv.get("client_name") or None,
                "invoice_number": inv.get("invoice_number") or None,
                "date": _date(inv.get("invoice_date")),
                "tax": _money(sub.get("tax")),
                "total": _money(sub.get("total")),
            }
            (out / "reference_text" / f"{Path(name).stem}.txt").write_text(s.get("ocr_text") or "", encoding="utf-8")
        (out / "truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
        print(f"voxel51/{split}: {len(truth)} documents")


def prepare_cord(root: Path, n: int) -> None:
    import pyarrow.parquet as pq

    for split, parquet in (("dev", "validation.parquet"), ("holdout", "test.parquet")):
        table = pq.read_table(root / "cord" / parquet).to_pylist()
        rows = sorted(enumerate(table), key=lambda r: _key(f"{parquet}:{r[0]}"))[:n]
        out = root / "cord" / split
        (out / "docs").mkdir(parents=True, exist_ok=True)
        truth = {}
        for idx, row in rows:
            image = row["image"]
            data = image["bytes"] if isinstance(image, dict) else image
            ext = ".png" if data[:4] == b"\x89PNG" else ".jpg"
            name = f"cord_{split}_{idx:03d}{ext}"
            (out / "docs" / name).write_bytes(data)
            gt = json.loads(row["ground_truth"]).get("gt_parse", {})
            total = gt.get("total", {}) if isinstance(gt.get("total"), dict) else {}
            sub = gt.get("sub_total", {}) if isinstance(gt.get("sub_total"), dict) else {}
            truth[name] = {
                "total": _money(total.get("total_price")),
                "subtotal": _money(sub.get("subtotal_price")),
                "tax": _money(sub.get("tax_price")),
            }
        (out / "truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
        print(f"cord/{split}: {len(truth)} documents ({io.StringIO().getvalue() or 'images + truth.json'})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--only", choices=["voxel51", "cord"], default=None)
    args = ap.parse_args()
    if args.only in (None, "voxel51"):
        prepare_voxel51(args.root, args.n)
    if args.only in (None, "cord"):
        prepare_cord(args.root, args.n)


if __name__ == "__main__":
    main()
