"""Normal windows of 04 §5.4 item 6 (R-13, #393): RCAEval pre-injection segments.

`dataset.normal_windows: rcaeval_pre_injection` adds, for every fault case of an RCAEval part, a
run of the same case under the oracle protocol with `alert.shift_s = -510`: t_alert = t_inject -
510 s, so the incident window [t_alert - 2 min, t_alert + 8 min] ends 30 s before injection. Core's
alert step clamps the baseline to the data start (03 §2.6 `windows.baseline`); a window left with
less than 60 s of baseline is dropped (no row, no fit). The window has no truth: it is scored like
a no-fault case (null hits), belongs to its case's cluster and fold (item 1), enters the tau_nf fit
of that fold as source `rcaeval_pre_injection` and the held-out false-alarm rate of the other.
Only verdict-scored (`veyltrace`) methods run windows: nothing else has a NO_FAULT status.
`veyllab` (VeylLab no-fault captures) is not run until VeylLab data exists (X-11, O-07).
"""

from __future__ import annotations

from pathlib import Path

from veyltrace_bench.experiment import Experiment
from veyltrace_contracts.models import Alert, AnswerKeyRow
from veyltrace_core import io
from veyltrace_core.errors import ArtifactMissing, ConfigError, ContractValidationError

PRE_INJECTION = "rcaeval_pre_injection"  # 04 §9 dataset.normal_windows value
SHIFT_S = -510  # 04 §5.4 item 6: the incident window ends 30 s before injection
VARIANT = f"shift{SHIFT_S}"  # bench_result.variant of a window (03 §13.2 example "shift-510")
MIN_BASELINE_S = 60  # 04 §5.4 item 6: segments with < 60 s of baseline are dropped
EMPTY_WINDOW = "empty_window"  # core's CaseRejected reason for a window without data (core alert step)
NS_PER_S = 1_000_000_000
#: RCAEval benchmarks: dataset ids `re1-*`, `re2-*`, `re3-*` (04 §3).
RCAEVAL_BENCHMARKS = ("re1", "re2", "re3")


def check(exp: Experiment) -> None:
    """Windows are defined for the unshifted oracle protocol over RCAEval parts only (item 6); a
    transfer fit always fits its source parts with their windows (item 7), whatever
    `dataset.normal_windows` says about the experiment's own (test) parts."""
    p = exp.protocol
    unshifted = p.alert == "oracle" and p.shift_s == 0
    if exp.split.scheme == "transfer" and exp.calibration.fit and not unshifted:
        raise ConfigError("a transfer fit's source windows need protocol.alert oracle and shift_s 0")
    if exp.dataset.normal_windows != PRE_INJECTION:
        return
    if not unshifted:
        raise ConfigError("normal_windows rcaeval_pre_injection needs protocol.alert oracle and shift_s 0")
    if not any(has_windows(d) for d in exp.dataset.parts):
        raise ConfigError(
            f"normal_windows rcaeval_pre_injection needs an RCAEval part, got {list(exp.dataset.parts)}"
        )


def has_windows(dataset: str) -> bool:
    return dataset.partition("-")[0] in RCAEVAL_BENCHMARKS


def pre_injection(keys: list[AnswerKeyRow]) -> list[AnswerKeyRow]:
    """The cases that have a pre-injection window: the fault cases of RCAEval parts."""
    return [k for k in keys if not k.is_no_fault and has_windows(k.dataset)]


def windows_of(exp: Experiment, keys: list[AnswerKeyRow]) -> list[AnswerKeyRow]:
    """The experiment's own cases that get a window, when it asks for them."""
    return pre_injection(keys) if exp.dataset.normal_windows == PRE_INJECTION else []


def dropped(run_dir: Path | None, reason: str | None) -> bool:
    """A window is dropped, not counted as a false alarm, when its clamped baseline is too short or
    core rejected it for an empty window (no data before the injection)."""
    return reason == EMPTY_WINDOW or too_short(run_dir)


def too_short(run_dir: Path | None) -> bool:
    """True when the window's clamped baseline is under MIN_BASELINE_S; a run without alert.json
    (rejected before the alert step) is kept, so its failure is counted, never hidden."""
    if run_dir is None:
        return False
    try:
        alert = io.read_model("alert", run_dir, Alert)
    except (ArtifactMissing, ContractValidationError):
        return False
    start, end = alert.windows.baseline
    return end - start < MIN_BASELINE_S * NS_PER_S
