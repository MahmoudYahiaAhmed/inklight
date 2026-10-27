"""PDFium is not thread-safe: the OCR, the structure stage and the workspace's page previews run in different
threads, so every call into it goes through this lock (one PDF operation at a time, held per page)."""

from __future__ import annotations

import threading

PDFIUM = threading.RLock()
