"""Indra's OCR lines as a Docling OCR engine, so Docling's layout, reading order and table models run on the text
Indra already read, without a second OCR pass.

Docling's supported extension point for OCR is an OCR model class (``BaseOcrModel``) registered in its OCR factory
and selected by an options class. This engine does no recognition: for each page it hands Docling the lines Inklight
stored from Indra, as ``TextCell``s in Docling's page coordinates, and ``OcrMode.FULL_PAGE`` makes Docling use those
cells only (its own PDF text cells are discarded, and their extraction is skipped).

The lines are registered per input file for the duration of one conversion (``lines_for``).
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal

from docling.datamodel.pipeline_options import OcrMode, OcrOptions
from docling.models.base_ocr_model import BaseOcrModel
from docling_core.types.doc import BoundingBox, CoordOrigin
from docling_core.types.doc.page import BoundingRectangle, TextCell

from ..schemas import BBox, PageContent

KIND = "inklight_indra"


@dataclass(frozen=True)
class PageLines:
    """One page's stored OCR lines in Inklight's frame (pixels of the rendered page, top-left origin)."""

    width: float
    height: float
    lines: tuple[tuple[str, BBox, float | None], ...]
    rotation: int = 0


_PAGES: dict[
    str, dict[int, PageLines]
] = {}  # resolved input path -> page number (1-based, as Docling's page_no) -> lines
_LOCK = threading.Lock()
_DELIVERED: dict[str, int] = {}  # resolved input path -> cells handed to Docling (the experiment's evidence)


def _key(path: Path | str) -> str:
    return str(Path(path).resolve()).lower()


@contextmanager
def lines_for(path: Path, pages: list[PageContent]) -> Iterator[dict[str, int]]:
    """Register the pages' OCR lines for the conversion of ``path``; yields a counter of the cells delivered."""
    table = {
        p.number: PageLines(
            float(p.width or 0.0),
            float(p.height or 0.0),
            tuple((ln.text, ln.bbox, ln.conf) for ln in p.lines if ln.bbox is not None and ln.text.strip()),
            p.rotation,
        )
        for p in pages
    }
    key = _key(path)
    with _LOCK:
        _PAGES[key] = table
        _DELIVERED[key] = 0
    counter: dict[str, int] = {}
    try:
        yield counter
    finally:
        with _LOCK:
            _PAGES.pop(key, None)
            counter["cells"] = _DELIVERED.pop(key, 0)


class IndraLinesOcrOptions(OcrOptions):
    """Select the engine that passes Indra's stored lines to Docling (no recognition of its own)."""

    kind: ClassVar[Literal["inklight_indra"]] = "inklight_indra"
    canonicalize_lang: ClassVar[bool] = False
    lang: list[str] = []
    mode: OcrMode = OcrMode.FULL_PAGE


class IndraLinesOcrModel(BaseOcrModel):
    def __init__(self, *, enabled: bool, artifacts_path: Path | None, options: Any, accelerator_options: Any) -> None:
        super().__init__(
            enabled=enabled, artifacts_path=artifacts_path, options=options, accelerator_options=accelerator_options
        )
        self.enabled = enabled

    @classmethod
    def get_options_type(cls) -> type[OcrOptions]:
        return IndraLinesOcrOptions

    def __call__(self, conv_res: Any, page_batch: Iterable[Any]) -> Iterable[Any]:
        key = _key(conv_res.input.file)
        with _LOCK:
            stored = _PAGES.get(key, {})
        for page in page_batch:
            if not self.enabled or page._backend is None or not page._backend.is_valid():
                yield page
                continue
            cells = _cells(stored.get(page.page_no), page.size)
            with _LOCK:
                if key in _DELIVERED:
                    _DELIVERED[key] += len(cells)
            self.post_process_cells(cells, page, conv_res)
            yield page


def _cells(lines: PageLines | None, size: Any) -> list[TextCell]:
    """The page's lines as Docling text cells, scaled from Inklight's frame to Docling's page size."""
    if lines is None or size is None or not lines.width or not lines.height or lines.rotation:
        return []
    if abs(size.width / size.height - lines.width / lines.height) > 0.02 * (lines.width / lines.height):
        return []  # not the same frame (an image one side turned upright): the page keeps Indra's layout
    sx, sy = size.width / lines.width, size.height / lines.height
    cells = []
    for i, (text, (x0, y0, x1, y1), conf) in enumerate(lines.lines):
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


def register() -> None:
    """Make the engine selectable in Docling's OCR factory (idempotent). Docling's own plugin loading stays
    restricted to its built-in engines (``allow_external_plugins=False``)."""
    from docling.models.factories import get_ocr_factory

    factory = get_ocr_factory(allow_external_plugins=False)
    if IndraLinesOcrOptions not in factory.classes:
        factory.register(IndraLinesOcrModel, "inklight", __name__)
