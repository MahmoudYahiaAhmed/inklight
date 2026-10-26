"""Prepare a private document set for the agent-run evaluation (nothing here is committed with document content).

    python bench/agent_eval/prepare_docs.py SOURCE_DIR WORKSPACE

For every PDF or image under SOURCE_DIR (one sub-folder per organisation/source):
- copies it to WORKSPACE/docs/<doc_id><ext>, with a pseudonymous id <group>-<nn> (the group keeps one source's
  documents together when splitting);
- records SHA-256, size, page count, whether the PDF has a text layer, and the original relative path;
- renders every page to WORKSPACE/pages/<doc_id>/p<n>.png (150 dpi) for the reference author and the judge;
- computes a perceptual hash per page and lists near-duplicate pages across documents.

The manifest (WORKSPACE/manifest.json) keeps the original names; the repository only ever gets the pseudonymous ids.
Needs PyMuPDF and Pillow.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pymupdf
from PIL import Image

KINDS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}


def dhash(img: Image.Image, size: int = 16) -> int:
    small = img.convert("L").resize((size + 1, size))
    px = list(small.getdata())
    bits = 0
    for row in range(size):
        for col in range(size):
            bits = (bits << 1) | (px[row * (size + 1) + col] > px[row * (size + 1) + col + 1])
    return bits


def main() -> None:
    source, work = Path(sys.argv[1]), Path(sys.argv[2])
    (work / "docs").mkdir(parents=True, exist_ok=True)
    (work / "pages").mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in KINDS)
    groups: dict[str, str] = {}
    manifest, hashes = [], []
    for path in files:
        group_key = path.parent.relative_to(source).as_posix() or "."
        group = groups.setdefault(group_key, f"g{len(groups) + 1:02d}")
        n = sum(1 for m in manifest if m["group"] == group) + 1
        doc_id = f"{group}-{n:02d}"
        data = path.read_bytes()
        target = work / "docs" / f"{doc_id}{path.suffix.lower()}"
        shutil.copyfile(path, target)
        entry = {
            "doc_id": doc_id,
            "group": group,
            "original": path.relative_to(source).as_posix(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }
        out = work / "pages" / doc_id
        out.mkdir(exist_ok=True)
        if path.suffix.lower() == ".pdf":
            doc = pymupdf.open(target)
            entry["pages"] = doc.page_count
            entry["text_layer_chars"] = sum(len(p.get_text().strip()) for p in doc)
            for i, page in enumerate(doc, 1):
                pix = page.get_pixmap(dpi=150)
                png = out / f"p{i}.png"
                pix.save(png)
                hashes.append((doc_id, i, dhash(Image.open(png))))
            doc.close()
        else:
            img = Image.open(target)
            entry["pages"] = 1
            entry["text_layer_chars"] = 0
            img.convert("RGB").save(out / "p1.png")
            hashes.append((doc_id, 1, dhash(img)))
        manifest.append(entry)
        print(doc_id, entry["pages"], "pages", entry["original"], flush=True)
    near = []
    for i, (d1, p1, h1) in enumerate(hashes):
        for d2, p2, h2 in hashes[i + 1 :]:
            if bin(h1 ^ h2).count("1") <= 12:
                near.append({"a": f"{d1} p{p1}", "b": f"{d2} p{p2}", "distance": bin(h1 ^ h2).count("1")})
    (work / "manifest.json").write_text(
        json.dumps({"documents": manifest, "near_duplicate_pages": near}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"{len(manifest)} documents, {sum(m['pages'] for m in manifest)} pages, {len(near)} near-duplicate page pairs")


if __name__ == "__main__":
    main()
