"""The runner behind `veyltrace bench run` (R-04, #67; the CLI over it is #14).

Every (case × method) of the experiment's dataset parts runs through core's public pipeline API
(`pipeline.run_case`, the entry `veyltrace diagnose` uses), so bench learns every outcome (ok,
failed, no_alert, rejected) from the RunSummary. Runs go to bench's own, emptied
`<runs root>/bench/<experiment_id>/`, so each is executed and timed: a reused run has no wall time,
which would turn a timeout (a miss, 04 §9) into ok and lose its cost (04 §6). The one exception is
a run another method of this experiment made with the same config and a different `kind` (e.g.
`causatrix:rrf` and `veyltrace:off`, #172): it is scored again with that run's time. Results, in
`<results root>/<experiment_id>/`: per_case.csv (bench_result, 03 §13.2, through core io),
summary.json (the requested metrics per (dataset, system, method)) and manifest.json (experiment,
code, uv.lock, answer-key, telemetry-input and config hashes, run ids; 04 §9, §10.2), both canonical
JSON and byte-identical across invocations; only per_case.csv's wall_ms differs.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import replace
from pathlib import Path
from typing import cast

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
from veyltrace_core.config import ResolvedConfig, config_sha256, find_config_dir, resolve_config
from veyltrace_core.errors import ArtifactMissing, ConfigError, ContractValidationError, UsageError
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

_log = get_logger(__name__)


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


def _read[M: (Verdict, Slate, CaseManifest, Onsets)](name: str, run_dir: Path, model: type[M]) -> M | None:
    """A JSON output of the run, or None when the run did not write a valid one."""
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
    timed: dict[str, tuple[float, frozenset[str]]],
) -> tuple[dict[str, object], CaseScore, dict[str, object]]:
    """Diagnose one case with one method and score it: (per_case row, score, manifest run entry).
    n_i (its `services`) and the input hashes come from the run's case_manifest (Infralume, step 0):
    the case's own, the same for every method and for every outcome that got that far."""
    start = time.perf_counter()
    summary = run_case(key.dataset, key.case_id, method.ai.mode, config=cfg, runs_root=runs_root)
    wall_ms = (time.perf_counter() - start) * MS_PER_S
    kinds: frozenset[str] = frozenset()  # the method kinds that already scored this run
    if summary.cached:  # bench emptied its runs dir, so another method of this experiment ran it
        earlier = timed.get(summary.run_id)
        if earlier is None or method.kind in earlier[1]:  # unknown time, or a duplicated method
            raise ConfigError(
                f"method {method.id} reuses run {summary.run_id}: same config as another method"
            )
        wall_ms, kinds = earlier  # e.g. causatrix:rrf and veyltrace:off: one run, scored two ways
    timed[summary.run_id] = (wall_ms, kinds | {method.kind})
    outcome = run_outcome(summary.outcome, wall_ms, exp.resources.timeout_s)
    slate_scored = method.kind == "causatrix"
    verdict = _read("verdict", summary.run_dir, Verdict) if outcome == "ok" and not slate_scored else None
    slate = _read("slate", summary.run_dir, Slate) if outcome == "ok" else None
    if outcome == "ok" and (slate is None or (verdict is None and not slate_scored)):
        outcome = "failed"  # a missing output is a failed run (04 §7)
    case = _read("case_manifest", summary.run_dir, CaseManifest)
    universe = tuple(case.services) if case is not None else None
    detected = outcome == "ok" and exp.protocol.alert == DETECTED
    onsets = _read("onsets", summary.run_dir, Onsets) if detected else None
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
        **score.columns(),
    }
    inputs = manifest_hash((i.name, i.sha256) for i in case.inputs) if case is not None else None
    run: dict[str, object] = {"case_id": key.case_id, "dataset": key.dataset, "method": method.id}
    return row, score, run | {"run_id": summary.run_id, "inputs_sha256": inputs}


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
    fold (split none), decoy_present and decoy_ranked_first (not evaluated yet), peak_rss_mb (not
    measurable in-process) and tokens_in/out (AI off); onset_error_ms is filled under the detected
    protocol only (04 §7).
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
    timed: dict[str, tuple[float, frozenset[str]]] = {}  # run_id -> (wall_ms, kinds that scored it)
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
