"""Layout-aware chunking: chunks never cross a page and keep block boundaries."""

from __future__ import annotations

from dataclasses import dataclass

from .schemas import BBox, Block, PageContent

TARGET_CHARS = 700
HEADINGS = {"Section-Header", "Title", "Page-Header"}
STANDALONE = {"Table", "Form", "Table-Of-Contents"}


@dataclass(frozen=True)
class Chunk:
    page: int
    block_start: int
    block_end: int
    text: str
    bbox: BBox | None
    conf: float | None


def _union(boxes: list[BBox]) -> BBox | None:
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _make(page: int, blocks: list[Block]) -> Chunk:
    confs = [b.conf for b in blocks if b.conf is not None]
    return Chunk(
        page=page,
        block_start=blocks[0].index,
        block_end=blocks[-1].index,
        text="\n".join(b.text for b in blocks if b.text.strip()),
        bbox=_union([b.bbox for b in blocks if b.bbox is not None]),
        conf=min(confs) if confs else None,
    )


def chunk_page(page: PageContent, target: int = TARGET_CHARS) -> list[Chunk]:
    chunks: list[Chunk] = []
    group: list[Block] = []
    size = 0
    for block in page.blocks:
        if not block.text.strip() or block.label == "Picture":
            continue
        heading_alone = len(group) > 0 and all(b.label in HEADINGS for b in group)
        if block.label in STANDALONE or (group and size + len(block.text) > target and not heading_alone):
            if group:
                chunks.append(_make(page.number, group))
            group, size = [], 0
        group.append(block)
        size += len(block.text)
        if block.label in STANDALONE:
            chunks.append(_make(page.number, group))
            group, size = [], 0
    if group:
        chunks.append(_make(page.number, group))
    return chunks
