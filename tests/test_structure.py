"""Docling's structure on Indra's OCR: the adapter, the stored structure, and answers from table cells.

The OCR lines are fixed (as Indra would store them) and so is the Docling structure (built with docling-core, see
structure_fixtures.py); the questions go through the public ``DocumentAgent.ask``. Only Docling's model inference is
replaced: the adapter, the store, chunking, search, answering and citation checks all run as in production.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("docling_core")

from inklight import DocumentAgent  # noqa: E402
from inklight.library import Library  # noqa: E402
from inklight.schemas import Block, DocStatus, DocumentContent, PageContent, Source, TextLine  # noqa: E402
from inklight.store import Store  # noqa: E402
from inklight.structure import Structured  # noqa: E402
from inklight.structure.adapter import adapt, table_text  # noqa: E402

from . import structure_fixtures as fx  # noqa: E402
from .conftest import make_settings  # noqa: E402

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC")
FIXTURES = {"card-ar.png": fx.arabic_card, "partners-en.png": fx.english_partners, "fields-mixed.png": fx.mixed_fields}


@pytest.fixture(scope="module", autouse=True)
def _no_model_preload():
    """These tests replace Docling's inference with fixed documents: its models need not load in the background."""
    mp = pytest.MonkeyPatch()
    mp.setattr("inklight.structure.docling_run.preload", lambda settings: None)
    yield
    mp.undo()


def _page(fixture: fx.Page) -> PageContent:
    lines = tuple(TextLine(text=t, bbox=b, conf=c) for t, b, c in fixture.lines)
    blocks = tuple(Block(index=i, label="Text", text=ln.text, bbox=ln.bbox, conf=ln.conf) for i, ln in enumerate(lines))
    return PageContent(
        number=1, width=fx.PIXEL_W, height=fx.PIXEL_H, source="ocr", lines=lines, blocks=blocks,
        markdown="\n".join(ln.text for ln in lines),
    )  # fmt: skip


class FixedOCR:
    """Stands in for Indra: the fixed lines of each fixture page."""

    name = "indra"

    def __init__(self, pages: dict[str, fx.Page]) -> None:
        self.pages = pages

    def supports(self, kind: str) -> bool:
        return kind in ("png", "jpeg")

    def read(self, path: Path, *, max_pages: int, password: str | None = None) -> DocumentContent:  # noqa: ARG002
        return DocumentContent(path=str(path), pages=(_page(self.pages[path.name]),), total_pages=1, engine="indra")


def _fixed_structure(pages: dict[str, fx.Page]):  # noqa: ANN202
    """structure_document with Docling's inference replaced by the fixture's DoclingDocument."""

    def run(path: Path, content: DocumentContent, settings, password=None) -> Structured:  # noqa: ANN001, ARG001
        document = pages[path.name].doc
        adapted = adapt(document, list(content.pages))
        meta = {**adapted.meta, "components": {"docling": "fixture"}, "cells_delivered": len(content.pages[0].lines)}
        return Structured(
            content=content.model_copy(update={"pages": tuple(adapted.pages)}),
            document_json=json.dumps(document.export_to_dict(), ensure_ascii=False),
            meta=meta,
        )

    return run


@pytest.fixture(scope="module")
def library(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("structure")
    pages = {name: build() for name, build in FIXTURES.items()}
    for k, name in enumerate(pages):
        (tmp / name).write_bytes(PNG + bytes(k + 40))
    settings = make_settings(tmp / "home", structure={"engine": "docling"})
    lib = Library(settings, engine=FixedOCR(pages))
    mp = pytest.MonkeyPatch()
    mp.setattr("inklight.structure.structure_document", _fixed_structure(pages))
    agent = DocumentAgent(settings, library=lib)
    agent.add([tmp / n for n in pages])
    ids = {d.name: d.id for d in agent.library.documents()}
    yield agent, ids, pages
    mp.undo()
    agent.close()
    lib.close()


def _ask(library, doc: str, q: str):  # noqa: ANN202
    agent, ids, _ = library
    return agent.ask(q, doc_ids=[ids[doc]], save=False)


def _head(res) -> str:  # noqa: ANN001
    return res.answer.split("\n\nEvidence:")[0]


def _flagged(res) -> bool:  # noqa: ANN001
    return any(w.startswith("Low confidence") for w in res.warnings)


# ---------------------------------------------------------------- answers from table cells


@pytest.mark.parametrize(
    ("doc", "question", "expect", "not_expected"),
    [
        # Arabic, right to left: the value under the heading, never the heading itself
        ("card-ar.png", "ما اسم الشركة؟", "شركة النخيل الذهبي للتجارة", "اسم الشركة"),
        ("card-ar.png", "ما نوع الشركة؟", "شركة ذات مسئولية محدودة", "نوع الشركة"),
        ("card-ar.png", "ما رقم القيد؟", "٤٧٣١٩", "١٢/٠٣/٢٠٢٤"),  # printed digits kept as printed
        ("card-ar.png", "ما تاريخ القيد؟", "١٢/٠٣/٢٠٢٤", "٤٧٣١٩"),
        ("card-ar.png", "ما المأمورية؟", "مأمورية ضرائب الدقي", "٥٢٠"),  # a header row Docling did not mark
        ("card-ar.png", "ما رقم التسجيل الضريبي؟", "٥٢٠-٨٨١-٣٠٦", "مأمورية"),
        # several people, the same fields: the row named in the question
        ("card-ar.png", "ما نسبة مشاركة ليلى منصور؟", "٤٠٪", "٦٠٪"),
        ("card-ar.png", "من المدير؟", "سامي عبد الرحيم", "ليلى"),
        # English: generic words decide between "Company name" and "Company type"
        ("partners-en.png", "What is the company name?", "Golden Palm Trading Co.", "Limited"),
        ("partners-en.png", "What is the company type?", "Limited liability company", "Golden"),
        # merged two-level headings ("Contribution / Amount") and the row of the person named
        ("partners-en.png", "What is Laila Mansour's contribution amount?", "3,000", "5,000"),
        ("partners-en.png", "What is Samuel Reed's role?", "Manager", "Partner"),
        ("partners-en.png", "Who is the manager?", "Samuel Reed", "Laila"),
        # a field/value table in two languages
        ("fields-mixed.png", "What is the company name?", "Golden Palm Trading Co.", "Company name"),
        ("fields-mixed.png", "ما رقم القيد؟", "47319", "Limited"),
        ("fields-mixed.png", "What is the company type?", "Limited liability company", "Golden"),
    ],
)
def test_a_table_value_is_answered_from_its_cell(library, doc, question, expect, not_expected):
    res = _ask(library, doc, question)
    head = _head(res)
    assert expect in head and not_expected not in head, res.answer
    assert not _flagged(res), res.warnings
    src = res.sources[0]
    assert src.page == 1 and src.bbox is not None and expect in src.excerpt
    assert not any("Dropped a citation" in w for w in res.warnings), res.warnings


def test_the_cited_box_is_the_value_cell_in_the_pixel_frame(library):
    """Docling's bottom-left page coordinates come back as the OCR's top-left pixel box of the cell."""
    res = _ask(library, "card-ar.png", "ما اسم الشركة؟")
    x0, y0, x1, y1 = res.sources[0].bbox
    assert (x0, y0, x1, y1) == pytest.approx((700, 200, 890, 240), abs=0.5)


def test_a_wrapped_value_is_whole(library):
    res = _ask(library, "partners-en.png", "What is the company name?")
    assert _head(res).startswith("Golden Palm Trading Co."), res.answer


def test_a_blank_cell_is_declined_as_a_blank_field(library):
    res = _ask(library, "partners-en.png", "What is Samuel Reed's payment date?")
    assert res.answer.startswith("I couldn't find supporting evidence"), res.answer
    assert any("blank" in c for c in res.checks), res.checks


@pytest.mark.parametrize(
    ("doc", "question"),
    [("card-ar.png", "ما نسبة المشاركة؟"), ("partners-en.png", "What is the contribution amount?")],
)
def test_a_field_repeated_for_several_people_is_listed_not_chosen(library, doc, question):
    res = _ask(library, doc, question)
    assert _flagged(res) and res.confidence <= 0.25, (res.answer, res.warnings)
    assert len(res.sources) == 2, res.sources


# ---------------------------------------------------------------- what the structure keeps


def test_original_ocr_lines_and_boxes_are_kept_unchanged(library):
    agent, ids, pages = library
    stored = agent.library.pages(ids["card-ar.png"])[0]
    original = [(t, b, c) for t, b, c in pages["card-ar.png"].lines]
    assert [(ln.text, ln.bbox, ln.conf) for ln in stored.lines] == original


def test_blocks_follow_docling_with_refs_and_header_named_values(library):
    agent, ids, _ = library
    blocks = agent.library.pages(ids["card-ar.png"])[0].blocks
    tables = [b for b in blocks if b.label == "Table"]
    assert [b.ref for b in tables] == ["#/tables/0", "#/tables/1", "#/tables/2"]
    assert "اسم الشركة: شركة النخيل الذهبي للتجارة" in tables[0].text
    assert "الاسم: ليلى منصور" in tables[1].text and "نسبة المشاركة: ٤٠٪" in tables[1].text
    assert blocks[0].label == "Section-Header" and blocks[0].ref == "#/texts/0"


def test_text_inside_a_picture_is_kept_and_searchable(library):
    agent, ids, _ = library
    blocks = agent.library.pages(ids["card-ar.png"])[0].blocks
    assert any(b.label == "Picture-Text" and b.text == "ختم الإدارة" for b in blocks)
    hits = agent.search("ختم الإدارة")
    assert any(h.source.doc_id == ids["card-ar.png"] for h in hits)


def test_the_structure_is_stored_with_what_ran(library):
    agent, ids, _ = library
    meta, document = agent.library.structure(ids["card-ar.png"])
    assert meta["foreign_tokens"] == 0 and meta["orphan_lines"] == 0 and meta["tables"] == 3
    assert document is not None and len(document.tables) == 3


def test_structured_exports_hold_every_ocr_line(library):
    agent, ids, pages = library
    _, document = agent.library.structure(ids["card-ar.png"])
    markdown = "".join(document.export_to_markdown(traverse_pictures=True).split())
    as_json = json.dumps(document.export_to_dict(), ensure_ascii=False)
    for text, _box, _conf in pages["card-ar.png"].lines:
        assert "".join(text.split()) in markdown, text
        assert text in as_json, text


def test_the_structure_cli_exports_markdown_and_json(library, tmp_path):
    from typer.testing import CliRunner

    from inklight.cli import app

    agent, ids, _ = library
    config = tmp_path / "config.toml"
    home = agent.settings.home.as_posix()
    config.write_text(
        f'home = "{home}"\n[models]\nbrain = "rules"\n[structure]\nengine = "docling"\n', encoding="utf-8"
    )
    runner = CliRunner()
    md = runner.invoke(app, ["structure", ids["card-ar.png"], "--format", "md", "-c", str(config)])
    assert md.exit_code == 0 and "شركة النخيل الذهبي للتجارة" in md.output, md.output
    meta = runner.invoke(app, ["structure", ids["card-ar.png"], "--format", "meta", "-c", str(config)])
    assert meta.exit_code == 0 and json.loads(meta.output)["tables"] == 3


# ---------------------------------------------------------------- the adapter on its own


def test_a_line_docling_did_not_place_is_kept_as_a_block():
    page = fx.Page()
    page.line("Placed", (100, 100, 300, 140))
    page.text(fx.DocItemLabel.TEXT, "Placed", (100, 100, 300, 140))
    page.line("Missed by layout", (100, 600, 500, 640))
    adapted = adapt(page.doc, [_page(page)])
    texts = [b.text for b in adapted.pages[0].blocks]
    assert texts == ["Placed", "Missed by layout"] and adapted.meta["orphan_lines"] == 1


def test_text_docling_has_that_indra_did_not_read_is_counted():
    page = fx.Page()
    page.line("Indra read this", (100, 100, 400, 140))
    page.text(fx.DocItemLabel.TEXT, "Indra read this plus extra", (100, 100, 400, 140))
    assert adapt(page.doc, [_page(page)]).meta["foreign_tokens"] == 2


def test_a_merged_heading_names_each_column_it_spans():
    page = fx.english_partners()
    text = table_text(page.doc.tables[1], page.doc)
    assert "Contribution / Amount: 3,000" in text and "Partner / Name: Laila Mansour" in text
    assert "Payment date: |" not in text  # a blank cell is left out, not written as empty


def test_a_rotated_page_keeps_indras_own_layout():
    page = fx.arabic_card()
    content = _page(page).model_copy(update={"rotation": 90})
    adapted = adapt(page.doc, [content])
    assert adapted.pages[0].blocks == content.blocks and adapted.meta["rotated_pages_kept"] == [1]


# ---------------------------------------------------------------- failures and compatibility


def test_a_structure_failure_keeps_the_document_and_says_so(tmp_path, monkeypatch):
    pages = {"card-ar.png": fx.arabic_card()}
    (tmp_path / "card-ar.png").write_bytes(PNG + b"x")
    settings = make_settings(tmp_path / "home", structure={"engine": "docling"})

    def broken(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("layout model missing")

    monkeypatch.setattr("inklight.structure.structure_document", broken)
    with Library(settings, engine=FixedOCR(pages)) as lib:
        report = lib.add([tmp_path / "card-ar.png"])
        doc = lib.documents()[0]
        assert doc.status == DocStatus.READY and not report.failed
        assert lib.structure(doc.id) is None
        assert lib.pages(doc.id)[0].blocks[0].ref is None  # Indra's own blocks


def test_structure_off_runs_no_docling(tmp_path, monkeypatch):
    pages = {"card-ar.png": fx.arabic_card()}
    (tmp_path / "card-ar.png").write_bytes(PNG + b"y")
    monkeypatch.setattr("inklight.structure.structure_document", lambda *a, **k: pytest.fail("Docling ran"))
    with Library(make_settings(tmp_path / "home"), engine=FixedOCR(pages)) as lib:
        lib.add([tmp_path / "card-ar.png"])
        assert lib.structure(lib.documents()[0].id) is None


def test_a_library_from_before_structure_support_opens_and_keeps_its_blocks(tmp_path):
    db_path = tmp_path / "library.db"
    db = sqlite3.connect(db_path)
    db.executescript(
        """
        CREATE TABLE documents (id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            sha256 TEXT NOT NULL, size INTEGER, mtime REAL, pages INTEGER DEFAULT 0, total_pages INTEGER DEFAULT 0,
            status TEXT NOT NULL, doc_type TEXT DEFAULT 'unknown', engine TEXT DEFAULT '', error TEXT,
            mean_conf REAL, added_at TEXT);
        CREATE TABLE blocks (doc_id TEXT NOT NULL, page INTEGER NOT NULL, idx INTEGER NOT NULL, label TEXT, text TEXT,
            bbox TEXT, conf REAL, PRIMARY KEY (doc_id, page, idx));
        INSERT INTO documents (id, path, name, sha256, status) VALUES ('d1', '/x/a.png', 'a.png', '0', 'ready');
        INSERT INTO blocks VALUES ('d1', 1, 0, 'Text', 'old block', '[1, 2, 3, 4]', 0.9);
        """
    )
    db.close()
    with Store(db_path) as store:
        ((page, block),) = store.get_blocks("d1")
        assert block.text == "old block" and block.ref is None
        assert store.get_structure("d1") is None


# ---------------------------------------------------------------- citations


def test_an_answer_that_loses_its_only_citation_is_not_presented_as_supported(library, monkeypatch):
    """A citation's presence is not proof: when the only one cannot be found in the document, the answer is
    marked unverified, flagged, and its confidence capped."""

    def made_up(ctx, question):  # noqa: ANN001, ANN202, ARG001
        doc_id = ctx.scratch.doc_ids[0]
        doc = ctx.library.get(doc_id)
        ctx.scratch.answer = "Ocean Breeze Holdings"
        ctx.scratch.confidence = 0.7
        ctx.scratch.sources = [
            Source(doc_id=doc_id, path=doc.path, name=doc.name, page=1, excerpt="Ocean Breeze Holdings")
        ]
        return "table cell"

    monkeypatch.setattr("inklight.agent.table_answer.table_answer", made_up)
    res = _ask(library, "partners-en.png", "What is the company name?")
    assert res.answer.startswith("Unverified"), res.answer
    assert not res.sources and res.confidence <= 0.2 and _flagged(res)


def test_a_citation_of_separate_lines_is_kept_when_each_line_is_in_the_document(library):
    res = _ask(library, "card-ar.png", "ما رقم القيد؟")
    assert res.sources and res.sources[0].excerpt == "رقم القيد\n٤٧٣١٩"
    assert not any("Dropped a citation" in w for w in res.warnings)


# ---------------------------------------------------------------- from the review of the first version

MORE = {
    "kv-plain.png": lambda: fx.key_value(flag_first_row=False),
    "kv-flagged.png": lambda: fx.key_value(flag_first_row=True),
    "kv-ar.png": fx.key_value_arabic,
    "staff.png": fx.staff,
}


@pytest.fixture(scope="module")
def more(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("structure-more")
    pages = {name: build() for name, build in MORE.items()}
    for k, name in enumerate(pages):
        (tmp / name).write_bytes(PNG + bytes(k + 70))
    settings = make_settings(tmp / "home", structure={"engine": "docling"})
    lib = Library(settings, engine=FixedOCR(pages))
    mp = pytest.MonkeyPatch()
    mp.setattr("inklight.structure.structure_document", _fixed_structure(pages))
    agent = DocumentAgent(settings, library=lib)
    agent.add([tmp / n for n in pages])
    ids = {d.name: d.id for d in agent.library.documents()}
    yield agent, ids, pages
    mp.undo()
    agent.close()
    lib.close()


@pytest.mark.parametrize("doc", ["kv-plain.png", "kv-flagged.png"])
def test_a_field_value_table_is_read_across_its_rows(more, doc):
    """Its first row is a field, not a header, whether or not TableFormer marked it as one."""
    res = _ask(more, doc, "What is the company name?")
    assert _head(res).startswith("Acme Ltd"), res.answer
    res = _ask(more, doc, "What is the tax number?")
    assert _head(res).startswith("12345"), res.answer
    agent, ids, _ = more
    table = next(b for b in agent.library.pages(ids[doc])[0].blocks if b.label == "Table")
    assert "Company name: Acme Ltd" in table.text and "Company name: Tax number" not in table.text


def test_a_right_to_left_field_value_table_reads_from_its_rightmost_column(more):
    res = _ask(more, "kv-ar.png", "ما رقم القيد؟")
    assert _head(res).startswith("٤٧٣١٩"), res.answer


def test_who_prefers_the_exact_role_and_lists_equal_ones(more):
    res = _ask(more, "staff.png", "Who is the manager?")
    assert _head(res).startswith("Rana Saleh") and not _flagged(res), res.answer
    res = _ask(more, "staff.png", "Who is the partner?")
    assert _flagged(res) and "Yusuf Amr" in res.answer and "Hala Nabil" in res.answer, res.answer


def test_a_cell_spanning_several_rows_is_one_value(more):
    res = _ask(more, "staff.png", "What is the department?")
    assert _head(res).startswith("Sales") and not _flagged(res), res.answer


def test_a_short_line_whose_text_occurs_elsewhere_is_still_kept(more):
    agent, ids, _ = more
    blocks = agent.library.pages(ids["staff.png"])[0].blocks
    assert any(b.text == "14%" and b.bbox == (700, 400, 760, 440) for b in blocks), [b.text for b in blocks]


def test_a_page_in_another_frame_keeps_indras_layout():
    """An image one side turned upright (width and height swapped) is not the same frame: no structure is mapped."""
    page = fx.arabic_card()
    content = _page(page).model_copy(update={"width": fx.PIXEL_H, "height": fx.PIXEL_W})
    adapted = adapt(page.doc, [content])
    assert adapted.pages[0].blocks == content.blocks and adapted.meta["rotated_pages_kept"] == [1]


def test_without_stored_text_the_structure_keeps_only_what_ran(tmp_path, monkeypatch):
    pages = {"card-ar.png": fx.arabic_card()}
    (tmp_path / "card-ar.png").write_bytes(PNG + b"p")
    monkeypatch.setattr("inklight.structure.structure_document", _fixed_structure(pages))
    settings = make_settings(tmp_path / "home", structure={"engine": "docling"}, privacy={"store_text": False})
    with Library(settings, engine=FixedOCR(pages)) as lib:
        lib.add([tmp_path / "card-ar.png"])
        meta, document = lib.structure(lib.documents()[0].id)
        assert document is None and meta["tables"] == 3


def test_a_citation_of_lines_from_another_page_is_dropped(library, monkeypatch):
    """Each line of a citation must be on the page it cites."""

    def elsewhere(ctx, question):  # noqa: ANN001, ANN202, ARG001
        doc_id = ctx.scratch.doc_ids[0]
        doc = ctx.library.get(doc_id)
        ctx.scratch.answer, ctx.scratch.confidence = "Golden Palm Trading Co.", 0.7
        ctx.scratch.sources = [
            Source(doc_id=doc_id, path=doc.path, name=doc.name, page=2, excerpt="Company name\nGolden Palm Trading")
        ]
        return "table cell"

    monkeypatch.setattr("inklight.agent.table_answer.table_answer", elsewhere)
    res = _ask(library, "partners-en.png", "What is the company name?")
    assert res.answer.startswith("Unverified") and not res.sources, res.answer


def test_the_structure_endpoint(library, monkeypatch):
    from fastapi.testclient import TestClient

    from inklight.server import create_app

    agent, ids, _ = library
    monkeypatch.setenv("INKLIGHT_ALLOWED_HOSTS", "testserver")
    client = TestClient(create_app(agent.settings, agent=agent))
    doc_id = ids["card-ar.png"]
    assert client.get(f"/api/documents/{doc_id}/structure?format=meta").json()["tables"] == 3
    assert "شركة النخيل" in client.get(f"/api/documents/{doc_id}/structure?format=md").text
    html = client.get(f"/api/documents/{doc_id}/structure?format=html")
    assert html.status_code == 200 and "x-inklight-note" in html.headers  # the stamp's text is not in Docling's HTML
    assert client.get(f"/api/documents/{doc_id}/structure?format=pdf").status_code == 400
    assert client.get("/api/documents/nope/structure").status_code == 404


# ---------------------------------------------------------------- only the pages with tables


def test_only_pages_where_indra_found_a_table_are_chosen():
    from inklight.config import StructureSettings
    from inklight.structure.docling_run import chosen_pages

    text_page = _page(fx.Page()).model_copy(update={"number": 1, "blocks": (Block(index=0, label="Text", text="x"),)})
    table_page = _page(fx.arabic_card()).model_copy(
        update={"number": 2, "blocks": (Block(index=0, label="Table", text="y"),)}
    )
    pages = [text_page, table_page]
    assert [p.number for p in chosen_pages(pages, StructureSettings(pages="tables"))] == [2]
    assert [p.number for p in chosen_pages(pages, StructureSettings(pages="all"))] == [1, 2]


def test_docling_page_numbers_are_mapped_back_to_the_documents():
    from inklight.structure.docling_run import _renumbered

    document = fx.arabic_card().doc  # Docling numbered the one page it was given 1; it is the document's page 3
    _renumbered(document, {1: 3})
    assert list(document.pages) == [3] and document.pages[3].page_no == 3
    assert all(p.page_no == 3 for t in document.tables for p in t.prov)
    assert all(p.page_no == 3 for item, _ in document.iterate_items(traverse_pictures=True) for p in item.prov)


# ---------------------------------------------------------------- stacked tables read as one


@pytest.fixture(scope="module")
def stacked(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("structure-stacked")
    pages = {"stacked.png": fx.stacked_card()}
    (tmp / "stacked.png").write_bytes(PNG + b"stacked")
    settings = make_settings(tmp / "home", structure={"engine": "docling"})
    lib = Library(settings, engine=FixedOCR(pages))
    mp = pytest.MonkeyPatch()
    mp.setattr("inklight.structure.structure_document", _fixed_structure(pages))
    agent = DocumentAgent(settings, library=lib)
    agent.add([tmp / "stacked.png"])
    ids = {d.name: d.id for d in agent.library.documents()}
    yield agent, ids, pages
    mp.undo()
    agent.close()
    lib.close()


@pytest.mark.parametrize(
    ("question", "expect", "absent"),
    [
        ("ما اسم الشركة؟", "شركة النخيل الذهبي للتجارة", "سامي"),
        ("ما نوع الشركة؟", "شركة ذات مسئولية محدودة", "مدير"),
        ("من المدير؟", "سامي عبد الرحيم", "ليلى"),
        ("ما نسبة مشاركة ليلى منصور؟", "٤٠٪", "٦٠٪"),
        ("ما المأمورية؟", "مأمورية ضرائب الدقي", "شريك"),
        ("ما رقم التسجيل الضريبي؟", "٥٢٠-٨٨١-٣٠٦", "شركة"),
    ],
)
def test_each_stacked_table_answers_under_its_own_heading(stacked, question, expect, absent):
    res = _ask(stacked, "stacked.png", question)
    head = _head(res)
    assert head.startswith(expect) and absent not in head, res.answer
    assert not _flagged(res), res.warnings


def test_stacked_tables_are_indexed_under_their_own_headings(stacked):
    agent, ids, _ = stacked
    table = next(b for b in agent.library.pages(ids["stacked.png"])[0].blocks if b.label == "Table")
    assert "الاسم: سامي عبد الرحيم" in table.text and "المأمورية: مأمورية ضرائب الدقي" in table.text
    assert "اسم الشركة: الاسم" not in table.text and "الشركاء" in table.text
