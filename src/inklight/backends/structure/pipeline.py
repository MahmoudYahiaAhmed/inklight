"""Inklight document structure: layout, tables and reading order on pages whose text the OCR has already read.

For each page: its image (pages.py), the OCR lines as the page's text cells, the layout model and its
post-processing (layout.py, layout_postprocessor.py), table structure (tables.py) and page assembly (assemble.py);
then reading order over all pages builds the document (reading_order.py), a ``DoclingDocument``.

The stages run one after another in this thread; the models are loaded once per settings and reused.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, PdfPageGeometry, SegmentedPdfPage, TextCell

from .datamodel import AssembledUnit, ConfidenceReport, ErrorItem, Page
from .options import LayoutPostprocessorOptions
from .pages import PdfPageBackend

CellSource = Callable[[int, Any], list[TextCell]]  # (page number, page size) -> the page's text cells


@dataclass(frozen=True)
class Models:
    """Where the model files are: the layout model folder and the TableFormer folder (accurate or fast)."""

    layout: Path
    tables: Path
    threads: int
    batch_size: int = 4


@dataclass
class _Input:
    file: Path
    document_hash: str


@dataclass
class _Run:
    """What the stages read and write about one conversion (upstream's conversion result, cut to its use here)."""

    input: _Input
    pages: list[Page] = field(default_factory=list)
    assembled: AssembledUnit | None = None
    errors: list[ErrorItem] = field(default_factory=list)
    confidence: ConfidenceReport = field(default_factory=ConfidenceReport)


class Pipeline:
    def __init__(self, models: Models) -> None:
        from .assemble import PageAssembleModel, PageAssembleOptions
        from .layout import LayoutModel
        from .reading_order import ReadingOrderModel, ReadingOrderOptions
        from .tables import TableStructureModel

        self.models = models
        self.layout = LayoutModel(models.layout, models.threads)
        self.tables = TableStructureModel(models.tables, models.threads)
        self.assemble = PageAssembleModel(options=PageAssembleOptions())
        self.reading_order = ReadingOrderModel(options=ReadingOrderOptions(use_page_separators=True))
        self.postprocess = LayoutPostprocessorOptions()
        self._lock = threading.Lock()  # one conversion at a time per loaded pipeline

    def convert(self, source: Path, pages: Iterator[PdfPageBackend], cells: CellSource) -> Any:
        """The document of ``pages`` (numbered 1.. in order), each with the text cells ``cells(number, size)``
        returns (page coordinates in points, top-left origin)."""
        with self._lock:
            return self._convert(source, pages, cells)

    def _convert(self, source: Path, backends: Iterator[PdfPageBackend], cells: CellSource) -> Any:
        from .layout_postprocessor import LayoutPostprocessor

        run = _Run(input=_Input(file=source, document_hash=_file_hash(source)))
        batch: list[Page] = []

        def flush() -> None:
            self.layout.predict_layout(run, batch)
            for page in batch:
                if page.predictions.layout is not None:
                    clusters = LayoutPostprocessor(
                        page, page.predictions.layout.clusters, self.postprocess
                    ).postprocess()
                    page.predictions.layout = page.predictions.layout.model_copy(update={"clusters": clusters})
            self.tables.predict_tables(run, batch)
            run.pages.extend(self.assemble(run, batch))
            for page in batch:
                page._image_cache = {}
                if page._backend is not None:
                    page._backend.unload()
            batch.clear()

        for index, backend in enumerate(backends):
            page = Page(page_no=index + 1)
            page._backend = backend
            page.size = backend.get_size()
            page.get_image(scale=1.0)  # the layout model's view, kept for the table stage's crops
            _set_cells(page, cells(page.page_no, page.size))
            batch.append(page)
            if len(batch) >= self.models.batch_size:
                flush()
        if batch:
            flush()
        elements, headers, body = [], [], []
        for page in run.pages:
            if page.assembled:
                elements.extend(page.assembled.elements)
                headers.extend(page.assembled.headers)
                body.extend(page.assembled.body)
        run.assembled = AssembledUnit(elements=elements, headers=headers, body=body)
        return self.reading_order(run)


def _set_cells(page: Page, cells: list[TextCell]) -> None:
    """The page's text is the OCR lines given, and nothing else (no text layer is read)."""
    for i, cell in enumerate(cells):
        cell.index = i
    assert page.size is not None
    width, height = page.size.width, page.size.height
    rect = BoundingRectangle(
        r_x0=0, r_y0=0, r_x1=width, r_y1=0, r_x2=width, r_y2=height, r_x3=0, r_y3=height,
        coord_origin=CoordOrigin.BOTTOMLEFT,
    )  # fmt: skip
    bbox = BoundingBox(l=0, t=height, r=width, b=0, coord_origin=CoordOrigin.BOTTOMLEFT)
    page.parsed_page = SegmentedPdfPage(
        dimension=PdfPageGeometry(
            angle=0.0,
            rect=rect,
            boundary_type="crop_box",
            art_bbox=bbox,
            bleed_bbox=bbox,
            crop_bbox=bbox,
            media_bbox=bbox,
            trim_bbox=bbox,
        ),
        char_cells=[],
        word_cells=[],
        textline_cells=cells,
    )
    page.parsed_page.has_lines = len(cells) > 0


def _file_hash(path: Path) -> str:
    hasher = hashlib.sha256(usedforsecurity=False)
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            hasher.update(block)
    return hasher.hexdigest()
