"""Questions answered from a table's cells, using the recovered table structure (rows, columns, header cells).

A registration card prints "Company name | Company type | Registration number" as column headings over one row of
values; a partners table repeats "Name | Role | Share" for several people. Read as lines, the heading nearest the
question is easily returned as if it were the answer. With the table's cells:

1. Column heading: a header cell naming the question's field ("What is the company name?" -> "Company name") gives
   the value in the same column. The other words of the question pick the row ("Laila Mansour's share", "نسبة
   مشاركة ليلى منصور"); with several rows and nothing to pick one, each row's value is listed and none is chosen.
2. Row label: in a two-way table ("Field | Value"), a body cell naming the field gives the value beside it, in
   reading direction (Arabic: to its left).
3. "Who …?": a body cell matching the question ("Who is the manager?" -> "Manager") gives the name in its row.

The value is never the heading itself, a blank cell is a blank field, and the citation is the value's cell (page
and box). Headings follow the same qualifier rule as printed labels: "Tax registration number" does not answer
"the registration number" when the question lacks "tax" (scope.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..extract import layout
from ..schemas import Candidate, PageContent, Source
from ..structure.adapter import Grid, same_frame, table_grid, to_inklight
from . import lines as ln
from .answer import expected_kind, words
from .binding import _digits, _has_kind, _key
from .context import ToolContext
from .labels import terms_for, wanted_words
from .scope import conflicts
from .unmentioned import say_no_evidence

_MAX_DOCS = 3
_SHOWN = 4  # candidate tables listed when the question does not say which
_NAME_KEYS = {_key(w) for w in words("name names الاسم اسم")}
_VALUE_KEYS = {_key(w) for w in words("value values القيمه")}
_FIELD_KEYS = {_key(w) for w in words("field fields item البيان البند")}
_DATE_KEYS = {_key(w) for w in words("date تاريخ")}
_COUNT_KEYS = {_key(w) for w in words("number no amount total sum value price cost fee رقم عدد مبلغ قيمه اجمالي نسبه")}
_LOW_CELL_CONF = 0.85  # as for a field value read beside its label (extract/fields.py)
_WHO = re.compile(r"(?:who|whom)\b|من\s", re.IGNORECASE)


@dataclass(frozen=True)
class _Hit:
    table: Any
    grid: Grid
    rows: list[int]  # the candidate value rows
    col: int  # the value column (column mode) or -1 (row mode: per row, see cells)
    header: str  # the heading or row label that names the field
    score: float
    overlap: int  # the question's words the heading carries, generic ones too: breaks ties of score
    cells: tuple[tuple[int, int], ...] = ()  # (row, col) of each value, row mode and "who" mode


def table_answer(ctx: ToolContext, question: str) -> str | None:
    """Answer from a table cell; None when no table in scope has a heading or cell for the question."""
    if not wanted_words(question):
        return None
    docs = list(dict.fromkeys(h.source.doc_id for h in ctx.scratch.hits)) or ctx.scratch.doc_ids
    found: list[tuple[str, Any, _Hit]] = []  # every table, in every document in scope, whose heading matches
    for doc_id in docs[:_MAX_DOCS]:
        document = ctx.structure(doc_id)
        if document is None or not document.tables:
            continue
        terms = terms_for(ctx, doc_id, question)
        fields = set(terms.fields) | set(terms.names)
        tables = _upright_tables(ctx, doc_id, document)
        hits = [h for table in tables for h in _hits(table, document, fields, terms)]
        if not hits and fields and _is_who(question):
            hits = [h for table in tables for h in _who_hits(table, document, fields)]
        found += [(doc_id, document, h) for h in hits]
    if not found:
        return None
    found.sort(key=lambda x: (-x[2].score, -x[2].overlap))
    doc_id, document, best = found[0]
    top = [x for x in found if (x[2].score, x[2].overlap) == (best.score, best.overlap)]
    tied = [h for _, _, h in top[1:] if h.header != best.header]
    same = [x for x in top if ln.keys(x[2].header) == ln.keys(best.header)]  # the same heading in other tables
    if len({_values_of(h) for _, _, h in same}) > 1:
        return _say_candidates(ctx, same)
    return _answer(ctx, doc_id, document, best, tied=bool(tied), kind=expected_kind(question))


def _values_of(hit: _Hit) -> tuple[str, ...]:
    cells = hit.cells or tuple((r, hit.col) for r in hit.rows)
    return tuple(" ".join(hit.grid.rows[r][c].split()) for r, c in cells if hit.grid.rows[r][c].strip())


def _say_candidates(ctx: ToolContext, found: list[tuple[str, Any, _Hit]]) -> str:
    """Several tables carry the heading asked about, with different values, and the question does not say which:
    each is listed with its document and page, none is chosen."""
    s = ctx.scratch
    shown, sources = [], []
    s.candidates = []
    for doc_id, document, hit in found[:_SHOWN]:
        doc = ctx.library.get(doc_id)
        page_no = hit.table.prov[0].page_no if hit.table.prov else 1
        page = next((p for p in ctx.pages(doc_id) if p.number == page_no), None)
        cells = hit.cells or tuple((r, hit.col) for r in hit.rows)
        filled = _distinct(hit.grid, [(r, c, hit.grid.rows[r][c]) for r, c in cells if hit.grid.rows[r][c].strip()])
        for r, c, v in filled[:2]:
            where = f"{doc.name}, page {page_no}" if doc is not None else f"page {page_no}"
            shown.append(f"- {v}: table on {where}")
            if doc is not None:
                sources.append(_source(doc, doc_id, document, page, hit, r, c, v))
                s.candidates.append(Candidate(value=v, source=sources[-1], context=f"table on {where}"))
    s.outcome = "ambiguous"
    header = found[0][2].header
    s.answer = f"“{header}” has a different value in each of {len(found)} tables:\n" + "\n".join(shown)
    s.sources = sources
    s.confidence = 0.25
    s.warn(
        f"Low confidence: “{header}” is a heading in {len(found)} tables with different values and the question does "
        "not say which is meant; name the company, person or document."
    )
    s.notes.append(f"answer: the heading “{header}” is in several tables; none chosen")
    return "heading in several tables"


def _upright_tables(ctx: ToolContext, doc_id: str, document: Any) -> list[Any]:
    """Tables on pages whose frame the structure and the OCR share: upright pages, and turned pages structured turned
    upright (a structure stored before that keeps the OCR's own layout on them)."""
    pages = {p.number: p for p in ctx.pages(doc_id)}
    upright = ctx.structure_meta(doc_id).get("rotated_pages_structured", [])
    out = []
    for table in document.tables:
        page = pages.get(table.prov[0].page_no) if table.prov else None
        if page is not None and same_frame(page, document, upright):
            out.append(table)
    return out


def _hits(table: Any, document: Any, fields: set[str], terms: Any) -> list[_Hit]:
    grid = table_grid(table, document)
    if not grid.rows:
        return []
    headers = set() if grid.field_value() else grid.heads()
    body = [r for r in range(len(grid.rows)) if r not in headers]
    grid = Grid(grid.rows, headers, grid.boxes)
    out: list[_Hit] = []
    for heads, rows_below in grid.sections(headers) if headers else []:  # each stacked sub-table on its own
        if not heads or not rows_below:
            continue
        for col in range(len(grid.rows[0])):
            header = grid.header_for(col, heads)
            hit = _scored(header, fields, terms, grid, rows_below, skip_col=col)
            if hit is not None:
                score, rows = hit
                out.append(_Hit(table, grid, rows, col, header, score, _overlap(terms, header)))
    if not _field_value_table(grid):
        return out
    for r in body:  # row labels: a body cell naming the field, its value beside it
        for col, label in enumerate(grid.rows[r]):
            if not label.strip():
                continue
            hit = _scored(label, fields, terms, grid, [r], skip_col=col, own_row=True)
            if hit is None:
                continue
            value_col = _beside(grid, r, col, label)
            if value_col is not None:
                out.append(_Hit(table, grid, [r], -1, label, hit[0] - 0.01, _overlap(terms, label), ((r, value_col),)))
    return out


def _scored(
    header: str, fields: set[str], terms: Any, grid: Grid, body: list[int], *, skip_col: int, own_row: bool = False
) -> tuple[float, list[int]] | None:
    """(score, value rows) when ``header`` names the question's field, else None. Question words the heading
    lacks may name the row instead ("Laila Mansour's share")."""
    if not header.strip() or len(ln.WORD.findall(header)) > ln.MAX_LABEL_WORDS:
        return None
    keys, own = ln.keys(header), ln.own_keys(header)
    leftover = fields - keys
    rows = body
    if leftover and not own_row:
        scoped = [r for r in body if leftover <= _row_keys(grid, r, skip_col)]
        if scoped:
            rows, fields = scoped, fields - leftover
    shared = fields & keys
    if not shared or len(shared) < 0.5 * len(fields) or conflicts(fields, keys, own, terms.about):
        return None
    return len(shared) / len(fields) - 0.15 * len(own - fields), rows


def _who_hits(table: Any, document: Any, fields: set[str]) -> list[_Hit]:
    """ "Who is the manager?": a body cell holding the question's words, answered with its row's name cell. A cell
    that is exactly those words ("Manager") beats one that only contains them ("Deputy Manager"); several equally
    good rows are listed together, not chosen between."""
    grid = table_grid(table, document)
    headers = grid.heads()
    if not headers or not fields or not grid.rows:
        return []
    grid = Grid(grid.rows, headers, grid.boxes)
    matches: list[tuple[int, int, int, list[int]]] = []  # (exactness, row, name column, the section's header rows)
    for heads, body in grid.sections(headers):
        names = [c for c in range(len(grid.rows[0])) if _NAME_KEYS & ln.keys(grid.header_for(c, heads))]
        if not heads or not names:
            continue
        for r in body:
            for c, text in enumerate(grid.rows[r]):
                if c in names or not text.strip() or not fields <= ln.keys(text):
                    continue
                matches.append((int(ln.own_keys(text) == fields), r, names[0], heads))
    if not matches:
        return []
    best = max(m[0] for m in matches)
    chosen = sorted({(r, c) for m, r, c, _ in matches if m == best})
    heads = next(h for m, r, c, h in matches if m == best)
    rows = [r for r, _ in chosen]
    return [_Hit(table, grid, rows, -1, grid.header_for(chosen[0][1], heads), 1.0, 0, tuple(chosen))]


def _field_value_table(grid: Grid) -> bool:
    """A table of fields and their values, read across rows: no header row, or a column headed as the value or
    the field ("Field | Value", "البيان | القيمة"). A table of records ("Name | Role | Share") is read down its
    columns instead, so its cells ("Manager") are values, not labels."""
    if not grid.header_rows or grid.field_value():
        return True
    heads = [ln.keys(grid.header_for(c)) for c in range(len(grid.rows[0]))]
    return any(h & (_VALUE_KEYS | _FIELD_KEYS) for h in heads)


def _overlap(terms: Any, text: str) -> int:
    return len(terms.asked & ln.keys(text))


def _row_keys(grid: Grid, r: int, skip_col: int) -> set[str]:
    return ln.keys(" ".join(v for c, v in enumerate(grid.rows[r]) if c != skip_col))


def _beside(grid: Grid, r: int, col: int, label: str) -> int | None:
    """The value cell of a row label: a column headed as the value, else the nearest non-empty cell after the
    label in reading direction."""
    row = grid.rows[r]
    others = [c for c, v in enumerate(row) if c != col and v.strip() and v != label]
    if not others:
        return None
    valued = [c for c in others if _VALUE_KEYS & ln.keys(grid.header_for(c))]
    if valued:
        return valued[0]
    after = [c for c in others if (c < col if layout.rtl(label) else c > col)]
    if not after:
        return None
    return max(after) if layout.rtl(label) else min(after)


def _is_who(question: str) -> bool:
    return bool(_WHO.match(question.strip())) or expected_kind(question) == "name"


def _answer(ctx: ToolContext, doc_id: str, document: Any, hit: _Hit, *, tied: bool, kind: str | None) -> str:
    s = ctx.scratch
    doc = ctx.library.get(doc_id)
    page_no = hit.table.prov[0].page_no if hit.table.prov else 1
    page = next((p for p in ctx.pages(doc_id) if p.number == page_no), None)
    cells = hit.cells or tuple((r, hit.col) for r in hit.rows)
    values = [(r, c, hit.grid.rows[r][c]) for r, c in cells]
    filled = [(r, c, v) for r, c, v in values if v.strip() and v.strip() != hit.header.strip()]
    filled = _distinct(hit.grid, filled)
    if not filled:
        say_no_evidence(
            ctx,
            f"a value of “{hit.header}”",
            f"the table on page {page_no} has the heading “{hit.header}” but its cell is empty (a blank field)",
        )
        return "blank table cell"
    unread = _unreadable(kind, hit.header, [v for _, _, v in filled])
    if unread:
        say_no_evidence(
            ctx,
            f"a value of “{hit.header}”",
            f"the cell under “{hit.header}” on page {page_no} reads “{unread}”, which is not a {_kind_name(kind, hit)} "
            "(the OCR may have misread it)",
        )
        return "table cell unreadable"
    sources = [_source(doc, doc_id, document, page, hit, r, c, v) for r, c, v in filled[:4]]
    if len(filled) > 1:
        listed = "\n".join(f"- {v}: row of “{_row_name(hit.grid, r, c)}”" for r, c, v in filled[:6])
        s.answer = f"The table on page {page_no} has {len(filled)} values under “{hit.header}”:\n{listed}"
        s.candidates = [
            Candidate(value=v, source=src, context=f"row of “{_row_name(hit.grid, r, c)}”")
            for (r, c, v), src in zip(filled[:4], sources, strict=False)
        ]
        s.outcome = "ambiguous"
        s.warn(
            f"Low confidence: “{hit.header}” has a value in each of {len(filled)} rows and the question does not "
            "say which row is meant; name the person or item."
        )
        s.confidence = 0.25
    else:
        r, c, value = filled[0]
        s.answer = f"{value}\n\nEvidence: “{hit.header}: {value}” (table, page {page_no})"
        conf = sources[0].ocr_conf
        doubt = (
            "more than one table heading matches the question; check the cited cell"
            if tied
            else f"the OCR read this cell with low confidence ({conf:.2f}); check it against the page"
            if conf is not None and conf < _LOW_CELL_CONF
            else ""
        )
        s.confidence = 0.25 if doubt else 0.7
        if doubt:
            s.warn(f"Low confidence: {doubt}.")
    s.sources = sources
    s.notes.append(f"answer: the table cell under “{hit.header}” on page {page_no} ({hit.table.self_ref})")
    return "table cell"


def _distinct(grid: Grid, values: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """One value per cell: a cell spanning several rows ("Department: Sales") is repeated in each slot it covers."""
    seen: set[tuple[str, int]] = set()
    out = []
    for r, c, v in values:
        key = (v, id(grid.boxes[r][c]))
        if key not in seen:
            seen.add(key)
            out.append((r, c, v))
    return out


def _unreadable(kind: str | None, header: str, values: list[str]) -> str | None:
    """The first value that cannot be what the question or heading asks for: a date that does not read as a date,
    an amount or number without a digit."""
    heading = ln.keys(header)
    dated = kind == "date" or bool(heading & _DATE_KEYS)
    counted = kind in ("money", "number") and bool(heading & _COUNT_KEYS)  # "Tax office" is not an amount
    for value in values:
        if dated and not _has_kind("date", _digits(value)):
            return value
        if counted and not any(ch.isdigit() for ch in _digits(value)):
            return value
    return None


def _kind_name(kind: str | None, hit: _Hit) -> str:
    return "date" if kind == "date" or ln.keys(hit.header) & _DATE_KEYS else "number"


def _row_name(grid: Grid, r: int, value_col: int) -> str:
    named = [c for c in range(len(grid.rows[r])) if _NAME_KEYS & ln.keys(grid.header_for(c))]
    for c in [*named, *range(len(grid.rows[r]))]:
        if c != value_col and grid.rows[r][c].strip():
            return grid.rows[r][c]
    return f"row {r + 1}"


def _source(doc, doc_id: str, document: Any, page: PageContent | None, hit: _Hit, r: int, c: int, v: str) -> Source:  # type: ignore[no-untyped-def]
    box = hit.grid.boxes[r][c]
    page_no = hit.table.prov[0].page_no if hit.table.prov else 1
    bbox = to_inklight(box, document.pages[page_no].size, page) if page is not None and box is not None else None
    return Source(
        doc_id=doc_id,
        path=doc.path,
        name=doc.name,
        page=page_no,
        bbox=bbox,
        excerpt=f"{hit.header}\n{v}",
        ocr_conf=_cell_conf(page, bbox),
    )


def _cell_conf(page: PageContent | None, bbox: Any) -> float | None:
    """The lowest confidence the OCR gave a line read inside the cell."""
    if page is None or bbox is None:
        return None
    confs = [
        line.conf
        for line in page.lines
        if line.conf is not None
        and line.bbox is not None
        and bbox[0] - 4 <= (line.bbox[0] + line.bbox[2]) / 2 <= bbox[2] + 4
        and bbox[1] - 4 <= (line.bbox[1] + line.bbox[3]) / 2 <= bbox[3] + 4
    ]
    return min(confs) if confs else None
