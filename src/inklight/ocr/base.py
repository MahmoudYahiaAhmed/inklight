"""Pluggable OCR engine interface."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from ..schemas import DocumentContent


@runtime_checkable
class OCREngine(Protocol):
    """Anything that turns a validated file into pages of text with layout."""

    name: str

    def supports(self, kind: str) -> bool:
        """True when the engine reads this sniffed file kind (pdf, png, text, ...)."""
        ...

    def read(self, path: Path, *, max_pages: int, password: str | None = None) -> DocumentContent:
        """Read one document. Raise OCRError for an unreadable file."""
        ...
