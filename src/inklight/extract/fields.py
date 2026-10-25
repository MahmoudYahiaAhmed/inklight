"""Typed field extraction with provenance.

Fields are found by label ("Total: $5,616.00", "Invoice Date 2026-03-14",
or a label line followed by its value) and parsed by type. Every value keeps
the page, line box and OCR confidence it came from. Inferred values (no label
found) are marked with lower confidence and a warning, never as verified.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from ..errors import InputRejected
from ..schemas import BBox, DocumentInfo, ExtractedValue, PageContent, Record, Source
from . import layout
from .amounts import PAYMENT, Reread, check_amounts
from .values import EMAIL_RE, PHONE_RE, all_money, parse_dates, parse_money, parse_number

FieldType = Literal["text", "money", "number", "date", "email", "phone", "id"]


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: FieldType = "text"
    labels: tuple[str, ...] = ()
    description: str = ""
    required: bool = False

    def all_labels(self) -> tuple[str, ...]:
        base = self.labels or (self.name.replace("_", " "),)
        return tuple(sorted(set(base), key=len, reverse=True))


CATALOG: dict[str, FieldSpec] = {
    s.name: s
    for s in [
        FieldSpec(
            "invoice_number",
            "id",
            (
                "invoice number",
                "invoice no",
                "invoice #",
                "invoice id",
                "inv no",
                "inv #",
                "bill number",
                "invoice",
                "رقم الفاتورة",
            ),
            "Invoice identifier",
        ),
        FieldSpec(
            "date",
            "date",
            (
                "invoice date",
                "date of issue",
                "issue date",
                "issued on",
                "issued",
                "letter dated",
                "letters dated",
                "date",
                "تاريخ الفاتورة",
                "تاريخ الإصدار",
                "رسالة مؤرخة",
                "التاريخ",
            ),  # fmt: skip
            "Document or invoice date",
        ),
        FieldSpec(
            "due_date", "date", ("payment due", "due date", "due by", "due on", "تاريخ الاستحقاق"), "Payment due date"
        ),
        FieldSpec(
            "vendor",
            "text",
            ("vendor", "supplier", "seller", "billed by", "from", "company", "البائع", "المورد"),
            "Issuer of the document",
        ),
        FieldSpec(
            "customer",
            "text",
            (
                "customer name",
                "bill to",
                "billed to",
                "customer",
                "client",
                "sold to",
                "ship to",
                "name",
                "المشتري",
                "العميل",
            ),
            "Customer or recipient",
        ),
        FieldSpec(
            "subtotal",
            "money",
            (
                "subtotal",
                "sub-total",
                "sub total",
                "net amount",
                "net worth",
                "net total",
                "المجموع قبل الضريبة",
                "المجموع الفرعي",
            ),
            "Amount before tax",
        ),
        FieldSpec(
            "tax",
            "money",
            (
                "total tax",
                "sales tax",
                "tax amount",
                "vat",
                "gst",
                "hst",
                "tax",
                "pajak",
                "ppn",
                "pb1",
                "p.rest",
                "p. rest",
                "ضريبة القيمة المضافة",
                "الضريبة",
            ),
            "Tax amount",
        ),
        FieldSpec(
            "total",
            "money",
            (
                "grand total",
                "total due",
                "amount due",
                "balance due",
                "total amount",
                "amount payable",
                "gross worth",
                "gross amount",
                "total",
                "المبلغ الإجمالي",
                "الإجمالي",
                "الاجمالي",
                "المجموع",
            ),
            "Total amount",
        ),
        FieldSpec(
            "effective_date",
            "date",
            ("effective date", "commencement date", "start date", "effective as of"),
            "Contract start",
        ),
        FieldSpec(
            "expiry_date",
            "date",
            (
                "expiration date",
                "expiry date",
                "termination date",
                "expires on",
                "expires",
                "valid until",
                "end date",
                "term ends",
                "renewal date",
            ),
            "Contract or document expiry",
        ),
        FieldSpec(
            "contract_value",
            "money",
            ("contract value", "total value", "fees", "fee", "consideration"),
            "Contract value",
        ),
        FieldSpec("email", "email", ("email", "e-mail"), "Email address"),
        FieldSpec("phone", "phone", ("phone", "tel", "telephone", "mobile"), "Phone number"),
        FieldSpec("po_number", "id", ("purchase order", "po number", "po #", "po no"), "Purchase order"),
        FieldSpec("account_number", "id", ("account number", "account no", "acct no", "account #"), "Account id"),
    ]
}

# Words people use for catalog fields.
ALIASES: dict[str, str] = {
    "invoice number": "invoice_number",
    "invoice no": "invoice_number",
    "invoice id": "invoice_number",
    "number": "invoice_number",
    "invoice date": "date",
    "issue date": "date",
    "dates": "date",
    "due": "due_date",
    "due date": "due_date",
    "supplier": "vendor",
    "seller": "vendor",
    "vendors": "vendor",
    "company": "vendor",
    "issuer": "vendor",
    "customer name": "customer",
    "customer names": "customer",
    "customers": "customer",
    "client": "customer",
    "clients": "customer",
    "client name": "customer",
    "name": "customer",
    "names": "customer",
    "amount": "total",
    "total amount": "total",
    "totals": "total",
    "grand total": "total",
    "amount due": "total",
    "price": "total",
    "vat": "tax",
    "gst": "tax",
    "taxes": "tax",
    "sales tax": "tax",
    "net": "subtotal",
    "expiry": "expiry_date",
    "expiration": "expiry_date",
    "expiration date": "expiry_date",
    "expiry date": "expiry_date",
    "end date": "expiry_date",
    "expires": "expiry_date",
    "start date": "effective_date",
    "effective date": "effective_date",
    "emails": "email",
    "phone number": "phone",
    "phones": "phone",
    "po": "po_number",
    "purchase order": "po_number",
    "value": "contract_value",
    "contract value": "contract_value",
}

_SEP = r"\s*(?:[:#=]|no\.?|number)?\s*[:#]?\s*"
_TEXT_GAP = 6.0  # a name further right than this many line heights belongs to another column
_TABLE_TEXT_GAP = 25.0  # ... unless the row holds only the "label:" and that one value
_TITLE_DATE = re.compile(r"letters? dated|رسالة مؤرخة", re.IGNORECASE)  # a document's own date only in its title
# Words that make the next label a qualifier: "incl. Tax", "excluding VAT", "prices include VAT", "شاملة ضريبة".
_QUALIFIER = re.compile(
    r"(?:\bincl\.?|\binc\.|\bincluding|\binclusive\s+of|\binclude[sd]?|\bexcl\.?|\bexcluding|\bexclusive\s+of"
    r"|\bw/o|\bplus|شامل[ةه]?|شاملة\s+ل|غير\s+شامل[ةه]?|بدون|يشمل|تشمل)\s*\(?\s*$",
    re.IGNORECASE,
)


def resolve_field(word: str) -> FieldSpec:
    """Map a user's word ("vendor", "VAT", "customer names") to a field spec."""
    key = re.sub(r"\s+", " ", word.strip().lower().replace("_", " "))
    key = re.sub(r"^(the|all|every|each)\s+", "", key)
    name = ALIASES.get(key) or key.replace(" ", "_")
    if name in CATALOG:
        return CATALOG[name]
    if name.endswith("s") and name[:-1] in CATALOG:
        return CATALOG[name[:-1]]
    return FieldSpec(name=re.sub(r"\W+", "_", name).strip("_") or "field", labels=(key,))


# ---------------------------------------------------------------- schema files


def load_schema(path: str | Path) -> list[FieldSpec]:
    """Read a schema: JSON Schema ``properties``, ``{"fields": [...]}`` or ``{"name": "type"}``."""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InputRejected(f"Cannot read schema {p.name}: {exc}") from exc
    return schema_from_dict(data)


_JSON_TYPES: dict[str, FieldType] = {"string": "text", "number": "number", "integer": "number"}


def schema_from_dict(data: Any) -> list[FieldSpec]:
    specs: list[FieldSpec] = []
    if isinstance(data, dict) and isinstance(data.get("properties"), dict):
        required = set(data.get("required", []))
        for name, prop in data["properties"].items():
            ftype = prop.get("x-type") or _JSON_TYPES.get(prop.get("type", "string"), "text")
            if prop.get("format") == "date":
                ftype = "date"
            specs.append(_spec(name, ftype, prop.get("x-labels"), prop.get("description", ""), name in required))
    elif isinstance(data, dict) and isinstance(data.get("fields"), list):
        for item in data["fields"]:
            if not isinstance(item, dict) or "name" not in item:
                raise InputRejected("Each schema field needs a 'name'")
            specs.append(
                _spec(
                    item["name"],
                    item.get("type", "text"),
                    item.get("labels"),
                    item.get("description", ""),
                    bool(item.get("required")),
                )
            )
    elif isinstance(data, dict) and all(isinstance(v, str) for v in data.values()):
        specs = [_spec(name, ftype, None, "", False) for name, ftype in data.items()]
    else:
        raise InputRejected("Unrecognised schema format; see docs/extraction.md")
    if not specs:
        raise InputRejected("Schema defines no fields")
    return specs


def _spec(name: str, ftype: str, labels: Any, description: str, required: bool) -> FieldSpec:
    if ftype not in ("text", "money", "number", "date", "email", "phone", "id"):
        raise InputRejected(f"Field {name!r}: unknown type {ftype!r}")
    known = CATALOG.get(ALIASES.get(name.lower().replace("_", " "), name))
    label_tuple = tuple(labels) if labels else (known.labels if known else ())
    return FieldSpec(
        name=name,
        type=ftype,  # type: ignore[arg-type]  # validated just above
        labels=label_tuple,
        description=description,
        required=required,
    )


# ---------------------------------------------------------------- extraction


@dataclass
class _Line:
    page: int
    text: str
    bbox: BBox | None
    conf: float | None


@dataclass
class _Candidate:
    value: Any
    raw: str
    line: _Line
    quality: float
    method: str
    extra: dict[str, Any] = field(default_factory=dict)


def _lines(pages: list[PageContent]) -> list[_Line]:
    out: list[_Line] = []
    for p in pages:
        if p.lines:
            out.extend(_Line(p.number, ln.text, ln.bbox, ln.conf) for ln in p.lines if ln.text.strip())
        else:
            out.extend(_Line(p.number, b.text, b.bbox, b.conf) for b in p.blocks if b.text.strip())
    return out


def parse_typed(ftype: FieldType, raw: str, day_first: bool = False) -> tuple[Any, str] | None:
    """Parse ``raw`` as ``ftype``; return (value, matched text) or None."""
    raw = raw.strip()
    if not raw:
        return None
    if ftype == "money":
        money = parse_money(raw)
        return (money[0], raw) if money else None
    if ftype == "number":
        m = re.search(r"-?\d[\d,. ]*", raw)
        num = parse_number(m.group(0)) if m else None
        return (num, m.group(0)) if num is not None and m else None
    if ftype == "date":
        hits = parse_dates(raw, day_first)
        return (hits[0][0], hits[0][1]) if hits else None
    if ftype == "email":
        m = EMAIL_RE.search(raw)
        return (m.group(0), m.group(0)) if m else None
    if ftype == "phone":
        m = PHONE_RE.search(raw)
        return (m.group(0).strip(), m.group(0)) if m else None
    if ftype == "id":
        m = re.search(r"[A-Z0-9][A-Z0-9\-/_.]{0,40}", raw, re.IGNORECASE)
        if not m or not re.search(r"\d", m.group(0)):
            return None
        return (m.group(0).rstrip("."), m.group(0))
    text = re.split(r"\s{3,}", raw)[0].strip(" :-")
    return (text, text) if 1 < len(text) <= 160 else None


def _label_regex(specs: list[FieldSpec]) -> list[tuple[re.Pattern[str], FieldSpec, str]]:
    pairs = [(label, spec) for spec in specs for label in spec.all_labels()]
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return [
        (re.compile(rf"(?<![\w-]){re.escape(label)}(?![\w-]){_SEP}", re.IGNORECASE), spec, label)
        for label, spec in pairs
    ]


def _find_candidates(
    lines: list[_Line], specs: list[FieldSpec], day_first: bool = False, doc_type: str | None = None
) -> dict[str, list[_Candidate]]:
    # Claim labels of the whole catalog too, so "Due Date" is never read as "Date"
    # even when only "date" was requested; only requested fields are recorded.
    wanted = {s.name for s in specs}
    others = [s for name, s in CATALOG.items() if name not in wanted]
    patterns = _label_regex(specs + others)
    found: dict[str, list[_Candidate]] = {s.name: [] for s in specs}

    def is_label_line(text: str) -> bool:
        return any(p.match(text.strip()) for p, _, _ in patterns)

    def header_field(text: str) -> str | None:
        """The field a column title names ("Gross worth" -> total), longest label first."""
        return next((spec.name for p, spec, _ in patterns if p.match(text.strip())), None)

    for i, line in enumerate(lines):
        # Claim label spans longest-first so "Subtotal" never also counts as "Total".
        claimed: list[tuple[int, int, FieldSpec]] = []
        for pattern, spec, _label in patterns:
            for m in pattern.finditer(line.text):
                if any(m.start() < e and s < m.end() for s, e, _ in claimed):
                    continue
                # Free-text labels mid-sentence ("... from the ...") are not field labels.
                if spec.type == "text" and m.start() > 0 and ":" not in m.group(0):
                    continue
                # A bare one-word label like "Invoice" only counts with an explicit ':' or '#'.
                if _label == "invoice" and not re.search(r"[:#]", m.group(0)):
                    continue
                # "Total (incl Tax) 65.00", "Prices include VAT": a qualifier of another amount, not a label.
                if _QUALIFIER.search(line.text[: m.start()]):
                    continue
                claimed.append((m.start(), m.end(), spec))
        claimed.sort(key=lambda c: c[0])
        for k, (_start, end, spec) in enumerate(claimed):
            if spec.name not in wanted:
                continue
            stop = claimed[k + 1][0] if k + 1 < len(claimed) else len(line.text)
            if spec.name in ("total", "subtotal") and PAYMENT.search(line.text[_start:stop]):
                continue  # "Total Tendered 210.00", "Total paid by card": money handed over, not the cost
            title_date = _TITLE_DATE.search(line.text[_start:stop])
            if (
                spec.name == "date"
                and title_date
                and (doc_type != "letter" or line.page != 1 or i > 15 or line.text[:_start].strip())
            ):
                # A letter's own "Letter dated …" starts its title line. In a report ("has received a letter
                # dated 13 February"), or anywhere else, it dates another document.
                continue
            tail = line.text[end:stop]
            parsed = parse_typed(spec.type, tail, day_first)
            quality = 1.0 if line.text[:end].rstrip().endswith((":", "#")) else 0.9
            # A label alone on its line, or followed by no value of its type ("Pajak Resto", "Tax 10%"),
            # has its value elsewhere.
            if parsed is None and (not tail.strip() or spec.type != "text"):
                for name, cand in _value_elsewhere(lines, i, spec, day_first, is_label_line, header_field):
                    if name in found:
                        found[name].append(cand)
                continue
            if parsed is not None:
                found[spec.name].append(_Candidate(parsed[0], parsed[1], line, quality, "label"))
    return found


def _value_elsewhere(
    lines: list[_Line],
    i: int,
    spec: FieldSpec,
    day_first: bool,
    is_label: Callable[[str], bool],
    header_field: Callable[[str], str | None],
) -> list[tuple[str, _Candidate]]:
    """Values for a label that stands alone: beside it on its row, else under it in its column.

    A summary row ("Total  2 205,34  220,53  2 425,87") can hold several fields at once; each
    value whose column title names a field ("Net worth", "VAT", "Gross worth") is returned for it.
    """
    line = lines[i]
    if line.bbox is None:
        # No geometry: the next line in reading order, unless that line is itself another label.
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if nxt is None or nxt.page != line.page or is_label(nxt.text):
            return []
        parsed = parse_typed(spec.type, nxt.text, day_first)
        return [(spec.name, _Candidate(parsed[0], parsed[1], nxt, 0.8, "label-next-line"))] if parsed else []
    row = [j for j in layout.row_after(lines, i) if not is_label(lines[j].text)]
    if spec.type == "text":  # a name belongs to its label only when it sits close by
        rtl = layout.rtl(line.text)
        # A two-cell row ("label: | value") pairs its cells at any distance; with more cells, only a close one.
        limit = _TABLE_TEXT_GAP if len(row) == 1 and line.text.rstrip().endswith(":") else _TEXT_GAP
        row = [j for j in row if layout.gap_after(line.bbox, lines[j].bbox, rtl) <= limit][:1]  # type: ignore[arg-type]
    hits = [(j, p) for j, text in _row_cells(lines, row) if (p := _cell_value(spec.type, text, day_first)) is not None]
    if len(hits) == 1:
        j, (value, raw) = hits[0]
        return [(spec.name, _Candidate(value, raw, lines[j], 0.9, "label-row"))]
    if len(hits) > 1:
        titled: dict[str, list[tuple[int, tuple[Any, str]]]] = {}
        for j, p in hits:
            h = layout.header_above(lines, j, is_label)
            name = header_field(lines[h].text) if h is not None else None
            if name:
                titled.setdefault(name, []).append((j, p))
        out = [
            (name, _Candidate(p[0], p[1], lines[j], 0.85, "label-row-column"))
            for name, items in titled.items()
            if len(items) == 1
            for j, p in items
        ]
        if not any(name == spec.name for name, _ in out):
            j, (value, raw) = hits[-1]
            note = f"{len(hits)} values on the {line.text.strip()!r} row and no column title; took the last"
            out.append((spec.name, _Candidate(value, raw, lines[j], 0.5, "label-row", {"warning": note})))
        return out
    under = layout.below(lines, i)
    if under is None or is_label(lines[under].text):
        return []
    parsed = _cell_value(spec.type, lines[under].text, day_first)
    return [(spec.name, _Candidate(parsed[0], parsed[1], lines[under], 0.8, "label-below"))] if parsed else []


_SPACE_GROUPED = re.compile(r"\d{1,3}(?: \d{3})+(?:[.,]\d{2})?")


def _row_cells(lines: list[_Line], row: list[int]) -> list[tuple[int, str]]:
    """Row cells left to right, rejoining an amount OCR split into groups ("177" "870" -> "177 870")."""
    cells: list[tuple[int, str]] = []
    for j in row:
        text = lines[j].text.strip()
        if cells and re.fullmatch(r"\d{3}(?:[.,]\d{2})?", text) and re.fullmatch(r"[\d ]+", cells[-1][1]):
            prev = lines[cells[-1][0]].bbox
            if prev and layout.gap(prev, lines[j].bbox) < 1.5:  # type: ignore[arg-type]
                cells[-1] = (j, f"{cells[-1][1]} {text}")
                continue
        cells.append((j, text))
    return cells


def _cell_value(ftype: FieldType, text: str, day_first: bool) -> tuple[Any, str] | None:
    """A value read from a cell of its own; an amount must account for every digit in the cell,
    so "14 709,00" is never read as 709,00 and "1 x 28,636" never as one of its numbers."""
    if ftype == "money" and _SPACE_GROUPED.fullmatch(text.strip()):
        # The whole cell is one amount, so its spaces group thousands: "154 000" -> "154,000".
        sep = "" if re.search(r"[.,]\d{2}$", text.strip()) else ","
        text = text.strip().replace(" ", sep)
    parsed = parse_typed(ftype, text, day_first)
    if parsed is None or ftype != "money":
        return parsed
    digits = re.sub(r"\D", "", text)
    return parsed if digits and digits == re.sub(r"\D", "", f"{abs(parsed[0])}") else None


def _fallback(spec: FieldSpec, lines: list[_Line], day_first: bool = False) -> _Candidate | None:
    """Unlabelled guesses. Always low confidence and flagged as inferred."""
    if spec.type == "date" and spec.name in ("date", "invoice_date", "document_date"):
        for line in lines[:40]:
            hits = parse_dates(line.text, day_first)
            d = hits[0][0] if hits else None
            if d:
                return _Candidate(d, line.text, line, 0.5, "first-date")
    if spec.type == "money" and spec.name in ("total", "amount"):
        best: tuple[Decimal, _Line] | None = None
        for k, line in enumerate(lines):
            if _is_payment(lines, k):
                continue
            for value in all_money(line.text):
                if best is None or value > best[0]:
                    best = (value, line)
        if best:
            return _Candidate(best[0], best[1].text, best[1], 0.4, "largest-amount")
    if spec.name in ("vendor", "company"):
        # The issuer's name usually heads the document; labelled lines ("Bill To: X Inc.") are someone else.
        org = re.compile(
            r"\b(inc|ltd|llc|gmbh|corp|corporation|co\.|company|limited|plc|s\.a\.|pty|llp)\b", re.IGNORECASE
        )
        head = [ln for ln in lines[:8] if ":" not in ln.text and len(ln.text) < 80]
        for line in head:
            if org.search(line.text):
                return _Candidate(line.text.strip(), line.text, line, 0.6, "organisation-line")
    if spec.type in ("email", "phone"):
        for line in lines:
            parsed = parse_typed(spec.type, line.text)
            if parsed:
                return _Candidate(parsed[0], parsed[1], line, 0.6, f"first-{spec.type}")
    return None


def _is_payment(lines: list[_Line], k: int) -> bool:
    """Money handed over or given back ("Cash 100,000", "Change 33,500") is not what the document costs."""
    if PAYMENT.search(lines[k].text):
        return True
    me = lines[k].bbox
    return me is not None and any(
        ln.page == lines[k].page
        and ln.bbox is not None
        and ln.bbox[2] <= me[0] + 4
        and layout.same_row(me, ln.bbox)
        and PAYMENT.search(ln.text)
        for ln in lines
    )


def _source(doc: DocumentInfo, line: _Line) -> Source:
    return Source(
        doc_id=doc.id,
        path=doc.path,
        name=doc.name,
        page=line.page,
        bbox=line.bbox,
        excerpt=line.text,
        ocr_conf=line.conf,
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def extract_record(
    doc: DocumentInfo,
    pages: list[PageContent],
    specs: list[FieldSpec],
    *,
    day_first: bool = False,
    reread: Reread | None = None,
) -> Record:
    """Typed values with provenance. ``day_first`` reads 03/04/2026 as 3 April (most of the world)."""
    names = {s.name for s in specs}
    if "total" in names and not {"subtotal", "tax"} <= names:
        # Read subtotal and tax as hidden helpers so a total is always arithmetic-checked.
        helpers = [CATALOG[n] for n in ("subtotal", "tax") if n not in names]
        full = extract_record(doc, pages, [*specs, *helpers], day_first=day_first, reread=reread)
        return full.model_copy(update={"fields": {k: v for k, v in full.fields.items() if k in names}})
    lines = _lines(pages)
    doc_currency = _document_currency(lines)
    candidates = _find_candidates(lines, specs, day_first, doc.doc_type)
    values: dict[str, ExtractedValue] = {}
    raw_values: dict[str, Any] = {}
    for spec in specs:
        cands = candidates.get(spec.name) or []
        # Prefer the strongest label match; for totals prefer the last one (summary rows come last).
        if spec.name == "total" and cands:
            best: _Candidate | None = max(cands, key=lambda c: (c.quality, lines.index(c.line)))
        else:
            best = max(cands, key=lambda c: c.quality) if cands else None
        if best is None:
            best = _fallback(spec, lines, day_first)
        if best is None:
            values[spec.name] = ExtractedValue(field=spec.name, warning="not found" if spec.required else None)
            continue
        conf = best.quality * (best.line.conf if best.line.conf is not None else 0.9)
        distinct = {str(c.value) for c in cands}
        warning = None
        if not best.method.startswith("label"):
            warning = f"inferred ({best.method}); no label found"
        elif best.extra.get("warning"):
            warning = best.extra["warning"]
        elif len(distinct) > 1:
            warning = f"{len(distinct)} different values found; chose the strongest label match"
            conf *= 0.8
        if spec.type == "date" and _ambiguous_date(best.raw):
            order = "day-first (DD/MM)" if day_first else "month-first (MM/DD)"
            warning = (warning + "; " if warning else "") + (
                f"ambiguous date, read {order}; set [extraction] day_first if your documents use the other order"
            )
            conf *= 0.6
        if spec.type == "date" and _implausibly_future(spec.name, best.value):
            warning = (warning + "; " if warning else "") + "date is more than a year in the future; check the year"
            conf *= 0.5
        if best.line.conf is not None and best.line.conf < 0.85:
            warning = (warning + "; " if warning else "") + f"low OCR confidence ({best.line.conf:.2f})"
        raw_values[spec.name] = best.value
        values[spec.name] = ExtractedValue(
            field=spec.name,
            value=_jsonable(best.value),
            raw=best.raw,
            unit=_currency_of(best.raw, best.line.text, doc_currency) if spec.type == "money" else None,
            confidence=round(min(conf, 1.0), 3),
            method=best.method,
            source=_source(doc, best.line),
            verified=best.method.startswith("label") and best.raw.strip() in best.line.text,
            warning=warning,
        )
    _cross_check(values, raw_values)
    values = check_amounts(values, [s.name for s in specs if s.type == "money"], lines, reread)
    return Record(doc_id=doc.id, name=doc.name, path=doc.path, fields=values)


_CURRENCY_WORD = re.compile(r"\b(USD|EUR|GBP|EGP|SAR|AED|CAD|AUD|INR|JPY|CHF|IDR)\b|E£|[$€£]")
_SYMBOL = {"$": "USD", "€": "EUR", "£": "GBP", "E£": "EGP"}


def _currency_of(raw: str, line: str, doc_currency: str | None) -> str | None:
    """The amount's own currency, else one named on its line ("TOTAL DUE (USD)"), else the document's."""
    money = parse_money(raw)
    if money and money[1]:
        return money[1]
    found = {_SYMBOL.get(m.group(0), m.group(0).upper()) for m in _CURRENCY_WORD.finditer(line)}
    return found.pop() if len(found) == 1 else doc_currency


_AMBIGUOUS_DATE = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})\b")


_FUTURE_FIELD = re.compile(r"due|expir|end|until|renew|valid|term|deadline|maturity", re.IGNORECASE)


def _implausibly_future(name: str, value: Any) -> bool:
    """An issue date (not a due, expiry or end date) over a year ahead is usually a misread year ("85" as "35")."""
    if not isinstance(value, date) or _FUTURE_FIELD.search(name):
        return False
    return value > date.today() + timedelta(days=366)


def _ambiguous_date(raw: str) -> bool:
    """03/04/2026 can be March 4 or 3 April; 13/04/2026 cannot."""
    m = _AMBIGUOUS_DATE.search(raw)
    if m is None:
        return False
    return int(m.group(1)) <= 12 and int(m.group(2)) <= 12 and m.group(1) != m.group(2)


def _document_currency(lines: list[_Line]) -> str | None:
    """The document's currency when every amount that names one names the same one."""
    seen = set()
    for line in lines:
        money = parse_money(line.text)
        if money and money[1]:
            seen.add(money[1])
    return seen.pop() if len(seen) == 1 else None


def _cross_check(values: dict[str, ExtractedValue], raw: dict[str, Any]) -> None:
    """subtotal + tax should equal total when all three carry labels.

    Shipping or discounts legitimately break the identity, so a mismatch is a
    "please check" warning, and inferred (unlabelled) values are never checked.
    """
    if not all(k in raw for k in ("subtotal", "tax", "total")):
        return
    if any(not values[k].method.startswith("label") for k in ("subtotal", "tax", "total")):
        return
    try:
        ok = abs((Decimal(raw["subtotal"]) + Decimal(raw["tax"])) - Decimal(raw["total"])) <= Decimal("0.02")
    except (TypeError, ArithmeticError):
        return
    for key in ("subtotal", "tax", "total"):
        item = values[key]
        if ok:
            values[key] = item.model_copy(update={"verified": True, "confidence": max(item.confidence, 0.95)})
        else:
            values[key] = item.model_copy(
                update={
                    "verified": False,
                    "warning": "subtotal + tax does not equal total (shipping or discounts may explain it); "
                    "please check",
                    "confidence": item.confidence * 0.75,
                }
            )
