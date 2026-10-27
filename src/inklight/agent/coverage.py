"""Which of the selected documents a result was drawn from, said plainly when it is not all of them.

A document that failed to import, is still being read, or was removed has no text to read. An answer from the
others is at most a partial result: it never says "supported", a comparison cannot conclude, and a count or total
says what it left out.
"""

from __future__ import annotations

from typing import Any

_WHY = {
    "failed": "its import failed",
    "pending": "it is still being read",
    "missing": "it is no longer in the library",
}


def unavailable_reason(item: dict[str, Any]) -> str:
    why = _WHY.get(item["status"], f"it is {item['status']}")
    return f"{why} ({item['error']})" if item.get("error") and item["status"] == "failed" else why


def unavailable_warning(item: dict[str, Any]) -> str:
    return f"{item['document']} was not used: {unavailable_reason(item)}"


def coverage_line(used: int, unavailable: list[dict[str, Any]]) -> str:
    """The first line of a result drawn from part of the selection."""
    total = used + len(unavailable)
    names = "; ".join(f"{u['document']} ({_WHY.get(u['status'], u['status'])})" for u in unavailable)
    if not used:
        return f"NOT ANSWERED: none of the {total} selected document(s) can be read yet. Not available: {names}."
    return (
        f"INCOMPLETE SCOPE: this result covers {used} of the {total} selected document(s). Not available: {names}. "
        "It may change once they are read."
    )
