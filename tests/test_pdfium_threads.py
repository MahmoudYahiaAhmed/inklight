"""PDFium is not thread-safe: reading PDFs while the workspace renders page previews in other threads must neither
fail nor corrupt a page (every PDF call goes through inklight.pdfium_lock)."""

from __future__ import annotations

import threading

import pytest

from inklight.config import OCRSettings
from inklight.ocr.engine import InklightOCR
from inklight.server.render import preview_png, render_page

pytestmark = pytest.mark.ocr


def test_reading_while_previews_render(docs_dir):
    pdfs = sorted(docs_dir.glob("*.pdf"))
    engine = InklightOCR(OCRSettings())
    first = engine.read(pdfs[0], max_pages=5).pages[0]
    errors: list[str] = []
    stop = threading.Event()

    def previews() -> None:
        while not stop.is_set():
            for path in pdfs:
                try:
                    if preview_png(path) is None or render_page(pdfs[0], 1, first, 200) is None:
                        errors.append(f"no preview for {path.name}")
                except Exception as exc:  # noqa: BLE001 - the test reports any failure
                    errors.append(f"{type(exc).__name__}: {exc}")

    workers = [threading.Thread(target=previews) for _ in range(3)]
    for w in workers:
        w.start()
    try:
        for _ in range(3):
            for path in pdfs:
                content = engine.read(path, max_pages=5)
                assert all(p.source != "error" for p in content.pages), (path.name, [p.note for p in content.pages])
    finally:
        stop.set()
        for w in workers:
            w.join()
    assert not errors, errors[:5]
