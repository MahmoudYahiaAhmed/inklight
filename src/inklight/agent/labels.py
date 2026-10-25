"""Questions that name a label: answered with the value printed beside or below it on the page.

Forms, infoboxes and receipts print a label with its value: "MANUFACTURER:  B & W", "Elevation [1] 99 m",
"Area code (+20) 97", "المساحة 375 كيلومتر مربع", "12% Service:  66.72". A question that names the label ("Who is the
manufacturer?", "ما مساحة أسوان؟") is answered with that value, citing its page and box:

1. A label is a short bare noun phrase (at most six words, no function words or sentence punctuation) that holds at
   least half of the question's specific words. Among several, the one with the fewest words the question does not
   use wins ("Area" for "total area", "Area code" for "area code"). Titles and headings naming the document ("TAX
   INVOICE", "Letter dated …") are not labels.
2. Its value is the rest of its line, else the cells on its row in reading direction (Arabic: to the left), taken
   from the row nearest the label's own baseline, up to the next "Label:" cell, else the line just below it. A
   label without a colon must have a value with a digit, so headings and prose are not mistaken for fields.
3. Confidence follows the evidence: a value on the label's own line or row is 0.7; a colon-less label whose value
   is on another line, several equally good labels, or several values beside one label are flagged (0.25).
4. On a form (three or more word labels with values on the page), a label with nothing at all beside or below it
   is a blank field, and the answer says no value was found there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..extract import layout
from ..extract.values import parse_dates
from ..schemas import BBox, PageContent, Source, TextLine
from .answer import expected_kind, words
from .binding import _KIND_WORDS, _TITLE_START, _digits, _has_kind, _key
from .context import ToolContext
from .unmentioned import _GENERIC, say_no_evidence

_MAX_DOCS = 3
_MAX_PAGES = 5
_MAX_LABEL_WORDS = 6
_WORD = re.compile(r"[^\W\d_]+")
_SENTENCE = re.compile(r"[.!?؟]\s+\S")
_BULLET = "•·-–*"
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
_ROW_BAND = 0.35  # cells within this many line heights of the nearest one share its row
_QUESTION_ONLY = {
    _key(w) for w in ("what", "which", "who", "whose", "how", "much", "many", "is", "the", "ما", "من", "كم")
}


@dataclass(frozen=True)
class _Label:
    page: PageContent
    index: int  # of the line among the page's placed lines
    text: str  # the label words as written
    inline: str  # what follows the label on its own line
    colon: bool
    score: float
    tied: bool = False  # another label line matched the question as well


def label_answer(ctx: ToolContext, question: str) -> str | None:
    """Answer from a label's value on the page; None when no label line matches the question."""
    wanted = _wanted(question)
    if not wanted:
        return None
    kind = expected_kind(question)
    docs = list(dict.fromkeys(h.source.doc_id for h in ctx.scratch.hits)) or ctx.scratch.doc_ids
    for doc_id in docs[:_MAX_DOCS]:
        doc = ctx.library.get(doc_id)
        if doc is None:
            continue
        best = _best_label(ctx, doc_id, wanted)
        if best is None:
            continue
        lines = _placed(best.page)
        value, cells, nearby = _value(best, lines)
        if value is not None and kind == "date" and not _has_kind("date", _digits(value)):
            continue  # "When was it adopted?" is not answered by a page number beside a label
        if value is not None and kind != "date" and _only_a_date(value):
            continue  # "Which meeting …?", "What is the meeting number?" are not answered by a bare date
        if value is None:
            if not best.colon or nearby or _form_labels(lines) < _FORM_LIKE:
                continue  # prose ending in ":", or something sits beside it that is not read as a value
            say_no_evidence(
                ctx,
                f"a value of “{best.text}”",
                f"the label “{best.text}” is on page {best.page.number}, but nothing is written beside or below it "
                "(a blank field)",
            )
            return "blank field"
        _answer(ctx, doc, doc_id, best, lines, value, cells)
        return "value beside its label"
    return None


def _answer(ctx, doc, doc_id: str, best: _Label, lines: list[TextLine], value: str, cells: list[TextLine]) -> None:  # type: ignore[no-untyped-def]
    s = ctx.scratch
    label_line = lines[best.index]
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
            bbox=_union([label_line.bbox, *[c.bbox for c in cells]]),  # type: ignore[list-item]
            excerpt=" ".join([label_line.text.strip(), *[c.text.strip() for c in cells]]),
            ocr_conf=min([x.conf for x in [label_line, *cells] if x.conf is not None], default=None),
        )
    ]
    below_only = not best.inline and not best.colon and cells and not _beside(label_line.bbox, cells[0].bbox, False)  # type: ignore[arg-type]
    doubt = (
        "more than one value sits beside this label; check which one belongs to it"
        if len(cells) > 1
        else "more than one line on the page matches this label; check the cited one"
        if best.tied
        else "the value was read from the line under an unpunctuated label; check it"
        if below_only and not layout.rtl(label_line.text)
        else ""
    )
    if doubt:
        s.warn(f"Low confidence: {doubt}.")
    s.confidence = 0.25 if doubt else 0.7
    s.notes.append(f"answer: the value beside the label “{best.text}” on page {best.page.number}")


def _wanted(question: str) -> set[str]:
    """The question's words that a label would carry: not question words, and not generic ("what", "the")."""
    # words() drops "of", "the", "ما" …; the document itself ("this form", "the letter") is not a field it holds.
    keys = {_key(w) for w in words(question) if _WORD.fullmatch(w) and w not in _DOC_WORDS}
    return {w for w in keys if w not in _QUESTION_ONLY and w not in (_GENERIC - _KIND_WORDS)}


def _placed(page: PageContent) -> list[TextLine]:
    return [ln for ln in page.lines if ln.bbox is not None and ln.text.strip()]


def _split(text: str) -> tuple[str, str, bool]:
    """A line as (label words, the rest, has a colon): "Area code (+20) 97" -> ("Area code", "(+20) 97")."""
    if ":" in text and not re.search(r"\d:\d|://", text):  # "10:30" and URLs are not labels
        head, _, rest = text.partition(":")
        head = re.sub(r"^[\d%\s.]+", "", head).strip(_BULLET + " ")  # "12% Service" -> "Service"
        return head, rest.strip(), True
    tokens = [t for t in text.split() if t.strip(_BULLET)]  # a lone "•" is not a word
    k = 0
    while k < len(tokens) and _WORD.fullmatch(tokens[k].strip(_BULLET)):
        k += 1
    if k == 0:  # "375 كيلومتر مربع المساحة", "2 الكثافة السكانية": words after a number, on a short line
        if len(tokens) > 4:
            return "", "", False
        found = [t for t in tokens if _WORD.fullmatch(t)]
        others = [t for t in tokens if not _WORD.fullmatch(t)]
        return " ".join(found), (" ".join(others) if any(re.search(r"\d{2,}", t) for t in others) else ""), False
    return " ".join(t.strip(_BULLET) for t in tokens[:k]).strip(), " ".join(tokens[k:]), False


def _keys(text: str) -> set[str]:
    """Label words compared like question words (search form, light stem), plus each adjacent pair joined, so
    "Sub-Total" also reads as "subtotal"."""
    found = [w for w in words(text) if _WORD.fullmatch(w)]
    joined = ["".join(found[i : i + 2]) for i in range(len(found) - 1)]
    return {_key(w) for w in found + joined}


def _best_label(ctx: ToolContext, doc_id: str, wanted: set[str]) -> _Label | None:
    found: list[_Label] = []
    for page in ctx.pages(doc_id)[:_MAX_PAGES]:
        for i, line in enumerate(_placed(page)):
            text = line.text.strip()
            label, inline, colon = _split(text)
            label_words = _WORD.findall(label)
            if not label_words or len(label_words) > _MAX_LABEL_WORDS or _SENTENCE.search(text) or len(text) > 60:
                continue
            if not colon and (len(words(label)) < len(label_words) or label[:1].islower()):
                continue  # "Recalling that by its …", "account General …": prose, not a bare label
            if _TITLE_START.search(text) or set(words(label)) & _DOC_WORDS:
                continue  # "Letter dated …", "TAX INVOICE", "Form W-8BEN": the document's title, not a field
            keys = _keys(label)
            shared = wanted & keys
            if not shared or len(shared) < 0.5 * len(wanted):
                continue
            extra = len({_key(w) for w in words(label) if _WORD.fullmatch(w)} - wanted)
            score = len(shared) / len(wanted) - 0.15 * extra
            found.append(_Label(page, i, label, inline if _value_like(inline, colon) else "", colon, score))
    if not found:
        return None
    found.sort(key=lambda lab: -lab.score)
    best = found[0]
    rivals = [lab for lab in found[1:] if lab.score == best.score and _keys(lab.text) != _keys(best.text)]
    return _Label(best.page, best.index, best.text, best.inline, best.colon, best.score, tied=bool(rivals))


def _form_labels(lines: list[TextLine]) -> int:
    """Word-only labels with a colon that are not letter-header furniture: how form-like the page is."""
    count = 0
    for ln in lines:
        head, rest, colon = _split(ln.text.strip())
        word_label = colon and head and not re.search(r"\d", head) and len(_WORD.findall(head)) <= 4
        if word_label and not set(words(head)) <= _HEADER_LABELS:
            count += 1
    return count


def _only_a_date(value: str) -> bool:
    """The value is a date and nothing else ("2 January 2024")."""
    text = _digits(value)
    found = [raw for _, raw, _ in parse_dates(text)]
    return bool(found) and not re.sub(r"\W", "", text.replace(found[0], "", 1))


def _value_like(text: str, colon: bool) -> bool:
    """A value: any text after a colon; otherwise something with digits beyond a bare footnote or year in
    brackets ("(2024)", "[1]")."""
    rest = re.sub(r"\[\d+\]|\(\d{4}\)", "", text).strip()
    if not rest:
        return False
    return colon or bool(re.search(r"\d", rest))


def _value(label: _Label, lines: list[TextLine]) -> tuple[str | None, list[TextLine], bool]:
    """(value, its cells, whether anything at all sits beside or below the label)."""
    if label.inline:
        return re.sub(r"\[\d+\]\s*", "", label.inline).strip(), [], True
    me = lines[label.index]
    assert me.bbox is not None
    right_to_left = layout.rtl(me.text)
    side = [o for j, o in enumerate(lines) if j != label.index and _beside(me.bbox, o.bbox, right_to_left)]  # type: ignore[arg-type]
    cells: list[TextLine] = []
    if side:
        # The row nearest the label's own baseline; a closer-in-x cell of the next row does not count.
        h = max(me.bbox[3] - me.bbox[1], 1.0)
        nearest = min(_offset(me.bbox, o.bbox) for o in side)  # type: ignore[arg-type]
        row = [o for o in side if _offset(me.bbox, o.bbox) <= nearest + _ROW_BAND * h]  # type: ignore[arg-type]
        row.sort(key=lambda o: _gap(me.bbox, o.bbox, right_to_left))  # type: ignore[arg-type]
        for o in row:  # the label's cells end where the next "Label:" starts ("DATE: 8/10/90  TIME:")
            if _is_label(o.text):
                break
            if _value_like(o.text, label.colon):
                cells.append(o)
    if cells:
        return " ".join(o.text.strip() for o in cells[:3]), cells[:3], True
    under = _below(lines, label.index)
    if under is not None:
        text = under.text.strip()
        short = label.colon or len(text) <= 40  # without a colon, only a short value line belongs to the label
        if short and not _is_label(text) and _value_like(text, label.colon):
            return text, [under], True
    return None, [], any(not _is_label(o.text) for o in side)  # a "Label:" below or beside is another field


def _below(lines: list[TextLine], i: int) -> TextLine | None:
    """The nearest line under line ``i`` in its column, within about one and a half line heights."""
    me = lines[i].bbox
    assert me is not None
    h = max(me[3] - me[1], 1.0)
    under = [
        o
        for j, o in enumerate(lines)
        if j != i and o.bbox is not None and layout.same_column(me, o.bbox) and 0 <= o.bbox[1] - me[3] <= 1.5 * h
    ]
    return min(under, key=lambda o: o.bbox[1], default=None)  # type: ignore[index]


def _offset(a: BBox, b: BBox) -> float:
    return abs((a[1] + a[3]) / 2 - (b[1] + b[3]) / 2)


def _beside(a: BBox, b: BBox, right_to_left: bool) -> bool:
    """On the label's row, after it in reading direction. Typed values sit a little above or below a printed
    label's baseline, so the row reaches one label height either way; the nearest row wins (see _value)."""
    same = _offset(a, b) <= max(a[3] - a[1], 1.0)
    after = b[2] <= a[0] + 4 if right_to_left else b[0] >= a[2] - 4
    return same and after


def _gap(a: BBox, b: BBox, right_to_left: bool) -> float:
    return a[0] - b[2] if right_to_left else b[0] - a[2]


def _is_label(text: str) -> bool:
    return text.strip().endswith(":")


def _union(boxes: list[BBox]) -> BBox:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
