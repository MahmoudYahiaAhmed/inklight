"""Page previews in the same pixel frame as the stored OCR boxes."""

from __future__ import annotations

from pathlib import Path

from ..schemas import PageContent

MAX_PREVIEW_PIXELS = 40_000_000  # ~160 MB of BGR; larger pages are scaled down


def render_page(path: Path, number: int, page: PageContent, dpi: float) -> bytes | None:
    """PNG of one page, sized to ``page.width x page.height`` so boxes overlay exactly."""
    if not path.is_file():
        return None
    try:
        import cv2
        import numpy as np
    except ImportError:  # pragma: no cover - indra-ocr installs opencv
        return None
    with path.open("rb") as fh:
        is_pdf = fh.read(5) == b"%PDF-"
    if is_pdf:
        import pypdfium2 as pdfium

        try:
            doc = pdfium.PdfDocument(str(path))
        except pdfium.PdfiumError:
            return None
        try:
            if number > len(doc):
                return None
            p = doc[number - 1]
            w_pt, h_pt = p.get_size()
            scale = (page.width / w_pt) if page.width and page.rotation in (0, 180) else dpi / 72.0
            # Never trust page geometry from an untrusted PDF: cap the render size.
            scale = min(scale, (MAX_PREVIEW_PIXELS / max(w_pt * h_pt, 1.0)) ** 0.5)
            # pdfium renders BGR(A) — already OpenCV's channel order; no Pillow needed.
            img = np.ascontiguousarray(p.render(scale=scale).to_numpy())
        finally:
            doc.close()
        if img.ndim == 3 and img.shape[2] == 4:
            img = img[:, :, :3]
    elif path.suffix.lower() in (".txt", ".md", ".markdown"):
        return None
    else:
        # Read just the requested frame, not every frame of a multi-page TIFF.
        ok, frames = cv2.imreadmulti(str(path), start=number - 1, count=1, flags=cv2.IMREAD_COLOR)
        frame = frames[0] if ok and frames else (cv2.imread(str(path), cv2.IMREAD_COLOR) if number == 1 else None)
        if frame is None:
            return None
        img = frame
        if img.shape[0] * img.shape[1] > MAX_PREVIEW_PIXELS:
            k = (MAX_PREVIEW_PIXELS / (img.shape[0] * img.shape[1])) ** 0.5
            img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img)
    return bytes(buf) if ok else None
