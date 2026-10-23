"""A typed Boolean expression over conditions.

The same validated expression is executed by the filter tool and rendered in
"Understood as", so the explanation cannot drift from the behaviour. Evaluation
is three-valued: a missing value or an incompatible currency is *unknown*, never
silently treated as a match or a mismatch.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from .plan import Condition, Group

# Unknown carries a reason: "missing" or "currency".
Verdict = tuple[bool | None, frozenset[str]]


def group(kind: Literal["all", "any"], items: list[Condition | Group]) -> Condition | Group:
    """Build a group, flattening same-kind children and collapsing single operands."""
    flat: list[Condition | Group] = []
    for item in items:
        if isinstance(item, Group) and item.kind == kind:
            flat.extend(item.items)
        else:
            flat.append(item)
    return flat[0] if len(flat) == 1 else Group(kind=kind, items=tuple(flat))


def leaves(expr: Condition | Group | None) -> list[Condition]:
    if expr is None:
        return []
    if isinstance(expr, Condition):
        return [expr]
    return [leaf for item in expr.items for leaf in leaves(item)]


def fields(expr: Condition | Group | None) -> list[str]:
    return list(dict.fromkeys(c.field for c in leaves(expr)))


def describe(expr: Condition | Group, top: bool = True) -> str:
    if isinstance(expr, Condition):
        return expr.describe()
    joiner = " and " if expr.kind == "all" else " or "
    text = joiner.join(describe(item, top=False) for item in expr.items)
    return text if top else f"({text})"


def evaluate(expr: Condition | Group, check: Callable[[Condition], Verdict]) -> Verdict:
    """Kleene logic: AND is False if any operand is False; OR is True if any operand is True."""
    if isinstance(expr, Condition):
        return check(expr)
    results = [evaluate(item, check) for item in expr.items]
    reasons = frozenset().union(*(r for v, r in results if v is None))
    values = [v for v, _ in results]
    if expr.kind == "all":
        if any(v is False for v in values):
            return False, frozenset()
        return (None, reasons) if None in values else (True, frozenset())
    if any(v is True for v in values):
        return True, frozenset()
    return (None, reasons) if None in values else (False, frozenset())
