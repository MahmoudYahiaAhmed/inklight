"""Keyword-scored document type classification (fast, explainable, model-free)."""

from __future__ import annotations

import re

DOC_TYPES: dict[str, dict[str, float]] = {
    "invoice": {
        "invoice": 3,
        "bill to": 2,
        "amount due": 2,
        "subtotal": 1.5,
        "due date": 1.5,
        "invoice number": 2,
        "remit": 1,
        "payment terms": 1,
        "tax": 0.5,
        "qty": 0.5,
    },
    "receipt": {
        "receipt": 3,
        "cashier": 2,
        "change due": 2,
        "thank you for your purchase": 2,
        "card ending": 1.5,
        "transaction": 1,
        "store": 0.5,
    },
    "contract": {
        "agreement": 3,
        "hereinafter": 2,
        "parties": 2,
        "party": 1,
        "governing law": 2,
        "terminate": 1.5,
        "term": 0.5,
        "whereas": 2,
        "effective date": 1.5,
        "expiration": 1,
        "indemnif": 1.5,
    },
    "report": {
        "report": 2.5,
        "executive summary": 2,
        "findings": 1.5,
        "analysis": 1,
        "quarter": 1,
        "results": 1,
        "conclusion": 1,
        "methodology": 1.5,
    },
    "form": {
        "form": 2,
        "signature": 1.5,
        "please complete": 2,
        "applicant": 1.5,
        "date of birth": 1.5,
        "check one": 1.5,
    },
    "letter": {"dear ": 2, "sincerely": 2, "regards": 1, "yours faithfully": 2},
    "resume": {"experience": 1.5, "education": 1.5, "skills": 1.5, "curriculum vitae": 3, "resume": 2},
}
SINGULAR = {
    "invoices": "invoice",
    "receipts": "receipt",
    "contracts": "contract",
    "reports": "report",
    "forms": "form",
    "letters": "letter",
    "resumes": "resume",
    "cvs": "resume",
    "agreements": "contract",
    "bills": "invoice",
}


def classify(text: str) -> tuple[str, float]:
    """Return (doc_type, confidence in 0..1). ``unknown`` when nothing scores."""
    head = text[:6000].lower()
    scores = {}
    for doc_type, cues in DOC_TYPES.items():
        score = 0.0
        for cue, weight in cues.items():
            hits = len(re.findall(re.escape(cue), head))
            score += weight * min(hits, 3)
        scores[doc_type] = score
    best = max(scores, key=lambda k: scores[k])
    total = sum(scores.values())
    if scores[best] < 3:
        return "unknown", 0.0
    return best, round(scores[best] / total, 3)
