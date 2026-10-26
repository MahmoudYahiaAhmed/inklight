"""The upright and original page frames (frames.py): synthetic geometry, no model.

A page image is drawn upright with a dark box, turned 0/90/180/270 degrees counter-clockwise (Indra's ``rotation``),
and the box is mapped into the turned image: the mapped box must cover the dark pixels and nothing else, stay in
bounds, and map back exactly. The real-model check (Indra and Docling on rotated pages) is in
test_structure_rotation.py.
"""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from inklight.frames import inside, original_size, to_original, to_upright

W, H = 600, 900
BOX = (120.0, 200.0, 360.0, 260.0)


def _upright() -> Image.Image:
    img = Image.new("L", (W, H), 255)
    ImageDraw.Draw(img).rectangle(BOX, fill=0)
    return img


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_a_box_maps_onto_the_turned_page_and_back(rotation):
    shown = _upright().rotate(rotation, expand=True)  # PIL turns counter-clockwise, as Indra's rotation counts
    ow, oh = original_size(rotation, W, H)
    assert shown.size == (ow, oh)
    box = to_original(BOX, rotation, W, H)
    assert inside(box, ow, oh)
    x0, y0, x1, y1 = (round(v) for v in box)
    inner = shown.crop((x0 + 2, y0 + 2, x1 - 2, y1 - 2))
    assert inner.getextrema() == (0, 0), "the mapped box must lie on the dark box"
    ring = shown.crop((max(x0 - 6, 0), max(y0 - 6, 0), min(x1 + 6, ow), min(y1 + 6, oh)))
    assert ring.getextrema()[1] == 255, "and the box must not be smaller than what it marks"
    back = to_upright(box, rotation, W, H)
    assert all(abs(a - b) < 1e-6 for a, b in zip(back, BOX, strict=True))


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_corners_stay_in_bounds(rotation):
    ow, oh = original_size(rotation, W, H)
    for box in [(0.0, 0.0, 1.0, 1.0), (W - 1.0, H - 1.0, W, H), (0.0, H - 5.0, W, H)]:
        assert inside(to_original(box, rotation, W, H), ow, oh)


def test_rotation_must_be_a_quarter_turn():
    with pytest.raises(ValueError):
        to_original(BOX, 45, W, H)
    assert to_original(BOX, 360, W, H) == BOX and to_original(BOX, -90, W, H) == to_original(BOX, 270, W, H)
