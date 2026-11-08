"""errors: the exit-code vocabulary of diagnose (lead decision §2.8) and replay (02 §6.10)."""

from __future__ import annotations

import pickle
from pathlib import Path

import pytest

from veyltrace_core.errors import (
    CASE_REJECT_REASONS,
    ArtifactMissing,
    CaseRejected,
    CassetteMiss,
    ChainBroken,
    ConfigError,
    ContractValidationError,
    DiagnoseExit,
    EnvironmentDrift,
    HashMismatch,
    InputChanged,
    NarrativeMismatch,
    NoAlert,
    ReplayExit,
    StepFailed,
    UsageError,
    VeyltraceError,
    exit_code_for,
)


def test_exit_code_values() -> None:
    assert [int(c) for c in DiagnoseExit] == [0, 1, 2, 3, 4, 7]
    assert DiagnoseExit.INPUTS_MISSING is DiagnoseExit.REJECTED
    assert [int(c) for c in ReplayExit] == [0, 1, 2, 3, 4, 5, 6]


ALL_ERRORS: list[tuple[VeyltraceError, int, int]] = [
    # (instance, diagnose exit, replay exit)
    (VeyltraceError("x"), 1, 1),
    (UsageError("bad flag"), 2, 1),
    (ConfigError("unknown key"), 4, 4),
    (ArtifactMissing("slate", Path("run/slate.json")), 3, 3),
    (ContractValidationError("slate", "bad"), 1, 1),
    (CaseRejected("no_hint"), 3, 3),
    (NoAlert("no breach"), 7, 3),
    (CassetteMiss("abc123"), 3, 2),
    (EnvironmentDrift("numpy differs"), 1, 5),
    (ChainBroken(4), 1, 3),
    (HashMismatch("verdict_hash", "a", "b"), 1, 2),
    (InputChanged("telemetry.metrics", "a", "b"), 3, 3),
    (NarrativeMismatch("card.md", "a", "b"), 1, 6),
]


@pytest.mark.parametrize(("exc", "diagnose", "replay"), ALL_ERRORS, ids=lambda v: type(v).__name__)
def test_exit_codes(exc: VeyltraceError, diagnose: int, replay: int) -> None:
    assert exit_code_for(exc) == diagnose
    assert exit_code_for(exc, "diagnose") == diagnose
    assert exit_code_for(exc, "replay") == replay


@pytest.mark.parametrize(("exc", "diagnose", "replay"), ALL_ERRORS, ids=lambda v: type(v).__name__)
def test_errors_pickle_round_trip(exc: VeyltraceError, diagnose: int, replay: int) -> None:
    clone = pickle.loads(pickle.dumps(exc))
    assert type(clone) is type(exc)
    assert str(clone) == str(exc)
    assert exit_code_for(clone, "replay") == replay


def test_non_veyltrace_errors_exit_one() -> None:
    assert exit_code_for(RuntimeError("boom")) == 1
    assert exit_code_for(KeyError("k"), "replay") == 1


def test_step_failed_unwraps_to_its_cause() -> None:
    inner = ConfigError("bad threads")
    wrapped = StepFailed("signalyth", inner)
    assert wrapped.__cause__ is inner
    assert wrapped.step == "signalyth"
    assert exit_code_for(wrapped) == 4
    assert exit_code_for(StepFailed("pipeline", wrapped), "replay") == 4
    assert exit_code_for(StepFailed("anomara", ValueError("x"))) == 1
    assert "signalyth" in str(wrapped)
    assert "ConfigError" in str(wrapped)


def test_artifact_missing_is_a_file_not_found_error() -> None:
    exc = ArtifactMissing("slate", "runs/x/slate.json")
    assert isinstance(exc, FileNotFoundError)
    assert exc.name == "slate"
    assert exc.path == Path("runs/x/slate.json")
    assert exc.filename == str(Path("runs/x/slate.json"))
    with pytest.raises(FileNotFoundError):
        raise exc


def test_contract_validation_error_is_a_value_error() -> None:
    exc = ContractValidationError("verdict", "verdict_hash mismatch")
    assert isinstance(exc, ValueError)
    assert (exc.name, exc.detail) == ("verdict", "verdict_hash mismatch")


@pytest.mark.parametrize("reason", CASE_REJECT_REASONS)
def test_case_rejected_reasons(reason: str) -> None:
    exc = CaseRejected(reason, "detail")  # pyright: ignore[reportArgumentType]  # str from the tuple
    assert exc.reason == reason
    assert reason in str(exc)


def test_case_rejected_unknown_reason() -> None:
    with pytest.raises(ValueError, match="unknown case rejection reason"):
        CaseRejected("because")  # pyright: ignore[reportArgumentType]  # deliberate: tests the runtime guard


def test_case_reject_vocabulary() -> None:
    assert CASE_REJECT_REASONS == (
        "no_hint",
        "hint_outside_span",
        "empty_window",
        "no_telemetry",
        "invalid_name",
        "invalid_capture",
        "unsupported_format",
    )


def test_cassette_miss_is_a_key_error_with_a_readable_message() -> None:
    exc = CassetteMiss("req-sha")
    assert isinstance(exc, KeyError)
    assert str(exc) == "no cassette entry for request req-sha"


def test_chain_broken_carries_seq() -> None:
    exc = ChainBroken(3, "line_hash does not match")
    assert exc.seq == 3
    assert "seq 3" in str(exc)
