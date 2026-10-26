"""Inklight OCR: line detection, CTC recognition (Latin, Arabic and other scripts), page orientation, reading order
and layout, run with ONNX Runtime on the pinned OCR models; PDFs keep a sound text layer and are OCR'd elsewhere."""

from __future__ import annotations

from pathlib import Path

from .document import Converter
from .pipeline import InputError, Line, OrtOCR, Page, read_images


def load(model_dir: Path, threads: int = 4, dpi: float = 200.0, mode: str = "auto") -> Converter:
    """A ready converter over the models in ``model_dir``. mode "ocr" never reads a PDF's text layer, "text" only
    reads it."""
    return Converter(OrtOCR(model_dir, threads=threads), dpi=dpi, mode=mode, image_ocr=True)


__all__ = ["Converter", "InputError", "Line", "OrtOCR", "Page", "load", "read_images"]
