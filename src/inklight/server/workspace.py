"""The workspace's document views: structure status, and (from inklight.exports) tables and raw exports.

Everything here is what was read, as read: OCR text and boxes, and tables when document structure ran.
Nothing is reviewed or corrected here; exports say so in their first line. Approved values come from review
(review.py, /api/reviews/export).
"""

from __future__ import annotations

from typing import Any

from ..exports import RAW_NOTE, export, tables
from ..schemas import DocumentInfo, PageContent

__all__ = ["RAW_NOTE", "export", "structure_status", "tables"]


def structure_status(agent: Any, info: DocumentInfo, pages: list[PageContent]) -> dict[str, Any]:
    """Whether document structure is available, and on which pages, in words a person can act on."""
    engine = agent.settings.structure.engine
    stored = agent.library.structure(info.id)
    if stored is None:
        if engine == "none":
            reason = 'Structure is off (settings: [structure] engine = "none"): pages show OCR lines only.'
        elif info.engine == "text" or all(p.source == "text" and not p.lines for p in pages):
            reason = "Plain text file: no page layout to structure."
        else:
            reason = (
                "No structure stored: it was not run for this document, or it failed (see the import message). "
                "Pages show OCR lines only."
            )
        return {"available": False, "reason": reason, "pages": {}}
    meta, document = stored
    # A structure stored before pages were chosen (structure.pages = "tables") covers every page.
    structured = set(meta["pages_structured"]) if "pages_structured" in meta else {p.number for p in pages}
    kept = set(meta.get("rotated_pages_kept") or [])
    upright = set(meta.get("rotated_pages_structured") or [])
    per_page = {}
    for p in pages:
        if p.number in kept:
            per_page[p.number] = "OCR layout only (this page's frame did not match the structure)"
        elif p.number in structured:
            turned = f", page turned {p.rotation}° and structured upright" if p.number in upright else ""
            per_page[p.number] = f"structured{turned}"
        else:
            per_page[p.number] = "not structured (no table found on this page); OCR layout only"
    return {
        "available": True,
        "reason": "",
        "tables": int(meta.get("tables", 0)),
        "components": meta.get("components", {}),
        "text_stored": document is not None,
        "pages": per_page,
    }
