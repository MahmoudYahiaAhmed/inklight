"""An answer must be connected to what was asked, not merely near it.

Two checks, both cheap and deterministic:

1. **Roles.** "Who sent the letter?" is answered from the letter's own title ("Letter dated … from X addressed
   to Y", in Arabic "موجهة إلى Y من X"), from "From:"/"To:" lines, or from the signature line ("(Signed) X"),
   instead of by whichever name sits nearest to the question's words. OCR damage in the title ("ADDRESSED 10 THE
   SECRElARY-GEKERAL") is tolerated.
2. **Typed answers.** A question that asks for a date, an amount or a count gets an answer only from a sentence
   that holds a value of that type *and* shares the question's specific words ("open debate", "renewal fee").
   The document's own date in its heading does not answer a question about an event. When the chosen sentence
   fails, a better connected one is looked for in the retrieved passages; when none exists, the answer says no
   supporting evidence was found instead of returning the nearest value.

A question with no specific words left ("What is the total?", "What is the date of the letter?") is not
restricted, so the check does not turn into declining.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..extract.values import parse_dates
from ..schemas import Source
from ..textnorm import search_form
from .answer import _stem, expected_kind, narrow, words
from .context import ToolContext
from .unmentioned import _BY_WORD, _GENERIC, _own_types, say_no_evidence

# ---------------------------------------------------------------- roles

_ROLE_QUESTIONS: list[tuple[str, re.Pattern[str]]] = [
    (
        "recipient",
        re.compile(
            r"\bto\s+whom\b|\baddressed\s+to\b|\bwho\s+(?:is|was)\s+(?:the\s+|this\s+|it\s+)?(?:\w+\s+)?(?:addressed|sent)"
            r"\s+to\b|\brecipient\b|\baddressee\b|(?:^|\s)(?:الي من|لمن (?:وجهت|ارسلت)|موجهه الي من|المرسل اليه)",
            re.IGNORECASE,
        ),
    ),
    (
        "sender",
        re.compile(
            r"\bwho\s+(?:sent|wrote|authored)\b|\bwho\s+is\s+(?:the\s+|this\s+|it\s+)?(?:\w+\s+)?from\b"
            r"|\bwhich\s+\w+(?:'s|’s)?(?:\s+\w+){0,2}\s+(?:sent|wrote)\b|\bfrom\s+whom\b|\bsender\b"
            r"|(?:^|\s)(?:من ارسل|من الذي ارسل|من كتب|من اي (?:بعثه|بلد|دوله|جهه)|الجهه المرسله|المرسل(?!\s+اليه))",
            re.IGNORECASE,
        ),
    ),
    ("signer", re.compile(r"\bwho\s+signed\b|\bsignator|(?:^|\s)من (?:وقع|الموقع)", re.IGNORECASE)),
]
_QUALIFIED = re.compile(r"\b(?:for|as|on behalf of)\b|(?:^|\s)(?:عن|بصفته|نيابه)", re.IGNORECASE)

_TO = r"(?:to|t[o0]|1[o0]|10)"
_TITLE_EN = re.compile(
    r"\bfrom\s+(?P<sender>.+?)\s+addre\S*\s+" + _TO + r"\s+(?P<recipient>.+?)\s*$", re.IGNORECASE | re.DOTALL
)
_TITLE_AR = re.compile(r"موجه\S*\s+(?:إلى|الى|إلي|الي)\s+(?P<recipient>.+?)\s+من\s+(?P<sender>.+?)\s*$", re.DOTALL)
_TITLE_START = re.compile(
    r"^\s*(?:identical\s+)?(?:letters?|note\s+verbale)\s+dated\b|^\s*رسال\S*\s+(?:متطابق\S*\s+)?مؤرخ", re.IGNORECASE
)
# A form's "To: X" / "From: X" line: a colon and a short value, so "to: be fair" in prose does not count.
_LABEL_LINE = {
    "recipient": re.compile(
        r"^\s*(?:to|attn|attention)\s*:\s*(?P<v>\S.{0,79})$|^\s*(?:إلى|الى)\s*[:\-]\s*(?P<a>\S.{0,79})$", re.I
    ),
    "sender": re.compile(r"^\s*from\s*:\s*(?P<v>\S.{0,79})$|^\s*من\s*[:\-]\s*(?P<a>\S.{0,79})$", re.IGNORECASE),
}
# A heading line: "Annex", "ANNEX I", "Annex to the letter …", "مرفق الرسالة …"; not "annex)." in the body.
_ANNEX = re.compile(
    r"^\s*(?:annex|enclosure|attachment|مرفق|المرفق)(?:\s+(?:[IVX]+|\d+)|\s+(?:to|of|الرسال|ب)\S*.*)?\s*[:.]?\s*$",
    re.IGNORECASE,
)
_SIGNED_AR = re.compile(r"[(（]\s*توقيع\s*[)）]")
# "(Signed) X", OCR's "(Siqnedd X", "Signed: X", "/s/ X". Not "Signature of the applicant" or "Significant …".
_SIGNED = re.compile(
    r"^\s*\(\s*(?:signed|s[il1][qg]ne?d\w*)\s*[)\]}]?\s*(?P<v>\S.{0,79})$"
    r"|^\s*signed\s*:\s*(?P<c>\S.{0,79})$|^\s*(?:by:\s*)?/s/\s*(?P<s>\S.{0,79})$",
    re.IGNORECASE,
)
# A role question is about a document: "who sent the letter", "who is the fax from", "من أرسل الرسالة".
_ROLE_OBJECT = re.compile(
    r"\b(?:letters?|note|memo|memorandum|fax|form|e-?mail|message|document|communication|it|this)\b"
    r"|(?:^|\s)(?:ال)?(?:رساله|رسالتين|رسالتان|خطاب|مذكره|وثيقه|فاكس|نموذج)(?:\s|$|؟)",
    re.IGNORECASE,
)


def role_asked(question: str) -> str | None:
    """ "sender", "recipient" or "signer" when that is what the question asks for, without a qualifier."""
    q = search_form(question).lower()
    if not _ROLE_OBJECT.search(q):
        return None  # "which country sent troops?" asks about the content, not about who sent a document
    for role, pattern in _ROLE_QUESTIONS:
        if pattern.search(q):
            if role == "signer" and _QUALIFIED.search(q):
                return None  # "who signed for Netzee?" names a party: the ordinary answer path handles it
            return role
    return None


@dataclass(frozen=True)
class _Found:
    doc_id: str
    page: int
    value: str
    line: str
    annex: bool = False  # found only after "Annex": it signs the annex, not the letter


def _find_role(ctx: ToolContext, doc_id: str, role: str) -> _Found | None:
    in_annex = False
    for page in ctx.pages(doc_id)[:3]:
        lines = [ln.text.strip() for ln in page.lines] or [ln.strip() for ln in page.markdown.splitlines()]
        if role == "signer":
            for ln in lines:
                in_annex = in_annex or bool(_ANNEX.match(ln))
                m = _SIGNED.match(ln)
                if m:
                    value = m.group("v") or m.group("c") or m.group("s")
                    return _Found(doc_id, page.number, value.strip(), ln, in_annex)
                if _SIGNED_AR.search(ln):  # right-to-left OCR may put "(توقيع)" after the name
                    name = _SIGNED_AR.sub(" ", ln).strip(" ()")
                    if name:
                        return _Found(doc_id, page.number, name, ln, in_annex)
            continue
        for k, ln in enumerate(lines[:40]):
            if _TITLE_START.search(ln) and page.number == 1:
                title = _title_from(lines[k : k + 5])
                for pattern in (_TITLE_AR, _TITLE_EN):
                    m = pattern.search(title)
                    if m and m.group(role).strip():
                        return _Found(doc_id, page.number, _trim(m.group(role)), title)
            m = _LABEL_LINE[role].match(ln)
            if m and k < 25:
                return _Found(doc_id, page.number, (m.group("v") or m.group("a")).strip(), ln)
    return None


# Matched against search_form(line), so OCR's "أتشرِف" reads as "اتشرف".
_BODY_START = re.compile(
    r"^(?:I have the honour|I have the honor|On instructions|Upon instructions|With reference|Further to|"
    r"I wish to|I am writing|يشرفني|اتشرف|لي الشرف|بناء|اشاره|بالاشاره|اكتب)",
    re.IGNORECASE,
)


def _body_starts(line: str) -> bool:
    return bool(_BODY_START.match(search_form(line)))


def _title_from(lines: list[str]) -> str:
    """A heading's lines, up to the first line of the letter's body or a blank line."""
    kept: list[str] = []
    for ln in lines:
        if not ln or (kept and _body_starts(ln)):
            break
        kept.append(ln)
    return " ".join(kept)


def _trim(value: str) -> str:
    """The party named in a title, without what follows it on the next line ("I have the honour …")."""
    value = re.split(r"\s{2,}|\n|(?<=[a-z؀-ۿ])\s+(?=I have the honour|يشرفني)", value)[0]
    return value.strip(" ,;:")


def role_answer(ctx: ToolContext, question: str) -> bool:
    """Answer a sender / recipient / signer question from the document's own layout, if it states one."""
    role = role_asked(question)
    if role is None:
        return False
    ordered = list(dict.fromkeys(h.source.doc_id for h in ctx.scratch.hits)) or ctx.scratch.doc_ids
    founds = [f for f in (_find_role(ctx, d, role) for d in ordered[:3]) if f is not None and not f.annex]
    if len({f.value for f in founds}) > 1:  # several documents in scope, each with its own sender
        s = ctx.scratch
        infos = {f.doc_id: ctx.library.get(f.doc_id) for f in founds}
        names = {d: info.name if info else d for d, info in infos.items()}
        s.answer = f"The {role} differs by document:\n" + "\n".join(f"- {names[f.doc_id]}: {f.value}" for f in founds)
        s.sources = [_source_for(ctx, f) for f in founds]
        s.confidence = 0.8
        s.notes.append(f"answer: the {role} of each document, as each states it ({_where(role)})")
        return True
    for doc_id in ordered[:3]:
        found = _find_role(ctx, doc_id, role)
        if found is None:
            continue
        s = ctx.scratch
        s.sources = [_source_for(ctx, found)]
        if found.annex:
            s.answer = (
                "The letter's own signature was not found in the processed text. "
                f"The annex is signed by {found.value}.\n\nEvidence: “{found.line}”"
            )
            s.confidence = 0.25
            s.warn("Low confidence: only the annex's signature was found; the letter's own may have been lost by OCR.")
            s.notes.append("answer: only an annex signature was found")
            return True
        s.answer = f"{found.value}\n\nEvidence: “{found.line}”"
        s.confidence = 0.8
        s.notes.append(f"answer: the {role} as the document states it ({_where(role)})")
        return True
    return False


def _where(role: str) -> str:
    return "signature line" if role == "signer" else "title or From/To line"


def _source_for(ctx: ToolContext, found: _Found) -> Source:
    for _, src in ctx.library.store.chunks_for([found.doc_id]):
        if src.page == found.page and found.value[:30] in src.excerpt:
            return narrow(ctx, src, found.value)
    doc = ctx.library.get(found.doc_id)
    return Source(
        doc_id=found.doc_id,
        path=doc.path if doc else "",
        name=doc.name if doc else "",
        page=found.page,
        excerpt=found.line,
    )


# ---------------------------------------------------------------- typed answers

_KIND_WORDS = {
    _stem(w)
    for w in words(
        "date when what which day time year month how many much amount number count total value cost price sum "
        "متي تاريخ موعد يوم كم عدد مبلغ قيمه اجمالي"
    )
}
_KIND_NAMES = {"date": "the date", "money": "the amount", "number": "the number"}


_MONTHS = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?"
    r"|nov(?:ember)?|dec(?:ember)?|يناير|فبراير|مارس|أبريل|ابريل|مايو|يونيو|يوليو|أغسطس|اغسطس|سبتمبر|أكتوبر|اكتوبر"
    r"|نوفمبر|ديسمبر|كانون|شباط|آذار|اذار|نيسان|أيار|ايار|حزيران|تموز|آب|أيلول|ايلول|تشرين"
)
# "5 June", "June 5", "٥ يونيو": a day and a month, without a year, still dates something.
_DAY_MONTH = re.compile(
    rf"(?<!\w)[0-9٠-٩]{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{_MONTHS})(?!\w)|(?<!\w)(?:{_MONTHS})\.?\s+[0-9٠-٩]{{1,2}}(?!\d)",
    re.IGNORECASE,
)


# An amount: cents ("65.00"), grouped thousands ("5,000", "5.000"), or a currency beside a number. A bare
# year or phone number ("1981") is not one.
_AMOUNT = re.compile(
    r"(?<![\d.,])\d{1,3}(?:[.,\s]\d{3})*[.,]\d{2}(?!\d)|(?<![\d.,])\d{1,3}(?:[.,]\d{3})+(?![\d.,])"
    r"|[$€£¥]\s*\d|\d\s*[$€£¥]|\b(?:EGP|LE|L\.E|USD|EUR|SAR|AED|QAR|KWD)\b"
    r"|ر\.س|ج\.م|د\.إ|جنيه|ريال|ريل|درهم|دينار|دولار",
    re.IGNORECASE,
)


def _digits(text: str) -> str:
    """Arabic-Indic digits and separators as ASCII ("٥٬٠٠٠٫٥٠" -> "5,000.50"), for value checks only."""
    return "".join(str(int(c)) if c.isdigit() and not c.isascii() else c for c in text).translate(
        {ord("٫"): ".", ord("٬"): ","}
    )


def _number_after(unit: str, keys: set[str]) -> bool:
    """A whole number right after one of the question's words: "Renewal fee: 500", "الأجرة 5000"."""
    tokens = re.findall(r"[^\W_]+|\d[\d,.]*", unit)
    for k, tok in enumerate(tokens):
        if tok[0].isdigit() and any(_key(t.lower()) in keys for t in tokens[max(0, k - 3) : k] if not t[0].isdigit()):
            return True
    return False


def _has_kind(kind: str, text: str) -> bool:
    if kind == "date":
        return bool(parse_dates(text)) or bool(_DAY_MONTH.search(text))
    if kind == "money":
        return bool(_AMOUNT.search(text))
    return bool(
        re.search(
            r"\d|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|forty|"
            r"hundred|thousand|million|billion)\b",
            text,
            re.IGNORECASE,
        )
    )


def _key(word: str) -> str:
    """A word's stem, or the name of its synonym group ("paid" and "payment" match; so do "rent" and "إيجار")."""
    stem = _stem(word)
    group = _BY_WORD.get(stem)
    return group[0] if group else stem


def _keys(text: str) -> set[str]:
    return {_key(w) for w in words(text)}


# Words naming a document itself: "the date of the letter" asks for the document's own date, not an event's.
_DOCUMENT_NOUNS = {
    _stem(w)
    for w in words(
        "letter letters document documents agreement contract report form certificate invoice receipt note memo fax "
        "communication statement resolution "
        "رساله رسالتين الرساله الرسالتان خطاب الوثيقه وثيقه المستند العقد عقد التقرير تقرير النموذج الشهاده الفاتوره"
    )
}


def _anchors(ctx: ToolContext, question: str) -> set[str]:
    """The question's specific words: not generic, not the kind of value asked, not a word for the document."""
    skip = _GENERIC | _KIND_WORDS | _DOCUMENT_NOUNS | _own_types(ctx)
    return {_key(w) for w in words(question) if _stem(w) not in skip and len(w) > 2}


def _is_heading(sentence: str) -> bool:
    """The document's own title or distribution line: its date is the document's, not an event's."""
    return bool(_TITLE_START.search(sentence) or re.search(r"\bdistr\b|\bdistribution\b", sentence, re.IGNORECASE))


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


_SENTENCE_END = re.compile(r"(?<=[.!?؟؛])\s+(?=[\"'(A-Z0-9؀-ۿ])")
_WRAPS = 35  # a line at least this long that does not end a sentence continues on the next line (wrapped prose)


def _units(excerpt: str) -> list[str]:
    """The passage as sentences. Prose wrapped over several PDF lines is joined back; short lines (receipts,
    forms: one fact per line) and headings stay on their own."""
    blocks: list[list[str]] = []
    for ln in (x.strip() for x in excerpt.splitlines()):
        if not ln:
            blocks.append([])
            continue
        prev = blocks[-1][-1] if blocks and blocks[-1] else ""
        wraps = len(prev) >= _WRAPS and not re.search(r"[.!?؟؛:]$", prev)
        if wraps and not (_body_starts(ln) or _TITLE_START.search(ln) or _TITLE_START.search(prev)):
            blocks[-1].append(ln)
        else:
            blocks.append([ln])
    units = [u.strip() for b in blocks if b for u in _SENTENCE_END.split(" ".join(b))]
    # Receipts and forms put a label and its value on neighbouring short lines ("Cash Tendered" / "200.00").
    short = [b[0] for b in blocks if len(b) == 1 and len(b[0]) < _WRAPS]
    units += [f"{a} {b}" for a, b in zip(short, short[1:], strict=False)]
    return list(dict.fromkeys(u for u in units if u))


# "Total (incl Tax)", "prices include VAT": the word names what the amount contains, not what it is.
_QUALIFIED_WORD = re.compile(
    r"\b(?:incl\.?|including|inclusive\s+of|include[sd]?|excl\.?|excluding|exclusive\s+of|w/o)\s*\(?\s*[^\W\d_]+"
    r"|(?:شامل[ةه]?|غير\s+شامل[ةه]?|يشمل|تشمل)\s+[^\W\d_]+"
    # "VAT-Inclusive", "VAT inclusive 70.00": the qualifier written after the word
    r"|[^\W\d_]+[\s-]*(?:inclusive|incl\.?|included|exclusive|excl\.?)(?![^\W\d_])(?!\s*\(?\s*[^\W\d_])",
    re.IGNORECASE,
)


def check_typed_answer(ctx: ToolContext, question: str) -> str | None:
    """Keep, replace or decline the chosen answer to a date / amount / count question. Returns a note or None."""
    kind = expected_kind(question)
    s = ctx.scratch
    if kind not in _KIND_NAMES or not s.answer:
        return None
    anchors = _anchors(ctx, question)
    pool: list[tuple[Source, str, str]] = []  # (source, sentence, the sentence before it)
    for h in s.hits[:8]:
        units = _units(h.source.excerpt)
        pool += [(h.source, u, units[k - 1] if k else "") for k, u in enumerate(units)]
    vocab = set().union(*(_keys(unit) for _, unit, _ in pool)) if pool else set()
    present = anchors & vocab
    if not present:
        return None  # nothing specific to connect to ("What is the total?"): the answer is left as it is

    def connected(unit: str, before: str = "") -> float:
        """0 when the sentence cannot answer; otherwise the share of the question's specific words it holds, with
        the sentence before it ("…a civilian bus. … 54 others were injured" answers "injured in the attack on the
        bus"). The sentence itself must hold at least one of them, and a heading lends it none."""
        unit = _digits(unit)
        typed = _has_kind(kind, unit) or (kind == "money" and _number_after(unit, present))
        if not typed or (kind == "date" and _is_heading(unit)):
            return 0.0
        own = present & _keys(_QUALIFIED_WORD.sub(" ", unit))
        if not own:
            return 0.0
        context = set() if not before or _is_heading(before) else _keys(_QUALIFIED_WORD.sub(" ", _digits(before)))
        share = len(own | (present & context)) / len(present)
        return share if share >= 0.5 else 0.0

    head = s.answer.split("\n\nEvidence:")[0].strip()
    if head.startswith("The closest passage is:"):
        head = ""  # a whole passage is not a chosen value
    needles = _needles(head)
    if (
        needles
        and _has_kind(kind, head)
        and any(n in _flat(u) and connected(u, b) > 0 for n in needles for _, u, b in pool)
    ):
        return None
    ranked = sorted(
        ((connected(u, b), -len(u), -i, src, u) for i, (src, u, b) in enumerate(pool) if connected(u, b) > 0),
        key=lambda t: t[:3],
        reverse=True,
    )
    if ranked:
        _, _, _, src, unit = ranked[0]
        s.answer = unit
        s.sources = [narrow(ctx, src, unit, question)]
        s.confidence = min(s.confidence or 0.6, 0.6)
        return f"answer replaced: the first answer was not connected to {', '.join(sorted(present))}"
    what = f"{_KIND_NAMES[kind]} asked about ({' '.join(_as_written(question, present))})"
    say_no_evidence(
        ctx,
        what,
        f"no retrieved sentence holds {_KIND_NAMES[kind][4:]} together with the question's words "
        f"({', '.join(sorted(present))}); nearby values were not used",
    )
    return "typed answer declined"


def _needles(head: str) -> list[str]:
    """How to find the chosen value in the passages: whole, and by its first line when the reader's span ran
    across two OCR lines ("8.60" then "61.40")."""
    if not head:
        return []
    lines = [ln.strip() for ln in head.splitlines() if ln.strip()]
    return list(dict.fromkeys([_flat(head)[:60]] + ([_flat(lines[0])[:60]] if len(lines) > 1 else [])))


def _as_written(question: str, keys: set[str]) -> list[str]:
    return [w for w in re.findall(r"[^\W_]+", question) if _key(search_form(w).lower()) in keys]
