"""Field presets by document type: optional defaults, never a requirement.

Invoices and receipts get invoice fields; contracts get contract dates and value; letters, reports, forms,
certificates and unknown documents get only a date, because there is no field every such document has. Ask
for the fields you want (a field list or a schema file) and the preset is not used.
"""

from __future__ import annotations

INVOICE = ("vendor", "customer", "invoice_number", "date", "due_date", "subtotal", "tax", "total")
PRESETS: dict[str, tuple[str, ...]] = {
    "invoice": INVOICE,
    "receipt": ("vendor", "date", "total", "tax"),
    "contract": ("date", "effective_date", "expiry_date", "contract_value"),
}
GENERAL = ("date",)


def preset_fields(doc_type: str | None) -> list[str]:
    return list(PRESETS.get(doc_type or "", GENERAL))
