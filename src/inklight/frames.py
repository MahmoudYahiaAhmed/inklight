"""Page frames: the page as stored (upright) and the page as the file shows it (original).

Indra reads a page turned sideways or upside down by turning it upright first. ``PageContent.rotation`` is how far
the page as shown is turned counter-clockwise from upright (0, 90, 180 or 270), and the stored lines, blocks, table
cells and citation boxes are all in the upright frame, whose size is ``PageContent.width x height``. Docling is given
the page turned upright too, so its boxes share that frame. Only displaying a box on the page as the file shows it
needs the original frame:

    upright --to_original--> original --to_upright--> upright        (the same box, both ways)

The original frame of a PDF page is pdfium's rendering of it (its own /Rotate applied, as a viewer shows it); of an
image, the image as read. Measured with Indra on a page image turned 0/90/180/270 degrees counter-clockwise: the
stored boxes were identical in all four, and ``rotation`` was the turn.
"""

from __future__ import annotations

BBox = tuple[float, float, float, float]
TURNS = (0, 90, 180, 270)


def _turn(rotation: int) -> int:
    turn = int(rotation or 0) % 360
    if turn not in TURNS:
        raise ValueError(f"page rotation must be a multiple of 90 degrees, not {rotation}")
    return turn


def original_size(rotation: int, width: float, height: float) -> tuple[float, float]:
    """The page's size as the file shows it, from its upright size."""
    return (height, width) if _turn(rotation) in (90, 270) else (width, height)


def _point_to_original(x: float, y: float, turn: int, w: float, h: float) -> tuple[float, float]:
    # The upright page (w x h) turned counter-clockwise by ``turn``.
    if turn == 90:
        return y, w - x
    if turn == 180:
        return w - x, h - y
    if turn == 270:
        return h - y, x
    return x, y


def to_original(box: BBox, rotation: int, width: float, height: float) -> BBox:
    """A box in the upright frame (page ``width x height``) as it lies on the page the file shows."""
    turn = _turn(rotation)
    x0, y0, x1, y1 = box
    a = _point_to_original(x0, y0, turn, width, height)
    b = _point_to_original(x1, y1, turn, width, height)
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


def to_upright(box: BBox, rotation: int, width: float, height: float) -> BBox:
    """A box on the page as the file shows it, in the upright frame; ``width x height`` is the upright size."""
    turn = _turn(rotation)
    inverse = (360 - turn) % 360
    ow, oh = original_size(turn, width, height)
    return to_original(box, inverse, ow, oh)


def inside(box: BBox, width: float, height: float, slack: float = 1.0) -> bool:
    """Whether a box lies within a page of ``width x height``."""
    x0, y0, x1, y1 = box
    return -slack <= x0 <= x1 <= width + slack and -slack <= y0 <= y1 <= height + slack
