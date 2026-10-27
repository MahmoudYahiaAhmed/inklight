"""The selected examples and limitations shown in evaluation/REPORT.md, produced by the build under test.

    python -I evaluation/report/examples.py --un-letter S_2025_380-ar.pdf --out evaluation/report/examples

Everything written here is Inklight's own output on the public or synthetic documents named below: answers,
sources, tables, extracted fields and the reviewed export. Page images are rendered from the files themselves, with
the boxes Inklight reported drawn on the page as the file shows it (``frames.to_original``). Nothing is edited by
hand. ``S_2025_380-ar.pdf`` is the Arabic UN Security Council document S/2025/380, from
``https://documents.un.org/api/symbol/access?s=S/2025/380&l=ar&t=pdf`` (not redistributed in the repository).
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from inklight import DocumentAgent, __version__
from inklight.config import Settings
from inklight.frames import original_size, to_original
from inklight.server.render import render_page

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "examples" / "documents"
INK = (0, 168, 204)  # the report's accent; one colour for every box Inklight reported


def _source(s: Any) -> dict[str, Any] | None:
    return None if s is None else {"page": s.page, "bbox": list(s.bbox) if s.bbox else None, "excerpt": s.excerpt}


def crop(
    agent: DocumentAgent, doc_id: str, page_no: int, boxes: list, out: Path, pad: tuple[int, int] = (240, 120)
) -> dict[str, Any]:
    """The page as the file shows it, cut around ``boxes`` (upright frame), with each box outlined."""
    doc = agent.library.get(doc_id)
    page = next(p for p in agent.library.pages(doc_id) if p.number == page_no)
    png = render_page(Path(doc.path), page_no, page, agent.settings.ocr.dpi)
    img = Image.open(io.BytesIO(png)).convert("RGB")
    ow, oh = original_size(page.rotation, page.width, page.height)
    sx, sy = img.width / ow, img.height / oh
    shown = [to_original(tuple(b), page.rotation, page.width, page.height) for b in boxes]
    px = [(b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy) for b in shown]
    draw = ImageDraw.Draw(img)
    for b in px:
        draw.rectangle(b, outline=INK, width=4)
    x0 = max(0, min(b[0] for b in px) - pad[0])
    y0 = max(0, min(b[1] for b in px) - pad[1])
    x1 = min(img.width, max(b[2] for b in px) + pad[0])
    y1 = min(img.height, max(b[3] for b in px) + pad[1])
    img.crop((int(x0), int(y0), int(x1), int(y1))).save(out, optimize=True)
    return {"image": out.name, "page_rotation": page.rotation, "boxes_upright": [list(b) for b in boxes]}


def page_image(agent: DocumentAgent, doc_id: str, out: Path, width: int = 900) -> str:
    doc = agent.library.get(doc_id)
    page = agent.library.pages(doc_id)[0]
    img = Image.open(io.BytesIO(render_page(Path(doc.path), 1, page, agent.settings.ocr.dpi))).convert("RGB")
    img.thumbnail((width, width * 2))
    img.save(out, optimize=True)
    return out.name


def ask(agent: DocumentAgent, question: str, files: list[Path]) -> dict[str, Any]:
    r = agent.ask(question, files=files, save=False)
    return {
        "request": question,
        "state": r.state.value,
        "outcome": r.outcome,
        "answer": r.answer,
        "warnings": list(r.warnings),
        "sources": [_source(s) for s in r.sources[:3]],
        "_doc_id": r.sources[0].doc_id if r.sources else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--un-letter", type=Path, required=True, help="S_2025_380-ar.pdf (public UN document)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--home", type=Path, help="library folder (default: <out>/.home, removed afterwards by you)")
    args = ap.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    settings = Settings(home=args.home or out / ".home").with_overrides(
        models={"brain": "rules"}, structure={"engine": "inklight"}
    )
    examples: dict[str, Any] = {"inklight_version": __version__, "brain": "rules", "structure": "inklight"}
    card, suppliers = DOCS / "registration-card-turned.pdf", DOCS / "suppliers.pdf"
    with DocumentAgent(settings) as agent:
        # 1. Arabic: who signed a public UN letter, with the line it came from
        signer = ask(agent, "من وقع الرسالة؟", [args.un_letter])
        signer["crop"] = crop(
            agent, signer["_doc_id"], 1, [signer["sources"][0]["bbox"]], out / "arabic-signer.png", (700, 260)
        )
        examples["arabic_signer"] = signer

        # 2. Tables whose values stay under their headings (synthetic)
        examples["tables"] = {"file": suppliers.name, "tables": agent.tables(suppliers)}
        examples["tables"]["page"] = page_image(agent, agent.library.find(suppliers.name).id, out / "suppliers.png")

        # 3. A turned page: a value from a table cell, its box drawn on the page as the file shows it (synthetic)
        share = ask(agent, "What is Laila Mansour's share?", [card])
        share["crop"] = crop(
            agent, share["_doc_id"], 1, [share["sources"][0]["bbox"]], out / "turned-share.png", (330, 520)
        )
        examples["turned_share"] = share

        # 4. The same fields compared across two documents (synthetic invoices)
        records = agent.extract(
            [DOCS / "invoice_acme.pdf", DOCS / "invoice_globex.pdf"], fields=["invoice number", "total"]
        )
        examples["invoices"] = [
            {"file": r.name, **{k: {"value": v.value, "source": _source(v.source)} for k, v in r.fields.items()}}
            for r in records
        ]

        # 5. An ambiguous request: two tables answer it, so both are listed (synthetic)
        examples["ambiguous"] = ask(agent, "What is the company name?", [suppliers])

        # 6. Review: extracted values checked, one corrected, approved and exported with provenance (synthetic)
        rec = agent.extract(card, fields=["company name", "tax office"])[0]
        doc = agent.library.get(rec.doc_id)
        store = agent.reviews
        review = store.open(doc, rec, ["company_name", "tax_office"], reviewer="example reviewer")
        store.decide(
            review.id, "company_name", reviewer="example reviewer", action="corrected", value="Golden Palm Trading Co."
        )
        store.decide(review.id, "tax_office", reviewer="example reviewer", action="accepted")
        store.approve(review.id, reviewer="example reviewer")
        exported = store.export("csv", actor="example reviewer")
        (out / "review-export.csv").write_text(exported, encoding="utf-8")
        examples["review"] = {
            "predicted": {k: v.value for k, v in rec.fields.items()},
            "export": "review-export.csv",
        }

        # Limitations, on the same documents
        examples["limit_turned_card_extract"] = {
            "fields": {
                k: v.value
                for k, v in agent.extract(card, fields=["company name", "registration number"])[0].fields.items()
            },
            "tables": agent.tables(card),
            "registration_number_by_question": ask(agent, "What is the registration number?", [card])["answer"],
        }
        hits = agent.search("مجلس الأمن", k=1)
        letter = hits[0].source.doc_id
        head = next(ln for ln in agent.library.pages(letter)[0].lines if ln.text.strip() == "جلس الأمن")
        examples["limit_arabic_letterhead"] = {
            "query": "مجلس الأمن",
            "first_hit": _source(hits[0].source),
            "line": {"text": head.text, "conf": head.conf, "bbox": list(head.bbox)},
            "crop": crop(agent, letter, 1, [head.bbox], out / "arabic-letterhead.png", (500, 90)),
        }
        examples["limit_arabic_date"] = ask(agent, "ما تاريخ الرسالة؟", [args.un_letter])
    for v in examples.values():
        if isinstance(v, dict):
            v.pop("_doc_id", None)
    (out / "examples.json").write_text(json.dumps(examples, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out / 'examples.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
