"""Document structure from Docling on top of Indra's OCR (optional: ``pip install "inklight[structure]"``).

Indra reads the text; Docling's existing models find the layout, reading order, headings, lists, tables (rows,
columns, spans, headers) and pictures; Inklight keeps the indexing, retrieval, answers, citations and review.
See docs/STRUCTURE.md for how the pieces connect and what is measured.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config import StructureSettings
from ..schemas import DocumentContent

log = logging.getLogger(__name__)

ENGINE = "docling"


@dataclass(frozen=True)
class Structured:
    content: DocumentContent  # the same pages and OCR lines, with Docling's blocks
    document_json: str  # the DoclingDocument, as Docling serialises it
    meta: dict[str, Any]


def available() -> bool:
    from .docling_run import available as docling_available

    return docling_available()


def structure_document(
    path: Path, content: DocumentContent, settings: StructureSettings, password: str | None = None
) -> Structured:
    """Run Docling on ``path`` with ``content``'s OCR lines as its text, and map its structure onto the pages."""
    from .adapter import adapt
    from .docling_run import run

    result = run(path, content, settings, password)
    adapted = adapt(result.document, list(content.pages), upright=result.upright)
    meta = {
        **adapted.meta,
        "components": result.components,
        "seconds": round(result.seconds, 2),
        "load_seconds": round(result.load_seconds, 2),
        "cells_delivered": result.cells_delivered,
        "pages_structured": result.pages,
    }
    return Structured(
        content=content.model_copy(update={"pages": tuple(adapted.pages)}),
        document_json=json.dumps(result.document.export_to_dict(), ensure_ascii=False),
        meta=meta,
    )


def load_document(document_json: str | None) -> Any | None:
    """A stored DoclingDocument, or None when there is none or docling-core is not installed."""
    if not document_json:
        return None
    try:
        from docling_core.types.doc import DoclingDocument
    except ImportError:
        log.warning("A stored document structure needs docling-core to be read: pip install docling-core")
        return None
    return DoclingDocument.model_validate_json(document_json)
