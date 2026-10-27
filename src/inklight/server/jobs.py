"""Background imports with real progress, for the workspace.

An import job holds what the library reports while it reads a batch of files: which file is being read, each page
as the OCR finishes it, when the structure stage starts, and how each file ends (done, failed, or not read because
the job was stopped). Nothing here is estimated: a file shows a page count only once the OCR has reported one.

Jobs run one at a time (a later job waits, "queued"), are kept in memory for the life of the server (the most
recent ``KEEP``), and are read by polling (``snapshot``) or by waiting for the next change (``wait``, behind the
server-sent events endpoint), so a reloaded page can find a running job again.
"""

from __future__ import annotations

import contextlib
import copy
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any

KEEP = 20
TERMINAL = {"completed", "partial", "failed", "cancelled"}


class Jobs:
    def __init__(self) -> None:
        self._jobs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._cancel: dict[str, threading.Event] = {}
        self._paths: dict[str, list[Path]] = {}
        self._changed = threading.Condition()
        self._runner = threading.Lock()  # one import reads at a time

    # -- reading --------------------------------------------------------------

    def snapshot(self, job_id: str) -> dict[str, Any] | None:
        with self._changed:
            job = self._jobs.get(job_id)
            return copy.deepcopy(job) if job else None

    def recent(self) -> list[dict[str, Any]]:
        with self._changed:
            return [copy.deepcopy(j) for j in reversed(self._jobs.values())]

    def wait(self, job_id: str, version: int, timeout: float) -> dict[str, Any] | None:
        """The job once its version is past ``version`` (or after ``timeout`` seconds, unchanged)."""
        with self._changed:
            self._changed.wait_for(lambda: self._jobs.get(job_id, {}).get("version", version + 1) > version, timeout)
            job = self._jobs.get(job_id)
            return copy.deepcopy(job) if job else None

    def path(self, job_id: str, index: int) -> Path | None:
        paths = self._paths.get(job_id, [])
        return paths[index] if 0 <= index < len(paths) else None

    # -- running --------------------------------------------------------------

    def start_import(
        self,
        paths: list[Path],
        rejected: list[dict[str, Any]],
        add: Callable[..., Any],
        finish: Callable[[Any], dict[str, Any]],
        kind: str = "import",
    ) -> dict[str, Any]:
        """Queue an import of ``paths`` and return its first snapshot. ``add`` is the library's add; ``finish``
        turns its report into the job's result (and tidies uploads)."""
        job_id = secrets.token_hex(6)
        job = {
            "id": job_id,
            "kind": kind,  # import | structure (a stored document read again with its structure)
            "state": "queued",
            "version": 0,
            "created": time.time(),
            "started": None,
            "finished": None,
            "active": None,
            "cancel_requested": False,
            "files": [
                {"name": p.name, "state": "queued", "page": 0, "pages": None, "error": None, "doc_id": None}
                for p in paths
            ]
            + [
                {"name": r["file"], "state": "failed", "page": 0, "pages": None, "error": r["error"], "doc_id": None}
                for r in rejected
            ],  # fmt: skip
            "result": None,
        }
        with self._changed:
            self._jobs[job_id] = job
            self._cancel[job_id] = threading.Event()
            self._paths[job_id] = list(paths)
            while len(self._jobs) > KEEP:
                old = next(iter(self._jobs))
                if self._jobs[old]["state"] not in TERMINAL:
                    break
                self._jobs.pop(old)
                self._cancel.pop(old, None)
                self._paths.pop(old, None)
        thread = threading.Thread(
            target=self._run, args=(job_id, paths, add, finish), name=f"inklight-import-{job_id}", daemon=True
        )
        thread.start()
        return self.snapshot(job_id) or job

    def cancel(self, job_id: str) -> bool:
        """Stop the job before its next file (a file being read is finished). False for an unknown or ended job."""
        event = self._cancel.get(job_id)
        job = self._jobs.get(job_id)
        if event is None or job is None or job["state"] in TERMINAL:
            return False
        event.set()
        self._update(job_id, lambda j: j.update(cancel_requested=True))
        return True

    def _run(self, job_id: str, paths: list[Path], add: Callable[..., Any], finish: Callable[[Any], dict]) -> None:
        index = {str(p): i for i, p in enumerate(paths)}
        with self._runner:
            self._update(job_id, lambda j: j.update(state="running", started=time.time()))

            def progress(event: str, path: str, info: dict[str, Any]) -> None:
                i = index.get(path)
                if i is None:
                    return

                def change(job: dict[str, Any]) -> None:
                    f = job["files"][i]
                    if event == "start":
                        f["state"] = "reading"
                        job["active"] = i
                    elif event == "page":
                        f["page"], f["pages"] = info["page"], info["total"]
                    elif event == "structuring":
                        f["state"] = "structuring"
                    elif event == "done":
                        f["state"] = "done"
                        f["pages"] = info.get("pages", f["pages"])
                        f["page"] = f["pages"] or f["page"]
                    elif event == "failed":
                        f["state"], f["error"] = "failed", info.get("error")
                    elif event == "cancelled":
                        f["state"] = "cancelled"

                self._update(job_id, change)

            try:
                report = add(paths, progress=progress, cancel=self._cancel[job_id])
                result = finish(report)
            except Exception as exc:  # noqa: BLE001 - the job reports it; the server keeps running
                error = f"{type(exc).__name__}: {exc}"
                self._update(
                    job_id,
                    lambda j: j.update(state="failed", finished=time.time(), active=None, result={"error": error}),
                )
                return
        by_path = {str(Path(d["path"]).resolve()): d["id"] for d in result.get("documents", [])}

        def end(job: dict[str, Any]) -> None:
            states = {f["state"] for f in job["files"]}
            for i, path in enumerate(paths):
                if job["files"][i]["state"] == "done":
                    job["files"][i]["doc_id"] = by_path.get(str(path.resolve()))
            if "cancelled" in states:
                job["state"] = "cancelled"
            elif "failed" in states:
                job["state"] = "partial" if "done" in states else "failed"
            else:
                job["state"] = "completed"
            job.update(finished=time.time(), active=None, result=result)

        self._update(job_id, end)
        with contextlib.suppress(KeyError):
            self._paths[job_id] = [p for p in self._paths[job_id] if p.exists()]

    def _update(self, job_id: str, change: Callable[[dict[str, Any]], Any]) -> None:
        with self._changed:
            job = self._jobs.get(job_id)
            if job is None:
                return
            change(job)
            job["version"] += 1
            self._changed.notify_all()
