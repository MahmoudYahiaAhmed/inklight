"""A page's lines as labels and values: what a line's label is, where its value is printed, and which lines repeat
the same label. Shared by the label answers (labels.py), their scope (label_scope.py) and the check on the other
answering paths (label_guard.py).

A page without boxes (plain text, Markdown) is laid out as one column of evenly spaced lines, so "Label: value" on
one line and "Label:" over its value read the same way as on a scan; citations from such a page carry no box.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

from ..extract import layout
from ..schemas import BBox, PageContent, TextLine
from .answer import words
from .binding import _key

WORD = re.compile(r"[^\W\d_]+")
SENTENCE = re.compile(r"[.!?؟]\s+\S")
MAX_LABEL_WORDS = 6
_BULLET = "•·-–*"
_ROW_BAND = 0.35  # cells within this many line heights of the nearest one share its row
_TEXT_PITCH = 20.0  # synthetic layout of a page without boxes: one line every 20 points, 14 high
_TEXT_HEIGHT = 14.0
_CACHE_SIZE = 32


@dataclass(frozen=True)
class Label:
    page: PageContent
    index: int  # of the line among the page's placed lines
    text: str  # the label words as written
    inline: str  # what follows the label on its own line
    colon: bool
    score: float = 0.0
    tied: bool = False  # another label line matched the question as well
    unscoped: str = ""  # why the label's section does not show it belongs to whom the question names


@dataclass
class PageIndex:
    """One page's placed lines with what is computed about them once: each line's label keys and the value of the
    label it starts."""

    page: PageContent
    lines: list[TextLine]
    keys: list[frozenset[str]]  # the keys of each line's label part
    boxes: bool  # the page has real boxes (not the synthetic layout)
    splits: list[tuple[str, str, bool]]  # each line as (label words, the rest, has a colon)
    _values: dict[int, tuple[str | None, list[TextLine], bool]] = field(default_factory=dict)
    _headers: list[int] | None = None
    _words: set[str] | None = None
    _label_words: set[str] | None = None

    def split(self, i: int) -> tuple[str, str, bool]:
        return self.splits[i]

    def label(self, i: int) -> Label:
        text, inline, colon = self.splits[i]
        return Label(self.page, i, text, inline if value_like(inline, colon) else "", colon)

    def value(self, lab: Label) -> tuple[str | None, list[TextLine], bool]:
        if lab.index not in self._values:
            self._values[lab.index] = value(lab, self.lines)
        return self._values[lab.index]

    def copies(self, label_keys: frozenset[str]) -> list[int]:
        return [i for i, k in enumerate(self.keys) if k and k == label_keys]

    def headers(self) -> list[int]:
        """Copies of the label that opens each repeated section ("Employee:" in a payroll), or none: of the labels
        printed more than once, the one whose first copy is highest on the page."""
        if self._headers is None:
            first: dict[frozenset[str], list[int]] = {}
            for i, k in enumerate(self.keys):
                if k and _label_line(self.lines[i].text):
                    first.setdefault(k, []).append(i)
            repeated = [ids for ids in first.values() if len(ids) > 1]
            top = min(repeated, key=lambda ids: self.lines[ids[0]].bbox[1], default=[])  # type: ignore[index]
            self._headers = top
        return self._headers

    def word_keys(self) -> set[str]:
        if self._words is None:
            self._words = {_key(w) for ln in self.lines for w in words(ln.text)}
        return self._words

    def label_word_keys(self) -> set[str]:
        """Words of the page's labels: lines with a colon, or label words followed by a value. A heading such as
        "Alice Martin" is not one."""
        if self._label_words is None:
            out: set[str] = set()
            for i, ks in enumerate(self.keys):
                _, rest, colon = self.splits[i]
                if (colon or rest) and _label_line(self.lines[i].text):
                    out |= ks
            self._label_words = out
        return self._label_words


_INDEX: dict[int, tuple[PageContent, PageIndex]] = {}  # holds the page, so its id is not reused while cached
_INDEX_LOCK = threading.Lock()


def index(page: PageContent) -> PageIndex:
    """The page's index, built once per page object."""
    with _INDEX_LOCK:
        hit = _INDEX.get(id(page))
    if hit is not None and hit[0] is page:
        return hit[1]
    lines = placed(page)
    splits = [split(ln.text.strip()) for ln in lines]
    built = PageIndex(page, lines, [frozenset(keys(s[0])) for s in splits], has_boxes(page), splits)
    with _INDEX_LOCK:
        if len(_INDEX) >= _CACHE_SIZE:
            _INDEX.pop(next(iter(_INDEX)))
        _INDEX[id(page)] = (page, built)
    return built


def has_boxes(page: PageContent) -> bool:
    return any(ln.bbox is not None for ln in page.lines)


def placed(page: PageContent) -> list[TextLine]:
    """The page's non-empty lines with boxes; a page without any box gets the synthetic one-column layout."""
    if has_boxes(page):
        return [ln for ln in page.lines if ln.bbox is not None and ln.text.strip()]
    texts = [ln for ln in page.lines if ln.text.strip()]
    return [
        ln.model_copy(update={"bbox": (0.0, k * _TEXT_PITCH, 6.0 * len(ln.text), k * _TEXT_PITCH + _TEXT_HEIGHT)})
        for k, ln in enumerate(texts)
    ]


def split(text: str) -> tuple[str, str, bool]:
    """A line as (label words, the rest, has a colon): "Area code (+20) 97" -> ("Area code", "(+20) 97")."""
    if ":" in text and not re.search(r"\d:\d|://", text):  # "10:30" and URLs are not labels
        head, _, rest = text.partition(":")
        head = re.sub(r"^[\d%\s.]+", "", head).strip(_BULLET + " ")  # "12% Service" -> "Service"
        return head, rest.strip(), True
    tokens = [t for t in text.split() if t.strip(_BULLET)]  # a lone "•" is not a word
    k = 0
    while k < len(tokens) and WORD.fullmatch(tokens[k].strip(_BULLET)):
        k += 1
    if k == 0:  # "375 كيلومتر مربع المساحة", "2 الكثافة السكانية": words after a number, on a short line
        if len(tokens) > 4:
            return "", "", False
        found = [t for t in tokens if WORD.fullmatch(t)]
        others = [t for t in tokens if not WORD.fullmatch(t)]
        return " ".join(found), (" ".join(others) if any(re.search(r"\d{2,}", t) for t in others) else ""), False
    return " ".join(t.strip(_BULLET) for t in tokens[:k]).strip(), " ".join(tokens[k:]), False


def keys(text: str) -> set[str]:
    """Label words compared like question words (search form, light stem), plus each adjacent pair joined, so
    "Sub-Total" also reads as "subtotal"."""
    found = [w for w in words(text) if WORD.fullmatch(w)]
    joined = ["".join(found[i : i + 2]) for i in range(len(found) - 1)]
    return {_key(w) for w in found + joined}


def own_keys(label: str) -> set[str]:
    """The label's own word keys, without the joined pairs."""
    return {_key(w) for w in words(label) if WORD.fullmatch(w)}


def _label_line(text: str) -> bool:
    """A short label line ("Salary:", "Salary: 52,000", "Total 70.00"), not a sentence."""
    label, _, colon = split(text.strip())
    n = len(WORD.findall(label))
    return 0 < n <= (MAX_LABEL_WORDS if colon else 4) and len(text.strip()) <= 60 and not SENTENCE.search(text)


def value_like(text: str, colon: bool) -> bool:
    """A value: any text after a colon; otherwise something with digits beyond a bare footnote or year in
    brackets ("(2024)", "[1]")."""
    rest = re.sub(r"\[\d+\]|\(\d{4}\)", "", text).strip()
    if not rest:
        return False
    return colon or bool(re.search(r"\d", rest))


def value(label: Label, lines: list[TextLine]) -> tuple[str | None, list[TextLine], bool]:
    """(value, its cells, whether anything at all sits beside or below the label)."""
    if label.inline:
        return re.sub(r"\[\d+\]\s*", "", label.inline).strip(), [], True
    me = lines[label.index]
    assert me.bbox is not None
    right_to_left = layout.rtl(me.text)
    side = [o for j, o in enumerate(lines) if j != label.index and beside(me.bbox, o.bbox, right_to_left)]  # type: ignore[arg-type]
    cells: list[TextLine] = []
    if side:
        # The row nearest the label's own baseline; a closer-in-x cell of the next row does not count.
        h = max(me.bbox[3] - me.bbox[1], 1.0)
        nearest = min(offset(me.bbox, o.bbox) for o in side)  # type: ignore[arg-type]
        row = [o for o in side if offset(me.bbox, o.bbox) <= nearest + _ROW_BAND * h]  # type: ignore[arg-type]
        row.sort(key=lambda o: gap(me.bbox, o.bbox, right_to_left))  # type: ignore[arg-type]
        for o in row:  # the label's cells end where the next "Label:" starts ("DATE: 8/10/90  TIME:")
            if is_label(o.text):
                break
            if value_like(o.text, label.colon):
                cells.append(o)
    if cells:
        return " ".join(o.text.strip() for o in cells[:3]), cells[:3], True
    under = below(lines, label.index)
    if under is not None:
        text = under.text.strip()
        short = label.colon or len(text) <= 40  # without a colon, only a short value line belongs to the label
        if short and not is_label(text) and value_like(text, label.colon):
            return text, [under], True
    return None, [], any(not is_label(o.text) for o in side)  # a "Label:" below or beside is another field


def value_mode(lab: Label, lines: list[TextLine], cells: list[TextLine]) -> str:
    """How a label's value is read: "row" (its own line or row), "below", or "none"."""
    me = lines[lab.index].bbox
    if lab.inline or (cells and me is not None and beside(me, cells[0].bbox, layout.rtl(lines[lab.index].text))):  # type: ignore[arg-type]
        return "row"
    return "below" if cells else "none"


def below(lines: list[TextLine], i: int) -> TextLine | None:
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


def offset(a: BBox, b: BBox) -> float:
    return abs((a[1] + a[3]) / 2 - (b[1] + b[3]) / 2)


def beside(a: BBox, b: BBox, right_to_left: bool) -> bool:
    """On the label's row, after it in reading direction. Typed values sit a little above or below a printed
    label's baseline, so the row reaches one label height either way; the nearest row wins (see value)."""
    same = offset(a, b) <= max(a[3] - a[1], 1.0)
    after = b[2] <= a[0] + 4 if right_to_left else b[0] >= a[2] - 4
    return same and after


def gap(a: BBox, b: BBox, right_to_left: bool) -> float:
    return a[0] - b[2] if right_to_left else b[0] - a[2]


def is_label(text: str) -> bool:
    return text.strip().endswith(":")


def label_line(text: str) -> bool:
    return _label_line(text)


def union(boxes: list[BBox]) -> BBox:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
