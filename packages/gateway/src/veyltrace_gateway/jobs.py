"""The job runner (06 §2): one worker thread and a FIFO queue in front of `run_case`.

One worker: a run may use 3 GB of RAM and the LLM runtime has one slot (02 §9). The run id is
computed first with core's `plan_run_id` (02 §4.1), so `POST /runs` is idempotent. A job is
`run_case` on disk (package rule 1); a finished run is its directory.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from veyltrace_core.ids import AIMode
from veyltrace_core.pipeline import StepEvent, plan_run_id, run_case
from veyltrace_core.steps import STEPS

__all__ = ["Job", "JobRunner", "JobState", "ReplayJob"]

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


@dataclass
class ReplayJob:
    """One replay of a finished run's receipt (06 §3.2): the replay command's exit code (0-6)."""

    run_id: str
    state: JobState = "queued"
    exit_code: int | None = None
    error: str | None = None
    finished: threading.Event = field(default_factory=threading.Event)


class JobRunner:
    """FIFO runner with one worker thread, started on the first submit."""

    def __init__(self, runs_root: Path, *, commit: str | None = None, config_dir: Path | None = None) -> None:
        self._root, self._commit, self._config_dir = runs_root, commit, config_dir
        self._queue: queue.Queue[Callable[[], None]] = queue.Queue()  # runs and replays, in order
        self._jobs: dict[str, Job] = {}
        self._replays: dict[str, ReplayJob] = {}
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def plan_run_id(self, case_id: str, ai_mode: AIMode, dataset: str) -> str:
        """The run id `run_case` will use for this job (02 §4.1)."""
        return plan_run_id(dataset, case_id, ai_mode, {}, **self._plan())

    def _plan(self) -> dict[str, Any]:
        """The `run_case` plan of every job; `plan_run_id` needs the same one."""
        plan: dict[str, Any] = {"runs_root": self._root, "config_dir": self._config_dir}
        if self._commit is not None:
            plan["code_commit"] = self._commit
        return plan

    def get(self, run_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(run_id)

    def jobs(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.run_id)

    def submit(self, dataset: str, case_id: str, ai_mode: AIMode, run_id: str) -> Job:
        """Queue a run, or return the job already queued or running under `run_id`. An ended job is
        replaced: the caller found no finished run, so it failed or its directory lost the receipt."""
        with self._lock:
            job = self._jobs.get(run_id)
            if job is not None and job.state in ("queued", "running"):
                return job
            job = Job(run_id=run_id, dataset=dataset, case_id=case_id, ai_mode=ai_mode)
            self._jobs[run_id] = job
            self._start()
        self._queue.put(lambda: self._run(job))
        return job

    def replay(self, run_id: str) -> ReplayJob | None:
        with self._lock:
            return self._replays.get(run_id)

    def submit_replay(self, run_id: str, receipt: Path, command: Callable[[list[str]], int]) -> ReplayJob:
        """Queue `command([receipt])` (the replay entry point) unless one is queued or running."""
        with self._lock:
            job = self._replays.get(run_id)
            if job is not None and job.state in ("queued", "running"):
                return job
            job = ReplayJob(run_id=run_id)
            self._replays[run_id] = job
            self._start()
        self._queue.put(lambda: self._replay(job, receipt, command))
        return job

    def _start(self) -> None:
        if self._worker is None:  # caller holds the lock
            self._worker = threading.Thread(target=self._work, name="veyltrace-jobs", daemon=True)
            self._worker.start()

    def _work(self) -> None:
        while True:
            self._queue.get()()

    def _replay(self, job: ReplayJob, receipt: Path, command: Callable[[list[str]], int]) -> None:
        with self._lock:
            job.state = "running"
        try:
            code, error = int(command([str(receipt)])), None
        except Exception as exc:  # any failure is the replay's, never the worker thread's
            code, error = None, f"{type(exc).__name__}: {exc}"
        with self._lock:
            job.state, job.exit_code, job.error = ("done" if code is not None else "failed"), code, error
        job.finished.set()

    def _run(self, job: Job) -> None:
        def progress(event: StepEvent) -> None:
            with self._lock:
                job.step, job.step_name = event.index, event.name
                job.events.append({"step": event.index, "step_name": event.name, "event": event.event})

        with self._lock:
            job.state = "running"
        try:
            summary = run_case(job.dataset, job.case_id, job.ai_mode, {}, progress=progress, **self._plan())
            ok, error = summary.outcome == "ok", summary.reason
            if ok and summary.run_id != job.run_id:  # the id contract of 02 §4.1 broke: say so
                ok, error = False, f"run id {summary.run_id} differs from the planned {job.run_id}"
        except Exception as exc:  # any failure is the job's, never the worker thread's
            ok, error = False, f"{type(exc).__name__}: {exc}"
        with self._lock:
            job.state, job.error = ("done", None) if ok else ("failed", error or "the run failed")
            job.events.append({"step": job.step, "step_name": job.step_name, "event": job.state})
        job.finished.set()
