"""How the runner applies an experiment's calibration split (04 §5.4, §9; R-13, #376).

Bench chooses every run's calibration file through config overrides, so a run never depends on
which files happen to exist in `config/calibration/`: a calibration run, and every run of a
`split.scheme: none` experiment, is uncalibrated (no family, empty family map); a held-out run
names its family and the fold part of the file applied to it (`splits.FoldPlan.applied`). Only
`veyltrace` methods read the verdict's set and status; slate-scored and baseline methods take the
overrides of the full-pipeline run of their case (uncalibrated when the experiment fits, else the
applied file), so `causatrix:rrf` still shares `veyltrace:off`'s run (#172).

With `calibration.fit: true` a veyltrace method runs every case uncalibrated (the calibration
runs), the fits are written, and each held-out run restarts from `causentra` on its calibration
run's outputs with the applied file: q̂ and τ_nf change only Causentra's decision (09 §3.7), so
nothing upstream is computed twice. With `fit: false` each case runs once with a file an earlier
experiment wrote for the same `split.family` (perturbed runs, 04 §5.4 item 4); a missing file is
an error before the first case, never a silently uncalibrated run.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from veyltrace_bench import splits
from veyltrace_bench.experiment import CALIBRATION_KEYS, Experiment, MethodSpec
from veyltrace_contracts.models import AnswerKeyRow
from veyltrace_core.calibration import ai_arm_for, calibration_path, make_family_id
from veyltrace_core.config import CALIBRATION_DIRNAME, ResolvedConfig, find_config_dir
from veyltrace_core.errors import ConfigError

FAMILY_KEY, FAMILY_MAP_KEY, FOLD_KEY = CALIBRATION_KEYS
RESTART_STEP = "causentra"  # a held-out run re-runs from here on its calibration run (core reuse_dir)
CALIBRATED_KIND = "veyltrace"  # the method kind whose verdict (set, status) the split serves
UNCALIBRATED: Mapping[str, object] = {FAMILY_KEY: None, FAMILY_MAP_KEY: {}}


@dataclass(frozen=True)
class Split:
    """The experiment's split as the runner uses it: the files' benchmark family, the fold plan,
    whether this experiment fits, and (transfer) the calibration cases outside its dataset parts."""

    family: str
    plan: splits.FoldPlan
    fit: bool
    fit_keys: Mapping[str, AnswerKeyRow]

    def held_out(self, case: str) -> Mapping[str, object]:
        """The overrides of a case's held-out run: the file fitted without its cluster."""
        return {FAMILY_KEY: self.family, FOLD_KEY: self.plan.applied[case]}

    def first_run(self, case: str) -> Mapping[str, object]:
        """The overrides of every method's only (or, when fitting, first) run of a case."""
        return UNCALIBRATED if self.fit else self.held_out(case)


def make_split(
    exp: Experiment, keys: Mapping[str, AnswerKeyRow], fit_keys: Mapping[str, AnswerKeyRow]
) -> Split | None:
    """The split of `exp` over its selected cases (`keys`); None for scheme none."""
    spec = exp.split
    splits.check_split(spec)
    if spec.scheme == "none":
        return None
    if spec.scheme == "crossfit2":
        plan = splits.crossfit2(keys, spec.seed)
    elif spec.scheme == "loso":
        plan = splits.loso(keys)
    else:
        plan = splits.transfer(keys, frozenset(fit_keys), str(spec.calibrate_from))
    return Split(str(spec.family), plan, exp.calibration.fit, fit_keys if spec.scheme == "transfer" else {})


def first_run(split: Split | None, case: str) -> Mapping[str, object]:
    """A case's first-run calibration overrides; scheme none is uncalibrated."""
    return UNCALIBRATED if split is None else split.first_run(case)


def calibration_dir() -> Path:
    """Where core selects calibration files and bench writes them (03 §12.1)."""
    return find_config_dir() / CALIBRATION_DIRNAME


def arm(method: MethodSpec, cfg: ResolvedConfig) -> str:
    """The calibration ai_arm of a method's runs (03 §12.1), by core's own rule."""
    got = ai_arm_for(method.ai.mode, cast("Mapping[str, Any]", cfg.engine("relentra")))
    if got is None:
        raise ConfigError(f"method {method.id}: AI mode {method.ai.mode} has no calibration ai_arm (03 §1)")
    return got


def family_id(split: Split, exp: Experiment, method_arm: str, fold: str) -> str:
    return make_family_id(split.family, method_arm, exp.protocol.alert, fold)


def check(exp: Experiment, split: Split, method: MethodSpec, cfg: ResolvedConfig) -> None:
    """Before any run: the method's Causentra levels equal the experiment's (a file fitted at another
    alpha or beta fails Causentra's step, 09 §3.15), and with `fit: false` every file it needs exists."""
    causentra = cast("Mapping[str, Any]", cfg.engine("causentra"))
    levels = (round(float(causentra["alpha"]), 9), round(float(causentra["no_fault"]["beta"]), 9))
    if levels != (round(exp.calibration.alpha, 9), round(exp.calibration.no_fault_beta, 9)):
        raise ConfigError(
            f"method {method.id}: causentra alpha/no_fault.beta {levels} differ from calibration "
            f"alpha/no_fault_beta ({exp.calibration.alpha}, {exp.calibration.no_fault_beta})"
        )
    if split.fit:
        return
    method_arm = arm(method, cfg)
    wanted = sorted({family_id(split, exp, method_arm, f) for f in split.plan.applied.values()})
    if missing := [f for f in wanted if not calibration_path(calibration_dir(), f).is_file()]:
        raise ConfigError(
            f"calibration.fit is false but config/calibration/ has no {missing}: run the experiment"
            f" that fits split.family {split.family} first (04 §5.4 item 4)"
        )


def fit_cases(split: Split, fold: str, ran: Iterable[str]) -> list[str]:
    """The cases of the fit for `fold` among the ones that ran, sorted."""
    return sorted(set(ran) & split.plan.fits[fold])
