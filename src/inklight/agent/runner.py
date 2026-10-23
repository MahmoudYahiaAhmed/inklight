"""Bounded execution: step limits, time budgets, retries, cancellation and a full trace."""

from __future__ import annotations

import copy
import logging
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
        steps = list(plan.steps)
        if len(steps) > self.max_steps:
            ctx.scratch.warn(f"Plan has {len(steps)} steps; only the first {self.max_steps} ran (max_steps)")
            steps = steps[: self.max_steps]
            state = TaskState.PARTIAL
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
            sources=tuple(s.sources[:12]),
            records=tuple(s.records),
            files_written=tuple(s.files),
            warnings=tuple(s.warnings),
            trace=tuple(trace),
            brain=_brain_label(ctx, plan),
            duration_ms=round(1000 * (time.monotonic() - started), 1),
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


def _snapshot(s: Scratch) -> Scratch:
    """Shallow copies of every list, so late writes by an abandoned worker are not seen."""
    return Scratch(**{f.name: copy.copy(getattr(s, f.name)) for f in fields(Scratch)})


def _ms(t0: float) -> float:
    return round(1000 * (time.monotonic() - t0), 1)


def _brain_label(ctx: ToolContext, plan: Plan) -> str:
    used = sorted(ctx.scratch.brain_used)
    label = "+".join(used) if used else "rules"
    return f"{label} (planner: {plan.planner})"
