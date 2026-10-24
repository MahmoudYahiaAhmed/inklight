"""Is a PDF text layer's Arabic usable?

Indra already refuses a text layer with a broken font map, or one whose codes are Latin while the page shows
another script. It cannot see a layer whose codes are Arabic letters, but the wrong ones: a font that maps the
lam-alef ligature and positional forms badly. The UN's Arabic PDFs are like this ("األمم" for "الأمم",
"امرساااااا" for "المرسلة"). The text looks Arabic, but searching and reading it fails.

Two signatures are almost absent from correct Arabic and frequent in these layers:
- a word starting alef + hamza-alef + lam ("األ", "اإل", "اآل"): a lam-alef ligature written out in the wrong
  order. Correct text has "الأ";
- two alefs in a row inside a word ("اا").

Measured per page: 0.000 on every page of two Arabic Wikipedia PDFs, and at least 0.025 on every page of four
UN Arabic PDFs.
"""

from __future__ import annotations

import re

_ARABIC_LETTER = re.compile(r"[ء-ي]")
_SPLIT_LAM_ALEF = re.compile(r"^ا[أإآ]ل")
MIN_ARABIC_WORDS = 20
BROKEN_SHARE = 0.015


def broken_arabic_share(text: str) -> float | None:
    """Share of Arabic words carrying a broken-layer signature, or None when there are too few to judge."""
    words = [w for w in text.split() if _ARABIC_LETTER.search(w)]
    if len(words) < MIN_ARABIC_WORDS:
        return None
    bad = sum(bool(_SPLIT_LAM_ALEF.match(w)) or "اا" in w for w in words)
    return bad / len(words)


def layer_is_broken(text: str) -> bool:
    share = broken_arabic_share(text)
    return share is not None and share >= BROKEN_SHARE
