"""The shared error vocabulary of Veyltrace and the exit codes it maps to.

Every failure that crosses a package boundary is a `VeyltraceError`, so the pipeline, the CLI and
bench can turn it into a run outcome and an exit code without parsing messages. Each class has
two exit codes because the two commands that end a process speak different vocabularies:

- `exit_code`: `veyltrace diagnose` (M0 lead decision 2026-11-06): 0 ok, 1 error, 2 usage,
  3 case rejected or inputs missing, 4 config, 7 no alert.
- `replay_exit_code`: `veyltrace replay` (02 §6.10): 0 ok, 1 error, 2 verdict hash or agent-trace
  head mismatch, 3 inputs missing or changed, 4 invalid config, 5 environment drift,
  6 narrative mismatch only.

Exceptions not derived from `VeyltraceError` map to 1 in both. This module is a leaf: it imports
only the standard library, so every other core module may import it.
"""

from __future__ import annotations

import errno
from enum import IntEnum
from pathlib import Path
from typing import ClassVar, Literal, get_args

__all__ = [
    "CASE_REJECT_REASONS",
    "ArtifactMissing",
    "CaseRejectReason",
    "CaseRejected",
    "CassetteMiss",
    "ChainBroken",
    "Command",
    "ConfigError",
    "ContractValidationError",
    "DiagnoseExit",
    "EnvironmentDrift",
    "HashMismatch",
    "InputChanged",
    "NarrativeMismatch",
    "NoAlert",
    "ReplayExit",
    "RunDirUnavailable",
    "StepFailed",
    "UsageError",
    "VeyltraceError",
    "exit_code_for",
]


class DiagnoseExit(IntEnum):
    """Exit codes of `veyltrace diagnose` (M0 lead decision 2026-11-06)."""

    OK = 0
    ERROR = 1
    USAGE = 2
    REJECTED = 3  # case rejected (CaseRejected) ...
    INPUTS_MISSING = 3  # ... or a required input missing: one code, two names
    CONFIG = 4
    NO_ALERT = 7  # detected protocol, no breach; distinct from REJECTED so bench can tell them apart


class ReplayExit(IntEnum):
    """Exit codes of `veyltrace replay` (02 §6.10)."""

    OK = 0
    ERROR = 1
    HASH_MISMATCH = 2  # verdict_hash or agent_trace head differs
    INPUTS_CHANGED = 3  # stored inputs missing or changed
    CONFIG = 4  # invalid config
    ENV_DRIFT = 5  # Python major.minor, library versions or uv.lock differ
    NARRATIVE_MISMATCH = 6  # only the card narrative differs


Command = Literal["diagnose", "replay"]

#: Why a case is not run (core_api_spec §4). Infralume's InvalidCase / InvalidName / InvalidCapture /
#: UnsupportedFormat subclass CaseRejected with one of these reasons.
CaseRejectReason = Literal[
    "no_hint",
    "hint_outside_span",
    "empty_window",
    "no_telemetry",
    "invalid_name",
    "invalid_capture",
    "unsupported_format",
]
CASE_REJECT_REASONS: tuple[str, ...] = get_args(CaseRejectReason)


class VeyltraceError(Exception):
    """Base class of every Veyltrace failure; carries the exit codes the CLI returns for it."""

    exit_code: ClassVar[int] = DiagnoseExit.ERROR
    replay_exit_code: ClassVar[int] = ReplayExit.ERROR


class UsageError(VeyltraceError):
    """Bad command-line usage (unknown flag combination, malformed `--set`).

    02 §6.10 defines no usage code for replay, so replay reports it as a plain error (1).
    """

    exit_code: ClassVar[int] = DiagnoseExit.USAGE
    replay_exit_code: ClassVar[int] = ReplayExit.ERROR


class ConfigError(VeyltraceError):
    """Invalid configuration: unknown key, bad value, remote LLM URL without opt-in, or a
    calibration file whose arm or protocol disagrees with the run (core_api_spec §4, §5)."""

    exit_code: ClassVar[int] = DiagnoseExit.CONFIG
    replay_exit_code: ClassVar[int] = ReplayExit.CONFIG


class ArtifactMissing(VeyltraceError, FileNotFoundError):
    """A contract file that a step needs is absent from the run directory.

    It is also a FileNotFoundError, so generic file-handling code that catches that keeps working.
    """

    exit_code: ClassVar[int] = DiagnoseExit.INPUTS_MISSING
    replay_exit_code: ClassVar[int] = ReplayExit.INPUTS_CHANGED

    def __init__(self, name: str, path: Path | str) -> None:
        self.name = name
        self.path = Path(path)
        FileNotFoundError.__init__(self, errno.ENOENT, f"artifact {name!r} is missing", str(self.path))

    def __reduce__(self) -> tuple[type[ArtifactMissing], tuple[str, Path]]:
        return (type(self), (self.name, self.path))


class ContractValidationError(VeyltraceError, ValueError):
    """Data does not satisfy its contract (schema, sort order, self-hash, Arrow schema)."""

    def __init__(self, name: str, detail: str) -> None:
        super().__init__(f"contract {name!r}: {detail}")
        self.name = name
        self.detail = detail

    def __reduce__(self) -> tuple[type[ContractValidationError], tuple[str, str]]:
        return (type(self), (self.name, self.detail))


class CaseRejected(VeyltraceError):
    """The case cannot be diagnosed as given (run outcome `rejected`, 03 §13.2).

    `reason` is one of CASE_REJECT_REASONS, so bench can tabulate rejections without parsing text.
    """

    exit_code: ClassVar[int] = DiagnoseExit.REJECTED
    # A receipted run was not rejected, so a rejection during replay means its inputs changed.
    replay_exit_code: ClassVar[int] = ReplayExit.INPUTS_CHANGED

    def __init__(self, reason: CaseRejectReason, detail: str = "") -> None:
        if reason not in CASE_REJECT_REASONS:
            msg = f"unknown case rejection reason {reason!r}; expected one of {CASE_REJECT_REASONS}"
            raise ValueError(msg)
        super().__init__(f"case rejected ({reason})" + (f": {detail}" if detail else ""))
        self.reason: CaseRejectReason = reason
        self.detail = detail

    def __reduce__(self) -> tuple[type[CaseRejected], tuple[CaseRejectReason, str]]:
        return (type(self), (self.reason, self.detail))


class NoAlert(VeyltraceError):
    """Under the detected protocol no entry service breached its threshold (run outcome `no_alert`)."""

    exit_code: ClassVar[int] = DiagnoseExit.NO_ALERT
    # A receipted run had an alert, so losing it during replay means its inputs changed.
    replay_exit_code: ClassVar[int] = ReplayExit.INPUTS_CHANGED


class CassetteMiss(VeyltraceError, KeyError):
    """An LLM request has no recorded response in the cassette (strict replay).

    In replay the agent asked something the recording never saw, so its trace differs (2). In
    `diagnose --ai replay` the cassette is an input that lacks an entry (3). `veyltrace_llm`
    subclasses this; core never imports `veyltrace_llm` (08 §5.2).
    """

    exit_code: ClassVar[int] = DiagnoseExit.INPUTS_MISSING
    replay_exit_code: ClassVar[int] = ReplayExit.HASH_MISMATCH

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key

    def __str__(self) -> str:
        # KeyError.__str__ shows repr(key); a message reads better in CLI output.
        return f"no cassette entry for request {self.key}"

    def __reduce__(self) -> tuple[type[CassetteMiss], tuple[str]]:
        return (type(self), (self.key,))


class EnvironmentDrift(VeyltraceError):
    """Replay runs under a different Python major.minor, library versions or uv.lock (02 §6.10)."""

    replay_exit_code: ClassVar[int] = ReplayExit.ENV_DRIFT


class ChainBroken(VeyltraceError):
    """An agent_trace hash chain fails verification at line `seq` (03 §9.2; 10-causivra §3).

    During a run this is a pipeline error (1: the receipt is refused). During replay the stored
    trace was altered, so the inputs changed (3).
    """

    replay_exit_code: ClassVar[int] = ReplayExit.INPUTS_CHANGED

    def __init__(self, seq: int, reason: str = "") -> None:
        super().__init__(f"agent_trace chain broken at seq {seq}" + (f": {reason}" if reason else ""))
        self.seq = seq
        self.reason = reason

    def __reduce__(self) -> tuple[type[ChainBroken], tuple[int, str]]:
        return (type(self), (self.seq, self.reason))


class HashMismatch(VeyltraceError):
    """Replay produced a different verdict_hash or agent_trace head than the receipt (02 §6.10)."""

    replay_exit_code: ClassVar[int] = ReplayExit.HASH_MISMATCH

    def __init__(self, name: str, expected: str, actual: str) -> None:
        super().__init__(f"{name}: expected {expected}, got {actual}")
        self.name = name
        self.expected = expected
        self.actual = actual

    def __reduce__(self) -> tuple[type[HashMismatch], tuple[str, str, str]]:
        return (type(self), (self.name, self.expected, self.actual))


class InputChanged(HashMismatch):
    """A stored input or upstream output no longer has the hash the receipt records (02 §6.10)."""

    exit_code: ClassVar[int] = DiagnoseExit.INPUTS_MISSING
    replay_exit_code: ClassVar[int] = ReplayExit.INPUTS_CHANGED


class NarrativeMismatch(HashMismatch):
    """Only the card narrative differs on replay; the verdict matches (02 §6.10)."""

    replay_exit_code: ClassVar[int] = ReplayExit.NARRATIVE_MISMATCH


class RunDirUnavailable(VeyltraceError):
    """The run directory (or its lock file) could not be created, cleared or locked: an OSError
    from the file system, e.g. a file where a directory should be, or a file Windows keeps open.
    Exit 1; the original OSError is the `__cause__`."""


class StepFailed(VeyltraceError):
    """A pipeline step raised; the runner wraps the error and keeps it as `__cause__`.

    The exit code is the wrapped error's (see exit_code_for), so a ConfigError raised inside an
    engine still exits 4.
    """

    def __init__(self, step: str, cause: BaseException) -> None:
        super().__init__(f"step {step!r} failed: {type(cause).__name__}: {cause}")
        self.step = step
        self.cause = cause
        self.__cause__ = cause

    def __reduce__(self) -> tuple[type[StepFailed], tuple[str, BaseException]]:
        return (type(self), (self.step, self.cause))


def exit_code_for(exc: BaseException, command: Command = "diagnose") -> int:
    """Return the process exit code for `exc` under `command`.

    StepFailed is unwrapped to the error it carries (repeatedly, if nested); any exception that is
    not a VeyltraceError is a plain error (1).
    """
    while isinstance(exc, StepFailed):
        exc = exc.cause
    if isinstance(exc, VeyltraceError):
        return int(exc.exit_code if command == "diagnose" else exc.replay_exit_code)
    return int(DiagnoseExit.ERROR)
