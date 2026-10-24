"""Pilot intake: check permissions, keep cohorts apart, remove duplicates, assign the dev/reserved split.

    python -I pilot/intake.py --manifest manifest.csv --data <pilot data dir> [--reserved-share 0.4]

The manifest (see pilot/manifest_template.csv) has one row per document:

    file, cohort, vendor, layout, source, permission_ref, permission_scope, personal_data, redacted, notes

Rules (a row that breaks one is rejected, with the reason, and nothing is copied for it):

* ``cohort`` is genuine-invoice, synthetic-invoice or receipt. Cohorts are stored, reviewed and evaluated
  separately; nothing ever merges them.
* every document needs ``permission_ref`` (where the permission is recorded) and a ``permission_scope`` that
  includes "evaluation". Personal data must be redacted, or the scope must say "personal data".
* the file must exist, be a supported type and be at most 20 MB; identical files (sha256) are taken once.
* genuine invoices are split by **vendor**, not by document: every invoice of a vendor goes to the same
  group, so a fix made for one vendor's layout is never scored on that same vendor. ``reserved`` is about
  ``--reserved-share`` of the vendors, chosen by a salted hash that is recorded and never changes.

Output: copies under ``<data>/<cohort>/<split>/`` named by content hash (no personal names in file names),
and ``<data>/intake.json`` with every decision. Intake.json stays with the data: it holds vendor names.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench"))
from textnorm import fold  # noqa: E402

COHORTS = ("genuine-invoice", "synthetic-invoice", "receipt")
EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
MAX_BYTES = 20 * 1024 * 1024
COLUMNS = (
    "file",
    "cohort",
    "vendor",
    "layout",
    "source",
    "permission_ref",
    "permission_scope",
    "personal_data",
    "redacted",
    "notes",
)


def vendor_key(vendor: str) -> str:
    """'ACME Supplies, Ltd.' and 'Acme Supplies Ltd' are one vendor; names in any script stay distinct."""
    words = [fold(w) for w in re.split(r"[\s,./&()-]+", vendor)]
    words = [w for w in words if w]
    drop = {"ltd", "limited", "inc", "llc", "plc", "gmbh", "co", "corp", "corporation", "company", "the", "pt", "tbk"}
    return " ".join(w for w in words if w not in drop) or " ".join(words) or vendor.strip()


def split_for(vendor: str, salt: str, reserved_share: float) -> str:
    digest = hashlib.sha256(f"{salt}|{vendor_key(vendor)}".encode()).digest()
    return "reserved" if int.from_bytes(digest[:8], "big") / 2**64 < reserved_share else "dev"


def check_row(row: dict[str, str], base: Path) -> tuple[Path | None, str | None]:
    """The file to take, or the reason the row is rejected."""
    missing = [
        c for c in ("file", "cohort", "vendor", "permission_ref", "permission_scope") if not row.get(c, "").strip()
    ]
    if missing:
        return None, f"missing {', '.join(missing)}"
    if row["cohort"] not in COHORTS:
        return None, f"cohort must be one of {', '.join(COHORTS)}"
    if "evaluation" not in row["permission_scope"].lower():
        return None, "permission_scope does not include evaluation"
    personal = row.get("personal_data", "").strip().lower() in ("yes", "y", "true", "1")
    redacted = row.get("redacted", "").strip().lower() in ("yes", "y", "true", "1")
    if personal and not redacted and "personal data" not in row["permission_scope"].lower():
        return None, "contains personal data that is neither redacted nor covered by the permission scope"
    path = (base / row["file"]).resolve()
    if not path.is_file():
        return None, "file not found"
    if path.suffix.lower() not in EXTENSIONS:
        return None, f"unsupported file type {path.suffix}"
    if path.stat().st_size > MAX_BYTES:
        return None, "larger than 20 MB"
    return path, None


def intake(manifest: Path, data: Path, reserved_share: float, salt: str | None) -> dict:
    data.mkdir(parents=True, exist_ok=True)
    record_path = data / "intake.json"
    record = (
        json.loads(record_path.read_text(encoding="utf-8"))
        if record_path.exists()
        else {"salt": salt or hashlib.sha256(str(datetime.now(UTC)).encode()).hexdigest()[:16], "documents": []}
    )
    if salt and salt != record["salt"]:
        sys.exit("intake.json already uses another salt; the split must never change")
    if "reserved_share" in record and record["reserved_share"] != reserved_share:
        sys.exit("intake.json already uses another reserved share; the split must never change")
    record["reserved_share"] = reserved_share
    known = {d["sha256"] for d in record["documents"]}
    rejected, taken = [], 0
    with manifest.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        unknown = set(reader.fieldnames or ()) - set(COLUMNS)
        if unknown:
            sys.exit(f"unknown manifest columns: {', '.join(sorted(unknown))}")
        for line, row in enumerate(reader, start=2):
            row = {k: (v or "").strip() for k, v in row.items()}
            path, reason = check_row(row, manifest.parent)
            if path is None:
                rejected.append({"line": line, "file": row.get("file"), "reason": reason})
                continue
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if sha in known:
                rejected.append({"line": line, "file": row["file"], "reason": "duplicate of a document already taken"})
                continue
            split = (
                split_for(row["vendor"], record["salt"], reserved_share)
                if row["cohort"] == "genuine-invoice"
                else "dev"
            )
            target = data / row["cohort"] / split / f"{sha[:16]}{path.suffix.lower()}"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            record["documents"].append(
                {
                    "sha256": sha,
                    "stored_as": target.relative_to(data).as_posix(),
                    "original_name": path.name,
                    "cohort": row["cohort"],
                    "split": split,
                    "vendor": row["vendor"],
                    "vendor_group": vendor_key(row["vendor"]),
                    "layout": row.get("layout") or None,
                    "source": row.get("source") or None,
                    "permission_ref": row["permission_ref"],
                    "permission_scope": row["permission_scope"],
                    "personal_data": row.get("personal_data") or None,
                    "redacted": row.get("redacted") or None,
                    "taken_at": datetime.now(UTC).isoformat(timespec="seconds"),
                }
            )
            known.add(sha)
            taken += 1
    record_path.write_text(json.dumps(record, indent=1), encoding="utf-8")
    return {"taken": taken, "rejected": rejected, "summary": summary(record)}


def summary(record: dict) -> dict:
    out: dict = {}
    for d in record["documents"]:
        group = out.setdefault(d["cohort"], {}).setdefault(
            d["split"], {"documents": 0, "vendors": set(), "layouts": set()}
        )
        group["documents"] += 1
        group["vendors"].add(d["vendor_group"])
        if d["layout"]:
            group["layouts"].add(d["layout"])
    return {
        cohort: {
            split: {**g, "vendors": len(g["vendors"]), "layouts": len(g["layouts"])} for split, g in splits.items()
        }
        for cohort, splits in out.items()
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--reserved-share", type=float, default=0.4)
    ap.add_argument("--salt", default=None, help="Only for a reproducible test; normally generated once.")
    args = ap.parse_args()
    if not 0.2 <= args.reserved_share <= 0.6:
        sys.exit("--reserved-share must be between 0.2 and 0.6")
    result = intake(args.manifest, args.data, args.reserved_share, args.salt)
    print(json.dumps({k: v for k, v in result.items()}, indent=1))
    genuine = result["summary"].get("genuine-invoice", {})
    reserved = genuine.get("reserved", {"documents": 0, "vendors": 0})
    if genuine and (reserved["documents"] < 20 or reserved["vendors"] < 5):
        print(
            f"WARNING: the reserved group has {reserved['documents']} invoices from {reserved['vendors']} vendors; "
            "fewer than 20 invoices or 5 vendors gives a very wide uncertainty on later comparisons."
        )


if __name__ == "__main__":
    main()
