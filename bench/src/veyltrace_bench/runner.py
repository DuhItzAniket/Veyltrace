"""The runner behind `veyltrace bench run` (R-04, #67; the CLI over it is #14).

Every (case × method) of the experiment's dataset parts runs through core's public pipeline API
(`pipeline.run_case`, the entry `veyltrace diagnose` uses), so bench learns every outcome (ok,
failed, no_alert, rejected) from the RunSummary. Runs go to bench's own, emptied
`<runs root>/bench/<experiment_id>/`, so each is executed and timed: a reused run has no wall time,
which would turn a timeout (a miss, 04 §9) into ok and lose its cost (04 §6). The one exception is
a run another method of this experiment made with the same config and a different `kind` (e.g.
`causatrix:rrf` and `veyltrace:off`, #172): it is scored again with that run's time. Each run is a
child process (`veyltrace_bench.child`, #68): bench kills it at `resources.timeout_s` and records
its peak RSS. Results, in
`<results root>/<experiment_id>/`: per_case.csv (bench_result, 03 §13.2, through core io),
summary.json (the requested metrics per (dataset, system, method)) and manifest.json (experiment,
code, uv.lock, answer-key, telemetry-input and config hashes, run ids; 04 §9, §10.2), both canonical
JSON and byte-identical across invocations; only per_case.csv's wall_ms and peak_rss_mb differ.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

from veyltrace_bench import ALGO_VERSION
from veyltrace_bench.answer_keys import answer_key_path, load_answer_keys
from veyltrace_bench.experiment import (
    PROTOCOL_KEYS,
    RANKERS_KEY,
    Experiment,
    MethodSpec,
    code_state,
    load_experiment,
    select_cases,
    unsupported,
)
from veyltrace_bench.metrics import CaseScore, MethodOutput, Truth, score_case
from veyltrace_bench.summary import summarize
from veyltrace_contracts.models import AnswerKeyRow, BenchResultRow, CaseManifest, Onsets, Slate, Verdict
from veyltrace_core import io, textio
from veyltrace_core.canonical import JSONLike, canonical_json
from veyltrace_core.cli import THREAD_ENV
from veyltrace_core.config import ResolvedConfig, config_sha256, find_config_dir, resolve_config
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

PRODUCER = f"bench@{ALGO_VERSION}"
SUMMARY_SCHEMA = "veyltrace.bench_summary/0"
MANIFEST_SCHEMA = "veyltrace.bench_manifest/0"
RESULTS_DIR = ("bench", "results")  # default results root below the repo (04 §9)
BENCH_RUNS = "bench"  # bench's own subdirectory of the runs root, one directory per experiment
SYNTH = "synth"  # smoke cases, never reported (04 §3)
MS_PER_S = 1000.0
DETECTED = "detected"  # the alert protocol whose onset error is scored (04 §7 "Onset error")
STATISTICS_NOT_RUN = "not run: cluster bootstrap CIs and tests come from bench/stats (O-14)"
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


def child_command(request: Path, result: Path) -> list[str]:
    """The child process of one run (veyltrace_bench.child), in this interpreter's environment."""
    return [sys.executable, "-m", "veyltrace_bench.child", str(request), str(result)]


def _execute(
    key: AnswerKeyRow,
    method: MethodSpec,
    cfg: ResolvedConfig,
    overrides: dict[str, object],
    runs_root: Path,
    timeout_s: int,
) -> Executed:
    """Diagnose one case, in a child killed at `timeout_s` (#68), or in process (IN_PROCESS)."""
    if IN_PROCESS:
        start = time.perf_counter()
        s = run_case(key.dataset, key.case_id, method.ai.mode, config=cfg, runs_root=runs_root)
        wall_ms = (time.perf_counter() - start) * MS_PER_S
        return Executed(s.outcome, s.run_id, s.run_dir, s.cached, wall_ms, None)
    request = {
        "dataset": key.dataset,
        "case_id": key.case_id,
        "ai_mode": method.ai.mode,
        "overrides": overrides,
        "runs_root": str(runs_root),
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
    return Executed(
        str(s["outcome"]),
        str(s["run_id"]),
        Path(s["run_dir"]),
        bool(s["cached"]),
        float(got["wall_ms"]),
        float(got["peak_rss_mb"]),
    )


def overrides_for(exp: Experiment, method: MethodSpec) -> dict[str, object]:
    """The run's config overrides: the protocol hooks, then the method's own keys."""
    p = exp.protocol
    hooks = dict(zip(PROTOCOL_KEYS, (p.alert, p.shift_s, list(p.sources_drop)), strict=True))
    return {**hooks, **method.overrides}


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


def _run_one(
    exp: Experiment,
    method: MethodSpec,
    cfg: ResolvedConfig,
    key: AnswerKeyRow,
    runs_root: Path,
    timed: Timed,
) -> tuple[dict[str, object], CaseScore, dict[str, object]]:
    """Diagnose one case with one method and score it: (per_case row, score, manifest run entry).
    n_i (its `services`) and the input hashes come from the run's case_manifest (Infralume, step 0):
    the case's own, the same for every method and for every outcome that got that far."""
    done = _execute(key, method, cfg, overrides_for(exp, method), runs_root, exp.resources.timeout_s)
    wall_ms, peak = done.wall_ms, done.peak_rss_mb
    kinds: frozenset[str] = frozenset()  # the method kinds that already scored this run
    if done.cached and done.run_id is not None:  # bench emptied its runs dir: another method ran it
        earlier = timed.get(done.run_id)
        if earlier is None or method.kind in earlier[2]:  # unknown time, or a duplicated method
            raise ConfigError(f"method {method.id} reuses run {done.run_id}: same config as another method")
        wall_ms, peak, kinds = earlier  # e.g. causatrix:rrf and veyltrace:off: one run, scored twice
    if done.run_id is not None:
        timed[done.run_id] = (wall_ms, peak, kinds | {method.kind})
    outcome = run_outcome(done.outcome, wall_ms, exp.resources.timeout_s)
    slate_scored = method.kind == "causatrix"
    verdict = _read("verdict", done.run_dir, Verdict) if outcome == "ok" and not slate_scored else None
    slate = _read("slate", done.run_dir, Slate) if outcome == "ok" else None
    if outcome == "ok" and (slate is None or (verdict is None and not slate_scored)):
        outcome = "failed"  # a missing output is a failed run (04 §7)
    case = _read("case_manifest", done.run_dir, CaseManifest)
    universe = tuple(case.services) if case is not None else None
    detected = outcome == "ok" and exp.protocol.alert == DETECTED
    onsets = _read("onsets", done.run_dir, Onsets) if detected else None
    out = method_output(outcome, verdict, slate, slate_scored=slate_scored)
    out = replace(out, t_onset_ns=onsets.t_onset_ns if onsets is not None else None)
    score = score_case(Truth.from_answer_key(key), out, universe=universe)
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
        "protocol": p.alert,
        "run_outcome": outcome,
        "shift_s": p.shift_s,
        "sources_dropped": sorted(p.sources_drop),
        "status": verdict.status if verdict is not None else None,
        "verdict_hash": verdict.verdict_hash if verdict is not None else None,
        "wall_ms": wall_ms,
        "peak_rss_mb": peak,
        **score.columns(),
    }
    inputs = manifest_hash((i.name, i.sha256) for i in case.inputs) if case is not None else None
    run: dict[str, object] = {"case_id": key.case_id, "dataset": key.dataset, "method": method.id}
    return row, score, run | {"run_id": done.run_id, "inputs_sha256": inputs}  # run_id None: killed


def _write_json(path: Path, obj: dict[str, object]) -> None:
    """Canonical JSON plus LF (03 §1); summary and manifest hold only JSON values."""
    textio.write_bytes(path, canonical_json(cast("JSONLike", obj)) + b"\n")


def run_experiment(
    path: Path, *, out_root: Path | None = None, runs_root: Path | None = None, table: bool = False
) -> tuple[Path, dict[str, object]]:
    """Run the experiment at `path`; (results directory, summary). `table` and `out_root` are the
    CLI's `--table` and `--out` (#14). `table` marks results meant for a paper table: it refuses a
    dirty tree (bench/AGENTS.md Never 3). Synth is never reported (04 §3): it is refused with
    `table` and needs an explicit `out_root` outside the repository.

    per_case.csv columns v0 leaves null: seed and variant (no AI arms, no perturbed variants),
    fold (split none), decoy_present and decoy_ranked_first (not evaluated yet), peak_rss_mb of a
    run killed at the timeout (never reported) and tokens_in/out (AI off); onset_error_ms is filled
    under the detected protocol only (04 §7).
    """
    exp = load_experiment(path)
    if todo := unsupported(exp):
        raise ConfigError(f"{Path(path).as_posix()}: not supported by the v0 runner yet: {'; '.join(todo)}")
    repo = find_config_dir().parent
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
    bench_runs = (runs_root or default_runs_root()) / BENCH_RUNS / exp.experiment_id
    if bench_runs.exists():  # bench's own directory: stale runs would be reused untimed
        shutil.rmtree(bench_runs)
    rows: list[dict[str, object]] = []
    runs: list[dict[str, object]] = []
    configs: list[dict[str, object]] = []
    groups: dict[tuple[str, str, str], list[CaseScore]] = {}
    timed: Timed = {}
    for dataset, (cases, _) in selected.items():
        for method in exp.methods:
            cfg = resolve_config(overrides_for(exp, method), dataset=dataset, ai_mode=method.ai.mode)
            configs.append({"dataset": dataset, "method": method.id, "config_sha256": config_sha256(cfg)})
            for case_id in cases:
                row, score, run = _run_one(exp, method, cfg, keys[dataset][case_id], bench_runs, timed)
                rows.append(row)
                runs.append(run)
                groups.setdefault((dataset, str(row["system"]), method.id), []).append(score)
    summary: dict[str, object] = {
        "schema": SUMMARY_SCHEMA,
        "producer": PRODUCER,
        "experiment_id": exp.experiment_id,
        "groups": [
            {"dataset": d, "system": s, "method": m, **summarize(scores, exp.metrics)}
            for (d, s, m), scores in sorted(groups.items(), key=lambda item: item[0])
        ],
        "excluded": {d: excluded for d, (_, excluded) in selected.items()},
        "statistics": STATISTICS_NOT_RUN,  # 03 §13.2 wants bootstrap CIs here once bench/stats exists
    }
    out_dir = (out_root if out_root is not None else repo.joinpath(*RESULTS_DIR)) / exp.experiment_id
    io.write_path("bench_result", rows, out_dir / "per_case.csv")
    _write_json(out_dir / "summary.json", summary)
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
        "schema": MANIFEST_SCHEMA,
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
    }
    _write_json(out_dir / "manifest.json", manifest)  # written last: its presence marks a whole result
    return out_dir, summary
