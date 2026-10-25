"""Visual rows: the lines that sit side by side on a page, whatever order OCR read them in.

Forms, receipts and invoices print a label and its value on one row, and OCR often reads the labels as one block
and the values as another ("SubTotal", "VAT", "Total" … then "61.40", "8.60", "70.00"). Grouping the lines of each
row, in the reading direction of its script, gives "VAT 8.60" back. Each row keeps its page and bounding box, so an
answer taken from it cites the exact place on the page.

Rows are disjoint: lines are taken top to bottom and each joins the row of the line that opened it, so one tall line
cannot merge two rows into a third, overlapping one.
"""

from __future__ import annotations

from ..extract import layout
from ..schemas import BBox, Source, TextLine
from .context import ToolContext

_MAX_DOCS = 3
_MAX_PAGES = 5


def visual_rows(ctx: ToolContext, doc_ids: list[str]) -> list[Source]:
    """Rows of two or more lines on the pages of ``doc_ids``, as sources whose excerpt is the row's text."""
    out: list[Source] = []
    for doc_id in doc_ids[:_MAX_DOCS]:
        if doc_id not in ctx.rows:
            ctx.rows[doc_id] = _rows_of(ctx, doc_id)
        out += ctx.rows[doc_id]
    return out


def _rows_of(ctx: ToolContext, doc_id: str) -> list[Source]:
    doc = ctx.library.get(doc_id)
    if doc is None:
        return []
    out: list[Source] = []
    for page in ctx.pages(doc_id)[:_MAX_PAGES]:
        for cells in _cluster([ln for ln in page.lines if ln.bbox is not None and ln.text.strip()]):
            if len(cells) < 2:
                continue
            text = " ".join(c.text for c in cells)
            right_to_left = layout.rtl(text)
            cells.sort(key=lambda c: -c.bbox[2] if right_to_left else c.bbox[0])  # type: ignore[index]
            confs = [c.conf for c in cells if c.conf is not None]
            out.append(
                Source(
                    doc_id=doc_id,
                    path=doc.path,
                    name=doc.name,
                    page=page.number,
                    bbox=_union([c.bbox for c in cells]),  # type: ignore[misc]
                    excerpt=" ".join(c.text.strip() for c in cells),
                    ocr_conf=min(confs) if confs else None,
                )
            )
    return out


def _cluster(lines: list[TextLine]) -> list[list[TextLine]]:
    """Disjoint rows, top to bottom: a line joins the open row when it shares the row with that row's first line."""
    rows: list[list[TextLine]] = []
    for ln in sorted(lines, key=lambda x: (x.bbox[1] + x.bbox[3]) / 2):  # type: ignore[index]
        if rows and layout.same_row(rows[-1][0].bbox, ln.bbox):  # type: ignore[arg-type]
            rows[-1].append(ln)
        else:
            rows.append([ln])
    return rows


def _union(boxes: list[BBox]) -> BBox:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
