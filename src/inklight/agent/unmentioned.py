"""Questions about something the documents never mention.

Without this check, "What is the IBAN?" over a letter is answered with the letter's best-matching sentence. The
check looks up every specific word of the question in the full-text index of the documents in scope. If none of
them occurs anywhere, the answer says no supporting evidence was found in the processed text, instead of a
guess. It does not claim the fact is absent from the document itself: OCR can miss words.

It is deliberately narrow, because declining a question the documents do answer is also an error:
- Generic words ("number", "date", "total", "name") are not looked up: documents say "No." or "Dated". Nor is
  the type of the document asked about: a form rarely prints "form".
- One specific word that occurs anywhere in scope is enough to answer as before.
- At least one missing word must name a distinctive subject: one from the subject list below ("IBAN", "landlord",
  "rent"), or an acronym ("VAT"). Everyday words with many paraphrases ("order", "due", "phone", "price") are
  looked up but never decide on their own, and neither are verbs ("sent", "wrote").
- English synonyms count as the same subject ("salary" is found by "wages"; "rent" by "rental").
- When the question and the documents may be in different languages (an English question over an Arabic
  receipt, or a question over the whole library), only words with a known equivalent in the other language can
  be looked up. One unknown word means nothing is concluded. So does a document in scope that is not indexed yet.

Measured on the dev split of bench/usecases before it was adopted; see evaluation/EVALUATION.md.
"""

from __future__ import annotations

import re

from ..schemas import DocStatus
from ..textnorm import mostly_arabic, search_form
from .answer import _stem, words
from .context import ToolContext

# Words a question can use without naming its subject. Compared by stem.
_GENERIC = {
    _stem(w)
    for w in words(
        "number numbers no amount amounts date dates dated name names total totals value values many much long "
        "type kind document documents file files page pages mention mentioned say says said state stated give "
        "given list show find tell about please exact exactly full main current first last new here written "
        "write wrote provided listed shown according part section day days year years time times "
        "اسم رقم تاريخ مبلغ قيمه اجمالي مجموع عدد الوثيقه المستند الملف صفحه يذكر ذكر مذكور"
    )
}

# Subjects people ask documents about, with English synonyms and Arabic equivalents (Arabic in search form). The
# first word names the group. A missing subject from this list can decide that a question is unanswerable.
_SUBJECTS: list[tuple[str, ...]] = [
    ("invoice", "bill", "فاتوره", "فواتير"),
    ("receipt", "ايصال", "وصل"),
    ("contract", "agreement", "عقد", "اتفاقيه"),
    ("agreement", "contract", "اتفاقيه", "اتفاق", "عقد"),
    ("rent", "rental", "lease", "ايجار", "اجره"),
    ("landlord", "lessor", "owner", "مؤجر", "المؤجر", "مالك"),
    ("tenant", "lessee", "occupant", "مستاجر"),
    ("employer", "employ", "company", "صاحب العمل", "جهه العمل"),
    ("salary", "wage", "pay", "remuneration", "compensation", "راتب", "اجر"),
    ("iban", "international bank account", "ايبان", "رقم الحساب الدولي"),
    ("vat", "value added", "ضريبه القيمه المضافه"),
    ("governing", "govern", "يخضع", "تخضع", "يحكم", "الواجب التطبيق"),
    ("court", "tribunal", "arbitration", "محكمه"),
    ("certificate", "certify", "شهاده"),
    ("deposit", "security", "تامين", "وديعه"),
    ("penalty", "liquidated damages", "fine", "غرامه", "شرط جزائي"),
    ("cashier", "served", "كاشير", "امين الصندوق"),
]
# Everyday words: looked up with their equivalents, but too often paraphrased to decide on their own.
_LOOKUP_ONLY: list[tuple[str, ...]] = [
    ("employee", "staff", "worker", "موظف", "عامل"),
    ("tax", "ضريبه", "ضريبي"),
    ("customer", "client", "عميل", "زبون"),
    ("seller", "vendor", "supplier", "بائع"),
    ("buyer", "purchaser", "مشتري"),
    ("order", "طلب"),
    ("price", "cost", "charge", "fee", "سعر", "ثمن"),
    ("operation", "عمليه"),
    ("transaction", "معامله", "عمليه"),
    ("payment", "pay", "paid", "دفع", "سداد", "مدفوع"),
    ("due", "payable", "مستحق", "استحقاق"),
    ("term", "period", "duration", "مده"),
    ("law", "legal", "قانون"),
    ("phone", "telephone", "tel", "mobile", "هاتف", "تليفون", "جوال"),
    ("address", "عنوان"),
    ("card", "بطاقه"),
    ("shipping", "شحن"),
    ("delivery", "deliver", "توصيل"),
    ("discount", "خصم"),
    ("signature", "signed", "توقيع"),
    ("bank", "بنك", "مصرف"),
    ("account", "حساب"),
]
_BY_WORD: dict[str, tuple[str, ...]] = {}
for _group in _SUBJECTS + _LOOKUP_ONLY:  # a group's own name wins over its use as another group's synonym
    _BY_WORD.setdefault(_stem(search_form(_group[0])), _group)
for _group in _SUBJECTS + _LOOKUP_ONLY:
    for _w in _group[1:]:
        _BY_WORD.setdefault(_stem(search_form(_w)), _group)
# A subject's name and its Arabic equivalents decide; English synonyms ("pay", "owner") only help find it.
_DECIDING = {_stem(search_form(w)) for g in _SUBJECTS for w in g if w == g[0] or re.search(r"[ء-ي]", w)}

# A question names the document it is about by its type ("Who is the form from?"); forms rarely print "form".
_TYPE_WORDS = {
    "invoice": "invoice فاتوره",
    "receipt": "receipt ايصال",
    "letter": "letter رساله خطاب",
    "report": "report تقرير",
    "form": "form نموذج استماره",
    "contract": "contract agreement عقد اتفاقيه",
    "certificate": "certificate شهاده",
}
_ARABIC = re.compile(r"[ء-ي]")
_LATIN = re.compile(r"[A-Za-z]")
_FULL_TEXT_DOCS = 20  # larger scopes, and the whole library, are treated as possibly in either language


def unmentioned(ctx: ToolContext, question: str) -> list[str] | None:
    """The question's specific words, when none of them occurs in any document in scope; otherwise None."""
    generic = _GENERIC | _own_types(ctx)
    terms = [w for w in dict.fromkeys(words(question)) if _stem(w) not in generic and not w.isdigit()]
    terms = [w for w in terms if len(w) > 2]
    if not terms or not any(_stem(w) in _DECIDING or _acronym(question, w) for w in terms):
        return None
    ids = ctx.scratch.doc_ids
    docs = [ctx.library.get(i) for i in ids[: _FULL_TEXT_DOCS + 1]]
    if any(d is None or d.status != DocStatus.READY for d in docs):
        return None  # a document that is not indexed yet cannot show that something is missing
    for term in terms:  # cheap index lookups first
        ctx.check()
        if ctx.library.store.mentions(_forms(term), ids or None):
            return None
    if _other_language(ctx, question) and any(_stem(t) not in _BY_WORD for t in terms):
        return None  # an unknown word may be written in the other language
    return terms


def say_not_found(ctx: ToolContext, question: str, terms: list[str]) -> None:
    """Answer that no supporting evidence was found for ``terms``, and say why in the result's checks."""
    shown = [_as_asked(question, t) for t in terms[:4]]
    say_no_evidence(
        ctx,
        " or ".join(f"“{t}”" for t in shown),
        "no indexed passage in scope contains " + ", ".join(shown) + " (or a known English/Arabic equivalent)",
    )


def say_no_evidence(ctx: ToolContext, what: str, why: str) -> None:
    """The answer when nothing in the processed text supports one: it does not claim the fact is absent."""
    s = ctx.scratch
    where = "this document" if len(s.doc_ids) == 1 else "these documents"
    s.answer = f"I couldn't find supporting evidence for {what} in the processed text of {where}."
    s.sources = []
    s.confidence = 0.6
    s.notes.append(f"no supporting evidence: {why}")


def _forms(word: str) -> list[str]:
    """Index lookups for one word: itself (plurals and endings by prefix), plus known equivalents."""
    group = _BY_WORD.get(_stem(word), ())
    out = []
    for w in dict.fromkeys((word, *group)):
        stem = _stem(w)
        out.append(f"{stem}*" if len(stem) >= 4 and " " not in w else w)
        if len(w) <= 3 and not _ARABIC.search(w):
            out.append(f"{w}s")
    return out


def _other_language(ctx: ToolContext, question: str) -> bool:
    """Whether the documents in scope may be partly in the other language from the question."""
    ids = ctx.scratch.doc_ids
    if not ids or len(ids) > _FULL_TEXT_DOCS:
        return True
    text = " ".join(ctx.library.text(i) for i in ids)
    arabic, latin = len(_ARABIC.findall(search_form(text))), len(_LATIN.findall(text))
    letters = max(arabic + latin, 1)
    return latin / letters >= 0.25 if mostly_arabic(question) else arabic / letters >= 0.10


def _own_types(ctx: ToolContext) -> set[str]:
    """Stems of the words that name the type of a document in scope."""
    types = {d.doc_type for d in map(ctx.library.get, ctx.scratch.doc_ids[:_FULL_TEXT_DOCS]) if d is not None}
    return {_stem(w) for t in types for w in words(_TYPE_WORDS.get(t, ""))}


def _acronym(question: str, term: str) -> bool:
    """IBAN or VAT in an ordinary question; not a shouted question, and not A4 or Q3."""
    shown = _as_asked(question, term)
    letters = [c for c in question if c.isalpha()]
    shouting = sum(c.isupper() for c in letters) > len(letters) / 2
    return not shouting and 2 <= len(shown) <= 6 and shown.isascii() and shown.isalpha() and shown.isupper()


def _as_asked(question: str, term: str) -> str:
    """The word as the user wrote it ("IBAN", not "iban")."""
    for w in re.findall(r"[^\W_]+", question):
        if search_form(w).lower() == term:
            return w
    return term
