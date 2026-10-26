"""The label checks applied to answers from the other paths (field shortcut, reader, rules).

Whatever path found an answer, it must not get around what a printed label says about it:

- a bare label ("Invoice Date:"), a passage that only repeats the question's words ("اسم الشركة" for "ما اسم
  الشركة؟"), or a table's column heading is not an answer;
- a value printed beside or under a label naming a different field ("Billing Address:" for the shipping address,
  "Invoice Date:" for the delivery date) is declined;
- a value under a label that is repeated with different values, or outside the section of the person the question
  names, is flagged (label_scope.py has the rules).

Pages without boxes (plain text) are checked on their lines in order (lines.py lays them out as one column); the
cited value is then found by its text.
"""

from __future__ import annotations

from ..schemas import Source
from . import label_scope as sc
from . import lines as ln
from .answer import words
from .binding import _key
from .context import ToolContext
from .labels import terms_for
from .scope import conflicts, names_in, section_text
from .unmentioned import say_no_evidence

_DECLINED = ("I couldn't find", "I could not find")
_MAX_BARE_WORDS = 6
_MIN_PART = 4  # an answer shorter than this ("12") is too common to locate as part of a line


def check_label_scope(ctx: ToolContext, question: str) -> str | None:
    """Decline or flag the current answer when a printed label contradicts it; None when nothing applies."""
    s = ctx.scratch
    if not s.sources or s.answer.startswith(_DECLINED):
        return None
    src = s.sources[0]
    terms = terms_for(ctx, src.doc_id, question)
    fields = set(terms.fields)
    if not fields:
        return None
    head = s.answer.split("\n\nEvidence:")[0].strip()
    if _bare_label(head):
        say_no_evidence(ctx, _phrase(question, fields), f"the passage found is only the label “{head}”")
        return "a bare label is not an answer"
    named = _field_name(ctx, src, head)
    if named:
        say_no_evidence(
            ctx,
            _phrase(question, fields),
            f"the passage found is the field name “{named}” printed on page {src.page}, not its value",
        )
        s.answer = (
            f"{s.answer[:-1]}: the passage found is the field name “{named}” on page {src.page}, not its value. "
            "Check that place on the page."
        )
        return "a field name is not an answer"
    if _restates(head, question):
        say_no_evidence(
            ctx, _phrase(question, fields), f"the passage found only repeats the question's words (“{head}”)"
        )
        return "a passage repeating the question is not an answer"
    heading = _table_heading(ctx, src.doc_id, head)
    if heading:
        say_no_evidence(
            ctx, _phrase(question, fields), f"the passage found is the table heading “{heading}”, not a value"
        )
        return "a table heading is not an answer"
    found = _governing(ctx, src, head)
    if found is None:
        return None
    page, j, k = found
    label = page.split(j)[0]
    keys = ln.keys(label)
    if not fields & keys:
        other = _matching_label(page, fields, terms) if page.lines[j].text.strip().endswith(":") or k == j else None
        if other is None:
            return None  # a label of another field altogether; the typed check judges that
        doubt = f"the cited value is printed beside “{label}”, while the document has a “{other}” label"
        s.warn(f"Low confidence: {doubt}. Check the cited value.")
        s.confidence = min(s.confidence, 0.25)
        return f"flagged: {doubt}"
    if conflicts(fields, keys, ln.own_keys(label), terms.about):
        say_no_evidence(
            ctx,
            _phrase(question, fields),
            f"the value found is printed beside “{label}”, a different field from the one asked for",
        )
        return f"declined: the value belongs to “{label}”"
    doubt = _scope_doubt(page, j, k, terms)
    if not doubt:
        return None
    s.warn(f"Low confidence: {doubt}. Check the cited value.")
    s.confidence = min(s.confidence, 0.25)
    return f"flagged: {doubt}"


def _governing(ctx: ToolContext, src: Source, head: str) -> tuple[ln.PageIndex, int, int] | None:
    """(page, label line, value line) for the cited value, or None when it is not a label's value."""
    page_content = next((p for p in ctx.pages(src.doc_id) if p.number == src.page), None) if src.page else None
    if page_content is None:
        return None
    page = ln.index(page_content)
    box = src.bbox if page.boxes else None
    for k, line in enumerate(page.lines):
        if not _cited_value(line, page.split(k), box, head):
            continue
        j = _governing_label(page.lines, k)
        if j is not None:
            return page, j, k
    return None


def _matching_label(page: ln.PageIndex, fields: set[str], terms: sc.Terms) -> str | None:
    """A colon label on the page naming the question's field ("Salary:" for "Alice's salary"), if any."""
    for i, line in enumerate(page.lines):
        label, _, colon = page.split(i)
        if not colon or not ln.label_line(line.text):
            continue
        keys = set(page.keys[i])
        if fields & keys and not conflicts(fields, keys, ln.own_keys(label), terms.about):
            return label
    return None


def _scope_doubt(page: ln.PageIndex, j: int, k: int, terms: sc.Terms) -> str:
    copies = sc.page_copies(page.page, j)
    if terms.unprinted:
        return sc.unprinted_doubt(terms)
    if terms.names:
        extent = ln.union([page.lines[j].bbox, page.lines[k].bbox])  # type: ignore[list-item]
        if names_in(set(terms.names), section_text(page.lines, j, extent, page.headers())):
            return ""
        return sc.doubt_for(terms, page.page, single=len(copies) < 2)
    row = j == k or ln.beside(page.lines[j].bbox, page.lines[k].bbox, ln.layout.rtl(page.lines[j].text))  # type: ignore[arg-type]
    if len(copies) > 1 and len(sc.copy_values(copies, "row" if row else "below")) > 1:
        label = page.split(j)[0]
        return f"“{label}” is printed more than once with different values and the question does not say which"
    return ""


def _restates(head: str, question: str) -> bool:
    """The answer is the question's own words and nothing else ("Company name" for "What is the company name?")."""
    text = head.strip().strip('“”"')
    found = [w for w in words(text) if ln.WORD.fullmatch(w)]
    if not found or len(found) > _MAX_BARE_WORDS or any(ch.isdigit() for ch in text):
        return False
    asked = {_key(w) for w in words(question)}
    return {_key(w) for w in found} <= asked


def _table_heading(ctx: ToolContext, doc_id: str, head: str) -> str | None:
    """The table heading the answer is, when the document's structure has one with exactly that text."""
    document = ctx.structure(doc_id)
    if document is None or not head.strip():
        return None
    from ..structure.adapter import table_grid

    first = _squash(head.splitlines()[0])
    for table in document.tables:
        grid = table_grid(table, document)
        if grid.field_value():
            continue  # its first row is a field and its value, not a heading
        for r in grid.header_rows:
            for text in grid.rows[r]:
                if text.strip() and _squash(text) == first:
                    return text
    return None


def _field_name(ctx: ToolContext, src: Source, head: str) -> str | None:
    """The answer is one of the page's field names: a numbered field name ("(ب) ٢- عنوان الشركة") or a bare
    "Label:", wherever on the page it is printed; the field it names is not the question's value."""
    parts = [x.strip() for x in head.splitlines() if x.strip()]
    if len(parts) != 1:
        return None  # "Move-in:" followed by its value is a label and its value, not a field name alone
    first = parts[0].strip('“”"')
    if not ln.WORD.search(first):
        return None
    page_content = next((p for p in ctx.pages(src.doc_id) if p.number == src.page), None) if src.page else None
    if page_content is None:
        return None
    target = _squash(ln.strip_markers(first)).rstrip(":")
    for line in ln.index(page_content).lines:
        text = line.text.strip()
        if not (ln.enumerated_label(text) or _bare_label(text)):
            continue
        if _squash(ln.strip_markers(text)).rstrip(":") == target:
            return ln.strip_markers(text).rstrip(":")
    if ln.enumerated_label(first):
        return ln.strip_markers(first)
    return None


def _squash(text: str) -> str:
    return "".join(text.split()).strip('“”"')


def _bare_label(head: str) -> bool:
    """ "Invoice Date:" with nothing after it."""
    text = head.strip().strip('“”"')
    return text.endswith(":") and 0 < len(ln.WORD.findall(text)) <= _MAX_BARE_WORDS and "\n" not in text


def _cited_value(line, parts: tuple[str, str, bool], box, head: str) -> bool:  # type: ignore[no-untyped-def]
    """The line lies in the cited box (when there is one) and its value text is part of the answer."""
    b = line.bbox
    if box is not None and (b is None or b[2] < box[0] or b[0] > box[2] or b[3] < box[1] or b[1] > box[3]):
        return False
    _, rest, colon = parts
    value = rest if colon else line.text.strip()
    return bool(value) and (value in head or (len(head) >= _MIN_PART and head in value))


def _governing_label(lines, k: int) -> int | None:  # type: ignore[no-untyped-def]
    """The label a value line belongs to: itself when it reads "Label: value", else the nearest label line before
    it on its row in reading direction, else the label line just above it."""
    label, rest, colon = ln.split(lines[k].text.strip())
    if colon and rest and _label_like(f"{label}:"):  # a short "Label: value", not a sentence with a colon in it
        return k
    me = lines[k].bbox
    assert me is not None
    h = max(me[3] - me[1], 1.0)
    near = [j for j, x in enumerate(lines) if j != k and abs(x.bbox[1] - me[1]) <= 3 * h and _label_like(x.text)]
    beside = [j for j in near if ln.beside(lines[j].bbox, me, ln.layout.rtl(lines[j].text))]
    if beside:
        return min(beside, key=lambda j: ln.gap(lines[j].bbox, me, ln.layout.rtl(lines[j].text)))
    above = [j for j in near if ln.below(lines, j) is lines[k]]
    return above[0] if above else None


def _label_like(text: str) -> bool:
    """A label line without its value, as short as the label path requires: not a sentence ending in ":"."""
    _, rest, _ = ln.split(text.strip())
    return not rest and ln.label_line(text)


def _phrase(question: str, fields: set[str]) -> str:
    shown = [w for w in words(question) if _key(w) in fields]
    return "the " + " ".join(dict.fromkeys(shown)) if shown else "the value asked for"
