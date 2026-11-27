"""RQ3 intervals and the literal-§5.4 τ_nf sensitivity, from the kept runs of one RQ3 experiment (#555).

Usage: `uv run python scripts/rq3_intervals.py --runs-root DIR [--experiment ID] [--results DIR]`

Why: 04 §2 RQ3 is "estimation with cluster-bootstrap CIs" and 04 §8 gives every metric and proportion
(coverage, false-alarm rates) a 95% cluster-bootstrap interval. summary.json (bench_summary 1.2) has
intervals only for case means such as AC@k, so Table 7 shows coverage, the NO_FAULT rates and the
AURCs (H3a, H3c, SC-4) as bare numbers. AURC also needs each run's margin and leader fused score,
which per_case.csv does not keep. This script reads them from the kept run directories, which it
matches to per_case.csv rows by `verdict_hash` (exactly one run per row, or the script stops).

Writes `<results>/rq3-intervals/<experiment>/rows.csv` (one row per per_case row, with an opaque
cluster id, margin, fused score and Causentra's M; enough to redo every interval, but without the
root service or fault label, so the file does not publish the case-to-truth mapping) and
`summary.json`, with per system and pooled (RE2, system as stratum, 04 §8 "Pooling"):

- coverage, false-alarm rate and wrong-NO_FAULT rate, with veyltrace_stats' cluster bootstrap (the
  procedure summary.json uses for AC@k), and they must equal the committed summary's values;
- AURC of V and of F and their paired difference V - F (H3c: below 0 favours V), by resampling
  clusters in the same way and computing veyltrace_bench.summary.aurc on each resample;
- `literal_tau`, a sensitivity analysis computed after the results (04 §12, row of 26 Nov): τ_nf by
  the literal 04 §5.4 item 6 reading, where windows Causentra can never call NO_FAULT (M undefined or
  a silent service) are left out of m instead of scoring +∞, and the held-out NO_FAULT rates that τ
  would give. The windows are the held-out windows of the other folds: M does not depend on the
  calibration (bench calibration.py), and the file that serves fold X is fit on the other folds
  (the other fold of crossfit2, the other two systems of LOSO).
  The rule used is Causentra's (09 §3.8): NO_FAULT iff M is defined, no service is silent and
  M ≤ τ_nf at 9 decimals. A NO_FAULT status is checked before every other status, so these two rates
  are exact for that τ. The other columns (sets, AURC) would also change, and are not recomputed.

Clusters are (system, root service, fault) from the answer key (04 §8). A normal window joins its
case's cluster. Seeds and resamples are the experiment's `statistics.bootstrap`.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np

from veyltrace_bench.answer_keys import load_answer_keys
from veyltrace_bench.calibration import kth, rank_index, run_statistic
from veyltrace_bench.experiment import Experiment, load_experiment
from veyltrace_bench.summary import DECIMALS, NO_FAULT, STATUS_ORDER, aurc
from veyltrace_stats.cluster import LEVEL, Interval, cluster_bootstrap, stratified_cluster_bootstrap

BENCH = "bench"  # the runs root's folder of deterministic runs (veyltrace_bench.runner)
POOLED = "pooled"
OUT = "rq3-intervals"
SUMMARY_TOLERANCE = 1e-8  # both sides are rounded at 9 decimals (summary.DECIMALS); a priori


@dataclass(frozen=True)
class Row:
    """One per_case.csv row of the experiment with what the intervals need."""

    dataset: str
    system: str
    case_id: str
    variant: str
    fold: str
    root_service: str | None  # answer_key columns (03 §13.1), the cluster of 04 §8
    fault_label: str | None
    fault: bool  # a fault case (has a truth), else a normal window
    hit_at_1: bool
    in_set: bool
    status: str
    margin: float | None
    leader_fused: float | None
    m: float | None  # Causentra's M (09 §3.8), None without a robust_z atom
    silent: bool
    run_id: str

    @property
    def cluster(self) -> tuple[str | None, ...]:
        return (self.system, self.root_service, self.fault_label)

    def verified_key(self) -> tuple[float, float]:
        """summary._verified_key: status, then margin desc."""
        rank = STATUS_ORDER.index(self.status) if self.status in STATUS_ORDER else len(STATUS_ORDER)
        return (float(rank), -round(self.margin, DECIMALS) if self.margin is not None else math.inf)

    def fused_key(self) -> tuple[float, float]:
        """summary._fused_key: the leader's fused score desc."""
        f = self.leader_fused
        return (0.0, -round(f, DECIMALS) if f is not None else math.inf)

    def no_fault_at(self, tau: float) -> bool:
        """Causentra's outcome.no_fault at threshold `tau` (09 §3.8)."""
        if self.m is None or self.silent:
            return False
        return round(self.m, DECIMALS) <= round(tau, DECIMALS)


def _flag(cell: str) -> bool:
    return cell == "1"


def find_run(case_dir: Path, verdict_hash: str) -> Path:
    """The one run directory of the case whose verdict has `verdict_hash`."""
    hits = []
    for run in sorted(p for p in case_dir.iterdir() if p.is_dir()):
        verdict = json.loads((run / "verdict.json").read_text(encoding="utf-8"))
        if verdict.get("verdict_hash") == verdict_hash:
            hits.append(run)
    if len(hits) != 1:
        raise SystemExit(f"rq3: {len(hits)} runs of {case_dir} have verdict_hash {verdict_hash}")
    return hits[0]


def load_rows(exp: Experiment, results: Path, runs_root: Path, data_root: Path | None) -> list[Row]:
    """The experiment's per_case rows, each joined with its kept run and its answer-key cluster."""
    path = results / exp.experiment_id / "per_case.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        raw = list(csv.DictReader(fh))
    if any(r["run_outcome"] != "ok" for r in raw):
        raise SystemExit("rq3: a run is not ok; its row has no verdict to join (04 §7)")
    keys = {d: load_answer_keys(d, data_root) for d in sorted({r["dataset"] for r in raw})}
    rows: list[Row] = []
    for r in raw:
        run = find_run(runs_root / BENCH / exp.experiment_id / r["dataset"] / r["case_id"], r["verdict_hash"])
        verdict = json.loads((run / "verdict.json").read_text(encoding="utf-8"))
        if verdict["status"] != r["status"]:
            raise SystemExit(f"rq3: {run} has status {verdict['status']}, its row {r['status']}")
        ranked = verdict.get("ranked") or []
        m, silent = run_statistic(run)
        k = keys[r["dataset"]][r["case_id"]]
        rows.append(
            Row(
                dataset=r["dataset"], system=r["system"], case_id=r["case_id"], variant=r["variant"],
                fold=r["fold"], root_service=k.root_service, fault_label=k.fault_label,
                fault=r["hit_at_1"] != "", hit_at_1=_flag(r["hit_at_1"]), in_set=_flag(r["in_set"]),
                status=r["status"], margin=(verdict.get("confidence") or {}).get("margin"),
                leader_fused=ranked[0].get("fused_score") if ranked else None,
                m=round(m, DECIMALS) if m is not None else None, silent=silent,
                run_id=run.name,
            )
        )  # fmt: skip
    return sorted(rows, key=lambda x: (x.dataset, x.case_id, x.variant, x.fold, x.run_id))


def _interval(i: Interval) -> dict[str, object]:
    return {
        "estimate": round(i.estimate, DECIMALS), "low": round(i.low, DECIMALS),
        "high": round(i.high, DECIMALS), "n": i.n_cases, "n_clusters": i.n_clusters,
    }  # fmt: skip


def mean_interval(rows: Sequence[Row], flag: Callable[[Row], bool], seed: int, resamples: int,
                  pooled: bool) -> dict[str, object] | None:  # fmt: skip
    """A proportion with its cluster-bootstrap interval (stratified by system when pooled)."""
    if not rows:
        return None
    values = [1.0 if flag(r) else 0.0 for r in rows]
    clusters: list[Hashable] = [r.cluster for r in rows]
    if pooled:
        strata: list[Hashable] = [r.system for r in rows]
        i = stratified_cluster_bootstrap(values, clusters, strata, seed=seed, resamples=resamples)
    else:
        i = cluster_bootstrap(values, clusters, seed=seed, resamples=resamples)
    return _interval(i)


def aurc_intervals(rows: Sequence[Row], seed: int, resamples: int) -> dict[str, object]:
    """AURC of V, of F and V - F over the fault rows, with percentile intervals from resampling
    clusters within each system (one stratum per system, strata in sorted order, one generator)."""
    fault = [r for r in rows if r.fault]

    def areas(sample: Sequence[Row]) -> tuple[float, float]:
        v = aurc((r.verified_key(), not r.hit_at_1) for r in sample)
        f = aurc((r.fused_key(), not r.hit_at_1) for r in sample)
        assert v is not None and f is not None  # a resample is never empty
        return v, f

    by_stratum: dict[str, dict[tuple[str | None, ...], list[Row]]] = {}
    for r in fault:
        by_stratum.setdefault(r.system, {}).setdefault(r.cluster, []).append(r)

    def order(item: tuple[tuple[str | None, ...], list[Row]]) -> tuple[str, ...]:
        return tuple("" if x is None else x for x in item[0])

    strata = [
        [members for _, members in sorted(cl.items(), key=order)] for _, cl in sorted(by_stratum.items())
    ]
    rng = np.random.default_rng(seed)
    draws: list[tuple[float, float]] = []
    for _ in range(resamples):
        sample: list[Row] = []
        for clusters in strata:
            for j in rng.integers(0, len(clusters), size=len(clusters)):
                sample.extend(clusters[int(j)])
        draws.append(areas(sample))
    v0, f0 = areas(fault)
    out: dict[str, object] = {}
    for name, est, vals in (
        ("aurc_verdict", v0, [d[0] for d in draws]),
        ("aurc_fused", f0, [d[1] for d in draws]),
        ("aurc_difference", v0 - f0, [d[0] - d[1] for d in draws]),
    ):
        low, high = np.quantile(vals, [(1 - LEVEL) / 2, (1 + LEVEL) / 2])
        out[name] = {
            "estimate": round(est, DECIMALS), "low": round(float(low), DECIMALS),
            "high": round(float(high), DECIMALS), "n": len(fault),
            "n_clusters": sum(len(c) for c in strata),
        }  # fmt: skip
    return out


def literal_tau(windows: Sequence[Row], beta: float) -> dict[str, object]:
    """τ_nf of 04 §5.4 item 6 read literally: the ⌈(m + 1)(1 - beta)⌉-th smallest M over the windows
    Causentra could call NO_FAULT, m their count; next to it the fitted rule's m and index."""
    usable = sorted(round(w.m, DECIMALS) for w in windows if w.m is not None and not w.silent)
    index = rank_index(len(usable), beta)
    fitted_index = rank_index(len(windows), beta)
    return {
        "m_fitted": len(windows), "rank_index_fitted": fitted_index,
        "lands_on_infinity": fitted_index > len(usable), "n_never": len(windows) - len(usable),
        "m_literal": len(usable), "rank_index_literal": index, "tau_nf_literal": kth(usable, index),
    }  # fmt: skip


def group(rows: Sequence[Row], seed: int, resamples: int, pooled: bool, with_aurc: bool) -> dict[str, Any]:
    """The intervals of one system (or pooled); AURC only where the experiment pre-registers
    `risk_coverage` (re2-oracle-loso-off-v1 does not, #635)."""
    fault = [r for r in rows if r.fault]
    normal = [r for r in rows if not r.fault]
    return {
        "coverage": mean_interval(fault, lambda r: r.in_set, seed, resamples, pooled),
        "false_alarm_rate": mean_interval(normal, lambda r: r.status != NO_FAULT, seed, resamples, pooled),
        "wrong_no_fault_rate": mean_interval(fault, lambda r: r.status == NO_FAULT, seed, resamples, pooled),
        **(aurc_intervals(rows, seed, resamples) if with_aurc else {}),
    }


def sensitivity(rows: Sequence[Row], beta: float, seed: int, resamples: int) -> dict[str, object]:
    """Per fold: the literal τ fit on the other folds' windows, and the held-out NO_FAULT rates with it."""
    folds = sorted({r.fold for r in rows})
    if len(folds) < 2:
        raise SystemExit(f"rq3: the literal-τ sensitivity needs at least two folds, got {folds}")
    fit_on_label = "the other fold" if len(folds) == 2 else "the other folds"  # crossfit2 text kept (#555)
    taus: dict[str, dict[str, object]] = {}
    for fold in folds:
        fit_on = [r for r in rows if not r.fault and r.fold != fold]
        taus[fold] = literal_tau(fit_on, beta)

    def nf(r: Row) -> bool:
        tau = taus[r.fold]["tau_nf_literal"]
        return isinstance(tau, float) and r.no_fault_at(tau)

    out: dict[str, object] = {"held_out_fold": {f: {"fit_on": fit_on_label, **t} for f, t in taus.items()}}
    for system in [*sorted({r.system for r in rows}), POOLED]:
        mine = rows if system == POOLED else [r for r in rows if r.system == system]
        pooled = system == POOLED
        out[system] = {
            "false_alarm_rate": mean_interval([r for r in mine if not r.fault], lambda r: not nf(r),
                                              seed, resamples, pooled),
            "wrong_no_fault_rate": mean_interval([r for r in mine if r.fault], nf, seed, resamples, pooled),
        }  # fmt: skip
    return out


def check_against_summary(result: Mapping[str, Mapping[str, Any]], summary: Mapping[str, Any]) -> None:
    """The point estimates must equal the committed summary.json's (03 §13.3), or the join is wrong."""
    for g in cast("list[dict[str, Any]]", summary["groups"]):
        mine, m = result[g["system"]], g["metrics"]
        pairs = [
            ("coverage", m["coverage"]["coverage"]),
            ("false_alarm_rate", m["no_fault_rates"]["false_alarm_rate"]),
            ("wrong_no_fault_rate", m["no_fault_rates"]["wrong_no_fault_rate"]),
        ]
        if "aurc_verdict" in mine:  # computed only with risk_coverage, so the summary has it too
            pairs += [
                ("aurc_verdict", m["risk_coverage"]["aurc_verdict"]),
                ("aurc_fused", m["risk_coverage"]["aurc_fused"]),
            ]
        for name, want in pairs:
            got = mine[name]["estimate"]
            if abs(float(got) - float(want)) > SUMMARY_TOLERANCE:
                raise SystemExit(f"rq3: {g['system']} {name} is {got}, summary.json says {want}")


HIDDEN = ("root_service", "fault_label")  # answer-key labels: replaced by the opaque `cluster` id


def write_rows(path: Path, rows: Sequence[Row]) -> None:
    """rows.csv: every Row field except HIDDEN, plus `cluster`, the system and the cluster's ordinal
    in sorted cluster order (stable for a given answer key)."""
    ordinal: dict[str, dict[tuple[str | None, ...], int]] = {}
    for c in sorted({r.cluster for r in rows}, key=lambda c: tuple("" if x is None else x for x in c)):
        mine = ordinal.setdefault(str(c[0]), {})
        mine[c] = len(mine) + 1
    fields = ["cluster", *(f for f in asdict(rows[0]) if f not in HIDDEN)]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for r in rows:
            d = {k: v for k, v in asdict(r).items() if k not in HIDDEN}
            cell = {k: ("" if v is None else int(v) if isinstance(v, bool) else v) for k, v in d.items()}
            w.writerow({"cluster": f"{r.system}-{ordinal[r.system][r.cluster]:02d}", **cell})


def fitted_beta(calibration_dir: Path) -> float:
    """The beta of the experiment's committed calibration files, which must agree (09 §3.8)."""
    betas = {
        json.loads(p.read_text(encoding="utf-8"))["no_fault"]["beta"]
        for p in sorted(calibration_dir.glob("*.json"))
    }
    if len(betas) != 1:
        raise SystemExit(f"rq3: calibration files in {calibration_dir} have betas {sorted(betas)}")
    return float(betas.pop())


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rq3_intervals.py", description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--runs-root", type=Path, required=True, help="the runs root that holds bench/")
    ap.add_argument("--experiment", default="re2-oracle-rq3-off-v1")
    ap.add_argument("--results", type=Path, default=Path("bench/results"), help="results root")
    ap.add_argument("--data-root", type=Path, default=None, help="answer keys (default $VEYLTRACE_DATA)")
    args = ap.parse_args(argv)
    exp = load_experiment(Path("bench/experiments") / f"{args.experiment}.yaml")
    seed, resamples = exp.statistics.bootstrap.seed, exp.statistics.bootstrap.resamples
    beta = fitted_beta(args.results / exp.experiment_id / "calibration")
    rows = load_rows(exp, args.results, args.runs_root, args.data_root)
    with_aurc = "risk_coverage" in exp.metrics
    result: dict[str, dict[str, Any]] = {}
    for system in sorted({r.system for r in rows}):
        mine = [r for r in rows if r.system == system]
        result[system] = group(mine, seed, resamples, pooled=False, with_aurc=with_aurc)
    result[POOLED] = group(rows, seed, resamples, pooled=True, with_aurc=with_aurc)
    summary = json.loads((args.results / exp.experiment_id / "summary.json").read_text(encoding="utf-8"))
    check_against_summary(result, summary)
    doc = {
        "experiment_id": exp.experiment_id,
        "level": LEVEL,
        "resamples": resamples,
        "seed": seed,
        "beta": beta,
        "intervals": result,
        "literal_tau_sensitivity": sensitivity(rows, beta, seed, resamples),
    }
    out = args.results / OUT / exp.experiment_id
    out.mkdir(parents=True, exist_ok=True)
    write_rows(out / "rows.csv", rows)
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    (out / "summary.json").write_text(text, encoding="utf-8", newline="\n")  # LF on every OS
    print(f"rq3: {len(rows)} rows -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
