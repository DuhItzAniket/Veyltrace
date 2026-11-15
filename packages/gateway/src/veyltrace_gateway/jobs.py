"""The job runner (06 §2): one worker thread and a FIFO queue in front of `run_case`.

One worker: a run may use 3 GB of RAM and the LLM runtime has one slot (02 §9). The run id is
computed first, from core's public pieces as `pipeline.execute` does (02 §4.1), so `POST /runs` is
idempotent. A job is `run_case` on disk (package rule 1); a finished run is its directory.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from veyltrace_core.config import resolve_config
from veyltrace_core.hashing import sha256_bytes
from veyltrace_core.ids import AIMode
from veyltrace_core.ids import run_id as make_run_id
from veyltrace_core.pipeline import StepEvent, code_commit, run_case
from veyltrace_core.steps import STEPS

__all__ = ["Job", "JobRunner", "JobState"]

JobState = Literal["queued", "running", "done", "failed"]


@dataclass
class Job:
    """One requested run. `events` are the step events in order (the SSE stream replays them)."""

    run_id: str
    dataset: str
    case_id: str
    ai_mode: AIMode
    state: JobState = "queued"
    step: int = 0
    step_name: str = STEPS[0].name
    error: str | None = None
    events: list[dict[str, Any]] = field(default_factory=lambda: [])
    finished: threading.Event = field(default_factory=threading.Event)


class JobRunner:
    """FIFO runner with one worker thread, started on the first submit."""

    def __init__(self, runs_root: Path, *, commit: str | None = None, config_dir: Path | None = None) -> None:
        self._root, self._commit, self._config_dir = runs_root, commit, config_dir
        self._queue: queue.Queue[Job] = queue.Queue()
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def plan_run_id(self, case_id: str, ai_mode: AIMode, dataset: str) -> str:
        """The run id `run_case` will use (02 §4.1), as `pipeline.execute` computes it."""
        resolved = resolve_config({}, config_dir=self._config_dir, dataset=dataset, ai_mode=ai_mode)
        commit = self._commit if self._commit is not None else code_commit()[0]
        return make_run_id(case_id, sha256_bytes(resolved.lock_bytes()), commit, ai_mode)

    def get(self, run_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(run_id)

    def jobs(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.run_id)

    def submit(self, dataset: str, case_id: str, ai_mode: AIMode, run_id: str) -> Job:
        """Queue a run, or return the job already queued, running or failed under `run_id`
        (a failed one is queued again)."""
        with self._lock:
            job = self._jobs.get(run_id)
            if job is not None and job.state != "failed":
                return job
            job = Job(run_id=run_id, dataset=dataset, case_id=case_id, ai_mode=ai_mode)
            self._jobs[run_id] = job
            if self._worker is None:
                self._worker = threading.Thread(target=self._work, name="veyltrace-jobs", daemon=True)
                self._worker.start()
        self._queue.put(job)
        return job

    def _work(self) -> None:
        while True:
            self._run(self._queue.get())

    def _run(self, job: Job) -> None:
        def progress(event: StepEvent) -> None:
            with self._lock:
                job.step, job.step_name = event.index, event.name
                job.events.append({"step": event.index, "step_name": event.name, "event": event.event})

        with self._lock:
            job.state = "running"
        plan: dict[str, Any] = {"runs_root": self._root, "config_dir": self._config_dir}
        if self._commit is not None:
            plan["code_commit"] = self._commit
        try:
            summary = run_case(job.dataset, job.case_id, job.ai_mode, {}, progress=progress, **plan)
            ok, error = summary.outcome == "ok", summary.reason
            if ok and summary.run_id != job.run_id:  # the id contract of 02 §4.1 broke: say so
                ok, error = False, f"run id {summary.run_id} differs from the planned {job.run_id}"
        except Exception as exc:  # any failure is the job's, never the worker thread's
            ok, error = False, f"{type(exc).__name__}: {exc}"
        with self._lock:
            job.state, job.error = ("done", None) if ok else ("failed", error or "the run failed")
            job.events.append({"step": job.step, "step_name": job.step_name, "event": job.state})
        job.finished.set()
