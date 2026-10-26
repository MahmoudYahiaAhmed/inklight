"""Rotated pages with the real components: Indra OCR turns the page upright, and Docling is given it upright.

Before this, a page Indra read turned (rotation 90/180/270) was left out of the structure: Docling saw the page as
the file shows it while Indra's lines are in the upright frame, so the two did not match and the page kept Indra's
plain layout. Here the synthetic English registration card (bench/structure/make_synthetic.py), scanned, is turned
90, 180 and 270 degrees counter-clockwise and saved as an image-only PDF. For each: Indra reports the turn, the page
is structured (its lines delivered to Docling, nothing foreign), the answers come from table cells, and each cited
box, mapped back onto the page as the file shows it, covers the value: re-reading that region of the turned page
with Indra finds it.

Skipped where Docling or the OCR models are not available, as in CI (frames.py's geometry is tested without
models in test_frames.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("docling")
pymupdf = pytest.importorskip("pymupdf")

from PIL import Image  # noqa: E402

from inklight import DocumentAgent  # noqa: E402
from inklight.frames import inside, original_size, to_original  # noqa: E402

from .conftest import make_settings  # noqa: E402

pytestmark = [pytest.mark.ocr, pytest.mark.structure]
ROOT = Path(__file__).resolve().parents[1]
TURNS = (90, 180, 270)


@pytest.fixture(scope="module")
def turned(tmp_path_factory):
    sys.path.insert(0, str(ROOT / "bench" / "structure"))
    import make_synthetic

    out = tmp_path_factory.mktemp("turned")
    sys.argv = ["make_synthetic", str(out)]
    make_synthetic.main()
    src = pymupdf.open(out / "regcard-en-scan.pdf")
    pix = src[0].get_pixmap(dpi=150)
    upright = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    files = {}
    for turn in TURNS:
        image = upright.rotate(turn, expand=True, fillcolor="white")
        path = out / f"card-turned-{turn}.pdf"
        image.save(path, resolution=150)
        files[turn] = path
    settings = make_settings(out / "home", structure={"engine": "docling"})
    with DocumentAgent(settings) as agent:
        report = agent.add(list(files.values()))
        assert not report.failed, report.failed
        ids = {d.name: d.id for d in agent.library.documents()}
        yield agent, ids, files


@pytest.mark.parametrize("turn", TURNS)
def test_a_turned_page_is_structured(turned, turn):
    agent, ids, files = turned
    doc_id = ids[files[turn].name]
    page = agent.library.pages(doc_id)[0]
    assert page.rotation == turn
    meta, document = agent.library.structure(doc_id)
    assert 1 in meta["pages_structured"] and meta["rotated_pages_kept"] == [], meta
    assert meta["rotated_pages_structured"] == [1], meta
    lines = sum(1 for ln in page.lines if ln.text.strip() and ln.bbox)
    assert meta["cells_delivered"] == lines and meta["foreign_tokens"] == 0, meta
    assert document.tables, "Docling found no table on the upright page"
    assert page.lines == tuple(page.lines)  # Indra's own lines are kept as read (provenance)


@pytest.mark.parametrize("turn", TURNS)
@pytest.mark.parametrize(
    ("question", "expect"),
    [("What is the company name?", "Golden Palm"), ("What is the registration number?", "47319")],
)
def test_turned_page_answers_cite_the_value_on_the_page_as_shown(turned, turn, question, expect):
    agent, ids, files = turned
    doc_id = ids[files[turn].name]
    res = agent.ask(question, doc_ids=[doc_id], save=False)
    assert expect in res.answer.split("\n\nEvidence:")[0], res.answer
    assert any("table cell" in n for n in res.checks), res.checks
    src = res.sources[0]
    page = agent.library.pages(doc_id)[0]
    # In the stored (upright) frame, Docling's cell box covers the line Indra read the value from.
    held = [ln.bbox for ln in page.lines if expect in ln.text and ln.bbox]
    assert held and any(_overlap(src.bbox, b) > 0.5 for b in held), (src.bbox, held)
    box = to_original(src.bbox, page.rotation, page.width, page.height)
    ow, oh = original_size(page.rotation, page.width, page.height)
    assert inside(box, ow, oh), (box, ow, oh)
    # The page as the file shows it, at the stored frame's scale; the cited region, turned upright, read again.
    shown = pymupdf.open(files[turn])[0]
    scale = ow / shown.rect.width
    pix = shown.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    x0, y0, x1, y1 = box
    pad = 40
    crop = image.crop((max(x0 - pad, 0), max(y0 - pad, 0), min(x1 + pad, image.width), min(y1 + pad, image.height)))
    crop = crop.rotate(-turn, expand=True, fillcolor="white")
    canvas = Image.new("RGB", (max(crop.width + 200, 1000), max(crop.height + 200, 600)), "white")
    canvas.paste(crop, (100, 100))  # OCR's text detector needs a page around a lone value
    crop_path = files[turn].with_name(f"crop-{turn}-{expect[:4]}.png")
    canvas.save(crop_path)
    read = " ".join(ln.text for ln in agent.library.engine.read(crop_path, max_pages=1).pages[0].lines)
    assert all(word in read for word in expect.split()), read


def _overlap(a, b) -> float:  # noqa: ANN001
    """How much of the smaller box the two share."""
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    return w * h / min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
