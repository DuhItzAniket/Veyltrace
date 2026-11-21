"""The runner behind `veyltrace bench run` (R-04, #67; the CLI over it is #14).

Every (case × method) of the experiment's dataset parts runs through core's public pipeline API
(`pipeline.run_case`, the entry `veyltrace diagnose` uses), so bench learns every outcome (ok,
failed, no_alert, rejected) from the RunSummary. Runs go to bench's own, emptied
`<runs root>/bench/<experiment_id>/`, so each is executed and timed: a reused run has no wall time,
which would turn a timeout (a miss, 04 §9) into ok and lose its cost (04 §6). The one exception is
a run another method of this experiment made with the same config and a different `kind` (e.g.
`causatrix:rrf` and `veyltrace:off`, #172): it is scored again with that run's time. Each run is a
child process (`veyltrace_bench.child`, #68): bench kills it at `resources.timeout_s` and records
its peak RSS. Baselines (R-05) run the pipeline through the alert step only, in their own runs
directory per method, so they read Infralume's tables and alert.json (the same t_alert as
Veyltrace, 04 §4): `simplerca` ranks in the child; `rcaeval:<m>` exports each case, then runs
RCAEval's main.py once per dataset in its own venv, and its report goes to `rcaeval/`. Results, in
`<results root>/<experiment_id>/`: per_case.csv (bench_result, 03 §13.2, through core io),
summary.json (bench_summary, 03 §13.3: the requested metrics per (dataset, system, method)) and
manifest.json (bench_manifest, 03 §13.4: experiment, code, uv.lock, answer-key, telemetry-input and
config hashes, run ids; 04 §9, §10.2), both written through core io (validated canonical JSON) and
byte-identical across invocations; only per_case.csv's wall_ms and peak_rss_mb differ. Under
`protocol.decoys` (RCAEval-C, #326) each case first gets its events overlay (`decoy_runs`), which
every method's run of it names.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from veyltrace_bench import (
    ALGO_VERSION,
    baselines,
    calibrated,
    calibration,
    decoy_runs,
    naive_change,
    normal_windows,
    rcaeval,
    simplerca,
    splits,
    upstream,
)
from veyltrace_bench.answer_keys import answer_key_path, load_answer_keys
from veyltrace_bench.child import after_run, restart
from veyltrace_bench.experiment import (
    OVERLAY_KEY,
    PROTOCOL_KEYS,
    RANKERS_KEY,
    Experiment,
    MethodSpec,
    code_state,
    load_experiment,
    select_cases,
    unsupported,
)
from veyltrace_bench.manifest_calibrations import recorded as recorded_calibrations
from veyltrace_bench.metrics import RUN_OUTCOMES, CaseScore, MethodOutput, Truth, score_case
from veyltrace_bench.stats_summary import Case, statistics
from veyltrace_bench.summary import entries as summary_entries
from veyltrace_bench.summary import summarize, with_rows
from veyltrace_contracts.models import (
    AnswerKeyRow,
    BenchResultRow,
    CaseManifest,
    Onsets,
    RunManifest,
    Slate,
    Verdict,
)
from veyltrace_core import io, textio
from veyltrace_core.calibration import write_calibration
from veyltrace_core.cli import THREAD_ENV
from veyltrace_core.config import ResolvedConfig, config_sha256, data_root, find_config_dir, resolve_config
from veyltrace_core.errors import (
    ArtifactMissing,
    ConfigError,
    ContractValidationError,
    UsageError,
    VeyltraceError,
)
from veyltrace_core.hashing import manifest_hash, sha256_file, sha256_text_lf
from veyltrace_core.log import get_logger
from veyltrace_core.pipeline import run_case, uv_lock_sha256
from veyltrace_core.pipeline import runs_root as default_runs_root
from veyltrace_core.steps import LAST_STEP

PRODUCER = f"bench@{ALGO_VERSION}"
RESULTS_DIR = ("bench", "results")  # default results root below the repo (04 §9)
BENCH_RUNS = "bench"  # bench's own subdirectory of the runs root, one directory per experiment
SYNTH = "synth"  # smoke cases, never reported (04 §3)
MS_PER_S = 1000.0
BASELINE_RUNS = "baselines"  # <bench runs>/baselines/<method>/: each baseline's own alert-step runs
RCAEVAL_WORK = "rcaeval"  # <bench runs>/rcaeval/<method>/<dataset>/: main.py's working directory
RCAEVAL_REPORTS = "rcaeval"  # <results>/<experiment>/rcaeval/<dataset>.<method>.txt: main.py stdout
INPUT_STEP = "alert"  # baselines read Infralume's tables and alert.json (03 §2), nothing later
DECOY_RUNS = "decoys"  # <bench runs>/decoys/: Infralume-only runs giving each case's services (#326)
SERVICES_STEP = "infralume"  # case_manifest.services, which RCAEval-C draws decoy entities from
BASELINE_KINDS = frozenset({"internal_baseline", "rcaeval"})
DETECTED = "detected"  # the alert protocol whose onset error is scored (04 §7 "Onset error")
#: Run each case in this process instead of a child: for tests that substitute `run_case` or
#: plugins here, which a child would not see. Such runs have no peak RSS and cannot be killed.
IN_PROCESS = False

_log = get_logger(__name__)
#: run_id -> (wall_ms, peak_rss_mb, the method kinds that scored it), for runs reused across kinds.
type Timed = dict[str, tuple[float, float | None, frozenset[str]]]


@dataclass(frozen=True)
class Executed:
    """One case run as bench sees it. run_id and run_dir are None for a run killed at the timeout."""

    outcome: str
    run_id: str | None
    run_dir: Path | None
    cached: bool
    wall_ms: float
    peak_rss_mb: float | None
    ranks: tuple[str, ...] | None = None  # a baseline's ranks (simplerca); None otherwise
    judged: bool = False  # outcome already judged per run against timeout_s (a held-out restart)
    reason: str | None = None  # core's rejection reason (RunSummary.reason), e.g. empty_window


def slug(method_id: str) -> str:
    """A method id as a directory name (`rcaeval:baro` -> `rcaeval-baro`)."""
    return method_id.replace(":", "-")


def child_command(request: Path, result: Path) -> list[str]:
    """The child process of one run (veyltrace_bench.child), in this interpreter's environment."""
    return [sys.executable, "-m", "veyltrace_bench.child", str(request), str(result)]


def _execute(
    key: AnswerKeyRow,
    method: MethodSpec,
    overrides: dict[str, object],
    runs_root: Path,
    timeout_s: int,
    baseline: dict[str, Any] | None = None,
) -> Executed:
    """Diagnose one case, in a child killed at `timeout_s` (#68), or in process (IN_PROCESS).
    `baseline` ({to_step, baseline?, export?}) stops the run early for a baseline, and
    {from_step, reuse_dir} restarts a held-out run on its calibration run (child.py)."""
    extra = baseline or {}
    if IN_PROCESS:
        cfg = resolve_config(overrides, dataset=key.dataset, ai_mode=method.ai.mode)  # as the child does
        start = time.perf_counter()
        step = cast("str", extra.get("to_step", LAST_STEP))
        s = run_case(
            key.dataset,
            key.case_id,
            method.ai.mode,
            config=cfg,
            runs_root=runs_root,
            to_step=step,
            **restart(extra),
        )
        ranks = after_run(extra, s)
        wall_ms = (time.perf_counter() - start) * MS_PER_S
        got = tuple(ranks) if ranks is not None else None
        return Executed(s.outcome, s.run_id, s.run_dir, s.cached, wall_ms, None, got, reason=s.reason)
    request = {
        "dataset": key.dataset,
        "case_id": key.case_id,
        "ai_mode": method.ai.mode,
        "overrides": overrides,
        "runs_root": str(runs_root),
        **extra,
    }
    env = {**os.environ, **{v: os.environ.get(v, "1") for v in THREAD_ENV}}  # as the CLI pins them
    with tempfile.TemporaryDirectory(prefix="veyltrace-bench-") as tmp:
        request_path, result_path = Path(tmp, "request.json"), Path(tmp, "result.json")
        textio.write_bytes(request_path, json.dumps(request).encode())
        start = time.perf_counter()
        try:  # on a timeout, subprocess.run kills the child and waits for it
            cmd = child_command(request_path, result_path)
            subprocess.run(
                cmd,
                cwd=find_config_dir().parent,
                env=env,
                stdout=subprocess.DEVNULL,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return Executed("timeout", None, None, False, (time.perf_counter() - start) * MS_PER_S, None)
        if not result_path.is_file():
            raise VeyltraceError(f"{key.case_id} ({method.id}): the bench child exited without a result")
        got = cast("dict[str, Any]", json.loads(textio.read_text(result_path)))
    if (error := got.get("error")) is not None:
        raise VeyltraceError(f"{key.case_id} ({method.id}): {error['type']}: {error['detail']}")
    s = cast("dict[str, Any]", got["summary"])
    ranks = cast("list[str] | None", got.get("ranks"))
    return Executed(
        str(s["outcome"]),
        str(s["run_id"]),
        Path(s["run_dir"]),
        bool(s["cached"]),
        float(got["wall_ms"]),
        float(got["peak_rss_mb"]),
        tuple(ranks) if ranks is not None else None,
        reason=cast("str | None", s.get("reason")),
    )


def protocol_overrides(
    exp: Experiment, overlay: str | None = None, variant: str | None = None
) -> dict[str, object]:
    """The protocol hooks as config overrides, with the case's events overlay if it has one; a
    normal window (`variant`) moves the oracle alert before the injection (04 §5.4 item 6)."""
    p = exp.protocol
    alert, shift, drop, _ = PROTOCOL_KEYS
    shift_s = normal_windows.SHIFT_S if variant == normal_windows.VARIANT else p.shift_s
    hooks: dict[str, object] = {alert: p.alert, shift: shift_s, drop: list(p.sources_drop)}
    return hooks | ({OVERLAY_KEY: overlay} if overlay is not None else {})


def overrides_for(
    exp: Experiment,
    method: MethodSpec,
    overlay: str | None = None,
    calibration_keys: Mapping[str, object] = calibrated.UNCALIBRATED,
    variant: str | None = None,
) -> dict[str, object]:
    """The run's config overrides: the protocol hooks, the calibration choice (`calibrated`), then
    the method's own keys (which may set neither)."""
    return {**protocol_overrides(exp, overlay, variant), **calibration_keys, **method.overrides}


def run_outcome(outcome: str, wall_ms: float, timeout_s: int) -> str:
    """bench_result.run_outcome: the run's own, or timeout past `timeout_s` (04 §9: a miss)."""
    return "timeout" if wall_ms > timeout_s * MS_PER_S else outcome


def slate_ranks(slate: Slate) -> tuple[str, ...]:
    """A slate-scored method's ranking (04 §3 `causatrix:*`): the top-K as `{service}_{indicator}`,
    then the rest of U in `all_scores` order (service only; RCAEval's coarse transform reads both)."""
    top = {c.service for c in slate.candidates}
    rest = (s.service for s in slate.all_scores if s.service not in top)
    return (*(f"{c.service}_{c.indicator}" for c in slate.candidates), *rest)


def method_output(
    outcome: str, verdict: Verdict | None, slate: Slate | None, *, slate_scored: bool = False
) -> MethodOutput:
    """A run as metrics input; without outputs its channels stay, empty, so they miss. A slate-scored
    method (kind causatrix) has no verdict: no pool, set or fault type (they belong to the verifier)."""
    if slate_scored:
        if slate is None:
            return MethodOutput(outcome=outcome, slate=())
        ranks = slate_ranks(slate)
        services = tuple(c.service for c in slate.candidates)
        return MethodOutput(
            outcome=outcome,
            ranks=ranks,
            rankers_active=tuple(slate.rankers_active),
            slate=services,
            slate_k=slate.k,
        )
    if verdict is None or slate is None:
        return MethodOutput(outcome=outcome, slate=(), pool=(), candidate_set=(), has_verdict=True)
    root = verdict.root
    return MethodOutput(
        outcome=outcome,
        ranks=tuple(verdict.ranks_rcaeval),
        rankers_active=tuple(slate.rankers_active),  # [] = unranked (R-00 stubs; metrics)
        slate=tuple(c.service for c in slate.candidates),
        pool=tuple(r.service for r in verdict.ranked),
        candidate_set=tuple(c.service for c in verdict.candidate_set),
        has_verdict=True,
        root_fault_class=root.fault_class if root is not None else None,
        root_mode=root.mode if root is not None else None,
        slate_k=slate.k,
        margin=verdict.confidence.margin,  # with the leader's fused score: risk-coverage (#405)
        leader_fused_score=verdict.ranked[0].fused_score if verdict.ranked else None,
    )


def check_rankers(exp: Experiment) -> None:
    """Each `causatrix:<ranker>` method names a configured ranker (07 §4), so a typo such as
    causatrix:baro_rz fails before the first case instead of mislabelling a result (04 §3)."""
    asked = sorted({m.ranker for m in exp.methods if m.ranker is not None})
    if not asked:
        return
    base = resolve_config({}, dataset=exp.dataset.parts[0], ai_mode="off").engine("causatrix")
    configured = set(cast("list[str]", base["rankers"]["enabled"]))
    if unknown := [r for r in asked if r not in configured]:
        raise ConfigError(f"methods name unknown rankers {unknown}: {RANKERS_KEY} is {sorted(configured)}")


def _read[M: (Verdict, Slate, CaseManifest, Onsets)](
    name: str, run_dir: Path | None, model: type[M]
) -> M | None:
    """A JSON output of the run, or None when the run did not write a valid one (or was killed)."""
    if run_dir is None:
        return None
    try:
        return io.read_model(name, run_dir, model)
    except (ArtifactMissing, ContractValidationError):
        return None


def _timed(
    exp: Experiment,
    method: MethodSpec,
    key: AnswerKeyRow,
    runs_root: Path,
    timed: Timed,
    baseline: dict[str, Any] | None = None,
    overlay: str | None = None,
    calibration_keys: Mapping[str, object] = calibrated.UNCALIBRATED,
    variant: str | None = None,
) -> Executed:
    """Diagnose one case with one method; a run another kind already made keeps that run's cost."""
    over = overrides_for(exp, method, overlay, calibration_keys, variant)
    done = _execute(key, method, over, runs_root, exp.resources.timeout_s, baseline)
    wall_ms, peak = done.wall_ms, done.peak_rss_mb
    kinds: frozenset[str] = frozenset()  # the method kinds that already scored this run
    if done.cached and done.run_id is not None:  # bench emptied its runs dir: another method ran it
        earlier = timed.get(done.run_id)
        if earlier is None or method.kind in earlier[2]:  # unknown time, or a duplicated method
            raise ConfigError(f"method {method.id} reuses run {done.run_id}: same config as another method")
        wall_ms, peak, kinds = earlier  # e.g. causatrix:rrf and veyltrace:off: one run, scored twice
    if done.run_id is not None:
        timed[done.run_id] = (wall_ms, peak, kinds | {method.kind})
    return replace(done, wall_ms=wall_ms, peak_rss_mb=peak)


def _restart(
    exp: Experiment,
    method: MethodSpec,
    key: AnswerKeyRow,
    first: Executed,
    split: calibrated.Split,
    root: Path,
    overlay: str | None,
    variant: str | None = None,
) -> Executed:
    """A held-out run: Causentra onwards on the calibration run's outputs with the applied file. Each
    run is judged against `timeout_s` on its own and the worse outcome kept; the cost is both runs'
    (wall times summed, the larger peak), since the prediction needed both (ADR
    20261121-ak-calibration-fit-conventions)."""
    if run_outcome(first.outcome, first.wall_ms, exp.resources.timeout_s) != "ok" or first.run_dir is None:
        return first  # nothing to restart: the calibration run's outcome is the case's
    over = overrides_for(exp, method, overlay, split.held_out(key.case_id), variant)  # only the file differs
    extra = {"from_step": calibrated.RESTART_STEP, "reuse_dir": str(first.run_dir)}
    done = _execute(key, method, over, root, exp.resources.timeout_s, extra)
    peaks = [p for p in (first.peak_rss_mb, done.peak_rss_mb) if p is not None]
    outcome = run_outcome(done.outcome, done.wall_ms, exp.resources.timeout_s)  # the first was ok
    total = first.wall_ms + done.wall_ms
    return replace(
        done, outcome=outcome, judged=True, wall_ms=total, peak_rss_mb=max(peaks) if peaks else None
    )


def _run_entry(method: MethodSpec, key: AnswerKeyRow, done: Executed) -> dict[str, object]:
    """The manifest entry of one executed run (03 §13.4 runs[])."""
    case = _read("case_manifest", done.run_dir, CaseManifest)
    inputs = manifest_hash((i.name, i.sha256) for i in case.inputs) if case is not None else None
    run: dict[str, object] = {"case_id": key.case_id, "dataset": key.dataset, "method": method.id}
    return run | {"run_id": done.run_id, "inputs_sha256": inputs}  # run_id None: killed


def _record(
    exp: Experiment,
    method: MethodSpec,
    key: AnswerKeyRow,
    done: Executed,
    fold: str | None = None,
    variant: str | None = None,
) -> tuple[dict[str, object], CaseScore, dict[str, object]]:
    """Score one executed run: (per_case row, score, manifest run entry). n_i (its `services`) and
    the input hashes come from the run's case_manifest (Infralume, step 0): the case's own, the
    same for every method and for every outcome that got that far. A baseline is scored on its
    ranks alone: it has no slate, pool, set or fault type (metrics.MethodOutput)."""
    wall_ms, peak = done.wall_ms, done.peak_rss_mb
    outcome = done.outcome if done.judged else run_outcome(done.outcome, wall_ms, exp.resources.timeout_s)
    slate_scored, baseline = method.kind == "causatrix", method.kind in BASELINE_KINDS
    verdict = (
        _read("verdict", done.run_dir, Verdict) if outcome == "ok" and method.kind == "veyltrace" else None
    )
    slate = _read("slate", done.run_dir, Slate) if outcome == "ok" and not baseline else None
    if outcome == "ok" and (
        done.ranks is None if baseline else slate is None or (verdict is None and not slate_scored)
    ):
        outcome = "failed"  # a missing output is a failed run (04 §7)
    case = _read("case_manifest", done.run_dir, CaseManifest)
    universe = tuple(case.services) if case is not None else None
    detected = outcome == "ok" and exp.protocol.alert == DETECTED
    onsets = _read("onsets", done.run_dir, Onsets) if detected else None
    if baseline:
        out = MethodOutput(outcome=outcome, ranks=done.ranks if outcome == "ok" and done.ranks else ())
    else:
        out = method_output(outcome, verdict, slate, slate_scored=slate_scored)
    out = replace(out, t_onset_ns=onsets.t_onset_ns if onsets is not None else None)
    window = variant == normal_windows.VARIANT  # only a normal window has no truth (04 §5.4 item 6)
    truth = Truth(None) if window else Truth.from_answer_key(key)
    score = score_case(truth, out, universe=universe)
    decoy = decoy_runs.decoy_columns(key, score.ranks)
    score = replace(score, wall_ms=wall_ms, peak_rss_mb=peak, **decoy)  # cost, decoy; no tokens (AI off)
    _log.info("bench.case", case_id=key.case_id, method=method.id, outcome=outcome, unranked=score.unranked)
    p = exp.protocol
    # Every column starts null; the ones v0 leaves null are listed in run_experiment's docstring.
    row: dict[str, object] = {name: None for name in BenchResultRow.model_fields}
    row |= {
        "case_id": key.case_id,
        "dataset": key.dataset,
        "system": key.system,
        "method": method.id,
        "ai_mode": method.ai.mode,
        "variant": variant,
        "fold": fold,
        "protocol": p.alert,
        "run_outcome": outcome,
        "shift_s": normal_windows.SHIFT_S if variant == normal_windows.VARIANT else p.shift_s,
        "sources_dropped": sorted(p.sources_drop),
        "status": verdict.status if verdict is not None else None,
        "verdict_hash": verdict.verdict_hash if verdict is not None else None,
        "wall_ms": wall_ms,
        "peak_rss_mb": peak,
        **score.columns(),
        **decoy,
    }
    return row, score, _run_entry(method, key, done)


type Scored = tuple[dict[str, object], CaseScore, dict[str, object]]


def _run_method(
    exp: Experiment,
    method: MethodSpec,
    cases: list[AnswerKeyRow],
    bench_runs: Path,
    timed: Timed,
    reports: dict[tuple[str, str], str],
    overlays: dict[str, str],
    split: calibrated.Split | None,
    windows: list[AnswerKeyRow] | None = None,
    dropped: list[dict[str, object]] | None = None,
    sources: dict[tuple[str, str], Executed] | None = None,
) -> list[Scored]:
    """Every case of one dataset with one method, each run once, then its normal `windows`; a window
    with too short a baseline goes to `dropped` (manifest runs only). A baseline gets its own runs
    directory, so its alert-step runs are executed and timed, never reused from another method.
    `sources` maps (method, case) to the AI-off veyltrace runs a causatrix:<ranker> method reuses
    up to FaultLoom (`upstream`, #413); this call adds its own veyltrace runs to it."""
    if method.kind == "rcaeval":
        return _run_rcaeval(exp, method, cases, bench_runs, reports, overlays, split)
    root, extra = bench_runs, None
    if method.kind == "internal_baseline":
        root, extra = (
            bench_runs / BASELINE_RUNS / slug(method.id),
            {"to_step": INPUT_STEP, "baseline": method.id},
        )
    out: list[Scored] = []
    units = [(k, None) for k in cases] + [(k, normal_windows.VARIANT) for k in windows or []]
    for key, variant in units:
        keys = calibrated.first_run(split, key.case_id)
        reuse = (
            _reused(exp, method, key, root, overlays.get(key.case_id), keys, sources)
            if variant is None
            else None
        )
        done = reuse or _timed(exp, method, key, root, timed, extra, overlays.get(key.case_id), keys, variant)
        if sources is not None and variant is None and method.kind == upstream.SOURCE_KIND:
            sources[(method.id, key.case_id)] = done
        if variant == normal_windows.VARIANT and normal_windows.dropped(done.run_dir, done.reason):
            (dropped if dropped is not None else []).append(_run_entry(method, key, done))
            continue
        out.append(_record(exp, method, key, done, _fold(split, key.case_id), variant))
    return out


def _reused(
    exp: Experiment,
    method: MethodSpec,
    key: AnswerKeyRow,
    root: Path,
    overlay: str | None,
    calibration_keys: Mapping[str, object],
    sources: dict[tuple[str, str], Executed] | None,
) -> Executed | None:
    """A causatrix:<ranker> run of one case that reuses its source's steps up to Causalith and runs
    FaultLoom and Causatrix (`upstream`); None when it does not apply, or the source cannot serve it."""
    if sources is None or not upstream.applies(method) or (source := upstream.source_of(exp, method)) is None:
        return None
    src = sources.get((source.id, key.case_id))
    if (
        src is None
        or src.run_dir is None
        or run_outcome(src.outcome, src.wall_ms, exp.resources.timeout_s) != "ok"
    ):
        _log.info(
            "bench.upstream_reuse",
            case_id=key.case_id,
            method=method.id,
            reused=False,
            why="no ok source run",
        )
        return None
    over = overrides_for(exp, method, overlay, calibration_keys)
    lock = resolve_config(over, dataset=key.dataset, ai_mode=method.ai.mode).lock_bytes()
    if (why := upstream.mismatch(src.run_dir, lock)) is not None:
        _log.info("bench.upstream_reuse", case_id=key.case_id, method=method.id, reused=False, why=why)
        return None
    _log.info("bench.upstream_reuse", case_id=key.case_id, method=method.id, reused=True, source=src.run_id)
    extra = {"from_step": upstream.START, "reuse_dir": str(src.run_dir), "to_step": upstream.STOP}
    # The run a full method would make includes the source's steps, so the timeout is what is left of
    # timeout_s after them (results unchanged by construction, ADR slate-method-upstream-reuse).
    left_ms = exp.resources.timeout_s * MS_PER_S - src.wall_ms
    done = _execute(key, method, over, root, max(1, math.ceil(left_ms / MS_PER_S)), extra)
    outcome = "timeout" if done.outcome == "timeout" or done.wall_ms > left_ms else done.outcome
    return replace(done, outcome=outcome, judged=True)


def _fold(split: calibrated.Split | None, case: str) -> str | None:
    """bench_result.fold: the case's test fold, null under split none (03 §13.2)."""
    return None if split is None else split.plan.test_fold[case]


def _run_rcaeval(
    exp: Experiment,
    method: MethodSpec,
    cases: list[AnswerKeyRow],
    bench_runs: Path,
    reports: dict[tuple[str, str], str],
    overlays: dict[str, str],
    split: calibrated.Split | None,
) -> list[Scored]:
    """Export every case (alert-step run, in a child), then one main.py run over the exported ones
    with a budget of `timeout_s` per case; its wall time is shared equally among them."""
    repo = find_config_dir().parent
    settings = rcaeval.settings(repo)
    args = rcaeval.method_args(method.rcaeval, settings, method.id)
    mapping = settings.datasets[cases[0].dataset]
    work = bench_runs / RCAEVAL_WORK / slug(method.id) / cases[0].dataset
    root, timeout_s = bench_runs / BASELINE_RUNS / slug(method.id), exp.resources.timeout_s
    done: dict[str, Executed] = {}
    for key in cases:
        extra = {"to_step": INPUT_STEP, "export": str(rcaeval.case_dir(work, mapping, key))}
        over = overrides_for(exp, method, overlays.get(key.case_id), calibrated.first_run(split, key.case_id))
        done[key.case_id] = _execute(key, method, over, root, timeout_s, extra)
    exported = [c for c, d in done.items() if run_outcome(d.outcome, d.wall_ms, timeout_s) == "ok"]
    if exported:
        got = rcaeval.run_main(settings, repo, work, mapping, args, exported, timeout_s * len(exported))
        reports[(cases[0].dataset, method.id)] = got.report
        share = got.wall_ms / len(exported)
        for c in exported:
            d = done[c]
            outcome = "timeout" if got.timed_out else d.outcome
            done[c] = replace(d, outcome=outcome, wall_ms=d.wall_ms + share, ranks=got.ranks[c])
    return [_record(exp, method, key, done[key.case_id], _fold(split, key.case_id)) for key in cases]


def _calibration_run(
    key: AnswerKeyRow, variant: str | None, done: Executed, timeout_s: int
) -> calibration.CalibrationRun | None:
    """A calibration run as the fit reads it: a fault case's root score (+inf without a verdict or
    unranked), a normal window (an RCAEval pre-injection window, or a no-fault case of synth-05 or
    VeylLab: M, or +inf when it could never be NO_FAULT), None for a dropped window or a no-fault case
    of another source (ADR 20261121-ak-calibration-fit-conventions)."""
    ok = run_outcome(done.outcome, done.wall_ms, timeout_s) == "ok"
    run_dir = done.run_dir if ok else None
    if variant == normal_windows.VARIANT:  # 04 §5.4 item 6
        if normal_windows.dropped(done.run_dir, done.reason):
            return None
        return calibration.window(key.case_id, variant, calibration.PRE_INJECTION, run_dir)
    if key.is_no_fault:
        if (source := calibration.window_source(key.dataset)) is None:
            return None
        return calibration.window(key.case_id, None, source, run_dir)
    verdict, slate = _read("verdict", run_dir, Verdict), _read("slate", run_dir, Slate)
    unranked = not (verdict and verdict.ranks_rcaeval and slate and slate.rankers_active)  # 04 §7
    score = calibration.root_score(verdict, str(key.root_service), unranked=unranked)
    return calibration.CalibrationRun(key.case_id, None, score=score)


def _fit(
    exp: Experiment,
    split: calibrated.Split,
    method: MethodSpec,
    ran: list[tuple[AnswerKeyRow, str | None, Executed]],
    commit: str,
) -> None:
    """Fit and write one file per fold part of the split for one method (04 §5.4; 09 §3.7-3.8)."""
    cfg = resolve_config(overrides_for(exp, method), dataset=ran[0][0].dataset, ai_mode=method.ai.mode)
    arm = calibrated.arm(method, cfg)
    default_tau = float(cast("dict[str, Any]", cfg.engine("causentra"))["no_fault"]["default_tau"])
    for fold in sorted(split.plan.fits):  # a window follows its case's fold (04 §5.4 item 1)
        members = [(k, v, d) for k, v, d in ran if k.case_id in split.plan.fits[fold]]
        timeout_s = exp.resources.timeout_s
        fitted = [(r, d) for k, v, d in members if (r := _calibration_run(k, v, d, timeout_s)) is not None]
        runs = [r for r, _ in fitted]
        manifests = [_read_manifest(d.run_dir) for _, d in fitted]  # dropped windows are not in the fit
        content = calibration.fit(
            runs,
            family=split.family,
            ai_arm=arm,
            alert_protocol=exp.protocol.alert,
            fold=fold,
            alpha=exp.calibration.alpha,
            beta=exp.calibration.no_fault_beta,
            default_tau=default_tau,
            seed=exp.split.seed,
            config_sha256s=[m.config_sha256 for m in manifests if m is not None] or [config_sha256(cfg)],
            code_commit=commit,
            experiment_id=exp.experiment_id,
        )
        write_calibration(calibrated.calibration_dir(), content)
        nf = content.no_fault
        _log.info(
            "bench.calibration.fit", family=content.family, n=content.n, q_hat=content.q_hat, m=nf.m,
            tau_nf=nf.tau_nf, calibrated=nf.calibrated, **calibration.never_counts(runs),
        )  # fmt: skip


def _read_manifest(run_dir: Path | None) -> RunManifest | None:
    if run_dir is None:
        return None
    try:
        return io.read_model("run_manifest", run_dir, RunManifest)
    except (ArtifactMissing, ContractValidationError):
        return None


def _split(
    exp: Experiment,
    keys: dict[str, dict[str, AnswerKeyRow]],
    selected: dict[str, tuple[list[str], list[str]]],
    repo: Path,
) -> calibrated.Split | None:
    """The experiment's split over its selected cases; a fitting transfer also selects its
    calibration cases from the file's source parts, development cases excluded (04 §5.4 item 7)."""
    splits.check_split(exp.split)
    chosen = {c: keys[d][c] for d, (cases, _) in selected.items() for c in cases}
    fits_transfer = exp.split.scheme == "transfer" and exp.calibration.fit
    outside = calibrated.transfer_keys(exp, repo) if fits_transfer else {}
    return calibrated.make_split(exp, chosen, outside)


def check_baselines(exp: Experiment, repo: Path) -> None:
    """Baseline settings, RCAEval method blocks, dataset mappings and the RCAEval environment are
    valid before the first case (a missing venv names the setup script)."""
    if any(m.kind == "internal_baseline" and m.id == "simplerca" for m in exp.methods):
        baselines.load("simplerca", simplerca.SimpleRcaConfig, repo)
    wrapped = [m for m in exp.methods if m.kind == "rcaeval"]
    if not wrapped:
        return
    settings = rcaeval.settings(repo)
    for m in wrapped:
        rcaeval.method_args(m.rcaeval, settings, m.id)
    if missing := [d for d in exp.dataset.parts if d not in settings.datasets]:
        raise ConfigError(f"bench/baselines.yaml rcaeval.datasets has no entry for {missing}")
    rcaeval.check_environment(settings, repo)


def method_config_sha256(method: MethodSpec, cfg: ResolvedConfig) -> str:
    """03 §13.4 configs[].config_sha256: the pipeline config, plus a baseline's own section."""
    if method.kind not in BASELINE_KINDS or method.id == naive_change.METHOD:
        return config_sha256(cfg)  # naive-change has no settings of its own
    name = "rcaeval" if method.kind == "rcaeval" else "simplerca"
    return baselines.config_sha256(config_sha256(cfg), name)


def case_services(key: AnswerKeyRow, cfg: ResolvedConfig, runs_root: Path) -> list[str] | None:
    """The case's `case_manifest.services` from an Infralume-only run; None if it was rejected."""
    s = run_case(key.dataset, key.case_id, "off", config=cfg, runs_root=runs_root, to_step=SERVICES_STEP)
    case = _read("case_manifest", s.run_dir if s.outcome == "ok" else None, CaseManifest)
    return list(case.services) if case is not None else None


def _prepare_decoys(
    exp: Experiment,
    spec: decoy_runs.DecoySpec,
    keys: dict[str, dict[str, AnswerKeyRow]],
    selected: dict[str, tuple[list[str], list[str]]],
    runs_root: Path,
) -> dict[str, str]:
    """Write every selected case's overlay and put `decoy_changes_json` into its row of `keys`;
    case_id -> overlay path. A case Infralume rejects gets none, so its runs are rejected as
    they would be without decoys."""
    overlays: dict[str, str] = {}
    for dataset, (cases, _) in selected.items():
        cfg = resolve_config(protocol_overrides(exp), dataset=dataset, ai_mode="off")
        for c in cases:
            if (services := case_services(keys[dataset][c], cfg, runs_root)) is None:
                continue
            got = decoy_runs.prepare_case(exp.experiment_id, keys[dataset][c], spec, services, data_root())
            keys[dataset][c], overlays[c] = got.key, got.overlay
    return overlays


def _group(
    key: tuple[str, str, str],
    scores: list[CaseScore],
    exp: Experiment,
    rows: list[dict[str, object]],
    no_cost: bool = False,
) -> dict[str, object]:
    """One bench_summary group (03 §13.3): its counts, every run_outcome counted (0 when none), and
    one `metrics` entry per METRIC_KEYS name, null when the experiment does not list it (04 §9).
    `rows` are all per_case rows; the group's, in run order, pair with `scores` (summary.with_rows).
    `no_cost` nulls the cost entry of a group whose wall times are not end to end (slate-scored
    methods, whose rows may reuse veyltrace:off's run; RQ5 comes only from veyltrace:off, #413)."""
    flat = summarize(scores, ())  # the counts
    counted = cast("dict[str, int]", flat.pop("outcomes"))
    mine = [r for r in rows if (r["dataset"], str(r["system"]), r["method"]) == key]
    entries = summary_entries(with_rows(scores, mine), exp.metrics, alpha=exp.calibration.alpha)
    if no_cost:
        entries["cost"] = None
    dataset, system, method = key
    outcomes = {o: counted.get(o, 0) for o in sorted(RUN_OUTCOMES)}
    return {
        "dataset": dataset,
        "system": system,
        "method": method,
        **flat,
        "outcomes": outcomes,
        "metrics": entries,
    }


def run_experiment(
    path: Path, *, out_root: Path | None = None, runs_root: Path | None = None, table: bool = False
) -> tuple[Path, dict[str, object]]:
    """Run the experiment at `path`; (results directory, summary). `table` and `out_root` are the
    CLI's `--table` and `--out` (#14). `table` marks results meant for a paper table: it refuses a
    dirty tree (bench/AGENTS.md Never 3). Synth is never reported (04 §3): it is refused with
    `table` and needs an explicit `out_root` outside the repository.

    Under a calibration split (#376, `calibrated`) every row is the case's held-out prediction and
    `fold` its test fold; a fitting experiment writes `config/calibration/` before its held-out runs
    and logs held-out coverage and NO_FAULT false-alarm rates per fold (`bench.held_out`).

    per_case.csv columns v0 leaves null: seed and variant (no AI arms, no perturbed variants),
    fold (split none), decoy_present and decoy_ranked_first (no protocol.decoys), peak_rss_mb of a
    run killed at the timeout (never reported) and tokens_in/out (AI off); onset_error_ms is filled
    under the detected protocol only (04 §7).
    """
    exp = load_experiment(path)
    if todo := unsupported(exp):
        raise ConfigError(f"{Path(path).as_posix()}: not supported by the v0 runner yet: {'; '.join(todo)}")
    spec = decoy_runs.decoy_spec(exp.protocol.decoys)  # a bad block fails before any case
    repo = find_config_dir().parent
    check_baselines(exp, repo)  # settings and the RCAEval venv, before any data is read
    code = code_state(repo)
    if table and (code["dirty"] or code["bench_dirty"]):
        raise UsageError("--table refuses a dirty work tree (bench/AGENTS.md Never 3); commit first")
    in_repo = out_root is None or Path(out_root).resolve().is_relative_to(repo.resolve())
    if SYNTH in exp.dataset.parts and (table or in_repo):  # not even an explicit --out bench/results
        raise UsageError("synth is never reported (04 §3): no --table; --out must be a dir outside the repo")
    keys = {d: load_answer_keys(d) for d in exp.dataset.parts}
    selected = select_cases(exp, repo)
    for d, (cases, _) in selected.items():
        if missing := [c for c in cases if c not in keys[d] or keys[d][c].system is None]:
            raise ContractValidationError("answer_key", f"{d}: no row with a system for {missing}")
        for c in cases:
            Truth.from_answer_key(keys[d][c])  # refuse a fault row without a root before any run
    check_rankers(exp)
    normal_windows.check(exp)
    split = _split(exp, keys, selected, repo)
    for dataset in selected:  # every file a held-out run needs exists before the first case
        for method in exp.methods:
            if split is not None and method.kind == calibrated.CALIBRATED_KIND:
                cfg = resolve_config(overrides_for(exp, method), dataset=dataset, ai_mode=method.ai.mode)
                calibrated.check(exp, split, method, cfg)
    if split is not None and split.fit:  # one file per family id: two fitting methods may not share one
        fitting = [m for m in exp.methods if m.kind == calibrated.CALIBRATED_KIND]
        arms = [calibrated.arm(m, resolve_config(overrides_for(exp, m), ai_mode=m.ai.mode)) for m in fitting]
        if len(set(arms)) != len(arms):
            pairs = [f"{m.id}: {a}" for m, a in zip(fitting, arms, strict=True)]
            raise ConfigError(f"fitting methods share a calibration arm, so a family id: {pairs}")
    bench_runs = (runs_root or default_runs_root()) / BENCH_RUNS / exp.experiment_id
    if bench_runs.exists():  # bench's own directory: stale runs would be reused untimed
        shutil.rmtree(bench_runs)
    overlays = _prepare_decoys(exp, spec, keys, selected, bench_runs / DECOY_RUNS) if spec else {}
    rows: list[dict[str, object]] = []
    runs: list[dict[str, object]] = []
    configs: list[dict[str, object]] = []
    groups: dict[tuple[str, str, str], list[CaseScore]] = {}
    cases_scored: list[Case] = []
    timed: Timed = {}
    reports: dict[tuple[str, str], str] = {}
    first: dict[str, list[tuple[AnswerKeyRow, str | None, Executed]]] = {}  # a fitting method's runs
    sources: dict[tuple[str, str], Executed] = {}  # (method, case): runs causatrix:<ranker> reuses (#413)

    def keep(scored: Scored, listed: bool = True) -> None:
        row, score, run = scored
        rows.append(row)
        if listed:  # False: the run is already in the manifest (a calibration run kept as the row)
            runs.append(run)
        dataset, k_sys, method_id = str(row["dataset"]), str(row["system"]), str(row["method"])
        groups.setdefault((dataset, k_sys, method_id), []).append(score)
        k = keys[dataset][str(row["case_id"])]
        cluster = (k.system, k.root_service, k.fault_label)  # 04 §8 clusters
        cases_scored.append(Case(k.case_id, dataset, k_sys, method_id, cluster, score))

    for dataset, (cases, _) in selected.items():
        for method in exp.methods:
            # The config apart from the calibration choice, which each run's own manifest records.
            cfg = resolve_config(overrides_for(exp, method), dataset=dataset, ai_mode=method.ai.mode)
            configs.append(
                {"dataset": dataset, "method": method.id, "config_sha256": method_config_sha256(method, cfg)}
            )
            rows_keys = [keys[dataset][c] for c in cases]
            verdicts = method.kind == calibrated.CALIBRATED_KIND
            windows = normal_windows.windows_of(exp, rows_keys) if verdicts else []
            if split is not None and split.fit and verdicts:
                units = [(k, None) for k in rows_keys] + [(k, normal_windows.VARIANT) for k in windows]
                uncal = calibrated.UNCALIBRATED
                for k, v in units:
                    done = _timed(exp, method, k, bench_runs, timed, None, overlays.get(k.case_id), uncal, v)
                    first.setdefault(method.id, []).append((k, v, done))
                    if v is None and method.ai.mode == "off":
                        sources[(method.id, k.case_id)] = done  # what causatrix:<ranker> reuses (#413)
                continue
            ran = _run_method(
                exp, method, rows_keys, bench_runs, timed, reports, overlays, split, windows, runs, sources
            )
            for scored in ran:
                keep(scored)
    for method in exp.methods:  # fit on the calibration runs, then the held-out runs (04 §5.4 item 3)
        if split is None or method.id not in first:
            continue
        outside_keys = list(split.fit_keys.values())  # transfer: its source parts, with their windows
        outside_units = [(k, None) for k in outside_keys]
        outside_units += [(k, normal_windows.VARIANT) for k in normal_windows.pre_injection(outside_keys)]
        outside = [(k, v, _timed(exp, method, k, bench_runs, timed, variant=v)) for k, v in outside_units]
        runs.extend(_run_entry(method, k, d) for k, _, d in [*first[method.id], *outside])
        _fit(exp, split, method, [*first[method.id], *outside], str(code["commit"]))
        for key, variant, done in first[method.id]:
            if variant == normal_windows.VARIANT and normal_windows.dropped(done.run_dir, done.reason):
                continue  # dropped (04 §5.4 item 6); its calibration run is in the manifest
            held_out = _restart(exp, method, key, done, split, bench_runs, overlays.get(key.case_id), variant)
            keep(
                _record(exp, method, key, held_out, _fold(split, key.case_id), variant), held_out is not done
            )
    if split is not None:
        verdicts = {m.id for m in exp.methods if m.kind == calibrated.CALIBRATED_KIND}  # sets and statuses
        for rates in calibration.held_out_rates(r for r in rows if r["method"] in verdicts):  # #37, per fold
            _log.info(
                "bench.held_out", **rates, alpha=exp.calibration.alpha, beta=exp.calibration.no_fault_beta
            )
    slate_scored = {m.id for m in exp.methods if m.kind == upstream.KIND}
    summary: dict[str, object] = {
        "producer": PRODUCER,
        "experiment_id": exp.experiment_id,
        "groups": [
            _group(k, scores, exp, rows, k[2] in slate_scored)
            for k, scores in sorted(groups.items(), key=lambda item: item[0])
        ],
        "excluded": {d: excluded for d, (_, excluded) in selected.items()},
        "statistics": statistics(exp, cases_scored),  # 04 §8 (#357)
    }
    out_dir = (out_root if out_root is not None else repo.joinpath(*RESULTS_DIR)) / exp.experiment_id
    io.write_path("bench_result", rows, out_dir / "per_case.csv")
    io.write_path("bench_summary", summary, out_dir / "summary.json")  # validated (03 §13.3)
    if (report_dir := out_dir / RCAEVAL_REPORTS).exists():
        shutil.rmtree(report_dir)  # no stale report of a method this run did not repeat
    for (dataset, method_id), text in sorted(reports.items()):  # RCAEval's own scoring, 04 §4
        textio.write_bytes(report_dir / f"{dataset}.{slug(method_id)}.txt", text.encode())
    datasets: list[dict[str, object]] = []
    for d, (cases, excluded) in selected.items():
        mine = [r for r in runs if r["dataset"] == d and r["inputs_sha256"] is not None]
        known = {str(r["case_id"]): str(r["inputs_sha256"]) for r in mine}  # case_manifest.inputs hashes
        datasets.append(
            {
                "dataset": d,
                "answer_key_sha256": sha256_file(answer_key_path(d)),
                "inputs_sha256": manifest_hash(known.items()),
                "cases_without_inputs": sorted(set(cases) - set(known)),
                "cases": cases,
                "excluded": excluded,
            }
        )
    manifest: dict[str, object] = {
        "producer": PRODUCER,
        "experiment_id": exp.experiment_id,
        "experiment_sha256": sha256_text_lf(Path(path)),
        "experiment": exp.model_dump(mode="json"),
        "code": code,
        "uv_lock_sha256": uv_lock_sha256(),
        "datasets": datasets,
        "configs": configs,
        "seeds": sorted({seed for m in exp.methods for seed in m.ai.seeds}),
        "runs": runs,
        "calibrations": recorded_calibrations(exp, runs, bench_runs),  # 03 §13.4 (#412)
    }
    io.write_path("bench_manifest", manifest, out_dir / "manifest.json")  # last: marks a whole result
    return out_dir, summary
