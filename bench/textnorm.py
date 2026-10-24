"""Comparison keys for names and identifiers, in any script.

``fold`` keeps every letter, digit and combining mark that is part of a letter, so different names in
Arabic, Devanagari, CJK and other scripts stay different. It removes only what does not change a name:
case, punctuation, spacing, the Arabic tatweel (kashida, a stretching stroke) and the optional Arabic short
vowel marks (harakat). Unicode digits become ASCII, so "INV-١٢٣" and "INV-123" compare equal.

(A standalone copy lives in bench/textnorm.py, because the evaluation harness also runs older builds.)
"""

from __future__ import annotations

import unicodedata

_TATWEEL = "ـ"
_ARABIC_HARAKAT = {chr(c) for c in range(0x064B, 0x0660)} | {"ٰ"}


def fold(text: object, keep: str = "") -> str:
    out = []
    for ch in unicodedata.normalize("NFKC", str(text)).casefold():
        if ch.isdigit():
            try:
                out.append(str(unicodedata.decimal(ch)))
                continue
            except ValueError:
                pass
        if ch == _TATWEEL or ch in _ARABIC_HARAKAT:
            continue
        if ch.isalnum() or unicodedata.category(ch).startswith("M") or ch in keep:
            out.append(ch)
    return "".join(out)


_SEARCH_LETTERS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه"})


def search_form(text: str) -> str:
    """The text as the search index stores it, and as queries are matched against it.

    Arabic is written with optional marks and interchangeable letter forms: "المُستحق" and "المستحق", "إلى" and
    "الى", "القاهرة" and "القاهره". Harakat and tatweel are removed, alef forms (أ إ آ ٱ) become ا, alef maqsura
    becomes ي, ta marbuta becomes ه, and every Unicode digit becomes ASCII. Everything else, including spacing,
    punctuation and Latin text, is left for the tokenizer. Excerpts shown to users come from the original text.
    """
    out = []
    for ch in unicodedata.normalize("NFKC", text):
        if ch == _TATWEEL or ch in _ARABIC_HARAKAT:
            continue
        if ch.isdigit() and not ch.isascii():
            try:
                out.append(str(unicodedata.decimal(ch)))
                continue
            except ValueError:
                pass
        out.append(ch)
    return "".join(out).translate(_SEARCH_LETTERS)
