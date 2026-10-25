"""Classification of general English and Arabic documents (each snippet is from a development document)."""

import pytest

from inklight.extract.classify import classify


@pytest.mark.parametrize(
    ("text", "doc_type"),
    [
        (
            "Letter dated 6 February 2023 from the Permanent Representative of the Islamic Republic of Iran "
            "to the United Nations addressed to the Secretary-General. I have the honour to bring to the "
            "attention of the Council. "
            "I should be grateful if the present letter could be circulated. (Signed) Ambassador",
            "letter",
        ),
        (
            "رسالة مؤرخة 6 شباط/فبراير 2023 موجهة إلى الأمين العام ورئيس مجلس الأمن من الممثل الدائم لجمهورية إيران "
            "الإسلامية لدى الأمم المتحدة. يشرفني أن أحيل إليكم. (توقيع) السفير",
            "letter",
        ),
        (
            "Implementation of resolution 2697 (2023). Report of the Secretary-General. I. Introduction. "
            "1. The present report is submitted pursuant to paragraph 5 of resolution 2697.",
            "report",
        ),
        ("تنفيذ القرار 2697 (2023). تقرير الأمين العام. أولا - مقدمة. 1 - يقدم هذا التقرير عملا بالفقرة 5.", "report"),
        (
            "وثائق تفويض ممثلة البرازيل في مجلس الأمن. تقرير الأمين العام. عملا بالمادة 15، يود الأمين العام الإبلاغ "
            "بأنه تلقى رسالة مؤرخة 29 آذار/مارس 2023 من القائم بالأعمال بالنيابة",
            "report",
        ),
        (
            "Abu Auf Mall Of Egypt Sales Receipt Cashier: abdallah hussain Total 160.00 Cash 210.00 L.E Change -50.00",
            "receipt",
        ),
        (
            "Starbucks Coffee Sokhna 1 Chk 3118 To Go Esp Doppio 25.00 Cash 51.00 Total 46.00 Inclusive Tax 5.65",
            "receipt",
        ),
        (
            "مصاري خدمات الدفع الذكية فاتورة دفع رقم العملية 334713895836 المبلغ المدفوع 133.6 الإجمالي 137.6 ج.م",
            "receipt",
        ),
        (
            "فاتورة ضريبية البائع: شركة الواحة الرقم الضريبي المشتري: مؤسسة الفجر رقم الفاتورة: INV-7731 "
            "المجموع قبل الضريبة ضريبة القيمة المضافة (15%) الإجمالي: 4,600.00 ر.س",
            "invoice",
        ),
        ("عقد إيجار شقة سكنية. الطرف الأول (المؤجر) الطرف الثاني (المستأجر) البند الأول: موضوع العقد", "contract"),
        ("FAX TO: George Baroody FROM: DATE: 12/10/98 NUMBER OF PAGES INCLUDING COVER SHEET: 3 FAX NUMBER:", "form"),
        (
            "Form W-9 (Rev. March 2024) Request for Taxpayer Identification Number and Certification. Give form to the "
            "requester. Print or type.",
            "form",
        ),
        (
            "معهد النور للتدريب المهني. شهادة إتمام دورة تدريبية. يشهد معهد النور بأن المتدرب قد أتم بنجاح دورة. "
            "رقم الشهادة: NR-2024-0457",
            "certificate",
        ),
        ("Invoice #2750 Bill to: GCI Advertising. Amount due 2,000.00 Payment terms Net 30", "invoice"),
        (
            "This Agreement is entered into by and between the parties. Governing law. The term shall terminate.",
            "contract",
        ),
        # a register's certificate citing the company's articles ("عقد التأسيس") is not a contract
        (
            "شهادة قيد في السجل التجاري. تشهد إدارة السجل التجاري بأن الشركة مقيدة بموجب عقد التأسيس. "
            "البطاقة الضريبية: رقم التسجيل الضريبي",
            "certificate",
        ),
        (
            "Certificate of Commercial Registration. Company name, company type. Tax card: tax registration number",
            "certificate",
        ),
    ],
)
def test_general_documents(text, doc_type):
    assert classify(text)[0] == doc_type
