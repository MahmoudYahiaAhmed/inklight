# SPDX-FileCopyrightText: The Docling Contributors
# SPDX-License-Identifier: MIT
"""Page images for the structure stages.

Every page reaches the layout and table models as an image with a known resolution: an image file's frames as they
are stored (EXIF orientation applied, transparency flattened onto white), or a PDF page rendered at 144 dpi. The page
size is in points (1/72 inch); an image of the page at another scale is a Lanczos resize of that one image.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import SupportsFloat

from docling_core.types.doc import BoundingBox, CoordOrigin, Size
from docling_core.types.doc.page import (
    BoundingRectangle,
    PdfPageBoundaryType,
    PdfPageGeometry,
    SegmentedPdfPage,
    TextCell,
)
from PIL import Image, ImageOps

POINTS_PER_INCH = 72.0
PDF_RENDER_DPI = 144.0  # PDF pages are rendered once at this resolution
_DEFAULT_DPI = (POINTS_PER_INCH, POINTS_PER_INCH)


def _validate_dpi(dpi: tuple[SupportsFloat, SupportsFloat]) -> tuple[float, float]:
    if not isinstance(dpi, tuple) or len(dpi) != 2:
        raise ValueError(f"Invalid image DPI metadata: {dpi!r}")
    try:
        dpi_x, dpi_y = float(dpi[0]), float(dpi[1])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid image DPI metadata: {dpi!r}") from exc
    if not math.isfinite(dpi_x) or not math.isfinite(dpi_y) or dpi_x <= 0 or dpi_y <= 0:
        raise ValueError(f"Invalid image DPI metadata: {dpi!r}")
    return dpi_x, dpi_y


def _frame_dpi(image: Image.Image) -> tuple[float, float]:
    dpi = image.info.get("dpi")
    return _validate_dpi(_DEFAULT_DPI if dpi in (None, (1, 1)) else dpi)


def oriented_frame(image: Image.Image) -> tuple[Image.Image, tuple[float, float]]:
    """The frame turned as its EXIF orientation says (a camera stores the sensor readout and a tag), with its dpi
    axes swapped when the turn swapped width and height."""
    dpi_x, dpi_y = _frame_dpi(image)
    oriented = ImageOps.exif_transpose(image)
    if oriented.size != image.size:
        dpi_x, dpi_y = dpi_y, dpi_x
    return oriented, (dpi_x, dpi_y)


def to_rgb(image: Image.Image) -> Image.Image:
    """RGB, with any transparency flattened onto white (a plain convert would keep the colour under it)."""
    if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, rgba).convert("RGB")
    return image.convert("RGB")


class PdfPageBackend:
    """One page image. The name is the one the page model expects of a page's source."""

    def __init__(self, image: Image.Image, page_no: int, dpi: tuple[float, float]) -> None:
        self._image: Image.Image | None = image
        self._page_no = page_no
        self._dpi = dpi
        self.valid: bool = self._image is not None

    @property
    def page_no(self) -> int:
        return self._page_no + 1

    def is_valid(self) -> bool:
        return self.valid

    def get_text_in_rect(self, bbox: BoundingBox) -> str:
        return ""

    def get_segmented_page(self) -> SegmentedPdfPage:
        """A page with no text of its own: its text cells are the OCR lines given to the pipeline."""
        assert self._image is not None
        size = self.get_size()
        bbox = BoundingBox(l=0.0, t=0.0, r=float(size.width), b=float(size.height), coord_origin=CoordOrigin.BOTTOMLEFT)
        dimension = PdfPageGeometry(
            angle=0.0,
            rect=BoundingRectangle.from_bounding_box(bbox),
            boundary_type=PdfPageBoundaryType.CROP_BOX,
            art_bbox=bbox,
            bleed_bbox=bbox,
            crop_bbox=bbox,
            media_bbox=bbox,
            trim_bbox=bbox,
        )
        return SegmentedPdfPage(
            dimension=dimension,
            char_cells=[],
            word_cells=[],
            textline_cells=[],
            has_chars=False,
            has_words=False,
            has_lines=False,
        )

    def get_text_cells(self) -> Iterable[TextCell]:
        return []

    def get_page_image(self, scale: float = 1, cropbox: BoundingBox | None = None) -> Image.Image:
        assert self._image is not None
        size = self.get_size()
        if cropbox is None:
            left, top, right, bottom = 0.0, 0.0, size.width, size.height
        else:
            if cropbox.coord_origin != CoordOrigin.TOPLEFT:
                cropbox = cropbox.to_top_left_origin(size.height)
            left, top, right, bottom = cropbox.as_tuple()
            left = min(max(0.0, left), size.width)
            top = min(max(0.0, top), size.height)
            right = min(max(0.0, right), size.width)
            bottom = min(max(0.0, bottom), size.height)
        target = (max(1, round((right - left) * scale)), max(1, round((bottom - top) * scale)))
        source_box = (
            left * self._dpi[0] / POINTS_PER_INCH,
            top * self._dpi[1] / POINTS_PER_INCH,
            right * self._dpi[0] / POINTS_PER_INCH,
            bottom * self._dpi[1] / POINTS_PER_INCH,
        )
        if target == self._image.size and source_box == (0.0, 0.0, float(self._image.width), float(self._image.height)):
            return self._image
        return self._image.resize(target, resample=Image.Resampling.LANCZOS, box=source_box)

    def get_size(self) -> Size:
        assert self._image is not None
        return Size(
            width=self._image.width * POINTS_PER_INCH / self._dpi[0],
            height=self._image.height * POINTS_PER_INCH / self._dpi[1],
        )

    def unload(self) -> None:
        self._image = None


class RenderedPageBackend(PdfPageBackend):
    """A page image prepared as the structure stages have always received a rendered page: the 144 dpi render is
    stored as a JPEG (quality 75), the page is seen at 72 dpi as an area-average of it, and at any other scale as a
    bilinear resize of that 72 dpi view."""

    def __init__(self, image: Image.Image, page_no: int) -> None:
        import io

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG")
        buffer.seek(0)
        stored = Image.open(buffer).convert("RGB")
        super().__init__(stored, page_no, (PDF_RENDER_DPI, PDF_RENDER_DPI))
        self._base: Image.Image | None = None

    def get_page_image(self, scale: float = 1, cropbox: BoundingBox | None = None) -> Image.Image:
        import cv2
        import numpy as np

        assert self._image is not None
        size = self.get_size()
        if self._base is None:
            target = (max(1, round(size.width)), max(1, round(size.height)))
            self._base = Image.fromarray(cv2.resize(np.asarray(self._image), target, interpolation=cv2.INTER_AREA))
        image = self._base
        if scale != 1:
            target = (max(1, round(size.width * scale)), max(1, round(size.height * scale)))
            image = image.resize(target, resample=Image.Resampling.BILINEAR)
        if cropbox is None:
            return image
        if cropbox.coord_origin != CoordOrigin.TOPLEFT:
            cropbox = cropbox.to_top_left_origin(size.height)
        left, top, right, bottom = (round(v * scale) for v in cropbox.as_tuple())
        return image.crop((left, top, right, bottom))

    def unload(self) -> None:
        super().unload()
        self._base = None


def image_pages(path: Path, numbers: list[int], turns: dict[int, int]) -> Iterator[PdfPageBackend]:
    """An image file's frames ``numbers`` (1-based). Upright frames are read as stored, at their own dpi; a frame
    the OCR found turned is taken as the OCR read it, turned upright, at 144 dpi."""
    if turns:
        from ..ocr.pipeline import read_images

        frames = read_images(path)
        for index, number in enumerate(numbers):
            if not 1 <= number <= len(frames):
                raise ValueError("the image has none of the pages asked for")
            image = upright(Image.fromarray(frames[number - 1]).convert("RGB"), turns.get(number, 0))
            yield RenderedPageBackend(image, index)
        return
    with Image.open(path) as source:
        count = getattr(source, "n_frames", 1)
        for index, number in enumerate(numbers):
            if not 1 <= number <= count:
                raise ValueError("the image has none of the pages asked for")
            source.seek(number - 1)
            frame, dpi = oriented_frame(source)
            yield PdfPageBackend(to_rgb(frame), index, dpi)


def pdf_pages(path: Path, numbers: list[int], password: str | None, turns: dict[int, int]) -> Iterator[PdfPageBackend]:
    """A PDF's pages ``numbers`` (1-based), rendered at 144 dpi and turned upright by ``turns``."""
    import pypdfium2 as pdfium

    from ...pdfium_lock import PDFIUM

    with PDFIUM:  # PDFium is not thread-safe; the OCR may be reading another PDF meanwhile
        pdf = pdfium.PdfDocument(str(path), password=password)
        wanted = [n for n in numbers if 1 <= n <= len(pdf)]
    try:
        if not wanted:
            raise ValueError("the PDF has none of the pages asked for")
        for index, number in enumerate(wanted):
            with PDFIUM:
                image = pdf[number - 1].render(scale=PDF_RENDER_DPI / POINTS_PER_INCH).to_pil().convert("RGB")
            image = upright(image, turns.get(number, 0))
            yield RenderedPageBackend(image, index)
    finally:
        with PDFIUM:
            pdf.close()


def upright(image: Image.Image, turn: int) -> Image.Image:
    """The page image turned upright: the OCR's rotation is how far the page is turned counter-clockwise."""
    return image.rotate(-turn, expand=True, fillcolor="white") if turn else image
