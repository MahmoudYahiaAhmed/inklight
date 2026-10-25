"""End to end with the real components: Indra OCR, then Docling's layout and TableFormer models on Indra's lines.

Skipped where Docling (an optional install) or the OCR models are not available, as in CI. The documents are the
synthetic registration cards of bench/structure/make_synthetic.py, scanned (no text layer).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("docling")
pytest.importorskip("pymupdf")

from inklight import DocumentAgent  # noqa: E402
from inklight.schemas import TextLine  # noqa: E402

from .conftest import make_settings  # noqa: E402

pytestmark = [pytest.mark.ocr, pytest.mark.structure]
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def cards(tmp_path_factory):
    sys.path.insert(0, str(ROOT / "bench" / "structure"))
    import make_synthetic

    out = tmp_path_factory.mktemp("cards")
    sys.argv = ["make_synthetic", str(out)]
    make_synthetic.main()
    settings = make_settings(out / "home", structure={"engine": "docling"})
    with DocumentAgent(settings) as agent:
        report = agent.add([out / "regcard-en-scan.pdf", out / "regcard-ar-scan.pdf"])
        assert not report.failed, report.failed
        ids = {d.name: d.id for d in agent.library.documents()}
        yield agent, ids, out


def _head(res) -> str:  # noqa: ANN001
    return res.answer.split("\n\nEvidence:")[0]


@pytest.mark.parametrize(
    ("question", "expect"),
    [
        ("What is the company name?", "Golden Palm Trading Co"),
        ("What is the company type?", "Limited liability company"),
        ("What is the registration number?", "47319"),
        ("Who is the manager?", "Samuel Reed"),
        ("What is Laila Mansour's share?", "40%"),
    ],
)
def test_english_card_answers_come_from_table_cells(cards, question, expect):
    agent, ids, _ = cards
    res = agent.ask(question, doc_ids=[ids["regcard-en-scan.pdf"]], save=False)
    assert expect in _head(res), res.answer
    assert res.sources and res.sources[0].bbox is not None


@pytest.mark.parametrize(
    ("question", "expect"),
    [("ما اسم الشركة؟", "شركة النخيل الذهبي للتجارة"), ("من المدير؟", "سامي عبد الرحيم")],
)
def test_arabic_card_answers_are_values_not_headings(cards, question, expect):
    agent, ids, _ = cards
    res = agent.ask(question, doc_ids=[ids["regcard-ar-scan.pdf"]], save=False)
    assert expect in _head(res), res.answer


def test_docling_text_is_indras_text_only(cards):
    """Every cell Docling worked on came from Indra's stored lines: none was read a second time."""
    agent, ids, _ = cards
    for name, doc_id in ids.items():
        meta, document = agent.library.structure(doc_id)
        lines = sum(1 for p in agent.library.pages(doc_id) for ln in p.lines if ln.text.strip() and ln.bbox)
        assert meta["cells_delivered"] == lines, (name, meta)
        assert meta["foreign_tokens"] == 0 and meta["orphan_lines"] == 0, (name, meta)
        assert "Indra's stored lines" in meta["components"]["ocr"]


def test_docling_runs_no_ocr_of_its_own(cards):
    """Control: with every Indra line replaced by a marker word, Docling's output holds the markers only."""
    from inklight.structure import structure_document

    agent, ids, out = cards
    content = agent.library.engine.read(out / "regcard-en-scan.pdf", max_pages=5)
    marked = content.model_copy(
        update={
            "pages": tuple(
                p.model_copy(
                    update={"lines": tuple(TextLine(text=f"MARK{i}", bbox=ln.bbox) for i, ln in enumerate(p.lines))}
                )
                for p in content.pages
            )
        }
    )
    done = structure_document(out / "regcard-en-scan.pdf", marked, agent.settings.structure)
    words = {w.strip("|:") for p in done.content.pages for b in p.blocks for w in b.text.split()} - {""}
    assert words and all(w.startswith("MARK") for w in words), sorted(words)[:10]
    assert done.meta["foreign_tokens"] == 0
    assert done.meta["cells_delivered"] == sum(1 for p in marked.pages for ln in p.lines if ln.bbox)
