"""The document structure as Inklight pages, without losing or changing the OCR's text.

- Each page keeps its original OCR ``lines`` untouched (text, box, confidence as the OCR read them).
- Its ``blocks`` become the structure's items in reading order, each with ``ref`` pointing back to the item
  ('#/tables/0') and its box converted from the structure's page coordinates (points) to Inklight's frame.
- A table block's text names each value with its column header ("اسم الشركة: شركة …"), row by row, so search and
  answers see which header a value belongs to; the cells themselves stay in the stored DoclingDocument.
- Text inside a picture becomes "Picture-Text" blocks, which are searched like any text.
- A line that no structure item holds is kept as a "Text" block of its own: no recognised text disappears.
- Text in the structure that is not in the OCR's lines would mean another OCR ran; it is counted ("foreign_tokens").
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any

from ..extract import layout
from ..schemas import BBox, Block, PageContent

_LABELS = {
    "title": "Title",
    "section_header": "Section-Header",
    "page_header": "Page-Header",
    "page_footer": "Page-Footer",
    "list_item": "List-Item",
    "caption": "Caption",
    "footnote": "Footnote",
    "table": "Table",
    "document_index": "Table-Of-Contents",
    "picture": "Picture",
    "chart": "Picture",
    "key_value_region": "Form",
    "form": "Form",
    "code": "Code",
    "formula": "Formula",
}
_TOKEN = re.compile(r"\w+", re.UNICODE)


@dataclass
class Adapted:
    pages: list[PageContent]
    meta: dict[str, Any] = field(default_factory=dict)


def adapt(document: Any, pages: list[PageContent], upright: Collection[int] = ()) -> Adapted:
    """Inklight pages whose blocks are ``document``'s items; ``pages`` are the OCR pages it was built from, and
    ``upright`` the turned pages (rotation 90/180/270) that were structured turned upright."""
    by_number = {p.number: p for p in pages}
    blocks: dict[int, list[Block]] = {p.number: [] for p in pages}
    pictures = {pic.self_ref for pic in document.pictures}
    kept = {p.number for p in pages if not same_frame(p, document, upright)}
    for item, _level in document.iterate_items(traverse_pictures=True):
        for prov in getattr(item, "prov", []) or []:
            page = by_number.get(prov.page_no)
            if page is None or page.number in kept:
                continue  # a rotated page keeps the OCR's own layout (its boxes are in the upright frame)
            label = _label(item, pictures)
            text = _text(item, document)
            if label == "Picture":
                text = ""  # its words are in its Picture-Text children
            elif not text.strip():
                continue
            out = blocks[page.number]
            box = _to_inklight(prov.bbox, document.pages[prov.page_no].size, page)
            out.append(
                Block(index=len(out), label=label, text=text, bbox=box, conf=_conf(page, box), ref=item.self_ref)
            )
    adapted: list[PageContent] = []
    orphans_total = 0
    for page in pages:
        if page.number in kept or not page.lines:
            adapted.append(page)
            continue
        own = blocks[page.number]
        orphans = _orphans(page, own)
        orphans_total += len(orphans)
        merged = [*own, *orphans]
        adapted.append(
            page.model_copy(
                update={
                    "blocks": tuple(b.model_copy(update={"index": i}) for i, b in enumerate(merged)),
                    "markdown": "\n".join(b.text for b in merged if b.text.strip()),
                }
            )
        )
    meta = {
        "items": sum(len(v) for v in blocks.values()),
        "tables": len(document.tables),
        "pictures": len(document.pictures),
        "orphan_lines": orphans_total,
        "rotated_pages_kept": sorted(kept),  # pages whose frame the structure did not share: OCR layout kept
        "rotated_pages_structured": sorted(p.number for p in pages if p.rotation % 360 and p.number not in kept),
        "foreign_tokens": _foreign_tokens(document, pages),
    }
    return Adapted(adapted, meta)


def same_frame(page: PageContent, document: Any, upright: Collection[int] = ()) -> bool:
    """Whether the structure's page and the OCR's are the same upright frame: a page the OCR read turned counts only
    when it was structured turned upright (``upright``; a structure stored before that keeps the OCR's layout), and
    both have the same shape (a frame turned by one of them and not the other has width and height swapped)."""
    size = getattr(document.pages.get(page.number), "size", None)
    if page.rotation % 360 and page.number not in upright:
        return False
    if size is None or not page.width or not page.height:
        return False
    return abs(size.width / size.height - page.width / page.height) <= 0.02 * (page.width / page.height)


def _label(item: Any, pictures: set[str]) -> str:
    raw = str(getattr(item.label, "value", item.label))
    parent = getattr(getattr(item, "parent", None), "cref", None)
    if raw not in ("picture", "chart") and parent in pictures:
        return "Picture-Text"
    return _LABELS.get(raw, "Text")


def _text(item: Any, document: Any) -> str:
    if type(item).__name__ == "TableItem":
        return table_text(item, document)
    return str(getattr(item, "text", "") or "")


def table_text(table: Any, document: Any) -> str:
    """A table's rows with each value named by its column header: "Name: Samuel Reed | Role: Manager"."""
    grid = table_grid(table, document)
    if not grid.rows:
        return ""
    if grid.field_value():
        key_col, value_col = grid.label_column(), 1 - grid.label_column()
        return "\n".join(
            f"{row[key_col]}: {row[value_col]}" if row[value_col].strip() else row[key_col]
            for row in grid.rows
            if row[key_col].strip()
        )
    lines = list(grid.titles())  # section titles of stacked sub-tables ("الشركاء")
    for heads, body in grid.sections():
        for r in body:
            parts = []
            for c, value in enumerate(grid.rows[r]):
                if not value.strip():
                    continue
                header = grid.header_for(c, heads)
                parts.append(f"{header}: {value}" if header and header != value else value)
            if parts:
                lines.append(" | ".join(dict.fromkeys(parts)))
    if not lines:  # a table of headers only
        lines = [" | ".join(v for v in row if v.strip()) for row in grid.rows]
    return "\n".join(lines)


@dataclass(frozen=True)
class Grid:
    """A table as rows of cell texts (a spanning cell repeated in each slot it covers), with its header rows."""

    rows: list[list[str]]
    header_rows: set[int]
    boxes: list[list[Any]]  # docling_core BoundingBox or None, per slot

    def field_value(self) -> bool:
        """A two-column table of fields and their values, read across ("Company name | Acme Ltd", "Tax number |
        12345"): every row starts with a plain-words label, and some value holds a number. Its first row is a field,
        not a header, even when TableFormer marked it as one ("Name | Role" has no number; "Tax registration number
        | Tax office" over "520-881-306 | Dokki" has a number in its first column)."""
        if len(self.rows) < 3 or len(self.rows[0]) != 2:
            return False  # two rows read either way; a heading over one row of values is the usual one
        key_col = self.label_column()
        labels = [row[key_col] for row in self.rows]
        plain = all(text.strip() and not any(ch.isdigit() for ch in text) for text in labels)
        return plain and any(any(ch.isdigit() for ch in row[1 - key_col]) for row in self.rows)

    def label_column(self) -> int:
        """The column a reader starts each row with: the first for left-to-right text, the last for Arabic."""
        cells = [c for row in self.rows for c in row if c.strip()]
        rtl = sum(layout.rtl(c) for c in cells) > len(cells) / 2
        return len(self.rows[0]) - 1 if rtl and self.rows else 0

    def header_for(self, col: int, rows: list[int] | set[int] | None = None) -> str:
        """The column's header text: its header-row cells top to bottom (of ``rows``, else the table's header rows),
        repeated spans written once."""
        heads = sorted(self.header_rows if rows is None else rows)
        parts = [self.rows[r][col] for r in heads if self.rows[r][col].strip()]
        return " / ".join(dict.fromkeys(parts))

    def heads(self) -> set[int]:
        """The header rows: those TableFormer marked, else the first row when it is words only and rows follow it
        (TableFormer leaves some header rows unmarked)."""
        if self.header_rows:
            return set(self.header_rows)
        return {0} if len(self.rows) > 1 and self._plain(0) else set()

    def sections(self, headers: set[int] | None = None) -> list[tuple[list[int], list[int]]]:
        """The table's stacked sub-tables, as (header rows, body rows). Layout analysis may read a page's stacked
        tables (company, partners, tax card) as one: a break row, empty or holding a single cell such as a section
        title ("الشركاء"), ends a sub-table, and a plain-words row after it heads the next one."""
        heads = sorted(self.heads() if headers is None else headers)
        out: list[tuple[list[int], list[int]]] = []
        body: list[int] = []
        r = heads[-1] + 1 if heads else 0
        while r < len(self.rows):
            if not self._break(r):
                body.append(r)
                r += 1
                continue
            if heads or body:
                out.append((heads, body))
            while r < len(self.rows) and self._break(r):
                r += 1
            heads, body = ([r], []) if r < len(self.rows) and self._plain(r) else ([], [])
            r += 1 if heads else 0
        if heads or body:
            out.append((heads, body))
        return out

    def titles(self) -> list[str]:
        """Text of the break rows that hold a section title."""
        return [next(c for c in row if c.strip()) for r, row in enumerate(self.rows) if self._break(r) and any(row)]

    def _break(self, r: int) -> bool:
        filled = [c for c in self.rows[r] if c.strip()]
        return not filled or (len(self.rows[r]) >= 3 and len(set(filled)) == 1 and len(filled) <= 1)

    def _plain(self, r: int) -> bool:
        filled = [c for c in self.rows[r] if c.strip()]
        return bool(filled) and not any(ch.isdigit() for c in filled for ch in c)


def table_grid(table: Any, document: Any = None) -> Grid:
    data = table.data
    rows: list[list[str]] = [["" for _ in range(data.num_cols)] for _ in range(data.num_rows)]
    boxes: list[list[Any]] = [[None for _ in range(data.num_cols)] for _ in range(data.num_rows)]
    headers: set[int] = set()
    for cell in data.table_cells:
        for r in range(cell.start_row_offset_idx, cell.end_row_offset_idx):
            for c in range(cell.start_col_offset_idx, cell.end_col_offset_idx):
                if 0 <= r < data.num_rows and 0 <= c < data.num_cols:
                    rows[r][c] = (cell.text or "").strip()
                    boxes[r][c] = cell.bbox
        if cell.column_header:
            headers.update(range(cell.start_row_offset_idx, cell.end_row_offset_idx))
    return Grid(rows, headers, boxes)


def to_inklight(bbox: Any, page_size: Any, page: PageContent) -> BBox | None:
    return _to_inklight(bbox, page_size, page)


def _to_inklight(bbox: Any, page_size: Any, page: PageContent) -> BBox | None:
    """A structure box (page units, either origin) in Inklight's frame (pixels of the rendered page, top-left)."""
    if bbox is None or page_size is None or not page.width or not page.height:
        return None
    top_left = bbox.to_top_left_origin(page_height=page_size.height)
    sx, sy = page.width / page_size.width, page.height / page_size.height
    return (
        round(top_left.l * sx, 1),
        round(top_left.t * sy, 1),
        round(top_left.r * sx, 1),
        round(top_left.b * sy, 1),
    )


def _conf(page: PageContent, box: BBox | None) -> float | None:
    if box is None:
        return None
    confs = [ln.conf for ln in page.lines if ln.conf is not None and _centre_in(ln.bbox, box)]
    return round(sum(confs) / len(confs), 4) if confs else None


def _centre_in(inner: BBox | None, outer: BBox, slack: float = 4.0) -> bool:
    if inner is None:
        return False
    cx, cy = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return outer[0] - slack <= cx <= outer[2] + slack and outer[1] - slack <= cy <= outer[3] + slack


def _orphans(page: PageContent, blocks: list[Block]) -> list[Block]:
    """Lines no block holds, as blocks of their own (in page order). A line is held by a block that both covers its
    position and contains its text: a short line ("14%") is not taken as held because its text occurs elsewhere."""
    squashed = [(b, _squash(b.text)) for b in blocks]
    out = []
    for line in page.lines:
        text = _squash(line.text)
        if not text:
            continue
        held = any(
            text in body and (line.bbox is None or b.bbox is None or _centre_in(line.bbox, b.bbox))
            for b, body in squashed
        )
        if not held:
            out.append(Block(index=0, label="Text", text=line.text.strip(), bbox=line.bbox, conf=line.conf))
    return out


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _foreign_tokens(document: Any, pages: list[PageContent]) -> int:
    """Tokens in the structure's text that are not in the OCR's lines: more than zero would mean another text source."""
    known = {t for p in pages for ln in p.lines for t in _TOKEN.findall(ln.text)}
    found = {
        t
        for item, _ in document.iterate_items(traverse_pictures=True)
        for t in _TOKEN.findall(str(getattr(item, "text", "") or ""))
    }
    for table in document.tables:
        found |= {t for cell in table.data.table_cells for t in _TOKEN.findall(cell.text or "")}
    return len(found - known)
