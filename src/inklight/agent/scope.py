"""What a printed label belongs to: the qualifier it carries and the person or section it sits under.

"Billing Address:" is not the shipping address, "Invoice Date:" is not the delivery date, and the "Salary:" under
"Bob Turner" is not Alice's salary. A question's own words decide:

1. Field words are the question's specific words ("shipping", "address"). A label conflicts with them when it
   carries a word the question does not ("billing") while the question has one the label lacks ("shipping"). A
   kind word the label lacks ("amount" for "Total Due") does not count, unless the label carries a different kind
   word ("Invoice Date" for "invoice number"); nor does a word the document is about (its title's "Egypt").
2. Names say whose or which: capitalised possessive owners ("Alice's") and capitalised words after the first that
   are not label words of the document ("the salary of Bob Turner"; but "Shipping" in "What's the Shipping
   address?" is a label word, so a field word). A lowercase owner ("the company's address") is a field word.
3. A label's section is the text above it, in its own columns, from the copy of the section-opening label above it
   ("Employee:" in a payroll that repeats it) or, on a page without repeated sections, from the top of the page.
"""

from __future__ import annotations

import re

from ..schemas import BBox, TextLine
from .answer import words
from .binding import _KIND_WORDS, _key

_TOKEN = re.compile(r"[^\W\d_][\w'’-]*")
_POSSESSIVE = re.compile(r"['’]s?$")
_CONTRACTIONS = {
    "it's", "its", "what's", "who's", "that's", "there's", "here's", "let's", "where's", "how's", "when's", "why's",
    "he's", "she's", "today's", "one's",
}  # fmt: skip
_EDGE = 4.0  # points of slack when comparing box edges


def name_candidates(question: str) -> tuple[set[str], set[str], list[set[str]]]:
    """Keys of (capitalised owners, lowercase owners, runs of adjacent capitalised words after the first).
    "What is Alice's salary?" -> ({alice}, ∅, []); "the date on globex’s invoice" -> (∅, {globex}, []); "the
    salary of Bob Turner" -> (∅, ∅, [{bob, turner}]). All-capital words ("VAT") are none of them."""
    owners: set[str] = set()
    lower: set[str] = set()
    runs: list[set[str]] = []
    previous = -2
    for k, token in enumerate(_TOKEN.findall(question)):
        base = _POSSESSIVE.sub("", token)
        if not base or base.isupper():
            continue
        found = {_key(w) for w in words(base)}
        owner = bool(_POSSESSIVE.search(token)) and token.lower().replace("’", "'") not in _CONTRACTIONS
        if owner:
            (owners if base[:1].isupper() else lower).update(found)
        elif k > 0 and base[:1].isupper() and found:
            if previous == k - 1 and runs:
                runs[-1] |= found
            else:
                runs.append(set(found))
            previous = k
    return owners, lower - owners, [run - owners for run in runs if run - owners]


def conflicts(
    fields: set[str], label_keys: set[str], label_words: set[str], about: frozenset[str] = frozenset()
) -> bool:
    """Whether a label names a different field from the question's: each side has a word the other lacks."""
    extra = label_words - fields
    missing = fields - label_keys - about
    if not extra or not missing:
        return False
    plain_missing = missing - _KIND_WORDS
    return bool(plain_missing) or bool(extra & _KIND_WORDS)


def section_text(lines: list[TextLine], i: int, extent: BBox, headers: list[int]) -> str:
    """The text above line ``i`` within the horizontal ``extent`` of its label and value, from the nearest copy of
    the section-opening label above it (its row included), or from the top of the page."""
    me = lines[i].bbox
    assert me is not None
    top = 0.0
    for j in headers:
        other = lines[j].bbox
        if other is not None and _overlaps(extent, other) and other[1] < me[1] - _EDGE:
            top = max(top, other[1])
    above = [
        ln
        for k, ln in enumerate(lines)
        if k != i
        and ln.bbox is not None
        and ln.bbox[1] >= top - _EDGE
        and ln.bbox[3] <= me[1] + _EDGE
        and _overlaps(extent, ln.bbox)
    ]
    return " ".join(ln.text.strip() for ln in sorted(above, key=lambda ln: ln.bbox[1]))  # type: ignore[index]


def names_in(names: set[str], text: str) -> set[str]:
    return names & {_key(w) for w in words(text)}


def _overlaps(extent: BBox, box: BBox) -> bool:
    return box[0] < extent[2] - _EDGE and box[2] > extent[0] + _EDGE
