"""Questions that name a label: answered with the value printed beside or below it on the page.

Forms, infoboxes and receipts print a label with its value: "MANUFACTURER:  B & W", "Elevation [1] 99 m",
"Area code (+20) 97", "المساحة 375 كيلومتر مربع", "12% Service:  66.72". A question that names the label ("Who is the
manufacturer?", "ما مساحة أسوان؟") is answered with that value, citing its page and box:

1. A label is a short bare noun phrase (at most six words, no function words or sentence punctuation) that holds at
   least half of the question's specific words. Among several, the one with the fewest words the question does not
   use wins ("Area" for "total area", "Area code" for "area code"). Titles and headings naming the document ("TAX
   INVOICE", "Letter dated …") are not labels, and a label naming a different field ("Billing Address" for the
   shipping address, "Invoice Date" for the delivery date) is not used (scope.py).
2. Copies of one label ("Salary:" per employee) are told apart by the person or section above each; when they
   cannot be, each is listed and none is chosen (label_scope.py).
3. Its value is the rest of its line, else the cells on its row in reading direction (Arabic: to the left), taken
   from the row nearest the label's own baseline, up to the next "Label:" cell, else the line just below it. A
   label without a colon must have a value with a digit, so headings and prose are not mistaken for fields.
4. Confidence follows the evidence: a value on the label's own line or row is 0.7; a colon-less label whose value
   is on another line, several equally good labels, several values beside one label, or a label outside the
   section the question names are flagged (0.25).
5. On a form (three or more word labels with values on the page), a label with nothing at all beside or below it
   is a blank field, and the answer says no value was found there.
"""

from __future__ import annotations

import re

from ..extract import layout
from ..extract.values import parse_dates
from ..schemas import Source, TextLine
from . import label_scope as sc
from . import lines as ln
from .answer import expected_kind, words
from .binding import _KIND_WORDS, _TITLE_START, _digits, _has_kind, _key
from .context import ToolContext
from .scope import conflicts
from .unmentioned import _GENERIC, say_no_evidence

_MAX_DOCS = 3
_MAX_PAGES = 5
# Whole words, not stems: "report" names a document, "reported" does not.
_DOC_WORDS = set(
    words(
        "letter letters document documents agreement contract report form certificate invoice receipt note memo fax "
        "رساله رسالتين الرساله الرسالتان خطاب الوثيقه وثيقه المستند العقد عقد التقرير تقرير النموذج الشهاده الفاتوره"
    )
)
# Labels a letter's header or a page's furniture carries; they do not make a page a form.
_HEADER_LABELS = set(
    words("distr original to from date subject cc attention ref reference page tel fax email www http")
)
_FORM_LIKE = 3
_DATE_KEYS = {_key(w) for w in words("date تاريخ")}
_QUESTION_ONLY = {
    _key(w) for w in ("what", "which", "who", "whose", "how", "much", "many", "is", "the", "ما", "من", "كم")
}


def label_answer(ctx: ToolContext, question: str) -> str | None:
    """Answer from a label's value on the page; None when no label line matches the question."""
    wanted = wanted_words(question)
    if not wanted:
        return None
    kind = expected_kind(question)
    docs = list(dict.fromkeys(h.source.doc_id for h in ctx.scratch.hits)) or ctx.scratch.doc_ids
    for doc_id in docs[:_MAX_DOCS]:
        doc = ctx.library.get(doc_id)
        if doc is None:
            continue
        terms = terms_for(ctx, doc_id, question)
        found = _labels(ctx, doc_id, terms)
        if not found:
            continue
        best = sc.pick(found, terms)
        if best is None:
            sc.say_ambiguous(ctx, doc, doc_id, found, terms)
            return "label repeated in several sections"
        page = ln.index(best.page)
        value, cells, nearby = page.value(best)
        date_label = bool(ln.keys(best.text) & _DATE_KEYS)
        if value is not None and kind == "date" and not _has_kind("date", _digits(value)):
            continue  # "When was it adopted?" is not answered by a page number beside a label
        if value is not None and kind != "date" and not date_label and _only_a_date(value):
            continue  # "Which meeting …?", "What is the meeting number?" are not answered by a bare date
        if value is None:
            if not best.colon or nearby or _form_labels(page.lines) < _FORM_LIKE:
                continue  # prose ending in ":", or something sits beside it that is not read as a value
            say_no_evidence(
                ctx,
                f"a value of “{best.text}”",
                f"the label “{best.text}” is on page {best.page.number}, but nothing is written beside or below it "
                "(a blank field)",
            )
            return "blank field"
        _answer(ctx, doc, doc_id, best, value, cells)
        return "value beside its label"
    return None


def terms_for(ctx: ToolContext, doc_id: str, question: str) -> sc.Terms:
    return sc.question_terms(ctx, doc_id, wanted_words(question), question, _DOC_WORDS)


def _answer(ctx, doc, doc_id: str, best: ln.Label, value: str, cells: list[TextLine]) -> None:  # type: ignore[no-untyped-def]
    s = ctx.scratch
    page = ln.index(best.page)
    label_line = page.lines[best.index]
    s.answer = (
        f"{value}\n\nEvidence: “{label_line.text.strip()}”"
        if best.inline
        else f"{value}\n\nEvidence: “{best.text}: {value}”"
    )
    s.sources = [
        Source(
            doc_id=doc_id,
            path=doc.path,
            name=doc.name,
            page=best.page.number,
            bbox=ln.union([label_line.bbox, *[c.bbox for c in cells]]) if page.boxes else None,  # type: ignore[list-item]
            excerpt=" ".join([label_line.text.strip(), *[c.text.strip() for c in cells]]),
            ocr_conf=min([x.conf for x in [label_line, *cells] if x.conf is not None], default=None),
        )
    ]
    below_only = not best.inline and not best.colon and cells and not ln.beside(label_line.bbox, cells[0].bbox, False)  # type: ignore[arg-type]
    doubt = (
        "more than one value sits beside this label; check which one belongs to it"
        if len(cells) > 1
        else "more than one line on the page matches this label; check the cited one"
        if best.tied
        else best.unscoped
        if best.unscoped
        else "the value was read from the line under an unpunctuated label; check it"
        if below_only and not layout.rtl(label_line.text)
        else ""
    )
    if doubt:
        s.warn(f"Low confidence: {doubt}.")
    s.confidence = 0.25 if doubt else 0.7
    s.notes.append(f"answer: the value beside the label “{best.text}” on page {best.page.number}")


def wanted_words(question: str) -> set[str]:
    """The question's words that a label would carry: not question words, and not generic ("what", "the"). A word
    naming the document is left out ("the date of the letter") unless it qualifies the next word ("the invoice
    date", "the invoice number")."""
    found = [w for w in words(question) if ln.WORD.fullmatch(w)]
    kept = [w for k, w in enumerate(found) if w not in _DOC_WORDS or (k + 1 < len(found) and _qualifies(found[k + 1]))]
    return {_key(w) for w in kept} - _QUESTION_ONLY - (_GENERIC - _KIND_WORDS)


def _qualifies(next_word: str) -> bool:
    """Whether a document word before ``next_word`` qualifies it: "invoice date", not "invoice from Acme"."""
    key = _key(next_word)
    return next_word not in _DOC_WORDS and key not in _QUESTION_ONLY and key not in (_GENERIC - _KIND_WORDS)


def _labels(ctx: ToolContext, doc_id: str, terms: sc.Terms) -> list[ln.Label]:
    """Label lines naming the question's field, best first; a label naming a different field ("Billing Address"
    for the shipping address) is left out."""
    wanted = set(terms.fields)
    found: list[ln.Label] = []
    for page in ctx.pages(doc_id)[:_MAX_PAGES]:
        if not ln.index(page).boxes:
            continue  # plain text answers from its sentences; label_guard still checks those answers
        for i, line in enumerate(ln.index(page).lines):
            text = line.text.strip()
            label, inline, colon = ln.split(text)
            label_words = ln.WORD.findall(label)
            if not label_words or len(label_words) > ln.MAX_LABEL_WORDS or ln.SENTENCE.search(text) or len(text) > 60:
                continue
            if not colon and (len(words(label)) < len(label_words) or label[:1].islower()):
                continue  # "Recalling that by its …", "account General …": prose, not a bare label
            if _TITLE_START.search(text) or (set(words(label)) & _DOC_WORDS and not colon):
                continue  # "Letter dated …", "TAX INVOICE", "Form W-8BEN": the document's title, not a field
            keys = ln.keys(label)
            own = ln.own_keys(label)
            shared = wanted & keys
            if not shared or len(shared) < 0.5 * len(wanted) or conflicts(wanted, keys, own, terms.about):
                continue
            score = len(shared) / len(wanted) - 0.15 * len(own - wanted)
            found.append(ln.Label(page, i, label, inline if ln.value_like(inline, colon) else "", colon, score))
    found.sort(key=lambda lab: -lab.score)
    return found


def _form_labels(lines: list[TextLine]) -> int:
    """Word-only labels with a colon that are not letter-header furniture: how form-like the page is."""
    count = 0
    for line in lines:
        head, _, colon = ln.split(line.text.strip())
        word_label = colon and head and not re.search(r"\d", head) and len(ln.WORD.findall(head)) <= 4
        if word_label and not set(words(head)) <= _HEADER_LABELS:
            count += 1
    return count


def _only_a_date(value: str) -> bool:
    """The value is a date and nothing else ("2 January 2024")."""
    text = _digits(value)
    found = [raw for _, raw, _ in parse_dates(text)]
    return bool(found) and not re.sub(r"\W", "", text.replace(found[0], "", 1))
