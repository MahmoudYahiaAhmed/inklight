"""Keyword-scored document type classification (fast, explainable, model-free)."""

from __future__ import annotations

import re

from ..textnorm import search_form

DOC_TYPES: dict[str, dict[str, float]] = {
    "invoice": {
        "invoice": 3,
        "bill to": 2,
        "فاتوره ضريبيه": 3,
        "رقم الفاتوره": 2.5,
        "الرقم الضريبي": 1,
        "المشتري": 1.5,
        "البائع": 1.5,
        "amount due": 2,
        "subtotal": 1.5,
        "due date": 1.5,
        "invoice number": 2,
        "remit": 1,
        "payment terms": 1,
        "tax": 0.5,
        "qty": 0.5,
    },
    "receipt": {
        "receipt": 3,
        "cashier": 2,
        "total tendered": 2,
        "change": 1,
        "cash": 1,
        "chk": 1.5,
        "to go": 1,
        "l.e": 1,
        "ايصال": 3,
        "خدمات الدفع": 2,
        "رقم العمليه": 2,
        "المبلغ المدفوع": 1.5,
        "الكاشير": 2,
        "رقم الطلب": 2,
        "طريقه الدفع": 1.5,
        "الشحن": 1,
        "الخصم": 1,
        "change due": 2,
        "thank you for your purchase": 2,
        "card ending": 1.5,
        "transaction": 1,
        "store": 0.5,
    },
    "contract": {
        "agreement": 3,
        "hereinafter": 2,
        "عقد": 2,
        "العقد": 2,
        "contract": 2.5,
        "party a": 1.5,
        "party b": 1.5,
        "الطرف الاول": 2,
        "الطرف الثاني": 2,
        "البند": 1.5,
        "اتفاق": 2,
        "الاتفاق": 1.5,
        "parties": 2,
        "party": 1,
        "governing law": 2,
        "terminate": 1.5,
        "term": 0.5,
        "whereas": 2,
        "effective date": 1.5,
        "expiration": 1,
        "indemnif": 1.5,
    },
    "report": {
        "report": 2.5,
        "executive summary": 2,
        "report of the secretary-general": 3,
        "the present report": 2,
        "تقرير": 2.5,
        "تقرير الامين العام": 3,  # = "report of the secretary-general"
        "التقرير": 1.5,
        "findings": 1.5,
        "analysis": 1,
        "quarter": 1,
        "results": 1,
        "conclusion": 1,
        "methodology": 1.5,
    },
    "form": {
        "form": 2,
        "signature": 1.5,
        "fax": 1.5,
        "to:": 1,
        "from:": 1,
        "subject:": 1,
        "number of pages": 1.5,
        "print or type": 1.5,
        "omb no": 1.5,
        "نموذج طلب": 2.5,
        "الاسم الكامل": 1.5,
        "تاريخ الميلاد": 1.5,
        "مقدم الطلب": 1.5,
        "please complete": 2,
        "applicant": 1.5,
        "date of birth": 1.5,
        "check one": 1.5,
    },
    "letter": {
        "dear ": 2,
        "sincerely": 2,
        "regards": 1,
        "yours faithfully": 2,
        "letter dated": 4.5,
        "letters dated": 4.5,
        "addressed to": 1.5,
        "i have the honour": 2,
        "to whom it may concern": 2.5,
        "(signed)": 1.5,
        "رساله مؤرخه": 3,
        "رسالتان": 3,
        "موجهه الي": 1.5,
        "يشرفني": 2,
        "اتشرف": 2,
        "(توقيع)": 1.5,
        "الي من يهمه الامر": 2.5,
    },
    "certificate": {
        "certificate of": 2,
        "this is to certify": 3,
        "hereby certif": 2.5,
        "شهاده": 2,
        "يشهد": 2.5,
        "رقم الشهاده": 2,
        # registration certificates and tax cards: a register's extract may cite the company's articles ("عقد
        # التاسيس"), which alone made it a "contract"
        "السجل التجاري": 2.5,
        "مستخرج": 1.5,
        "البطاقه الضريبيه": 2.5,
        "رقم التسجيل الضريبي": 1.5,
        "commercial regist": 2.5,
        "certificate of registration": 2.5,
        "tax card": 2.5,
        "tax registration number": 1.5,
    },
    "resume": {"experience": 1.5, "education": 1.5, "skills": 1.5, "curriculum vitae": 3, "resume": 2},
}
SINGULAR = {
    "invoices": "invoice",
    "receipts": "receipt",
    "contracts": "contract",
    "reports": "report",
    "forms": "form",
    "letters": "letter",
    "resumes": "resume",
    "cvs": "resume",
    "certificates": "certificate",
    "agreements": "contract",
    "bills": "invoice",
}


def _pattern(cue: str) -> str:
    """Arabic cues match whole words only: "عقد" (contract) must not match inside "عقدها" (held)."""
    if re.search(r"[\u0600-\u06FF]", cue):
        return rf"(?<![\u0621-\u064A]){re.escape(cue)}(?![\u0621-\u064A])"
    return re.escape(cue)


def _score(head: str, cues: dict[str, float]) -> float:
    return sum(weight * min(len(re.findall(_pattern(cue), head)), 3) for cue, weight in cues.items())


def cue_score(text: str, doc_type: str) -> float:
    """How much of ``doc_type``'s vocabulary the text holds (0 when none, or the type is not known)."""
    cues = DOC_TYPES.get(doc_type)
    return _score(search_form(text[:6000]).lower(), cues) if cues else 0.0


# Invoices and receipts are often typed "unknown" (a receipt photo prints no "receipt"), yet carry a total line.
_TOTAL_LINE = re.compile(r"\b(?:sub\s*total|grand\s*total|total)\b|المجموع|الاجمالي|الإجمالي", re.IGNORECASE)


def could_be(text: str, doc_type: str) -> bool:
    """Whether a document the classifier could not type shows any sign of ``doc_type``."""
    if cue_score(text, doc_type) > 0:
        return True
    return doc_type in ("invoice", "receipt") and bool(_TOTAL_LINE.search(text[:6000]))


def classify(text: str) -> tuple[str, float]:
    """Return (doc_type, confidence in 0..1). ``unknown`` when nothing scores."""
    head = search_form(text[:6000]).lower()  # Arabic cues are written in search form (ة → ه, أ → ا)
    scores = {doc_type: _score(head, cues) for doc_type, cues in DOC_TYPES.items()}
    best = max(scores, key=lambda k: scores[k])
    total = sum(scores.values())
    if scores[best] < 3:
        return "unknown", 0.0
    return best, round(scores[best] / total, 3)
