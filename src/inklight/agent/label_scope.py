"""Choosing among copies of a label, and saying when a label is not the one a question means.

Used by the label answers (labels.py) and by the check on the other answering paths (label_guard.py), so both
apply the same rules:

- copies of one label are told apart by the names in the section above each ("Salary:" under "Alice Martin");
- with no name, copies that print different values are reported, not chosen between;
- a single label whose section does not hold the name the question gives is flagged when the page is divided into
  sections, or when the document prints that name nowhere; otherwise it answers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from ..schemas import PageContent, Source
from . import lines as ln
from .answer import words
from .binding import _key
from .context import ToolContext
from .scope import name_candidates, names_in, section_text

_DOC_WORDS_RE = re.compile(r"\.[A-Za-z0-9]+$")
_TITLE_LINES = 3  # the first page's top lines name what the document is about
_MAX_PAGES = 5
_SHOWN = 4  # copies listed in an ambiguous answer


@dataclass(frozen=True)
class Terms:
    """A question's words as they bear on one document's labels."""

    fields: frozenset[str]  # what the label must name ("shipping", "address")
    names: frozenset[str]  # whose or which ("alice"): matched against the section above a label
    about: frozenset[str]  # field words the document's title or file name prints: a label need not carry them
    unprinted: frozenset[str]  # names the document prints nowhere
    asked: frozenset[str] = frozenset()  # every word of the question, generic ones too ("type", "name")


def question_terms(ctx: ToolContext, doc_id: str, wanted: set[str], question: str, doc_words: set[str]) -> Terms:
    """Field words, names and subject words of a question about one document. ``wanted`` are the question's label
    words; ``doc_words`` the words naming a document type, which never count as the subject."""
    pages = [ln.index(p) for p in ctx.pages(doc_id)[:_MAX_PAGES]]
    subject = _subject(ctx, doc_id, pages, doc_words)
    # The document's own name ("Aswan 1,568,000" in an infobox) is not one of its labels.
    label_words = (set().union(*(p.label_word_keys() for p in pages)) if pages else set()) - subject
    printed = set().union(*(p.word_keys() for p in pages)) if pages else set()
    owners, lower, runs = name_candidates(question)
    # "globex’s invoice" names the vendor the document prints; "the company's address" names no one.
    entities = (lower & printed) - label_words
    # A run of capitals is a name when the document prints any of it outside its labels ("Bob Turner", "Security
    # Council"); one made only of label words or of words the document never prints is the field asked for
    # ("What's the Shipping address?" on an invoice printing only "Billing Address").
    capitals = set().union(*runs) if runs else set()
    named_runs = set().union(*[run for run in runs if (run & printed) - label_words] or [set()])
    names = (owners | entities | named_runs) & wanted
    fields = wanted - names
    if not fields:  # a question that is all names: read them as field words
        fields, names = set(wanted), set()
    unprinted = ((owners | capitals) & wanted) - printed
    asked = frozenset(_key(w) for w in words(question))
    return Terms(frozenset(fields), frozenset(names), frozenset(fields & subject), frozenset(unprinted), asked)


def _subject(ctx: ToolContext, doc_id: str, pages: list[ln.PageIndex], doc_words: set[str]) -> set[str]:
    """Words of the file name and the title lines: the first page's top lines before any "Label:" or number."""
    doc = ctx.library.get(doc_id)
    title: list[str] = []
    for line in sorted(pages[0].lines, key=lambda x: x.bbox[1])[:_TITLE_LINES] if pages else []:  # type: ignore[index]
        if ":" in line.text or re.search(r"\d", line.text):
            break
        title.append(line.text)
    name = _DOC_WORDS_RE.sub("", doc.name) if doc is not None else ""
    return {_key(w) for w in words(" ".join([name, *title])) if ln.WORD.fullmatch(w) and w not in doc_words}


def section(lab: ln.Label) -> str:
    """The text above a label, back to the start of its section."""
    page = ln.index(lab.page)
    _, cells, _ = page.value(lab)
    extent = ln.union([page.lines[lab.index].bbox, *[c.bbox for c in cells]])  # type: ignore[list-item]
    return section_text(page.lines, lab.index, extent, page.headers())


def pick(found: list[ln.Label], terms: Terms) -> ln.Label | None:
    """The label to answer from among the best-scoring ones, or None when copies with different values cannot be
    told apart (the caller reports them with ``say_ambiguous``)."""
    top = [lab for lab in found if (lab.score, lab.overlap) == (found[0].score, found[0].overlap)]
    same = [lab for lab in top if ln.keys(lab.text) == ln.keys(top[0].text)]
    tied = len({frozenset(ln.keys(lab.text)) for lab in top}) > 1
    names = set(terms.names)
    if names:
        named = [(len(names_in(names, section(lab))), lab) for lab in same]
        most = max(n for n, _ in named)
        hits = [lab for n, lab in named if n == most and n > 0]
        if len(hits) == 1:
            return replace(hits[0], tied=tied)
        if hits or differ(same):
            return None
        return replace(same[0], tied=tied, unscoped=doubt_for(terms, same[0].page, single=len(same) == 1))
    if differ(same):
        return None
    return replace(same[0], tied=tied, unscoped=unprinted_doubt(terms))


def unprinted_doubt(terms: Terms) -> str:
    """A question naming something the document never prints ("the population of Egypt" on Aswan's page)."""
    if not terms.unprinted:
        return ""
    return f"the question names {', '.join(sorted(terms.unprinted))}, which this document does not print"


def doubt_for(terms: Terms, page: PageContent, *, single: bool) -> str:
    """Why a label found outside the named section is in doubt, or "" when it may answer."""
    shown = ", ".join(sorted(terms.names))
    if terms.unprinted:
        return unprinted_doubt(terms)
    if not single or len(ln.index(page).headers()) > 1:
        return f"the label is not under {shown}"
    return ""  # one label on a page without sections: "the company's address" is its address


def differ(copies: list[ln.Label]) -> bool:
    """Whether copies that read their value as the first one does print different values. A column header
    "Total" over an item table does not compete with the "Total 226.96" row."""
    if len(copies) < 2:
        return False
    first = ln.index(copies[0].page)
    mode = ln.value_mode(copies[0], first.lines, first.value(copies[0])[1])
    return len(copy_values(copies, mode)) > 1


def copy_values(copies: list[ln.Label], mode: str) -> set[str]:
    out: set[str] = set()
    for lab in copies:
        page = ln.index(lab.page)
        value, cells, _ = page.value(lab)
        if value is not None and ln.value_mode(lab, page.lines, cells) == mode:
            out.add(value)
    return out


def page_copies(page: PageContent, label_index: int) -> list[ln.Label]:
    """Every copy, on this page, of the label that line ``label_index`` starts."""
    idx = ln.index(page)
    return [idx.label(i) for i in idx.copies(idx.keys[label_index])]


def say_ambiguous(ctx: ToolContext, doc, doc_id: str, found: list[ln.Label], terms: Terms) -> None:  # type: ignore[no-untyped-def]
    """Report each copy of a repeated label with its value and the section it is under; pick none."""
    s = ctx.scratch
    top = [
        lab
        for lab in found
        if (lab.score, lab.overlap) == (found[0].score, found[0].overlap)
        and ln.keys(lab.text) == ln.keys(found[0].text)
    ]
    shown, sources = [], []
    for lab in top[:_SHOWN]:
        page = ln.index(lab.page)
        value, cells, _ = page.value(lab)
        heading = section(lab)[-60:].strip() or "the top of the page"
        shown.append(f"- {value or '(blank)'}: under “{heading}”, page {lab.page.number}")
        me = page.lines[lab.index]
        sources.append(
            Source(
                doc_id=doc_id,
                path=doc.path,
                name=doc.name,
                page=lab.page.number,
                bbox=ln.union([me.bbox, *[c.bbox for c in cells]]) if page.boxes else None,  # type: ignore[list-item]
                excerpt="\n".join([me.text.strip(), *[c.text.strip() for c in cells]]),
                ocr_conf=me.conf,
            )
        )
    label = top[0].text
    more = f" (the first {_SHOWN} are listed)" if len(top) > _SHOWN else ""
    names = ", ".join(sorted(terms.names))
    s.answer = (
        f"None of the {len(top)} copies of “{label}” is under {names}; they print different values{more}:\n"
        if names
        else f"“{label}” is printed {len(top)} times with different values{more}:\n"
    ) + "\n".join(shown)
    s.sources = sources
    s.confidence = 0.25
    s.warn(
        f"Low confidence: {names} is not printed in this document, so no copy of “{label}” can be chosen."
        if names and terms.unprinted
        else f"Low confidence: no copy of “{label}” is under {names}; check which one is meant."
        if names
        else f"Low confidence: “{label}” appears more than once and the question does not say which one is "
        "meant; name the person or section it belongs to."
    )
    s.notes.append(f"answer: the label “{label}” is repeated; none chosen")
