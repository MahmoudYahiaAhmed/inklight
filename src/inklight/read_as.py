"""How a document's text was obtained, in the same words wherever it is shown (workspace, CLI, API).

Each stored page records its source: ``plain`` (a .txt or .md file, read as it is), ``text`` (a PDF's own text layer),
``ocr`` (recognised from the image), ``hybrid`` (a PDF page where the text layer was completed by OCR) or ``error``.
Only a page read by OCR is called OCR: a text file never is.
"""

from __future__ import annotations

from collections.abc import Mapping

METHODS = {
    "plain": "plain text",
    "text": "PDF text layer",
    "hybrid": "PDF text layer and OCR",
    "ocr": "OCR",
    "error": "page failed",
}


def method(source: str) -> str:
    """One page's source in words; an unknown source is shown as it is, never assumed to be OCR."""
    return METHODS.get(source, source or "unknown")


def read_as(counts: Mapping[str, int]) -> str:
    """A document's pages by source, in words: "plain text", "OCR", or "mixed: 2 pages PDF text layer, 1 page OCR"."""
    read = {k: n for k, n in counts.items() if n and k != "error"}
    if not read:
        return "page failed" if counts.get("error") else ""
    if len(read) == 1:
        return method(next(iter(read)))
    parts = [f"{n} page{'s' if n != 1 else ''} {method(k)}" for k, n in sorted(read.items(), key=lambda kv: -kv[1])]
    return "mixed: " + ", ".join(parts)
