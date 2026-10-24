"""HTTP routes for human review (see inklight.review). Registered by create_app."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..agent import DocumentAgent

INVOICE_FIELDS = ["vendor", "customer", "invoice_number", "date", "due_date", "subtotal", "tax", "total"]


class OpenBody(BaseModel):
    doc_id: str = Field(min_length=1, max_length=64)
    reviewer: str = Field(min_length=1, max_length=100)
    fields: list[str] = Field(default_factory=lambda: list(INVOICE_FIELDS), min_length=1, max_length=40)
    mode: Literal["review", "manual"] = "review"
    cohort: str | None = Field(None, max_length=64)
    split: str | None = Field(None, max_length=32)


class DecideBody(BaseModel):
    field: str = Field(min_length=1, max_length=64)
    action: Literal["accepted", "corrected", "entered", "absent"]
    value: str | None = Field(None, max_length=500)
    reviewer: str = Field(min_length=1, max_length=100)


class ApproveBody(BaseModel):
    reviewer: str = Field(min_length=1, max_length=100)
    active_seconds: float | None = Field(None, ge=0)


class ReopenBody(BaseModel):
    reviewer: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=1, max_length=500)


class ExportBody(BaseModel):
    actor: str = Field(min_length=1, max_length=100)
    format: Literal["csv", "json"] = "csv"
    cohort: str | None = Field(None, max_length=64)


def register(app: FastAPI, current: Callable[[], DocumentAgent]) -> None:
    def baseline() -> str | None:
        return os.environ.get("INKLIGHT_PILOT_BASELINE") or None

    @app.get("/api/reviews")
    def list_reviews(status: str | None = None, cohort: str | None = None) -> list[dict[str, Any]]:
        if status not in (None, "open", "approved"):
            raise HTTPException(400, "status is open or approved")
        return [r.visible() for r in current().reviews.find(status=status, cohort=cohort)]

    @app.post("/api/reviews")
    async def open_review(body: OpenBody) -> dict[str, Any]:
        review = await run_in_threadpool(
            current().open_review,
            body.doc_id,
            body.fields,
            reviewer=body.reviewer,
            mode=body.mode,
            cohort=body.cohort,
            split=body.split,
            baseline=baseline(),
        )
        return review.visible()

    @app.get("/api/reviews/{review_id}")
    def get_review(review_id: str) -> dict[str, Any]:
        store = current().reviews
        review = store.get(review_id)
        return {**review.visible(), "events": store.events(review_id)}  # events hold decisions, never predictions

    @app.post("/api/reviews/{review_id}/decide")
    def decide(review_id: str, body: DecideBody) -> dict[str, Any]:
        store = current().reviews
        return store.decide(
            review_id, body.field, reviewer=body.reviewer, action=body.action, value=body.value
        ).visible()

    @app.post("/api/reviews/{review_id}/approve")
    def approve(review_id: str, body: ApproveBody) -> dict[str, Any]:
        return (
            current().reviews.approve(review_id, reviewer=body.reviewer, active_seconds=body.active_seconds).visible()
        )

    @app.post("/api/reviews/{review_id}/reopen")
    def reopen(review_id: str, body: ReopenBody) -> dict[str, Any]:
        return current().reviews.reopen(review_id, reviewer=body.reviewer, reason=body.reason).visible()

    @app.post("/api/reviews/export")
    def export(body: ExportBody) -> Response:
        content = current().reviews.export(body.format, actor=body.actor, cohort=body.cohort)
        media = "text/csv" if body.format == "csv" else "application/json"
        name = f"inklight-reviews{'-' + body.cohort if body.cohort else ''}.{body.format}"
        return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})
