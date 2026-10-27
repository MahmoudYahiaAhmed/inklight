"""Raw exports of what was read: a document's text, its tables and everything with boxes.

Everything here is what was read, as read: OCR text and boxes, and tables when document structure ran. Nothing is
reviewed or corrected; every export says so. Approved values come from review (review.py).
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from .schemas import DocumentInfo

RAW_NOTE = (
    "Raw extraction as read by OCR (and document structure for tables): not reviewed. OCR confidence is an estimate."
)


def tables(agent: Any, doc_id: str) -> list[dict[str, Any]]:
    stored = agent.library.structure(doc_id)
    if stored is None or stored[1] is None:
        return []
    from .structure.adapter import table_grid

    document = stored[1]
    out = []
    for k, table in enumerate(document.tables):
        grid = table_grid(table, document)
        if not grid.rows:
            continue
        out.append(
            {
                "index": k + 1,
                "page": table.prov[0].page_no if table.prov else None,
                "header_rows": sorted(grid.header_rows),
                "rows": grid.rows,
            }
        )
    return out


def export(agent: Any, info: DocumentInfo, fmt: str) -> tuple[str, str, str]:
    """(body, media type, file suffix) of a raw export."""
    pages = agent.library.pages(info.id)
    if fmt == "txt":
        parts = [f"# {RAW_NOTE}", f"# Document: {info.name}"]
        for p in pages:
            parts.append(f"\n===== page {p.number} =====\n")
            parts.append(p.markdown or "\n".join(line.text for line in p.lines))
        return "\n".join(parts) + "\n", "text/plain; charset=utf-8", "txt"
    if fmt == "json":
        data = {
            "note": RAW_NOTE,
            "document": info.model_dump(mode="json", exclude={"path"}),  # no local path in a file meant to be shared
            "pages": [
                {
                    "number": p.number,
                    "rotation": p.rotation,
                    "width": p.width,
                    "height": p.height,
                    "source": p.source,
                    "lines": [{"text": x.text, "bbox": x.bbox, "ocr_conf": x.conf} for x in p.lines],
                    "blocks": [{"label": b.label, "text": b.text, "bbox": b.bbox} for b in p.blocks],
                }
                for p in pages
            ],
            "tables": tables(agent, info.id),
        }
        return json.dumps(data, ensure_ascii=False, indent=1), "application/json", "json"
    if fmt == "tables.csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        # The note goes in a column of its own, so the first row stays the header for spreadsheets and pandas.
        writer.writerow(["table", "page", "row", "column", "header", "text", "note"])
        note = [RAW_NOTE + " Cells starting with = + - @ are prefixed with ' (spreadsheet safety)."]
        for t in tables(agent, info.id):
            for r, row in enumerate(t["rows"]):
                for c, text in enumerate(row):
                    writer.writerow(
                        [t["index"], t["page"], r + 1, c + 1, r in t["header_rows"], _safe_cell(text), *note]
                    )
                    note = []
        return "﻿" + buf.getvalue(), "text/csv; charset=utf-8", "tables.csv"
    raise ValueError("format must be txt, json or tables.csv")


def _safe_cell(text: str) -> str:
    """A cell that a spreadsheet would read as a formula is prefixed with a quote."""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text
