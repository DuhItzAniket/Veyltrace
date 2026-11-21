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
from veyltrace_bench.answer_keys import load_answer_keys
from veyltrace_bench.experiment import CALIBRATION_KEYS, Experiment, MethodSpec, load_experiment, select_cases
from veyltrace_contracts.models import AnswerKeyRow
from veyltrace_core.calibration import ai_arm_for, calibration_path, load_calibration, make_family_id
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
    clusters: Mapping[str, splits.Cluster]  # each test case's 04 §5.4 cluster

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
    clusters = {c: splits.cluster_of(k) for c, k in keys.items()}
    outside = fit_keys if spec.scheme == "transfer" else {}
    return Split(str(spec.family), plan, exp.calibration.fit, outside, clusters)


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
    for family in wanted:
        _check_file(exp, split, family)


def _check_file(exp: Experiment, split: Split, family: str) -> None:
    """A reused file must come from the same seed and levels, and from a fold plan in which no test
    case it serves shares a cluster with its fit (ADR 20261121-ak-calibration-fit-conventions)."""
    content = load_calibration(calibration_path(calibration_dir(), family)).content
    where = f"calibration {family} (fitted by {content.experiment_id})"
    got = (content.split.seed, round(content.alpha, 9), round(content.no_fault.beta, 9))
    want = (exp.split.seed, round(exp.calibration.alpha, 9), round(exp.calibration.no_fault_beta, 9))
    if got != want:
        raise ConfigError(f"{where}: split.seed/alpha/beta {got} differ from this experiment's {want}")
    repo = find_config_dir().parent
    fitting = load_experiment(repo / "bench" / "experiments" / f"{content.experiment_id}.yaml")
    if (fitting.split.scheme, fitting.split.family, fitting.split.seed) != (
        exp.split.scheme,
        exp.split.family,
        content.split.seed,
    ):
        raise ConfigError(
            f"{where}: fitted under split {fitting.split} (the file says seed {content.split.seed})"
        )
    fold = content.split.fold
    if exp.split.scheme == "transfer":  # the fit cases are the source parts' (04 §5.4 item 7)
        fit_keys = transfer_keys(fitting, repo)
        fit_cases, fit_clusters = set(fit_keys), {splits.cluster_of(k) for k in fit_keys.values()}
    else:
        answers = {d: load_answer_keys(d) for d in fitting.dataset.parts}
        keys = {c: answers[d][c] for d, (cases, _) in select_cases(fitting, repo).items() for c in cases}
        plan = make_split(fitting, keys, {})
        if plan is None or fold not in plan.plan.fits:
            raise ConfigError(f"{where}: its fold {fold} is not in that experiment's plan")
        fit_keys = {c: keys[c] for c in plan.plan.fits[fold]}
        fit_cases, fit_clusters = set(fit_keys), {plan.clusters[c] for c in fit_keys}
        planned = set(plan.clusters.values())
        for case, applied in sorted(split.plan.applied.items()):
            if applied == fold and exp.split.scheme == "crossfit2" and split.clusters[case] not in planned:
                raise ConfigError(
                    f"{where}: test case {case}'s cluster {split.clusters[case]} is not in that plan; the"
                    " folds differ (same parts, cases and exclusions as the fitting experiment?)"
                )
    for case, applied in sorted(split.plan.applied.items()):
        if applied == fold and (case in fit_cases or split.clusters[case] in fit_clusters):
            raise ConfigError(f"{where}: test case {case}'s cluster {split.clusters[case]} is in its fit")
    faults = sum(not k.is_no_fault for k in fit_keys.values())
    if content.n != faults:  # an AI arm is fitted on its first seed only: n = fault cases
        raise ConfigError(
            f"{where}: n = {content.n}, but that plan's fold has {faults} fault cases;"
            " the fitting experiment's selection changed since the fit"
        )


def transfer_keys(exp: Experiment, repo: Path) -> dict[str, AnswerKeyRow]:
    """The calibration cases of a transfer fit: every case of the file's source parts except the
    experiment's exclusions (04 §5.4 item 7: all RE2-OB and RE2-TT cases but the development ones)."""
    parts = splits.TRANSFER_SOURCES[str(exp.split.calibrate_from)]
    source = exp.model_copy(
        update={"dataset": exp.dataset.model_copy(update={"parts": parts, "cases": "all"})}
    )
    source_keys = {d: load_answer_keys(d) for d in parts}
    return {c: source_keys[d][c] for d, (cases, _) in select_cases(source, repo).items() for c in cases}


def fit_cases(split: Split, fold: str, ran: Iterable[str]) -> list[str]:
    """The cases of the fit for `fold` among the ones that ran, sorted."""
    return sorted(set(ran) & split.plan.fits[fold])
