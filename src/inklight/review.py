"""Human review of extracted values: compare with the document, correct, approve, export.

Every review keeps four things apart, and never overwrites one with another:

* the **prediction** as it was when the review opened (value, OCR text, confidence, method, warning,
  source box). It is frozen: a database trigger refuses any later change;
* the reviewer's **final value** and the action that produced it (accepted, corrected, entered, absent);
* the **approval** (who, when, how long the review took);
* an append-only **event log** (opened, set, approved, reopened, exported). Triggers refuse updates and deletes.

Two modes support measuring review burden against manual entry: ``review`` shows the predictions;
``manual`` keeps them hidden from the reviewer (they are still captured, for evaluation) and the reviewer
types every value.

Only approved reviews are exported.
"""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from .errors import InputRejected
from .extract.fields import parse_typed, resolve_field
from .extract.values import parse_number
from .schemas import DocumentInfo, ExtractedValue, Record
from .store import Store

Mode = Literal["review", "manual"]
Action = Literal["accepted", "corrected", "entered", "absent"]
FLAG_CONFIDENCE = 0.7

SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, doc_name TEXT, doc_sha256 TEXT, mode TEXT NOT NULL,
    cohort TEXT, split TEXT, baseline TEXT, opened_by TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL,
    approved_at TEXT, approved_by TEXT, active_seconds REAL, wall_seconds REAL, fields TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reviews_doc ON reviews(doc_id);
CREATE TABLE IF NOT EXISTS review_fields (
    review_id TEXT NOT NULL REFERENCES reviews(id), field TEXT NOT NULL, position INTEGER NOT NULL,
    predicted TEXT, raw TEXT, confidence REAL, method TEXT, warning TEXT, source TEXT, flagged INTEGER NOT NULL,
    final TEXT, action TEXT, updated_by TEXT, updated_at TEXT, PRIMARY KEY (review_id, field)
);
CREATE TABLE IF NOT EXISTS review_events (
    id INTEGER PRIMARY KEY, review_id TEXT NOT NULL, at TEXT NOT NULL, actor TEXT, kind TEXT NOT NULL,
    field TEXT, before TEXT, after TEXT, note TEXT
);
CREATE TRIGGER IF NOT EXISTS review_prediction_frozen
BEFORE UPDATE OF predicted, raw, confidence, method, warning, source, flagged ON review_fields
BEGIN SELECT RAISE(ABORT, 'predictions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS review_events_no_update BEFORE UPDATE ON review_events
BEGIN SELECT RAISE(ABORT, 'review events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS review_events_no_delete BEFORE DELETE ON review_events
BEGIN SELECT RAISE(ABORT, 'review events are append-only'); END;
"""


class ReviewField(BaseModel):
    field: str
    predicted: Any = None
    raw: str | None = None
    confidence: float | None = None
    method: str | None = None
    warning: str | None = None
    source: dict[str, Any] | None = None
    flagged: bool = False
    final: Any = None
    action: Action | None = None
    updated_by: str | None = None
    updated_at: str | None = None


class Review(BaseModel):
    id: str
    doc_id: str
    doc_name: str | None = None
    doc_sha256: str | None = None
    mode: Mode
    cohort: str | None = None
    split: str | None = None
    baseline: str | None = None
    opened_by: str | None = None
    status: Literal["open", "approved"]
    created_at: str
    approved_at: str | None = None
    approved_by: str | None = None
    active_seconds: float | None = None
    wall_seconds: float | None = None
    fields: list[ReviewField] = Field(default_factory=list)

    def visible(self) -> dict[str, Any]:
        """What a reviewer may see: in manual mode the predictions stay hidden until approval."""
        data = self.model_dump(mode="json")
        if self.mode == "manual" and self.status == "open":
            for f in data["fields"]:
                for key in ("predicted", "raw", "confidence", "method", "warning", "source", "flagged"):
                    f[key] = None
        return data


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _j(value: Any) -> str | None:
    return None if value is None else json.dumps(value)


def _uj(raw: str | None) -> Any:
    return None if raw is None else json.loads(raw)


def is_flagged(value: ExtractedValue) -> bool:
    return bool(value.warning) or (value.confidence or 0.0) < FLAG_CONFIDENCE


class ReviewStore:
    """Reviews in the library's SQLite file (repository over three tables)."""

    def __init__(self, store: Store) -> None:
        self.store = store
        with store._lock:  # executescript commits on its own, so it runs outside a transaction
            store._conn().executescript(SCHEMA)

    @contextmanager
    def _tx(self) -> Iterator[Any]:
        with self.store.tx() as db:
            yield db

    def _event(self, db: Any, review_id: str, actor: str | None, kind: str, **extra: Any) -> None:
        db.execute(
            "INSERT INTO review_events (review_id, at, actor, kind, field, before, after, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                review_id,
                _now(),
                actor,
                kind,
                extra.get("field"),
                _j(extra.get("before")),
                _j(extra.get("after")),
                extra.get("note"),
            ),
        )

    # -- opening ---------------------------------------------------------------

    def open(
        self,
        doc: DocumentInfo,
        record: Record,
        fields: list[str],
        *,
        mode: Mode = "review",
        reviewer: str,
        cohort: str | None = None,
        split: str | None = None,
        baseline: str | None = None,
    ) -> Review:
        """Freeze ``record``'s predictions for ``fields`` and open a review of them."""
        _require_name(reviewer)
        if mode not in ("review", "manual"):
            raise InputRejected(f"Unknown review mode {mode!r}")
        if not fields:
            raise InputRejected("A review needs at least one field")
        review_id = uuid.uuid4().hex[:16]
        with self._tx() as db:
            db.execute(
                "INSERT INTO reviews (id, doc_id, doc_name, doc_sha256, mode, cohort, split, baseline, opened_by, "
                "status, created_at, fields) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)",
                (review_id, doc.id, doc.name, doc.sha256, mode, cohort, split, baseline, reviewer, _now(), _j(fields)),
            )
            for position, name in enumerate(fields):
                value = record.fields.get(name) or ExtractedValue(field=name)
                db.execute(
                    "INSERT INTO review_fields (review_id, field, position, predicted, raw, confidence, method, "
                    "warning, source, flagged) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        review_id,
                        name,
                        position,
                        _j(value.value),
                        value.raw,
                        value.confidence,
                        value.method,
                        value.warning,
                        _j(value.source.model_dump(mode="json") if value.source else None),
                        int(value.value is not None and is_flagged(value)),
                    ),
                )
            self._event(db, review_id, reviewer, "opened", note=f"mode={mode}")
        return self.get(review_id)

    # -- reading ---------------------------------------------------------------

    def get(self, review_id: str) -> Review:
        rows = self.store._all("SELECT * FROM reviews WHERE id = ?", (review_id,))
        if not rows:
            raise InputRejected(f"Unknown review {review_id!r}")
        r = dict(rows[0])
        fields = [
            ReviewField(
                field=f["field"],
                predicted=_uj(f["predicted"]),
                raw=f["raw"],
                confidence=f["confidence"],
                method=f["method"],
                warning=f["warning"],
                source=_uj(f["source"]),
                flagged=bool(f["flagged"]),
                final=_uj(f["final"]),
                action=f["action"],
                updated_by=f["updated_by"],
                updated_at=f["updated_at"],
            )
            for f in self.store._all("SELECT * FROM review_fields WHERE review_id = ? ORDER BY position", (review_id,))
        ]
        return Review(**{**r, "fields": fields})

    def find(self, status: str | None = None, cohort: str | None = None) -> list[Review]:
        sql, args = "SELECT id FROM reviews WHERE 1 = 1", []
        if status:
            sql += " AND status = ?"
            args.append(status)
        if cohort:
            sql += " AND cohort = ?"
            args.append(cohort)
        return [self.get(row["id"]) for row in self.store._all(sql + " ORDER BY created_at", tuple(args))]

    def events(self, review_id: str) -> list[dict[str, Any]]:
        return [
            {**dict(e), "before": _uj(e["before"]), "after": _uj(e["after"])}
            for e in self.store._all("SELECT * FROM review_events WHERE review_id = ? ORDER BY id", (review_id,))
        ]

    # -- deciding --------------------------------------------------------------

    def decide(self, review_id: str, field: str, *, reviewer: str, action: Action, value: Any = None) -> Review:
        """Record the reviewer's decision for one field.

        ``accepted``: the prediction is right (review mode only). ``corrected`` / ``entered``: the reviewer's
        value (validated and typed like an extracted value). ``absent``: the document does not state it.
        """
        _require_name(reviewer)
        review = self.get(review_id)
        if review.status != "open":
            raise InputRejected("This review is approved; reopen it to change a value")
        current = next((f for f in review.fields if f.field == field), None)
        if current is None:
            raise InputRejected(f"Field {field!r} is not part of this review")
        if action == "accepted":
            if review.mode == "manual":
                raise InputRejected("Manual entry has no prediction to accept; enter the value")
            if current.predicted is None:
                raise InputRejected("Nothing was predicted for this field; enter the value or mark it absent")
            final = current.predicted
        elif action == "absent":
            final = None
        elif action in ("corrected", "entered"):
            final = typed_value(field, value)
        else:
            raise InputRejected(f"Unknown action {action!r}")
        with self._tx() as db:
            db.execute(
                "UPDATE review_fields SET final = ?, action = ?, updated_by = ?, updated_at = ? "
                "WHERE review_id = ? AND field = ?",
                (_j(final), action, reviewer, _now(), review_id, field),
            )
            self._event(
                db,
                review_id,
                reviewer,
                "set",
                field=field,
                before={"final": current.final, "action": current.action},
                after={"final": final, "action": action},
            )
        return self.get(review_id)

    def approve(self, review_id: str, *, reviewer: str, active_seconds: float | None = None) -> Review:
        """Approve a review in which every field has a decision."""
        _require_name(reviewer)
        review = self.get(review_id)
        if review.status != "open":
            raise InputRejected("This review is already approved")
        undecided = [f.field for f in review.fields if f.action is None]
        if undecided:
            raise InputRejected("Decide every field before approving: " + ", ".join(undecided))
        now = datetime.now(UTC)
        wall = (now - datetime.fromisoformat(review.created_at)).total_seconds()
        if active_seconds is not None and not 0 <= active_seconds <= wall + 5:
            raise InputRejected("active_seconds must be between 0 and the time since the review opened")
        with self._tx() as db:
            db.execute(
                "UPDATE reviews SET status = 'approved', approved_at = ?, approved_by = ?, active_seconds = ?, "
                "wall_seconds = ? WHERE id = ?",
                (now.isoformat(timespec="milliseconds"), reviewer, active_seconds, round(wall, 3), review_id),
            )
            self._event(db, review_id, reviewer, "approved", note=f"active_seconds={active_seconds}")
        return self.get(review_id)

    def reopen(self, review_id: str, *, reviewer: str, reason: str) -> Review:
        _require_name(reviewer)
        if not reason.strip():
            raise InputRejected("Say why the review is reopened")
        review = self.get(review_id)
        if review.status != "approved":
            raise InputRejected("Only an approved review can be reopened")
        with self._tx() as db:
            db.execute(
                "UPDATE reviews SET status = 'open', approved_at = NULL, approved_by = NULL WHERE id = ?",
                (review_id,),
            )
            self._event(
                db,
                review_id,
                reviewer,
                "reopened",
                before={"approved_at": review.approved_at, "approved_by": review.approved_by},
                note=reason,
            )
        return self.get(review_id)

    # -- export ----------------------------------------------------------------

    def export(self, fmt: Literal["csv", "json"], *, actor: str, cohort: str | None = None) -> str:
        """Approved reviews only: one row per field with prediction, warning, decision and approval."""
        _require_name(actor)
        reviews = self.find(status="approved", cohort=cohort)
        rows = [_export_row(r, f) for r in reviews for f in r.fields]
        with self._tx() as db:
            for r in reviews:
                self._event(db, r.id, actor, "exported", note=fmt)
        if fmt == "json":
            return json.dumps(rows, indent=1, default=str)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(EXPORT_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _csv_safe(v) for k, v in row.items()})
        return buf.getvalue()


EXPORT_COLUMNS = (
    "review_id",
    "document",
    "doc_sha256",
    "cohort",
    "mode",
    "baseline",
    "field",
    "predicted",
    "predicted_raw",
    "confidence",
    "method",
    "warning",
    "flagged",
    "final",
    "action",
    "decided_by",
    "approved_by",
    "approved_at",
)


def _export_row(r: Review, f: ReviewField) -> dict[str, Any]:
    return {
        "review_id": r.id,
        "document": r.doc_name,
        "doc_sha256": r.doc_sha256,
        "cohort": r.cohort,
        "mode": r.mode,
        "baseline": r.baseline,
        "field": f.field,
        "predicted": f.predicted,
        "predicted_raw": f.raw,
        "confidence": f.confidence,
        "method": f.method,
        "warning": f.warning,
        "flagged": f.flagged,
        "final": f.final,
        "action": f.action,
        "decided_by": f.updated_by,
        "approved_by": r.approved_by,
        "approved_at": r.approved_at,
    }


def _csv_safe(value: Any) -> Any:
    """Neutralise spreadsheet formula injection from document text."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "|", "\t", "\r"):
        return "'" + value
    return value


def typed_value(field: str, value: Any) -> Any:
    """A reviewer's value, validated and typed like an extracted one (money -> number, date -> ISO)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise InputRejected("Enter a value, or mark the field absent")
    text = str(value).strip()
    if len(text) > 500:
        raise InputRejected("A value is at most 500 characters")
    spec = resolve_field(field)
    if spec.type in ("text", "id", "email", "phone"):
        return text
    if spec.type in ("money", "number"):
        # A typed amount needs no currency or cents to count ("1234", "Rp 63.000", "-45.00").
        number = parse_number(re.sub(r"[^\d.,-]", "", text))
        if number is None:
            raise InputRejected(f"{text!r} is not a valid amount for {field}")
        return float(number)
    parsed = parse_typed(spec.type, text)
    if parsed is None:
        raise InputRejected(f"{text!r} is not a valid {spec.type} for {field}")
    return parsed[0].isoformat()


def _require_name(name: str | None) -> None:
    if not name or not name.strip() or len(name) > 100:
        raise InputRejected("Give the reviewer's name (1-100 characters)")


Predictor = Callable[[DocumentInfo, list[str]], Record]
