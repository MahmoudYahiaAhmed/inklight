"""Fixed OCR lines and fixed Docling structure for the structure tests.

The OCR side is what Indra would store (text, a box in the page's pixel frame, a confidence). The structure side is
built with docling-core's own API, in Docling's coordinates: page units with the origin at the BOTTOM-left, at half
the scale of the pixel frame, so the conversion back into Inklight's frame is exercised. Only Docling's model
inference is replaced; its data model, serialisation and exports are the real ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from docling_core.types.doc import (
    BoundingBox,
    CoordOrigin,
    DocItemLabel,
    DoclingDocument,
    ProvenanceItem,
    Size,
    TableCell,
    TableData,
)

PIXEL_W, PIXEL_H = 1000.0, 1400.0  # Inklight's frame (the rendered page)
POINT_W, POINT_H = 500.0, 700.0  # Docling's page size


def to_docling(box: tuple[float, float, float, float]) -> BoundingBox:
    x0, y0, x1, y1 = box
    return BoundingBox(l=x0 / 2, t=POINT_H - y0 / 2, r=x1 / 2, b=POINT_H - y1 / 2, coord_origin=CoordOrigin.BOTTOMLEFT)


def prov(box: tuple[float, float, float, float], text: str = "", page: int = 1) -> ProvenanceItem:
    return ProvenanceItem(page_no=page, bbox=to_docling(box), charspan=(0, len(text)))


@dataclass
class Cell:
    text: str
    row: int
    col: int
    box: tuple[float, float, float, float]
    header: bool = False
    rows: int = 1
    cols: int = 1


@dataclass
class Page:
    """One page: its OCR lines, and the Docling items built on them."""

    lines: list[tuple[str, tuple[float, float, float, float], float]] = field(default_factory=list)
    doc: DoclingDocument = field(default_factory=lambda: DoclingDocument(name="fixture"))

    def __post_init__(self) -> None:
        self.doc.add_page(page_no=1, size=Size(width=POINT_W, height=POINT_H))

    def line(self, text: str, box: tuple[float, float, float, float], conf: float = 0.95) -> None:
        self.lines.append((text, box, conf))

    def text(self, label: DocItemLabel, text: str, box: tuple[float, float, float, float], parent=None) -> None:  # noqa: ANN001
        self.doc.add_text(label=label, text=text, prov=prov(box, text), parent=parent)

    def table(self, cells: list[Cell], box: tuple[float, float, float, float]) -> None:
        rows = max(c.row + c.rows for c in cells)
        cols = max(c.col + c.cols for c in cells)
        data = TableData(
            num_rows=rows,
            num_cols=cols,
            table_cells=[
                TableCell(
                    text=c.text,
                    bbox=to_docling(c.box).to_top_left_origin(page_height=POINT_H),
                    start_row_offset_idx=c.row,
                    end_row_offset_idx=c.row + c.rows,
                    start_col_offset_idx=c.col,
                    end_col_offset_idx=c.col + c.cols,
                    row_span=c.rows,
                    col_span=c.cols,
                    column_header=c.header,
                )
                for c in cells
            ],
        )
        self.doc.add_table(data=data, prov=prov(box))

    def picture(self, box: tuple[float, float, float, float]):  # noqa: ANN201
        return self.doc.add_picture(prov=prov(box))


def arabic_card() -> Page:
    """A registration card, right to left: field names as column headings over one row of values; a partners
    table repeating the same fields for two people; a tax table whose header row Docling did not mark; a stamp."""
    p = Page()
    p.line("شهادة قيد في السجل التجاري", (400, 60, 900, 100))
    p.text(DocItemLabel.SECTION_HEADER, "شهادة قيد في السجل التجاري", (400, 60, 900, 100))
    head = [("اسم الشركة", 3), ("نوع الشركة", 2), ("رقم القيد", 1), ("تاريخ القيد", 0)]
    vals = [("شركة النخيل الذهبي للتجارة", 3), ("شركة ذات مسئولية محدودة", 2), ("٤٧٣١٩", 1), ("١٢/٠٣/٢٠٢٤", 0)]
    cells = []
    for text, col in head:  # column 0 is the leftmost: in a right-to-left table, the last field
        box = (100 + 200 * col, 150, 290 + 200 * col, 190)
        p.line(text, box)
        cells.append(Cell(text, 0, col, box, header=True))
    for text, col in vals:
        box = (100 + 200 * col, 200, 290 + 200 * col, 240)
        p.line(text, box)
        cells.append(Cell(text, 1, col, box))
    p.table(cells, (100, 150, 890, 240))
    partners = [
        [("الاسم", 2), ("الصفة", 1), ("نسبة المشاركة", 0)],
        [("سامي عبد الرحيم", 2), ("مدير", 1), ("٦٠٪", 0)],
        [("ليلى منصور", 2), ("شريك", 1), ("٤٠٪", 0)],
    ]
    cells = []
    for r, row in enumerate(partners):
        for text, col in row:
            box = (100 + 260 * col, 300 + 50 * r, 350 + 260 * col, 340 + 50 * r)
            p.line(text, box)
            cells.append(Cell(text, r, col, box, header=r == 0))
    p.table(cells, (100, 300, 870, 440))
    tax = [[("رقم التسجيل الضريبي", 1), ("المأمورية", 0)], [("٥٢٠-٨٨١-٣٠٦", 1), ("مأمورية ضرائب الدقي", 0)]]
    cells = []
    for r, row in enumerate(tax):
        for text, col in row:
            box = (100 + 400 * col, 500 + 50 * r, 480 + 400 * col, 540 + 50 * r)
            p.line(text, box)
            cells.append(Cell(text, r, col, box))  # no header flags: TableFormer left this header row unmarked
    p.table(cells, (100, 500, 880, 590))
    stamp = p.picture((120, 1100, 420, 1250))
    p.line("ختم الإدارة", (150, 1120, 400, 1160))
    p.text(DocItemLabel.TEXT, "ختم الإدارة", (150, 1120, 400, 1160), parent=stamp)
    return p


def english_partners() -> Page:
    """Merged two-level headers, a blank cell, a value wrapped over two OCR lines, a company table."""
    p = Page()
    company = [
        Cell("Company name", 0, 0, (100, 100, 400, 140), header=True),
        Cell("Company type", 0, 1, (400, 100, 700, 140), header=True),
        Cell("Golden Palm Trading Co.", 1, 0, (100, 150, 400, 230)),
        Cell("Limited liability company", 1, 1, (400, 150, 700, 190)),
    ]
    for c in company[:2] + company[3:]:
        p.line(c.text, c.box)
    p.line("Golden Palm Trading", (100, 150, 400, 190))  # the value wraps onto a second line
    p.line("Co.", (100, 195, 160, 230))
    p.table(company, (100, 100, 700, 230))
    cells = [
        Cell("Partner", 0, 0, (100, 300, 500, 340), header=True, cols=2),
        Cell("Contribution", 0, 2, (500, 300, 900, 340), header=True, cols=2),
        Cell("Name", 1, 0, (100, 350, 300, 390), header=True),
        Cell("Role", 1, 1, (300, 350, 500, 390), header=True),
        Cell("Amount", 1, 2, (500, 350, 700, 390), header=True),
        Cell("Payment date", 1, 3, (700, 350, 900, 390), header=True),
        Cell("Samuel Reed", 2, 0, (100, 400, 300, 440)),
        Cell("Manager", 2, 1, (300, 400, 500, 440)),
        Cell("5,000", 2, 2, (500, 400, 700, 440)),
        Cell("", 2, 3, (700, 400, 900, 440)),  # blank
        Cell("Laila Mansour", 3, 0, (100, 450, 300, 490)),
        Cell("Partner", 3, 1, (300, 450, 500, 490)),
        Cell("3,000", 3, 2, (500, 450, 700, 490)),
        Cell("12/03/2024", 3, 3, (700, 450, 900, 490)),
    ]
    for c in cells:
        if c.text:
            p.line(c.text, c.box)
    p.table(cells, (100, 300, 900, 490))
    return p


def mixed_fields() -> Page:
    """A field/value table in two languages: the value is in the "Value" column, not under a heading."""
    p = Page()
    rows = [
        ("Field", "البيان", "Value / القيمة"),
        ("Company name", "اسم الشركة", "Golden Palm Trading Co."),
        ("Registration number", "رقم القيد", "47319"),
        ("Company type", "نوع الشركة", "Limited liability company"),
    ]
    cells = []
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            box = (100 + 280 * c, 100 + 50 * r, 370 + 280 * c, 140 + 50 * r)
            p.line(text, box)
            cells.append(Cell(text, r, c, box, header=r == 0))
    p.table(cells, (100, 100, 930, 290))
    return p


def key_value(flag_first_row: bool) -> Page:
    """A two-column table of fields and values, read across ("Company name | Acme Ltd"); TableFormer may or may not
    mark its first row as a header."""
    p = Page()
    rows = [("Company name", "Acme Ltd"), ("Tax number", "12345"), ("Department", "Sales")]
    cells = []
    for r, (key, value) in enumerate(rows):
        for c, text in enumerate((key, value)):
            box = (100 + 300 * c, 100 + 50 * r, 390 + 300 * c, 140 + 50 * r)
            p.line(text, box)
            cells.append(Cell(text, r, c, box, header=flag_first_row and r == 0))
    p.table(cells, (100, 100, 690, 240))
    return p


def key_value_arabic() -> Page:
    """The same, right to left: the label is the rightmost column."""
    p = Page()
    rows = [("رقم القيد", "٤٧٣١٩"), ("المأمورية", "مأمورية ضرائب الدقي"), ("نوع الشركة", "شركة مساهمة")]
    cells = []
    for r, (key, value) in enumerate(rows):
        for c, text in ((1, key), (0, value)):
            box = (100 + 300 * c, 100 + 50 * r, 390 + 300 * c, 140 + 50 * r)
            p.line(text, box)
            cells.append(Cell(text, r, c, box))
    p.table(cells, (100, 100, 690, 240))
    return p


def staff() -> Page:
    """Names and roles: "Deputy Manager" and "Manager"; two partners; a department spanning every row."""
    p = Page()
    rows = [
        ("Name", "Role", "Department"),
        ("Omar Hadi", "Deputy Manager", "Sales"),
        ("Rana Saleh", "Manager", None),
        ("Yusuf Amr", "Partner", None),
        ("Hala Nabil", "Partner", None),
    ]
    cells = []
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            if text is None:
                continue
            span = 4 if (r, c) == (1, 2) else 1
            box = (100 + 260 * c, 100 + 50 * r, 350 + 260 * c, 140 + 50 * (r + span - 1))
            p.line(text, box)
            cells.append(Cell(text, r, c, box, header=r == 0, rows=span))
    p.table(cells, (100, 100, 870, 340))
    p.line("VAT 14% applies to all lines", (100, 400, 600, 440))
    p.text(DocItemLabel.TEXT, "VAT 14% applies to all lines", (100, 400, 600, 440))
    p.line("14%", (700, 400, 760, 440))  # a short line no Docling item holds; its text occurs in another block
    return p
