"""Synthetic Arabic and bilingual documents for gaps no openly licensed genuine data fills.

    python -I bench/usecases/make_synthetic.py --out <folder> [--browser <chrome or edge executable>]

SYNTHETIC: every value is invented here, and the ground truth is this file's data. Names, numbers and
organisations are fictional. Each template is printed to PDF by a Chromium browser (correct Arabic shaping),
and some are turned into degraded images (a slight rotation, blur, noise and JPEG compression) to stand in for
a photograph or a scan. They are labelled "synthetic" in the corpus and kept apart from genuine documents in
every result.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

STYLE = """<style>
body { font-family: Arial, 'Segoe UI', sans-serif; margin: 48px; font-size: 15px; line-height: 1.7; }
h1 { font-size: 22px; margin: 0 0 8px; } h2 { font-size: 17px; margin: 18px 0 6px; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; } td, th { border: 1px solid #555; padding: 5px 8px; }
.meta td { border: none; padding: 2px 8px 2px 0; } .box { border: 2px solid #333; padding: 22px; }
</style>"""


def page(body: str, lang: str = "ar") -> str:
    direction = "rtl" if lang == "ar" else "ltr"
    return (
        f'<!doctype html><html lang="{lang}" dir="{direction}"><meta charset="utf-8">{STYLE}<body>{body}</body></html>'
    )


CERTIFICATE = page("""
<div class="box">
<h1>معهد النور للتدريب المهني</h1>
<p>الرياض، المملكة العربية السعودية</p>
<h2>شهادة إتمام دورة تدريبية</h2>
<p>يشهد معهد النور للتدريب المهني بأن المتدرب <b>سالم عبد الله القحطاني</b> قد أتم بنجاح دورة
<b>إدارة المشاريع الاحترافية</b> بعدد ساعات تدريبية بلغ <b>٤٠ ساعة</b>، وذلك خلال الفترة من
٣ آذار/مارس ٢٠٢٤ إلى ١٤ آذار/مارس ٢٠٢٤، بتقدير <b>ممتاز</b>.</p>
<table class="meta">
<tr><td>رقم الشهادة:</td><td>NR-2024-0457</td></tr>
<tr><td>تاريخ الإصدار:</td><td>2024-03-17</td></tr>
<tr><td>مدير المعهد:</td><td>د. هالة منصور</td></tr>
</table>
</div>""")

INVOICE = page("""
<h1>فاتورة ضريبية</h1>
<table class="meta">
<tr><td>البائع:</td><td>شركة الواحة للتجهيزات المكتبية</td></tr>
<tr><td>الرقم الضريبي:</td><td>300456789100003</td></tr>
<tr><td>المشتري:</td><td>مؤسسة الفجر للاستشارات</td></tr>
<tr><td>رقم الفاتورة:</td><td>INV-7731</td></tr>
<tr><td>تاريخ الفاتورة:</td><td>2024-05-12</td></tr>
<tr><td>تاريخ الاستحقاق:</td><td>2024-06-11</td></tr>
</table>
<table>
<tr><th>الصنف</th><th>الكمية</th><th>سعر الوحدة (ر.س)</th><th>المبلغ (ر.س)</th></tr>
<tr><td>كرسي مكتب</td><td>4</td><td>450.00</td><td>1,800.00</td></tr>
<tr><td>طاولة اجتماعات</td><td>1</td><td>2,200.00</td><td>2,200.00</td></tr>
</table>
<table class="meta">
<tr><td>المجموع قبل الضريبة:</td><td>4,000.00 ر.س</td></tr>
<tr><td>ضريبة القيمة المضافة (15%):</td><td>600.00 ر.س</td></tr>
<tr><td>الإجمالي:</td><td>4,600.00 ر.س</td></tr>
</table>""")

FORM = page("""
<h1>نموذج طلب عضوية / Membership Application Form</h1>
<p>جمعية المكتبات العربية / Arab Libraries Association</p>
<table>
<tr><td>الاسم الكامل / Full name</td><td>ليلى حسن الزعبي — Layla Hasan Al-Zoubi</td></tr>
<tr><td>تاريخ الميلاد / Date of birth</td><td>03/04/1990</td></tr>
<tr><td>رقم الهوية / ID number</td><td>9876543210</td></tr>
<tr><td>الهاتف / Phone</td><td>+962 7 9555 0142</td></tr>
<tr><td>البريد الإلكتروني / Email</td><td>layla.zoubi@example.org</td></tr>
<tr><td>نوع العضوية / Membership type</td><td>عضوية مهنية / Professional</td></tr>
<tr><td>رسوم العضوية / Fee</td><td>25.00 JOD</td></tr>
<tr><td>تاريخ الطلب / Application date</td><td>2024-09-02</td></tr>
</table>
<p>توقيع مقدم الطلب / Applicant signature: ____________</p>""")

LEASE = page("""
<h1>عقد إيجار شقة سكنية</h1>
<p>إنه في يوم الأحد الموافق ٧ كانون الثاني/يناير ٢٠٢٤ تم الاتفاق بين كل من:</p>
<p><b>الطرف الأول (المؤجر):</b> السيد كريم فؤاد الشامي.</p>
<p><b>الطرف الثاني (المستأجر):</b> السيدة نور الهدى عادل سليم.</p>
<h2>البند الأول: موضوع العقد</h2>
<p>أجّر الطرف الأول للطرف الثاني الشقة رقم ١٢ الكائنة في ١٥ شارع النيل، الدقي، الجيزة.</p>
<h2>البند الثاني: مدة العقد</h2>
<p>مدة هذا العقد سنتان تبدأ من ١ شباط/فبراير ٢٠٢٤ وتنتهي في ٣١ كانون الثاني/يناير ٢٠٢٦.</p>
<h2>البند الثالث: الأجرة</h2>
<p>الأجرة الشهرية ثمانية آلاف جنيه مصري (8,000 ج.م) تدفع مقدماً في أول كل شهر،
وتأمين قدره 16,000 ج.م يرد عند نهاية العقد.</p>
<h2>البند الرابع: الاختصاص القضائي</h2>
<p>تختص محاكم الجيزة بنظر أي نزاع ينشأ عن هذا العقد.</p>""")

LEASE2 = page("""
<h1>عقد إيجار محل تجاري</h1>
<p>حُرر هذا العقد في مدينة جدة بتاريخ ١٠ أيار/مايو ٢٠٢٤ بين:</p>
<p><b>المؤجر:</b> شركة الريم للاستثمار العقاري.</p>
<p><b>المستأجر:</b> السيد فهد ناصر العتيبي.</p>
<h2>المادة الأولى: العين المؤجرة</h2>
<p>محل تجاري رقم ٤ في مركز البحر، طريق الكورنيش، جدة.</p>
<h2>المادة الثانية: الأجرة</h2>
<p>الأجرة الشهرية خمسة آلاف ريال سعودي (5,000 ر.س) تُسدد في الخامس من كل شهر.</p>
<h2>المادة الثالثة: المدة</h2>
<p>مدة العقد ثلاث سنوات تبدأ من ١ حزيران/يونيو ٢٠٢٤.</p>
<h2>المادة الرابعة: تسوية النزاعات</h2>
<p>تختص المحكمة التجارية في جدة بالفصل في أي نزاع.</p>""")

SALARY_LETTER = page(
    """
<p style="text-align:left">Ref: HR/2024/318 &nbsp;&nbsp; Date: 21 October 2024</p>
<h1>خطاب تعريف بالراتب / Salary Certificate</h1>
<p>إلى من يهمه الأمر،</p>
<p>تشهد شركة المدار للبرمجيات بأن السيد <b>عمر يوسف الخطيب</b> (Omar Yousef Al-Khatib) يعمل لديها
بوظيفة <b>مهندس برمجيات أول</b> منذ ١ أيلول/سبتمبر ٢٠١٩، ويتقاضى راتباً شهرياً إجمالياً قدره
<b>18,500 درهم إماراتي</b> (AED 18,500).</p>
<p>This certificate was issued at the employee's request without any liability on the company.</p>
<p>مدير الموارد البشرية: سارة إبراهيم — Sara Ibrahim</p>
<p>Al-Madar Software LLC, Dubai, United Arab Emirates</p>""",
    lang="ar",
)

TEMPLATES = {
    "syn-ar-certificate": CERTIFICATE,
    "syn-ar-invoice": INVOICE,
    "syn-mx-form": FORM,
    "syn-ar-lease": LEASE,
    "syn-mx-salary-letter": SALARY_LETTER,
    "syn-ar-lease2": LEASE2,
}
# Image versions: (template, suffix, rotation degrees, blur kernel, noise sigma, JPEG quality)
DEGRADED = [
    ("syn-ar-certificate", "photo", 1.8, 3, 9.0, 70),
    ("syn-ar-invoice", "scan", -0.7, 3, 6.0, 80),
    ("syn-ar-lease", "scan", 0.9, 3, 7.0, 75),
    ("syn-ar-lease2", "scan", -1.2, 3, 8.0, 72),
]


def find_browser(explicit: str | None) -> str:
    candidates = (
        [explicit]
        if explicit
        else [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "google-chrome",
            "chromium",
            "chromium-browser",
            "msedge",
        ]
    )
    for c in candidates:
        if c and (Path(c).exists() or shutil.which(c)):
            return c
    sys.exit("no Chromium browser found: pass --browser")


def print_pdf(browser: str, html: str, out: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "doc.html"
        src.write_text(html, encoding="utf-8")
        subprocess.run(
            [
                browser,
                "--headless=new",
                "--disable-gpu",
                "--no-pdf-header-footer",
                f"--print-to-pdf={out}",
                src.resolve().as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )


def degrade(pdf: Path, out: Path, rotation: float, blur: int, noise: float, quality: int) -> None:
    import cv2
    import numpy as np
    import pypdfium2

    doc = pypdfium2.PdfDocument(str(pdf))
    try:
        gray = doc[0].render(scale=150 / 72, grayscale=True).to_numpy()
    finally:
        doc.close()
    gray = gray[..., 0] if gray.ndim == 3 else gray
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), rotation, 1.0)
    img = cv2.warpAffine(gray, m, (w, h), borderValue=235)
    img = cv2.GaussianBlur(img, (blur, blur), 0)
    rng = np.random.default_rng(7)  # fixed seed: the same images every run
    img = np.clip(img.astype(np.float32) * 0.92 + 12 + rng.normal(0, noise, img.shape), 0, 255).astype(np.uint8)
    cv2.imwrite(str(out), img, [cv2.IMWRITE_JPEG_QUALITY, quality])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--browser")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    browser = find_browser(args.browser)
    for name, html in TEMPLATES.items():
        print_pdf(browser, html, (args.out / f"{name}-digital.pdf").resolve())
    for name, suffix, rot, blur, noise, q in DEGRADED:
        degrade(args.out / f"{name}-digital.pdf", args.out / f"{name}-{suffix}.jpg", rot, blur, noise, q)
    print("\n".join(sorted(p.name for p in args.out.iterdir())))


if __name__ == "__main__":
    main()
