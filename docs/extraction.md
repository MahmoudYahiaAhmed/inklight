# Structured extraction

Every extracted value carries:

| Field | Meaning |
|---|---|
| `value` | Typed value: money and numbers become floats, dates become ISO `YYYY-MM-DD`, everything else a string. |
| `raw` | The text it was parsed from. |
| `confidence` | 0–1: label-match quality × OCR line confidence, adjusted by cross-checks. |
| `method` | `label` (same line), `label-row` (to the right on the label's row), `label-row-column` (a summary row, resolved by its column title), `label-below` (under the label, same column), `label-next-line` (next line, when there are no boxes), `reader`, or an inferred method (`first-date`, `largest-amount`, `organisation-line`, …). |
| `source` | Document, page, bounding box (pixels of the rendered page), excerpt, OCR confidence. |
| `unit` | Currency code for money (`USD`, `EUR`, `EGP`, ...) when the document states one. Filters and sums never mix currencies. |
| `verified` | **Provenance only**: the raw text is literally on the cited line, or `subtotal + tax = total`. It does not mean the value answers your question. |
| `warning` | Why to double-check: inferred, low OCR confidence, conflicting values, arithmetic mismatch, … |

## Built-in fields

`invoice_number`, `date`, `due_date`, `vendor`, `customer`, `subtotal`, `tax`, `total`,
`effective_date`, `expiry_date`, `contract_value`, `email`, `phone`, `po_number`, `account_number`.
Common words map to these: "VAT" → `tax`, "customer names" → `customer`, "amount due" → `total`,
"expiration" → `expiry_date`. Any other word becomes a custom text field, found by its label.

## Schema files (`inklight extract --schema file.json`)

Three formats are accepted.

**Simple map:**
```json
{"invoice_number": "id", "total": "money", "due_date": "date"}
```

**Field list** (custom labels and required fields):
```json
{"fields": [
  {"name": "policy_number", "type": "id", "labels": ["policy no", "policy #"], "required": true},
  {"name": "premium", "type": "money", "labels": ["annual premium", "premium"]},
  {"name": "renewal", "type": "date", "labels": ["renewal date"]}
]}
```

**JSON Schema** (`properties`; `x-type` and `x-labels` are optional extensions):
```json
{"type": "object", "required": ["total"], "properties": {
  "total": {"type": "number", "x-type": "money"},
  "issued": {"type": "string", "format": "date", "x-labels": ["issued on"]}
}}
```

Types: `text`, `money`, `number`, `date`, `email`, `phone`, `id`.

## Known limits

- Ambiguous numeric dates (`03/04/2026`) are read month-first unless `[extraction] day_first = true`.
- Currency symbols: `$` is read as USD (it is also used by CAD, AUD and others); `E£`/`EGP` is Egyptian pound.
- Labels must be in English, apart from a few Indonesian receipt tax labels (`pajak`, `ppn`, `pb1`,
  `p.rest`). Values in other languages are read when Indra recognises the script.
- A summary row with several amounts and no column titles takes the last amount and is flagged.
- OCR digit loss is not detected yet: a receipt amount `63.000` read as `63.00` gives 63 (seen twice in 124
  held-out receipt values; see docs/BENCHMARKS.md).
- Values that appear only inside complex tables (merged cells, no ruling) may be missed. Indra itself
  documents complex tables as a limitation.
