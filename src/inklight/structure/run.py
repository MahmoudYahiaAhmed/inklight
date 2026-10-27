"""Running Inklight document structure on a document the OCR has already read.

The structure stages (``inklight.backends.structure``) find the layout (text, headings, lists, tables, pictures,
captions), recover each table's rows, columns, spans and header cells, and order everything into a document. Their
text is the OCR's stored lines, handed over as the pages' text cells, so no second OCR runs.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import modelstore
from ..config import StructureSettings
from ..errors import ModelUnavailable
from ..schemas import BBox, DocumentContent, PageContent

log = logging.getLogger(__name__)

_PIPELINES: dict[tuple[Any, ...], Any] = {}
_BUILD_LOCK = threading.Lock()
_TABLE_LABELS = {"Table", "Form", "Table-Of-Contents"}  # the OCR's layout labels worth the table model


@dataclass(frozen=True)
class StructureRun:
    document: Any  # docling_core DoclingDocument
    seconds: float
    load_seconds: float  # loading the models (0 when reused)
    cells_delivered: int  # OCR lines handed over as text cells
    components: dict[str, str]
    pages: list[int] = field(default_factory=list)  # the pages structured
    upright: list[int] = field(default_factory=list)  # pages the OCR read turned, structured turned upright
    without_text: list[int] = field(default_factory=list)  # pages whose OCR lines could not be placed (frame mismatch)


def available() -> bool:
    """Whether the structure runtime (PyTorch for the table model, docling-core for the document) is installed."""
    try:
        import docling_core  # noqa: F401
        import safetensors  # noqa: F401
        import torch  # noqa: F401
        import torchvision  # noqa: F401
    except ImportError:
        return False
    return True


def components(settings: StructureSettings) -> dict[str, str]:
    """What runs, for the record kept with each structured document."""
    tables = modelstore.TABLES if settings.table_mode == "accurate" else modelstore.TABLES_FAST
    return {
        "engine": "Inklight document structure",
        "layout": f"Heron layout model (ONNX), {modelstore.LAYOUT.repo}@{modelstore.LAYOUT.revision[:7]}",
        "tables": f"TableFormer ({settings.table_mode}), {tables.repo}@{tables.revision[:7]}, "
        "cells matched to the OCR's text cells",
        "ocr": "none: the OCR's stored lines are the text cells",
    }


def models_for(settings: StructureSettings, progress: modelstore.Progress | None = None) -> tuple[Path, Path]:
    tables = modelstore.TABLES if settings.table_mode == "accurate" else modelstore.TABLES_FAST
    return modelstore.ensure(modelstore.LAYOUT, progress=progress), modelstore.ensure(tables, progress=progress)


def run(path: Path, content: DocumentContent, settings: StructureSettings, password: str | None = None) -> StructureRun:
    """The structure of ``path``, its text being ``content``'s OCR lines. Raises ModelUnavailable when the runtime
    or the models are missing."""
    if not available():
        raise ModelUnavailable('Document structure needs its runtime: pip install "inklight[structure]"')
    from docling_core.types.doc import DoclingDocument

    from ..backends.structure.pages import image_pages, pdf_pages

    started = time.perf_counter()
    pdf = _is_pdf(path)
    chosen = chosen_pages(list(content.pages), settings) if pdf else list(content.pages)
    if not chosen:  # no page with a table or form: nothing to add, and no model to load
        return StructureRun(
            DoclingDocument(name=path.stem), time.perf_counter() - started, 0.0, 0, components(settings)
        )
    pipeline, load_seconds = _pipeline(settings)
    # A page the OCR read turned (rotation 90/180/270) has its lines in the upright frame: it is structured turned
    # upright too, so its boxes are in the same frame (frames.py). Pages are numbered 1.. in the order given and
    # mapped back to the document's own numbers.
    turns = {p.number: p.rotation % 360 for p in chosen if p.rotation % 360}
    numbers = [p.number for p in chosen]
    backends = pdf_pages(path, numbers, password, turns) if pdf else image_pages(path, numbers, turns)
    delivered = 0
    without_text: list[int] = []

    def cells_for(number: int, size: Any) -> list[Any]:  # pages are rendered one at a time, as they are structured
        nonlocal delivered
        page = chosen[number - 1]
        cells = _cells(page, size)
        if not cells and any(ln.text.strip() and ln.bbox for ln in page.lines):
            without_text.append(page.number)
            log.warning("structure: page %d's OCR lines do not fit its image frame; no text cells given", page.number)
        delivered += len(cells)
        return cells

    document = pipeline.convert(path, backends, cells_for)
    document = _renumbered(document, {i + 1: n for i, n in enumerate(numbers)})
    return StructureRun(
        document=document,
        seconds=time.perf_counter() - started,
        load_seconds=load_seconds,
        cells_delivered=delivered,
        components=components(settings),
        pages=numbers,
        upright=sorted(turns),
        without_text=without_text,
    )


def chosen_pages(pages: list[PageContent], settings: StructureSettings) -> list[PageContent]:
    """The pages structured: all of them, or (pages = "tables") those where the OCR's layout found a table or a
    form. The others keep the OCR's layout, as with structure off."""
    if settings.pages == "all":
        return pages
    return [p for p in pages if {b.label for b in p.blocks} & _TABLE_LABELS]


def _cells(page: PageContent, size: Any) -> list[Any]:
    """The page's OCR lines as text cells, scaled from Inklight's frame (pixels of the rendered page) to the
    structure page's size in points. The line boxes of a turned page are already upright, like its image."""
    from docling_core.types.doc import BoundingBox, CoordOrigin
    from docling_core.types.doc.page import BoundingRectangle, TextCell

    lines: list[tuple[str, BBox, float | None]] = [
        (ln.text, ln.bbox, ln.conf) for ln in page.lines if ln.bbox is not None and ln.text.strip()
    ]
    width, height = float(page.width or 0.0), float(page.height or 0.0)
    if not width or not height or size is None:
        return []
    if abs(size.width / size.height - width / height) > 0.02 * (width / height):
        return []  # not the same frame: the page keeps the OCR's layout
    sx, sy = size.width / width, size.height / height
    cells = []
    for i, (text, (x0, y0, x1, y1), conf) in enumerate(lines):
        box = BoundingBox(l=x0 * sx, t=y0 * sy, r=x1 * sx, b=y1 * sy, coord_origin=CoordOrigin.TOPLEFT)
        cells.append(
            TextCell(
                index=i,
                text=text,
                orig=text,
                confidence=1.0 if conf is None else float(conf),
                from_ocr=True,
                rect=BoundingRectangle.from_bounding_box(box),
            )
        )
    return cells


def _renumbered(document: Any, numbers: dict[int, int]) -> Any:
    """The document with its page numbers changed from 1..n (the pages given) to the document's own."""
    if all(k == v for k, v in numbers.items()):
        return document
    for item, _ in document.iterate_items(traverse_pictures=True, with_groups=True):
        for prov in getattr(item, "prov", []) or []:
            prov.page_no = numbers.get(prov.page_no, prov.page_no)
    pages = {}
    for number, page in document.pages.items():
        page.page_no = numbers.get(number, number)
        pages[page.page_no] = page
    document.pages = pages
    return document


def _is_pdf(path: Path) -> bool:
    with path.open("rb") as fh:
        return fh.read(5) == b"%PDF-"


def preload(settings: StructureSettings) -> None:
    """Load the layout and table models on a background thread, so the load overlaps the OCR of the first
    document. Idempotent; ``run`` waits for it through the build lock."""
    if not available():
        return

    def build() -> None:
        try:
            _pipeline(settings)
        except Exception as exc:  # noqa: BLE001 - reported by the first document that needs the structure
            log.warning("Document structure preload failed: %s", exc)

    threading.Thread(target=build, name="inklight-structure-preload", daemon=True).start()


def threads(settings: StructureSettings) -> int:
    """CPU threads for the layout and table models: the setting, or every core when it is 0."""
    return settings.threads or os.cpu_count() or 4


def _pipeline(settings: StructureSettings) -> tuple[Any, float]:
    key = (settings.table_mode, threads(settings), settings.batch_size)
    with _BUILD_LOCK:  # two threads must not each load the models
        if key in _PIPELINES:
            return _PIPELINES[key], 0.0
        started = time.perf_counter()
        layout, tables = models_for(settings)
        try:
            from ..backends.structure.pipeline import Models, Pipeline

            pipeline = Pipeline(Models(layout, tables, threads(settings), settings.batch_size))
        except Exception as exc:
            raise ModelUnavailable(
                f"Could not load the document structure models: {type(exc).__name__}: {exc}"
            ) from exc
        _PIPELINES[key] = pipeline
        return pipeline, time.perf_counter() - started
