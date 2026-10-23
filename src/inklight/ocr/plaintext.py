"""Plain-text and Markdown files: no OCR needed, same downstream shape."""

from __future__ import annotations

from pathlib import Path

from ..errors import OCRError
from ..schemas import Block, DocumentContent, PageContent, TextLine

# Form feed separates pages in plain-text exports; otherwise one page.
_PAGE_BREAK = "\f"


class PlainTextEngine:
    name = "plaintext"

    def supports(self, kind: str) -> bool:
        return kind == "text"

    def read(self, path: Path, *, max_pages: int, password: str | None = None) -> DocumentContent:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise OCRError(f"Cannot read {path.name}: {exc}") from exc
        chunks = raw.split(_PAGE_BREAK)
        warnings = []
        if len(chunks) > max_pages:
            warnings.append(f"Read the first {max_pages} of {len(chunks)} pages")
        pages = tuple(_page(i + 1, chunk) for i, chunk in enumerate(chunks[:max_pages]))
        return DocumentContent(
            path=str(path), pages=pages, total_pages=len(chunks), engine=self.name, warnings=tuple(warnings)
        )


def _page(number: int, text: str) -> PageContent:
    lines = tuple(TextLine(text=ln.rstrip(), conf=1.0) for ln in text.splitlines() if ln.strip())
    blocks: list[Block] = []
    for para in (p.strip() for p in text.split("\n\n")):
        if not para:
            continue
        label = "Section-Header" if para.startswith("#") else "Text"
        blocks.append(Block(index=len(blocks), label=label, text=para.lstrip("# ").strip(), conf=1.0))
    return PageContent(number=number, source="plain", markdown=text.strip(), lines=lines, blocks=tuple(blocks))
