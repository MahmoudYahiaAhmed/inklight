"""Bounded execution: step limits, time budgets, retries, cancellation and a full trace."""

from __future__ import annotations

import copy
import logging
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import fields, replace

from pydantic import ValidationError

from ..errors import InklightError, PermissionDenied, TaskCancelled, ToolError
from ..schemas import AgentResult, StepStatus, TaskState, TraceStep
from .compose import compose
from .context import Scratch, ToolContext
from .plan import Plan
from .planner import validate_plan
from .tools import TOOLS

log = logging.getLogger(__name__)


class Runner:
    def __init__(self, max_steps: int, task_timeout: float, step_timeout: float, max_retries: int) -> None:
        self.max_steps = max_steps
        self.task_timeout = task_timeout
        self.step_timeout = step_timeout
        self.max_retries = max_retries

    def run(self, ctx: ToolContext, plan: Plan) -> AgentResult:
        started = time.monotonic()
        ctx.deadline = started + self.task_timeout
        task_id = uuid.uuid4().hex[:12]
        trace: list[TraceStep] = []
        state = TaskState.RUNNING
        validate_plan(plan)  # a plan that would not enforce its stated conditions never runs
        steps = list(plan.steps)
        filter_at = next((i for i, s in enumerate(steps) if s.tool == "filter_records"), None)
        if len(steps) > self.max_steps:
            ctx.scratch.warn(f"Plan has {len(steps)} steps; only the first {self.max_steps} ran (max_steps)")
            steps = steps[: self.max_steps]
            state = TaskState.PARTIAL
            if filter_at is not None and filter_at >= self.max_steps:
                steps = steps[:1]  # never show records that the conditions were not applied to
                state = TaskState.FAILED
                ctx.scratch.warn("The conditions could not be applied within max_steps, so no records are shown")
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="inklight-tool")
        try:
            for index, step in enumerate(steps):
                outcome = self._run_step(pool, ctx, index, step.tool, step.args)
                trace.append(outcome)
                if ctx.cancel.is_set():
                    # A timed-out worker may still be running and writing to the old scratch:
                    # compose from a private snapshot so the result cannot change underneath us.
                    ctx = replace(ctx, scratch=_snapshot(ctx.scratch))
                    state = TaskState.CANCELLED
                    break
                if outcome.status == StepStatus.FAILED:
                    critical = step.tool not in ("write_output", "inspect_documents")
                    if filter_at is not None and index <= filter_at:
                        # Extracted but unfiltered records must never pass for the requested selection.
                        ctx.scratch.records = []
                        ctx.scratch.doc_ids = []
                        state = TaskState.FAILED
                        break
                    state = TaskState.FAILED if critical and not ctx.scratch.records else TaskState.PARTIAL
                    if critical:
                        break
                elif outcome.status == StepStatus.DENIED:
                    state = TaskState.PARTIAL
        finally:
            # Never block on a stuck worker; it stops at its next ctx.check().
            pool.shutdown(wait=False, cancel_futures=True)
        if state == TaskState.RUNNING:
            state = TaskState.SUCCEEDED
        if plan.blocked:
            state = TaskState.UNSUPPORTED
            ctx.scratch.warn("Not run: " + " ".join(plan.blocked))
        if plan.not_understood:
            ctx.scratch.warn(
                "Not applied: "
                + "; ".join(f"“{x}”" for x in plan.not_understood)
                + ". The result ignores these parts of your request: check it, or rephrase."
            )
        # A task that ignored part of the request, or could only do part of the job, did not succeed.
        if state == TaskState.SUCCEEDED and (plan.not_understood or ctx.scratch.partial):
            state = TaskState.PARTIAL
        answer_text = compose(ctx, plan, state)
        s = ctx.scratch
        evidence = max(0.0, min(1.0, s.confidence))
        understood = max(0.0, min(1.0, plan.confidence))
        return AgentResult(
            task_id=task_id,
            request=plan.query,
            intent=plan.intent.value,
            state=state,
            answer=answer_text,
            confidence=min(evidence, understood),
            interpretation_confidence=understood,
            evidence_confidence=evidence,
            interpretation=plan.understood(),
            not_understood=plan.not_understood,
            checks=_checks(plan, s, state),
            sources=tuple(s.sources[:12]),
            records=tuple(r.project(plan.fields) for r in s.records),
            calculation=dict(s.calc) if s.calc else None,
            files_written=tuple(s.files),
            warnings=tuple(s.warnings),
            trace=tuple(trace),
            brain=_brain_label(ctx, plan),
            duration_ms=round(1000 * (time.monotonic() - started), 1),
            outcome=result_outcome(plan, s, state, trace),
            candidates=tuple(s.candidates[:12]),
            comparison=s.comparison,
        )

    def _run_step(self, pool: ThreadPoolExecutor, ctx: ToolContext, index: int, name: str, raw_args: dict) -> TraceStep:
        t0 = time.monotonic()
        tool = TOOLS.get(name)
        if tool is None:
            return TraceStep(
                index=index,
                tool=name,
                args=raw_args,
                status=StepStatus.DENIED,
                summary="not an allowed tool",
                duration_ms=0.0,
                error="unknown tool",
            )
        try:
            args = tool.args.model_validate(raw_args)
        except ValidationError as exc:
            return TraceStep(
                index=index,
                tool=name,
                args=raw_args,
                status=StepStatus.FAILED,
                summary="invalid arguments",
                duration_ms=0.0,
                error=str(exc.errors()[:2]),
            )
        attempts = 0
        while True:
            attempts += 1
            remaining = ctx.deadline - time.monotonic()
            try:
                if remaining <= 0:
                    raise TaskCancelled("Task time budget exhausted")
                ctx.check()
                future = pool.submit(tool.run, ctx, args)
                try:
                    summary = future.result(timeout=min(self.step_timeout, remaining))
                except FutureTimeout:
                    if future.done():  # the tool raised its own TimeoutError: an ordinary, retryable failure
                        raise ToolError(f"{name} timed out internally", recoverable=True) from None
                    ctx.cancel.set()  # the worker stops at its next check()
                    ctx.scratch.warn(f"Step '{name}' exceeded its time budget and was stopped")
                    return self._fail(index, name, args, t0, attempts, "step time budget exhausted")
                return TraceStep(
                    index=index,
                    tool=name,
                    args=args.model_dump(mode="json"),
                    status=StepStatus.OK,
                    summary=summary,
                    duration_ms=_ms(t0),
                    attempts=attempts,
                )
            except PermissionDenied as exc:
                ctx.scratch.warn(str(exc))
                return TraceStep(
                    index=index,
                    tool=name,
                    args=args.model_dump(mode="json"),
                    status=StepStatus.DENIED,
                    summary="permission denied",
                    duration_ms=_ms(t0),
                    attempts=attempts,
                    error=str(exc),
                )
            except TaskCancelled as exc:
                ctx.cancel.set()  # the task is over, whichever budget ran out
                return self._fail(index, name, args, t0, attempts, str(exc))
            except ToolError as exc:
                if exc.recoverable and attempts <= self.max_retries:
                    log.info("retrying %s after: %s", name, exc)
                    continue
                ctx.scratch.warn(f"{name}: {exc}")
                return self._fail(index, name, args, t0, attempts, str(exc))
            except InklightError as exc:
                ctx.scratch.warn(f"{name}: {exc}")
                return self._fail(index, name, args, t0, attempts, str(exc))
            except Exception as exc:  # a tool bug must not crash the task; it is reported in the trace
                log.exception("tool %s crashed", name)
                ctx.scratch.warn(f"{name} failed unexpectedly: {type(exc).__name__}")
                return self._fail(index, name, args, t0, attempts, f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _fail(index: int, name: str, args: object, t0: float, attempts: int, error: str) -> TraceStep:
        dumped = args.model_dump(mode="json") if hasattr(args, "model_dump") else {}
        return TraceStep(
            index=index,
            tool=name,
            args=dumped,
            status=StepStatus.FAILED,
            summary="failed",
            duration_ms=_ms(t0),
            attempts=attempts,
            error=error,
        )


_DECLINED = ("I couldn't find", "I could not find", "No passage", "I could not find anything")
# Answer paths that read a value at its printed label or in its table cell (agent/labels.py, table_answer.py).
_AT_LABEL = ("value beside its label", "table cell")
_CLOSEST = "The closest passage is:"
_ASKS_FOR_DIGITS = re.compile(
    r"\b(?:number|no\.|date|when|how (?:many|much)|amount|total|percent(?:age)?)\b|رقم|تاريخ|متى|كم\s|نسبة|مبلغ",
    re.IGNORECASE,
)
_SHOWN_AS_FOUND = {"extract", "find", "cite", "summarize", "filter", "count", "inconsistencies", "process"}


def result_outcome(plan: Plan, s: Scratch, state: TaskState, trace: list[TraceStep]) -> str:
    """What kind of result this is, from what the steps did, not from how confident they sounded:

    - a step that knows (several candidates, a field compared, an operation not available) says so;
    - a decline is missing evidence; an error is failed; part of the job done is partial;
    - text, passages and extracted fields are shown as found ("extracted"), never as a conclusion;
    - an answer is "supported" only when it is a value read at its printed label or in its table cell, cited, with
      no warning; every other answer is "proposed" and needs review. OCR can still misread a supported value.
    """
    if state in (TaskState.FAILED, TaskState.CANCELLED):
        return "failed"
    if state == TaskState.UNSUPPORTED:
        return "unsupported"
    if s.outcome:
        return s.outcome
    if s.answer.startswith(_DECLINED) or s.answer.startswith(_CLOSEST):
        return "missing_evidence"
    if plan.intent.value == "ask" and _ASKS_FOR_DIGITS.search(plan.query):
        head = s.answer.split("\n\nEvidence:")[0]
        if not any(ch.isdigit() for ch in head):
            return "missing_evidence"  # a number or date was asked for and the passage found has none
    if state == TaskState.PARTIAL:
        return "partial"
    intent = plan.intent.value
    if intent in _SHOWN_AS_FOUND:
        return "extracted"
    used = next((t.summary for t in reversed(trace) if t.tool == "answer"), "")
    if intent == "ask" and used in _AT_LABEL and s.sources and not s.warnings and s.confidence >= 0.7:
        return "supported"
    return "proposed"


def _checks(plan: Plan, s: Scratch, state: TaskState) -> tuple[str, ...]:
    """Plain statements of what was checked — provenance, interpretation and evidence are different things."""
    out = [
        f"provenance: {len(s.sources)} citation(s) were found in the stored document text "
        "(this shows where values came from, not that they answer the question)"
    ]
    if plan.blocked:
        out.append("interpretation: not run; " + "; ".join(plan.blocked))
    elif plan.not_understood:
        out.append(f"interpretation: partial; {len(plan.not_understood)} part(s) of the request were not applied")
    elif plan.where is not None:
        out.append("interpretation: every recognised condition was applied by the filter step")
    else:
        out.append("interpretation: no conditions in the request")
    out.append(f"evidence: heuristic score {s.confidence:.2f} (labels, OCR confidence, arithmetic checks)")
    if state == TaskState.PARTIAL and s.partial:
        out.append("result: only part of the job could be done (see warnings)")
    for note in dict.fromkeys(s.models_skipped):
        out.append(f"models: {note}")
    out.extend(dict.fromkeys(s.notes))
    return tuple(out)


def _snapshot(s: Scratch) -> Scratch:
    """Shallow copies of every list, so late writes by an abandoned worker are not seen."""
    return Scratch(**{f.name: copy.copy(getattr(s, f.name)) for f in fields(Scratch)})


def _ms(t0: float) -> float:
    return round(1000 * (time.monotonic() - t0), 1)


def _brain_label(ctx: ToolContext, plan: Plan) -> str:
    used = sorted(ctx.scratch.brain_used)
    label = "+".join(used) if used else "rules"
    return f"{label} (planner: {plan.planner})"
