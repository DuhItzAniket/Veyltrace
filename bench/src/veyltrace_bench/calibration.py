"""Calibration fits of 04 §5.4 (R-13, #375): q̂ at alpha and τ_nf at beta, one file per family id.

A calibration run is a fault case or a normal window of the calibration fold, run through the full
pipeline uncalibrated with the arm and alert protocol of the runs the file will serve (09 §3.7
rule 1). Neither score depends on the calibration: V, so the nonconformity, and M are computed
before q̂ and τ_nf are applied. A fault case's score is the true root's `nonconformity` in
`verdict.ranked` after the coarse name transform (`-db` stripped; the smaller of two matches), +∞
outside the decision pool or without a verdict (09 §3.7 rule 2). A normal window's statistic is
09 §3.8's M, computed by Causentra's own code from the finished run. A window Causentra could
never declare NO_FAULT (a failed or timed-out run, M undefined because no robust_z atom exists, or
a silent service) scores +inf and stays in m, as a root outside the pool does for q-hat (ADR
20261121-ak-calibration-fit-conventions); an unranked fault-case run scores +inf (04 §7).

q̂ = the ⌈(n + 1)(1 - alpha)⌉-th smallest score, null (+∞) past n; τ_nf = the ⌈(m + 1)(1 - beta)⌉-th
smallest M, else (index past m, or that M is +inf) `no_fault.default_tau` with calibrated false
(09 §3.7–§3.8). The file holds no
label or case id (03 §12.1): `split.cases_sha256` hashes the sorted `case_id[/variant]` of the runs
that entered the fit, `scores_sha256` the sorted scores (+∞ as null), `config_sha256` their config
(the hash of the sorted distinct ones if the parts differ).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from veyltrace_bench.metrics import coarse_service
from veyltrace_causentra.config import config_from
from veyltrace_causentra.inputs import DECIMALS, load_inputs
from veyltrace_causentra.outcome import no_fault_statistic, silent_service
from veyltrace_contracts.models import Calibration, RunManifest, Verdict
from veyltrace_core import io
from veyltrace_core.calibration import make_family_id
from veyltrace_core.config import ResolvedConfig
from veyltrace_core.context import RunContext
from veyltrace_core.hashing import sha256_json

CAUSENTRA = "causentra"
LOCK = "config.lock.json"  # the run's resolved config (03 §12.2), which Causentra read
#: Why a normal window scores +inf: Causentra could never declare it NO_FAULT (09 §3.8).
FAILED, NO_M, SILENT = "failed", "no_m", "silent"
#: Normal-window sources (03 §12.1 no_fault.sources): synth's and VeylLab's no-fault cases, and
#: RCAEval pre-injection segments (04 §5.4 item 6).
SYNTH_05, VEYLLAB, PRE_INJECTION = "synth-05", "veyllab", "rcaeval_pre_injection"
NO_FAULT = "NO_FAULT"  # the verdict status a normal window should get (03 §1)
POOLED = "pooled"  # held_out_rates: every fold of a (method, seed) together


@dataclass(frozen=True)
class CalibrationRun:
    """One run of the calibration fold: a fault case (`score`) or a normal window (`source`,
    `statistic`: M, or +inf with the `never` reason when Causentra could never call it NO_FAULT)."""

    case_id: str
    variant: str | None
    score: float | None = None
    source: str | None = None
    statistic: float | None = None
    never: str | None = None  # FAILED, NO_M or SILENT for a +inf window

    @property
    def key(self) -> str:
        return self.case_id if self.variant is None else f"{self.case_id}/{self.variant}"


def window_source(dataset: str) -> str | None:
    """The normal-window source of a no-fault case of `dataset` (03 §12.1), None for others."""
    if dataset == "synth":
        return SYNTH_05
    return VEYLLAB if dataset.startswith(f"{VEYLLAB}-") else None


def root_score(verdict: Verdict | None, root_service: str, *, unranked: bool = False) -> float:
    """The calibration score of a fault case (09 §3.7 rule 2); +inf outside the pool, with no verdict,
    or for an unranked run (no ranker scored any candidate: a miss, 04 §7)."""
    if verdict is None or unranked:
        return math.inf
    root = coarse_service(root_service)
    found = [r.nonconformity for r in verdict.ranked if coarse_service(r.service) == root]
    return min(found) if found else math.inf


def window(case_id: str, variant: str | None, source: str, run_dir: Path | None) -> CalibrationRun:
    """A normal window of the fit: M of its finished run, or +inf when Causentra could never call it
    NO_FAULT (`run_dir` None: the run failed or timed out)."""
    if run_dir is None:
        return CalibrationRun(case_id, variant, source=source, statistic=math.inf, never=FAILED)
    m, silent = run_statistic(run_dir)
    if m is None or silent:
        return CalibrationRun(
            case_id, variant, source=source, statistic=math.inf, never=NO_M if m is None else SILENT
        )
    return CalibrationRun(case_id, variant, source=source, statistic=m)


def never_counts(runs: Iterable[CalibrationRun]) -> dict[str, int]:
    """How many windows of a fit scored +inf, per reason (logged next to the fit)."""
    got = [r.never for r in runs]
    return {f"n_{reason}": got.count(reason) for reason in (FAILED, NO_M, SILENT)}


def run_statistic(run_dir: Path) -> tuple[float | None, bool]:
    """(M, a silent service) of a finished run, by Causentra's code over the run's own inputs and
    locked config; M is None when no robust_z atom exists."""
    manifest = io.read_model("run_manifest", run_dir, RunManifest)
    resolved = ResolvedConfig.from_lock(run_dir / LOCK)
    engine = resolved.engine(CAUSENTRA)
    ctx = RunContext(
        case_id=manifest.case_id,
        run_id=manifest.run_id,
        dataset=manifest.dataset,
        run_dir=run_dir,
        ai_mode=manifest.ai.mode,
        engine=CAUSENTRA,
        config=engine,
        step=CAUSENTRA,
        resolved=resolved,
    )
    inp = load_inputs(ctx, config_from(engine, engine.core))
    return no_fault_statistic(inp), silent_service(inp)


def rank_index(n: int, level: float) -> int:
    """⌈(n + 1)(1 - level)⌉, rounded at 9 decimals first so 10 × 0.9 is 9, not 9.000000000000002."""
    return math.ceil(round((n + 1) * (1 - level), DECIMALS))


def kth(values: Sequence[float], index: int) -> float | None:
    """The index-th smallest value (1-based), None past the end."""
    return sorted(values)[index - 1] if 1 <= index <= len(values) else None


def _hash_scores(scores: Iterable[float]) -> str:
    return sha256_json([None if math.isinf(s) else s for s in sorted(scores)])


def fit(
    runs: Sequence[CalibrationRun],
    *,
    family: str,
    ai_arm: str,
    alert_protocol: str,
    fold: str,
    alpha: float,
    beta: float,
    default_tau: float,
    seed: int,
    config_sha256s: Iterable[str],
    code_commit: str,
    experiment_id: str,
) -> Calibration:
    """The calibration content of one family id from its calibration runs (09 §3.7–§3.8)."""
    scores = [r.score for r in runs if r.score is not None]
    windows = [r for r in runs if r.source is not None and r.statistic is not None]
    stats = [s if math.isinf(s) else round(s, DECIMALS) for r in windows if (s := r.statistic) is not None]
    q_index, m_index = rank_index(len(scores), alpha), rank_index(len(stats), beta)
    q_hat = kth(scores, q_index)
    tau = kth(stats, m_index)
    if tau is not None and math.isinf(tau):
        tau = None  # more than beta of the windows could never be NO_FAULT: no finite threshold
    configs = sorted(set(config_sha256s))
    return Calibration.model_validate(
        {
            "schema_version": io.contract_info("calibration").version,
            "family": make_family_id(family, ai_arm, alert_protocol, fold),
            "ai_arm": ai_arm,
            "alert_protocol": alert_protocol,
            "alpha": alpha,
            "n": len(scores),
            "rank_index": q_index,
            "q_hat": None if q_hat is None or math.isinf(q_hat) else q_hat,
            "no_fault": {
                "beta": beta,
                "m": len(stats),
                "rank_index": m_index,
                "tau_nf": default_tau if tau is None else tau,
                "calibrated": tau is not None,
                "sources": sorted({r.source for r in windows if r.source is not None}),
            },
            "split": {"seed": seed, "fold": fold, "cases_sha256": sha256_json(sorted(r.key for r in runs))},
            "scores_sha256": _hash_scores(scores),
            "config_sha256": configs[0] if len(configs) == 1 else sha256_json(configs),
            "code_commit": code_commit,
            "experiment_id": experiment_id,
        }
    )


def _share(hits: Sequence[bool]) -> float | None:
    return math.fsum(1.0 for h in hits if h) / len(hits) if hits else None


def held_out_rates(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """Held-out coverage and NO_FAULT false-alarm rate per (method, seed, fold), and pooled over
    folds, from per_case.csv rows (04 §7; R-12 acceptance, #37). Coverage = share of fault rows
    (those with a truth, `hit_at_1` set) whose root is in the set, an empty `in_set` a miss (failed
    runs count, 04 §7); false-alarm rate = share of no-truth rows (normal windows, no-fault cases)
    not declared NO_FAULT. Rows without a fold (split none) are not held out and are skipped."""
    groups: dict[tuple[str, int | None, str], list[Mapping[str, object]]] = {}
    for row in rows:
        if (fold := row.get("fold")) is None:
            continue
        seed = row.get("seed")
        for f in (str(fold), POOLED):
            groups.setdefault((str(row["method"]), seed if isinstance(seed, int) else None, f), []).append(
                row
            )
    out: list[dict[str, object]] = []
    for (method, seed, fold), members in sorted(
        groups.items(), key=lambda g: (g[0][0], g[0][1] or 0, g[0][2])
    ):
        fault = [r["in_set"] is True for r in members if r.get("hit_at_1") is not None]
        normal = [r.get("status") != NO_FAULT for r in members if r.get("hit_at_1") is None]
        out.append(
            {"method": method, "seed": seed, "fold": fold, "n_fault": len(fault), "coverage": _share(fault)}
            | {"n_normal": len(normal), "false_alarm_rate": _share(normal)}
        )
    return out
