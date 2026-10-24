"""Request cues the English rule planner does not cover: Arabic requests, actions Inklight cannot perform,
and questions about a document's content that must not become record filters.

Matching uses ``textnorm.search_form`` (no harakat or tatweel, unified alef, ya and ta marbuta), so "لخّص"
and "لخص" are the same cue.
"""

from __future__ import annotations

import re

from ..textnorm import search_form
from .plan import Intent

# Arabic cues, written in search_form (ة → ه, أ/إ/آ → ا, ى → ي).
_AR_INTENTS: list[tuple[Intent, re.Pattern[str]]] = [
    (Intent.COMPARE, re.compile(r"(?:^|\s)(?:قارن|مقارنه|الفرق بين|الفروق بين|ما الفرق|اختلاف)")),
    (Intent.SUMMARIZE, re.compile(r"(?:^|\s)(?:لخص|ملخص|تلخيص|اختصر|اوجز|النقاط الرئيسيه|اهم النقاط|نظره عامه)")),
    (Intent.FIND, re.compile(r"(?:^|\s)(?:اين ورد|اين ذكر|اين يذكر|في اي صفحه|اظهر المقطع|ابحث عن)")),
    (Intent.COUNT, re.compile(r"(?:^|\s)(?:كم عدد|ما عدد)")),
    (Intent.EXTRACT, re.compile(r"(?:^|\s)(?:استخرج|استخراج|صدر|تصدير|اعرض جدول)")),
]
_AR_DOC_TYPES: list[tuple[str, re.Pattern[str]]] = [
    ("invoice", re.compile(r"فاتور|فواتير")),
    ("receipt", re.compile(r"ايصال|ايصالات|وصل|وصولات")),
    ("contract", re.compile(r"عقد|عقود|اتفاق")),
    ("letter", re.compile(r"رساله|رسائل|خطاب|مراسله")),
    ("report", re.compile(r"تقرير|تقارير")),
    ("form", re.compile(r"نموذج|نماذج|استماره")),
]
_ARABIC = re.compile(r"[؀-ۿ]")

# An imperative to act outside the documents: translate, send, sign, pay, print, delete.
_ACTION_EN = re.compile(
    r"^(?:please\s+|can you\s+|could you\s+|kindly\s+)?(?P<verb>translate|send|e-?mail|forward|sign|pay|print|delete|"
    r"reply to|call|book|schedule)\b",
    re.IGNORECASE,
)
_ACTION_AR = re.compile(r"^(?:من فضلك\s+|رجاء\s+)?(?P<verb>ترجم|ارسل|ابعث|وقع|ادفع|اطبع|احذف|رد علي)(?:\s|$)")
_ACTION_NAMES = {
    "translate": "translation",
    "ترجم": "translation",
    "send": "sending",
    "e-mail": "sending",
    "email": "sending",
    "forward": "sending",
    "ارسل": "sending",
    "ابعث": "sending",
    "sign": "signing",
    "وقع": "signing",
    "pay": "payment",
    "ادفع": "payment",
    "print": "printing",
    "اطبع": "printing",
    "delete": "deleting documents",
    "احذف": "deleting documents",
}

_WH = re.compile(r"^(?:what|which|who|whom|whose|when|where|why|how(?!\s+many\b)(?!\s+much\b))\b")
_SET = re.compile(r"\b(?:list|show|all|every|each|how many|count|these|those)\b")
_PLURAL_SET_NOUN = re.compile(
    r"\b(?:invoices|receipts|contracts|letters|reports|forms|bills|orders|documents|files|agreements|ones)\b"
)
_THRESHOLD = re.compile(r"\b(?:above|below|over|under|more than|less than|at least|at most|between)\s+\S*\d")


def arabic(text: str) -> bool:
    return bool(_ARABIC.search(text))


def arabic_intent(text: str) -> Intent | None:
    t = search_form(text)
    for intent, pattern in _AR_INTENTS:
        if pattern.search(t):
            return intent
    return None


def arabic_doc_type(text: str) -> str | None:
    t = search_form(text)
    for doc_type, pattern in _AR_DOC_TYPES:
        if pattern.search(t):
            return doc_type
    return None


def unsupported_action(text: str) -> str | None:
    """ "Translate this letter" asks for an action, not an answer from the documents: say so, never 'succeed'."""
    t = text.strip()
    m = _ACTION_EN.match(t) or _ACTION_AR.match(search_form(t))
    if not m:
        return None
    verb = m.group("verb").lower()
    what = _ACTION_NAMES.get(verb, verb)
    return f"{what} is not something Inklight does: it reads, searches, answers from and extracts documents"


def content_question(text: str) -> bool:
    """A question about what one document says ("Which city was hit…?", "Who is the fax addressed to?").

    Not a set request: no plural document noun, no list/count/all words and no numeric threshold."""
    t = text.lower().strip()
    if not (_WH.match(t) or t.endswith("?")):
        return False
    return not (_SET.search(t) or _PLURAL_SET_NOUN.search(t) or _THRESHOLD.search(t))
