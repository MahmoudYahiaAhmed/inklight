"""Inklight OCR as an engine: PDFs (a sound text layer first, OCR where needed) and images, page by page.

The reading itself is ``inklight.backends.ocr``; this module turns its pages into Inklight's ``PageContent`` with
boxes in the frame of the rendered page, so overlays and citations line up.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import modelstore
from ..config import OCRSettings
from ..errors import ModelUnavailable, OCRError
from ..schemas import BBox, Block, DocumentContent, PageContent, TextLine
from .textcheck import layer_is_broken

_IMAGE_KINDS = {"png", "jpeg", "tiff", "bmp", "webp"}


class InklightOCR:
    name = "inklight"

    def __init__(self, settings: OCRSettings) -> None:
        self.settings = settings
        self._converter: Any = None
        self._lock = threading.Lock()
        self.progress: modelstore.Progress | None = None  # set by a caller that shows the first download
        self.on_page: Callable[[int, int], None] | None = None  # (page read, pages to read), set by a caller

    def supports(self, kind: str) -> bool:
        return kind == "pdf" or kind in _IMAGE_KINDS

    # -- lifecycle ---------------------------------------------------------

    def converter(self) -> Any:
        """Load the OCR models lazily, once (downloaded on first use: ~76 MB)."""
        with self._lock:
            if self._converter is None:
                from ..backends import ocr

                folder = modelstore.ensure(modelstore.OCR, self.settings.model_dir, progress=self.progress)
                try:
                    self._converter = ocr.load(
                        folder, threads=self.settings.threads, dpi=self.settings.dpi, mode=self.settings.mode
                    )
                except Exception as exc:
                    raise ModelUnavailable(f"Could not load the Inklight OCR models from {folder}: {exc}") from exc
            return self._converter

    # -- reading -----------------------------------------------------------

    def read(self, path: Path, *, max_pages: int, password: str | None = None) -> DocumentContent:
        from ..backends.ocr import InputError

        conv = self.converter()
        try:
            if _is_pdf(path):
                pages, total = self._read_pdf(conv, path, max_pages, password)
            else:
                pages, total = self._read_image(conv, path, max_pages)
        except InputError as exc:
            raise OCRError(str(exc)) from exc
        except OCRError:
            raise
        except Exception as exc:
            raise OCRError(f"{path.name}: {type(exc).__name__}: {exc}") from exc
        warnings = [f"Page {p.number} failed: {p.note}" for p in pages if p.source == "error"]
        broken = [p for p in pages if p.note.startswith("broken Arabic text layer")]
        reread = [str(p.number) for p in broken if p.source == "ocr"]
        kept = [str(p.number) for p in broken if p.source != "ocr"]
        if reread:
            warnings.append(f"Pages {', '.join(reread)}: broken Arabic text layer, read by OCR instead")
        if kept:
            warnings.append(f"Pages {', '.join(kept)}: broken Arabic text layer; OCR failed, kept the text layer")
        if total > len(pages):
            warnings.append(f"Read the first {len(pages)} of {total} pages (max_pages limit)")
        return DocumentContent(
            path=str(path), pages=tuple(pages), total_pages=total, engine=self.name, warnings=tuple(warnings)
        )

    def _read_pdf(self, conv: Any, path: Path, max_pages: int, password: str | None) -> tuple[list[PageContent], int]:
        import pypdfium2 as pdfium

        try:
            doc = pdfium.PdfDocument(str(path), password=password)
        except pdfium.PdfiumError as exc:
            locked = "password" in str(exc).lower()
            raise OCRError(
                f"{path.name}: password-protected PDF" if locked else f"{path.name}: cannot open the PDF ({exc})"
            ) from exc
        try:
            total = len(doc)
            sizes = [doc[i].get_size() for i in range(min(total, max_pages))]
        finally:
            doc.close()
        pages = []
        for index, page in conv.convert(path, max_pages=max_pages, password=password):
            w_pt, h_pt = sizes[index]
            scale = _pdf_scale(w_pt, h_pt, self.settings.dpi)
            note = None
            if self.settings.mode == "auto" and page.source in ("text", "hybrid") and _broken_layer(page):
                page, note = self._reread_broken_page(conv, path, index, scale, password, page)
            width, height = w_pt * scale, h_pt * scale
            if page.rotation in (90, 270):
                width, height = height, width
            content = _to_page(index + 1, page, width, height)
            if note:
                content = content.model_copy(update={"note": f"{note}; {content.note}".rstrip("; ")})
            pages.append(content)
            self._page_done(index + 1, min(total, max_pages))
        return pages, total

    def _reread_broken_page(
        self, conv: Any, path: Path, index: int, scale: float, password: str | None, layer_page: Any
    ) -> tuple[Any, str]:
        """OCR a page whose text layer is broken. If OCR fails or reads nothing, keep the layer: broken text is
        still partly searchable, and one page must not end the document."""
        import pypdfium2 as pdfium

        try:
            doc = pdfium.PdfDocument(str(path), password=password)
            try:
                arr = doc[index].render(scale=scale, grayscale=True).to_numpy()  # the OCR's scale: same box frame
            finally:
                doc.close()
            page = conv.ocr(arr[..., 0] if arr.ndim == 3 else arr)
        except Exception as exc:  # noqa: BLE001 - recorded on the page, never fatal
            return layer_page, f"broken Arabic text layer; OCR failed ({type(exc).__name__}), kept the text layer"
        if not any(ln.text.strip() for ln in page.lines):
            return layer_page, "broken Arabic text layer; OCR failed (read nothing), kept the text layer"
        page.source = "ocr"
        return page, "broken Arabic text layer; OCR instead"

    def _read_image(self, conv: Any, path: Path, max_pages: int) -> tuple[list[PageContent], int]:
        from ..backends.ocr import read_images

        frames = read_images(path)
        pages = []
        for index, gray in enumerate(frames[:max_pages]):
            started = time.perf_counter()
            try:
                page = conv.ocr(gray)
            except Exception as exc:  # one bad frame must not end the document
                pages.append(
                    PageContent(
                        number=index + 1,
                        source="error",
                        note=f"{type(exc).__name__}: {exc}",
                        ocr_ms=1000 * (time.perf_counter() - started),
                    )
                )
                continue
            height, width = gray.shape[:2]
            if int(getattr(page, "rotation", 0) or 0) in (90, 270):
                width, height = height, width  # the OCR's boxes are in the upright frame
            pages.append(_to_page(index + 1, page, float(width), float(height)))
            self._page_done(index + 1, min(len(frames), max_pages))
        return pages, len(frames)

    def _page_done(self, number: int, total: int) -> None:
        if self.on_page is not None:
            with contextlib.suppress(Exception):  # a progress display must never stop the reading
                self.on_page(number, total)

    def reread(self, path: Path, page: int, bbox: BBox, rotation: int = 0) -> str | None:
        """OCR one region of an image again, enlarged, to double-check a value read from it.

        Returns None where a re-read is not supported: PDFs (a text layer needs no re-read and a scan would
        need re-rendering), rotated pages (stored boxes are in the upright frame), or an empty crop.
        """
        if _is_pdf(path) or rotation:
            return None
        import cv2

        from ..backends.ocr import read_images

        frames = read_images(path)
        if not 1 <= page <= len(frames):
            return None
        gray = frames[page - 1]
        x0, y0, x1, y1 = bbox
        pad = max(y1 - y0, 8.0)
        h, w = gray.shape[:2]
        left, top = max(int(x0 - pad), 0), max(int(y0 - pad / 2), 0)
        right, bottom = min(int(x1 + pad), w), min(int(y1 + pad / 2), h)
        if right - left < 4 or bottom - top < 4:
            return None
        crop = gray[top:bottom, left:right]
        scale = max(1.0, 64.0 / max(y1 - y0, 1.0))  # enlarge so the text is ~64 px tall
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        try:
            result = self.converter().ocr(crop)
        except Exception:  # a failed double-check is "no second reading", never an error
            return None
        text = " ".join(ln.text for ln in result.lines if ln.text.strip())
        return text or None


def _broken_layer(page: Any) -> bool:
    return layer_is_broken(" ".join(ln.text for ln in page.lines))


def _is_pdf(path: Path) -> bool:
    with path.open("rb") as fh:
        return fh.read(5) == b"%PDF-"


def _pdf_scale(w_pt: float, h_pt: float, dpi: float) -> float:
    """The OCR's render scale, so stored boxes match a re-render."""
    from ..backends.ocr.document import MAX_PAGE_PIXELS

    k = dpi / 72.0
    return float(min(k, (MAX_PAGE_PIXELS / max(w_pt * h_pt, 1.0)) ** 0.5))


def _box(raw: Any) -> BBox | None:
    if raw is None:
        return None
    x0, y0, x1, y1 = (round(float(v), 1) for v in list(raw)[:4])
    return (x0, y0, x1, y1)


def _inside(inner: BBox | None, outer: BBox | None, slack: float = 4.0) -> bool:
    if inner is None or outer is None:
        return False
    cx, cy = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return outer[0] - slack <= cx <= outer[2] + slack and outer[1] - slack <= cy <= outer[3] + slack


def _to_page(number: int, page: Any, width: float, height: float) -> PageContent:
    lines = tuple(
        TextLine(text=ln.text, bbox=_box(ln.box), conf=None if ln.conf is None else round(float(ln.conf), 4))
        for ln in page.lines
    )
    blocks = []
    for i, raw in enumerate(page.blocks or []):
        bbox = _box(raw.get("bbox"))
        confs = [ln.conf for ln in lines if ln.conf is not None and _inside(ln.bbox, bbox)]
        blocks.append(
            Block(
                index=i,
                label=str(raw.get("label", "Text")),
                text=str(raw.get("text", "")),
                bbox=bbox,
                conf=round(sum(confs) / len(confs), 4) if confs else None,
            )
        )
    if not blocks and lines:
        # No layout heads: fall back to one block per line so citations still resolve.
        blocks = [Block(index=i, label="Text", text=ln.text, bbox=ln.bbox, conf=ln.conf) for i, ln in enumerate(lines)]
    timings = getattr(page, "timings", {}) or {}
    return PageContent(
        number=number,
        width=round(width, 1),
        height=round(height, 1),
        source=str(page.source),
        markdown=page.markdown or "\n".join(ln.text for ln in lines),
        lines=lines,
        blocks=tuple(blocks),
        rotation=int(getattr(page, "rotation", 0) or 0),
        note=str(getattr(page, "note", "") or ""),
        ocr_ms=timings.get("total_ms"),
    )


IndraEngine = InklightOCR  # the earlier name, kept for code that imports it
