"""Page geometry for label → value lookup.

Reading order flattens two-column blocks ("Seller:" "Client:" then both addresses) and summary
rows ("Total  $ 2 205,34  $ 220,53  $ 2 425,87"), so the value after a label in reading order is
often someone else's. When lines carry boxes, a label's value is looked for where people look:
to its right on the same row, else directly below it in the same column.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from ..schemas import BBox


class Placed(Protocol):
    page: int
    text: str
    bbox: BBox | None


def _height(b: BBox) -> float:
    return max(b[3] - b[1], 1.0)


def same_row(a: BBox, b: BBox) -> bool:
    """Vertical overlap of at least half the shorter line."""
    overlap = min(a[3], b[3]) - max(a[1], b[1])
    return overlap >= 0.5 * min(_height(a), _height(b))


def same_column(a: BBox, b: BBox, slack: float = 12.0) -> bool:
    return b[0] < a[2] + slack and b[2] > a[0] - slack


def row_right(lines: Sequence[Placed], i: int) -> list[int]:
    """Indices of lines to the right of line ``i`` on its row, left to right."""
    me = lines[i]
    if me.bbox is None:
        return []
    out = [
        j
        for j, ln in enumerate(lines)
        if j != i
        and ln.page == me.page
        and ln.bbox is not None
        and ln.bbox[0] >= me.bbox[2] - 4
        and same_row(me.bbox, ln.bbox)
    ]
    return sorted(out, key=lambda j: lines[j].bbox[0])  # type: ignore[index]


def below(lines: Sequence[Placed], i: int, max_gap_lines: float = 3.0) -> int | None:
    """The nearest line under line ``i`` in the same column, within a few line heights."""
    me = lines[i]
    if me.bbox is None:
        return None
    limit = me.bbox[3] + max_gap_lines * _height(me.bbox)
    best: int | None = None
    for j, ln in enumerate(lines):
        if j == i or ln.page != me.page or ln.bbox is None:
            continue
        if ln.bbox[1] < me.bbox[3] - 2 or ln.bbox[1] > limit or not same_column(me.bbox, ln.bbox):
            continue
        if best is None or ln.bbox[1] < lines[best].bbox[1]:  # type: ignore[index]
            best = j
    return best


def header_above(lines: Sequence[Placed], j: int, is_header: Callable[[str], bool]) -> int | None:
    """The nearest line above line ``j`` in its column that ``is_header`` accepts (a column title)."""
    me = lines[j]
    if me.bbox is None:
        return None
    best: int | None = None
    for k, ln in enumerate(lines):
        if k == j or ln.page != me.page or ln.bbox is None or ln.bbox[3] > me.bbox[1] + 2:
            continue
        if not same_column(me.bbox, ln.bbox, slack=0) or not is_header(ln.text):
            continue
        if best is None or ln.bbox[3] > lines[best].bbox[3]:  # type: ignore[index]
            best = k
    return best


def gap(a: BBox, b: BBox) -> float:
    """Horizontal gap from ``a`` to ``b``, in heights of ``a``."""
    return (b[0] - a[2]) / _height(a)
