"""Inklight document structure on top of Inklight OCR (optional: ``pip install "inklight[structure]"``).

The OCR reads the text; the structure models find the layout, reading order, headings, lists, tables (rows,
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

ENGINE = "inklight"


@dataclass(frozen=True)
class Structured:
    content: DocumentContent  # the same pages and OCR lines, with the structure's blocks
    document_json: str  # the structured document (docling-core's DoclingDocument format)
    meta: dict[str, Any]


def available() -> bool:
    from .run import available as runtime_available

    return runtime_available()


def structure_document(
    path: Path, content: DocumentContent, settings: StructureSettings, password: str | None = None
) -> Structured:
    """Structure ``path`` with ``content``'s OCR lines as its text, and map the structure onto the pages."""
    from .adapter import adapt
    from .run import run

    result = run(path, content, settings, password)
    adapted = adapt(result.document, list(content.pages), upright=result.upright)
    meta = {
        **adapted.meta,
        "components": result.components,
        "seconds": round(result.seconds, 2),
        "load_seconds": round(result.load_seconds, 2),
        "cells_delivered": result.cells_delivered,
        "pages_structured": result.pages,
        "pages_without_text": result.without_text,  # structured with no OCR text cells: their layout keeps no text
    }
    return Structured(
        content=content.model_copy(update={"pages": tuple(adapted.pages)}),
        document_json=json.dumps(result.document.export_to_dict(), ensure_ascii=False),
        meta=meta,
    )


def load_document(document_json: str | None) -> Any | None:
    """A stored structured document, or None when there is none or docling-core is not installed."""
    if not document_json:
        return None
    try:
        from docling_core.types.doc import DoclingDocument
    except ImportError:
        log.warning('A stored document structure needs the structure runtime: pip install "inklight[structure]"')
        return None
    return DoclingDocument.model_validate_json(document_json)
