"""Build the SYNTHETIC structure test documents (fictional companies and people, no real data).

A commercial-registration card and a tax card in Arabic (right to left) and in English, laid out the way such
cards often are: field names as column headings over one row of values, a partners table that repeats the same
fields for several people, a stamp drawn as a picture with text inside it, and an Arabic-Indic registration
number. Each is written twice: with a text layer, and as a scan (pages rendered to images and wrapped in a PDF
with no text), so Indra has to OCR it.

    python bench/structure/make_synthetic.py OUT_DIR

Needs PyMuPDF (a dev dependency).
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pymupdf

CSS = """
body { font-family: sans-serif; font-size: 12pt; }
h1 { font-size: 18pt; text-align: center; }
h2 { font-size: 14pt; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 1px solid black; padding: 6px; }
th { background: #dddddd; }
.stamp { border: 3px double #444444; padding: 10px; width: 45%; text-align: center; }
"""

AR = """
<div dir="rtl">
<h1>شهادة قيد في السجل التجاري</h1>
<p>تشهد إدارة السجل التجاري بأن البيانات التالية مقيدة بالسجل وفق أحكام القانون.</p>
<table>
<tr><th>اسم الشركة</th><th>نوع الشركة</th><th>رقم القيد</th><th>تاريخ القيد</th></tr>
<tr><td>شركة النخيل الذهبي للتجارة</td><td>شركة ذات مسئولية محدودة</td><td>٤٧٣١٩</td><td>١٢/٠٣/٢٠٢٤</td></tr>
</table>
<h2>الشركاء</h2>
<table>
<tr><th>الاسم</th><th>الصفة</th><th>نسبة المشاركة</th></tr>
<tr><td>سامي عبد الرحيم</td><td>مدير</td><td>٦٠٪</td></tr>
<tr><td>ليلى منصور</td><td>شريك</td><td>٤٠٪</td></tr>
</table>
<h2>البطاقة الضريبية</h2>
<table>
<tr><th>رقم التسجيل الضريبي</th><th>المأمورية</th></tr>
<tr><td>٥٢٠-٨٨١-٣٠٦</td><td>مأمورية ضرائب الدقي</td></tr>
</table>
</div>
"""

EN = """
<h1>Certificate of Commercial Registration</h1>
<p>The Commercial Registry certifies that the following particulars are entered in the register.</p>
<table>
<tr><th>Company name</th><th>Company type</th><th>Registration number</th><th>Registration date</th></tr>
<tr><td>Golden Palm Trading Co.</td><td>Limited liability company</td><td>47319</td><td>12/03/2024</td></tr>
</table>
<h2>Partners</h2>
<table>
<tr><th>Name</th><th>Role</th><th>Share</th></tr>
<tr><td>Samuel Reed</td><td>Manager</td><td>60%</td></tr>
<tr><td>Laila Mansour</td><td>Partner</td><td>40%</td></tr>
</table>
<h2>Tax card</h2>
<table>
<tr><th>Tax registration number</th><th>Tax office</th></tr>
<tr><td>520-881-306</td><td>Dokki Tax Office</td></tr>
</table>
"""

MIXED = """
<h1>Registration summary / ملخص القيد</h1>
<table>
<tr><th>Field</th><th>البيان</th><th>Value / القيمة</th></tr>
<tr><td>Company name</td><td>اسم الشركة</td><td>Golden Palm Trading Co. / شركة النخيل الذهبي للتجارة</td></tr>
<tr><td>Registration number</td><td>رقم القيد</td><td>47319</td></tr>
<tr><td>Company type</td><td>نوع الشركة</td><td>Limited liability company</td></tr>
</table>
"""


def _render(html: str, rect: pymupdf.Rect) -> pymupdf.Document:
    story = pymupdf.Story(html=html, user_css=CSS)
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    device = writer.begin_page(rect)
    story.place(rect + (4, 4, -4, -4))
    story.draw(device)
    writer.end_page()
    writer.close()
    return pymupdf.open("pdf", buffer.getvalue())


def stamp_image(html: str) -> bytes:
    """A picture with text inside it (a stamp), as PNG bytes: its text is pixels, not a text layer."""
    doc = _render(html, pymupdf.Rect(0, 0, 220, 90))
    return doc[0].get_pixmap(dpi=200).tobytes("png")


def write_pdf(html: str, out: Path, stamp: str | None = None) -> None:
    story = pymupdf.Story(html=html, user_css=CSS)
    writer = pymupdf.DocumentWriter(str(out))
    rect = pymupdf.paper_rect("a4")
    where = rect + (50, 50, -50, -50)
    more = True
    while more:
        device = writer.begin_page(rect)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()
    if stamp:
        doc = pymupdf.open(out)
        doc[0].insert_image(pymupdf.Rect(60, 640, 280, 730), stream=stamp_image(stamp))
        doc.saveIncr()
        doc.close()


def write_scan(source: Path, out: Path, dpi: int = 200) -> None:
    """The same pages as images only: a PDF without a text layer."""
    src = pymupdf.open(source)
    dst = pymupdf.open()
    for page in src:
        pix = page.get_pixmap(dpi=dpi)
        new = dst.new_page(width=page.rect.width, height=page.rect.height)
        new.insert_image(new.rect, pixmap=pix)
    dst.save(out)
    dst.close()
    src.close()


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    stamps = {
        "regcard-ar": '<p class="stamp" dir="rtl">ختم الإدارة<br/>صورة طبق الأصل</p>',
        "regcard-en": '<p class="stamp">Registry stamp<br/>Certified true copy</p>',
    }
    for name, html in (("regcard-ar", AR), ("regcard-en", EN), ("regcard-mixed", MIXED)):
        digital = out / f"{name}.pdf"
        write_pdf(html, digital, stamps.get(name))
        write_scan(digital, out / f"{name}-scan.pdf")
        print("wrote", digital, "and", out / f"{name}-scan.pdf")


if __name__ == "__main__":
    main()
