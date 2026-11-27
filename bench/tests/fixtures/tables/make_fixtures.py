"""Write the hand-made result fixtures of the table generator tests (R-17).

Run from the repo root: `uv run python bench/tests/fixtures/tables/make_fixtures.py`. Every number
here is synthetic (multiples of 1/8 over 8 services, so chance and lift are exact); the commit is
"fixture" and the producer "bench@fixture", so no fixture can pass for a real result. Files go
through core io, so they are validated and canonical like bench's own output.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from typing import Any

from veyltrace_bench.experiment import load_experiment
from veyltrace_bench.tables.subset import case_list
from veyltrace_core import io, textio
from veyltrace_core.hashing import sha256_text_lf

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
OUT = HERE / "results"
EXAMPLES = REPO / "contracts" / "examples"
EXPERIMENTS = REPO / "bench" / "experiments"
N_SERVICES = 8  # every fixture case has 8 services: Chance@k = k/8
PER_CASE_HEADER = (
    "case_id,dataset,system,method,ai_mode,seed,variant,fold,protocol,run_outcome,pool_hit,shift_s,"
    "sources_dropped,status,ranks,hit_at_1,hit_at_3,hit_at_5,retrieval_hit,fault_class_hit,in_set,"
    "set_size,onset_error_ms,decoy_present,decoy_ranked_first,wall_ms,peak_rss_mb,tokens_in,tokens_out,"
    "verdict_hash\n"
)
ENTRIES = ("ac_at_k", "avg_at_5", "chance", "cost", "decoy_ranked_first", "fine_ac_at_k", "lift", "mrr",
           "onset_error", "rerank_at_1", "retrieval_at_k", "coverage", "set_size", "no_fault_rates",
           "risk_coverage", "selective_accuracy", "decoy_top1_change", "permutation_invariance")  # fmt: skip
#: An R-05-era summary (bench_summary 0.1.0), which the tables read without its contract (R5).
R05_SUMMARY = {
    "experiment_id": "re2-oracle-baselines-r05",
    "groups": [{"dataset": "re2-ob"}, {"dataset": "re2-ss"}],
    "schema_version": "0.1.0",
    "statistics": "not run: cluster bootstrap CIs and tests come from bench/stats (O-14)",
}


def _example(name: str) -> dict[str, Any]:
    return json.loads(textio.read_text(EXAMPLES / f"{name}.example.json"))


def group(
    dataset: str, method: str, ac: list[float], *, slate: float | None, listed: tuple[str, ...], windows: int = 0
) -> dict[str, Any]:
    """One summary group of 8 fault cases (+ `windows` normal windows) with AC@1..5 = `ac`."""
    chance = [k / N_SERVICES for k in range(1, 6)]
    metrics: dict[str, Any] = {
        "ac_at_k": {f"ac_at_{k}": ac[k - 1] for k in range(1, 6)},
        "avg_at_5": {"avg_at_5": sum(ac) / 5},
        "mrr": {"mrr": ac[0]},
        "fine_ac_at_k": {f"fine_ac_at_{k}": ac[k - 1] / 2 for k in range(1, 6)},
        "retrieval_at_k": {"retrieval_at_k": slate, "retrieval_k": [5] if slate is not None else None,
                           "pool_retrieval": slate},
        "rerank_at_1": {"rerank_at_1": ac[0] / slate if slate else None},
        "chance": {f"chance_at_{k}": chance[k - 1] for k in range(1, 6)},
        "lift": {**{f"lift_at_{k}": ac[k - 1] / chance[k - 1] for k in range(1, 6)},
                 **{f"chance_diff_at_{k}": ac[k - 1] - chance[k - 1] for k in range(1, 6)}},
        "cost": {"n_cost": 8, "wall_ms_p50": 25000.0, "wall_ms_p95": 31000.0, "peak_rss_mb_p50": 1500.0,
                 "peak_rss_mb_p95": 1600.0, "tokens_in_p50": None, "tokens_in_p95": None,
                 "tokens_out_p50": None, "tokens_out_p95": None},
        "onset_error": None,
        "decoy_ranked_first": None,
        # bench_summary 1.2 entries (CCR #404), synthetic: 7 of 8 in the set, alpha 0.10
        "coverage": {"coverage": 0.875, "coverage_gap": -0.025, "pool_coverage": 1.0, "n_fault": 8, "by_fold": []},
        "set_size": {"set_size_mean": 1.5, "set_size_median": 1.0, "singleton_share": 0.5, "n_set": 8},
        "no_fault_rates": {"false_alarm_rate": 0.25, "n_normal": windows, "wrong_no_fault_rate": 0.0, "n_fault": 8,
                           "no_fault_precision": 1.0, "no_fault_recall": 0.75, "by_fold": []},
        "risk_coverage": {"aurc_verdict": 0.25, "aurc_fused": 0.375, "n_fault": 8},
        "selective_accuracy": {"ac_at_1_confirmed": 0.75, "answer_rate_confirmed": 0.5,
                               "ac_at_1_likely_or_better": 0.625, "answer_rate_likely_or_better": 0.875, "n_fault": 8},
        "decoy_top1_change": {"decoy_top1_change": 0.125, "n_pairs": 8},
        "permutation_invariance": {"permutation_invariance": 0.875, "n_cases": 8},
    }  # fmt: skip
    return {
        "dataset": dataset, "system": dataset.split("-")[1], "method": method,
        "metrics": {e: (metrics[e] if e in listed else None) for e in ENTRIES},
        "n_rows": 8 + windows, "n_fault": 8, "n_no_truth": windows, "n_unranked": 0, "n_fine": 8, "n_chance": 8,
        "n_outside_services": 0,
        "outcomes": {"failed": 0, "no_alert": 0, "ok": 8 + windows, "rejected": 0, "timeout": 0},
    }  # fmt: skip


def interval(dataset: str, method: str, metric: str, estimate: float) -> dict[str, Any]:
    system = None if "-" not in dataset else dataset.split("-")[1]
    return {"dataset": dataset, "system": system, "method": method, "metric": metric, "estimate": estimate,
            "low": max(0.0, estimate - 0.125), "high": min(1.0, estimate + 0.125), "n_cases": 8, "n_clusters": 4}  # fmt: skip


def write(
    experiment_id: str, summary: dict[str, Any] | None, *, dirty: bool = False, rows: list[dict[str, Any]] | None = None
) -> None:
    out = OUT / experiment_id
    manifest = _example("bench_manifest")
    yaml = EXPERIMENTS / f"{experiment_id}.yaml"  # the committed experiment, as bench records it
    manifest["experiment_id"] = experiment_id
    manifest["experiment"] = load_experiment(yaml).model_dump(mode="json")
    manifest["experiment_sha256"] = sha256_text_lf(yaml)
    manifest["code"]["dirty"] = dirty
    synth = manifest["datasets"][0]
    manifest["datasets"] = [  # 8 run cases and 1 excluded per RE2 part; ids unique across parts
        synth | {"dataset": part, "cases": [f"{j:04x}{i:08x}" for i in range(8)], "excluded": [f"{j:04x}{8:08x}"]}
        for j, part in enumerate(("re2-ob", "re2-ss", "re2-tt"), 1)
    ]
    io.write_path("bench_manifest", manifest, out / "manifest.json")
    if rows:
        io.write_path("bench_result", rows, out / "per_case.csv")  # validated and sorted like bench's
    else:
        textio.write_text(out / "per_case.csv", PER_CASE_HEADER)
    if summary is not None:
        io.write_path("bench_summary", summary, out / "summary.json")


def summary(experiment_id: str, groups: list[dict[str, Any]], statistics: object) -> dict[str, Any]:
    doc = _example("bench_summary")
    doc.update(experiment_id=experiment_id, groups=groups, producer="bench@fixture", statistics=statistics,
               excluded={"re2-ob": [], "re2-ss": [], "re2-tt": []})  # fmt: skip
    return doc


def rq1() -> dict[str, Any]:
    listed = (
        "ac_at_k",
        "avg_at_5",
        "mrr",
        "fine_ac_at_k",
        "retrieval_at_k",
        "rerank_at_1",
        "chance",
        "lift",
        "cost",
    )
    acs = {"veyltrace:off": [0.5, 0.75, 0.875, 0.875, 1.0], "rcaeval:baro": [0.375, 0.5, 0.625, 0.75, 0.75],
           "rcaeval:nsigma": [0.25, 0.5, 0.5, 0.625, 0.75], "simplerca": [0.125, 0.25, 0.375, 0.375, 0.5]}  # fmt: skip
    groups = [
        group(ds, m, ac, slate=0.875 if m == "veyltrace:off" else None, listed=listed)
        for ds in ("re2-ob", "re2-ss")
        for m, ac in sorted(acs.items())
    ]  # no re2-tt group: a system without rows
    intervals = [
        interval(ds, m, metric, ac[k - 1])
        for ds in ("re2-ob", "re2-ss")
        for m, ac in sorted(acs.items())
        for k, metric in ((1, "ac_at_1"), (3, "ac_at_3"), (5, "ac_at_5"))
        if not (ds == "re2-ss" and k == 5)
    ]  # no re2-ss ac_at_5 interval: a case mean whose interval the summary lacks
    base = {"metric": "ac_at_1", "method_a": "veyltrace:off", "method_b": "rcaeval:baro", "n_pairs": 8,
            "n_clusters": 4, "mcnemar_only_a": 2, "mcnemar_only_b": 1}  # fmt: skip
    comparisons = [
        base | {"dataset": "re2-ob", "system": "ob", "kind": kind, "family": fam, "margin": margin, "difference": 0.125,
                "low": -0.125, "high": 0.375, "sign_flip_p": 0.5, "mcnemar_p": 1.0, "holm_p": holm}
        for kind, fam, margin, holm in (("noninferiority", None, 0.0, None), ("superiority", "rq1", None, 0.0004))
    ]  # fmt: skip
    stats = {"params": _example("bench_summary")["statistics"]["params"], "intervals": sorted(
        intervals, key=lambda i: (i["dataset"], i["system"] or "", i["method"], i["metric"])),
        "comparisons": comparisons,
        "not_run": [{"scope": "re2 pooled intervals", "reason": "waits for the system-stratified cluster bootstrap"}]}  # fmt: skip
    return summary("re2-oracle-rq1-v1", groups, stats)


def case_row(case_id: str, dataset: str, method: str, seed: int | None, hits: tuple[int, int, int],
             variant: str | None = None) -> dict[str, Any]:  # fmt: skip
    """One per_case.csv row of an `ok` run with the given hits at 1, 3 and 5."""
    return {
        "case_id": case_id, "dataset": dataset, "system": dataset.split("-")[1], "method": method,
        "ai_mode": "record" if seed is not None else "off", "seed": seed, "variant": variant, "fold": None,
        "protocol": "oracle", "run_outcome": "ok", "pool_hit": True, "shift_s": 0, "sources_dropped": [],
        "status": None, "ranks": ["svc_cpu"], "hit_at_1": bool(hits[0]), "hit_at_3": bool(hits[1]),
        "hit_at_5": bool(hits[2]), "retrieval_hit": True, "fault_class_hit": None, "in_set": None, "set_size": None,
        "onset_error_ms": None, "decoy_present": None, "decoy_ranked_first": None, "wall_ms": 1000.0,
        "peak_rss_mb": 1000.0, "tokens_in": 10 if seed is not None else None,
        "tokens_out": 5 if seed is not None else None, "verdict_hash": None,
    }  # fmt: skip


def rq2() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """re2-oracle-rq2-v1: a summary over all cases, and brief rows on four 90-case-subset ids (two
    per part, ob and ss), one id outside the subset, an extra seed and a perturbed variant, so the
    shift curve's computed 0 s point (review H1) must pick exactly the subset's rows and seeds."""
    subset = sorted(case_list(REPO / "bench" / "re2_investigate_cases.yaml"))[:4]
    brief = "veyltrace:brief"
    rows = [
        *(case_row(subset[0], "re2-ob", brief, s, (1, 1, 1)) for s in (1, 2, 3)),  # in: AC@1 3/6 on ob
        *(case_row(subset[1], "re2-ob", brief, s, (0, 1, 1)) for s in (1, 2, 3)),  # in: AC@3 6/6 on ob
        case_row(subset[0], "re2-ob", brief, 4, (0, 0, 0)),  # out: seed 4 is not a shift-arm seed
        case_row(subset[1], "re2-ob", brief, 1, (1, 1, 1), variant="perm-1"),  # out: a perturbed variant
        *(case_row("aaaaaaaaaaaa", "re2-ob", brief, s, (1, 1, 1)) for s in (1, 2, 3)),  # out: not in the subset
        case_row(subset[0], "re2-ob", "veyltrace:off", None, (0, 0, 0)),  # out: another method
        *(case_row(c, "re2-ss", brief, s, (1, 1, 1)) for c in subset[2:] for s in (1, 2, 3)),  # in: AC@1 1 on ss
    ]
    listed = ("ac_at_k", "avg_at_5", "mrr", "fine_ac_at_k", "retrieval_at_k", "rerank_at_1", "chance", "lift", "cost")
    acs = {"agent-only:brief": [0.25, 0.5, 0.625, 0.75, 0.75], "veyltrace:brief": [0.625, 0.75, 0.875, 1.0, 1.0],
           "veyltrace:off": [0.5, 0.75, 0.875, 0.875, 1.0]}  # fmt: skip
    groups = [group(ds, m, ac, slate=0.875, listed=listed) for ds in ("re2-ob", "re2-ss") for m, ac in sorted(acs.items())]
    intervals = [interval(ds, m, "ac_at_1", ac[0]) for ds in ("re2-ob", "re2-ss") for m, ac in sorted(acs.items())]
    base = {"dataset": "re2-ob", "system": "ob", "metric": "ac_at_1", "method_a": brief, "method_b": "veyltrace:off",
            "n_pairs": 8, "n_clusters": 4, "difference": 0.125, "low": 0.0, "high": 0.25, "sign_flip_p": 0.25,
            "mcnemar_only_a": 3, "mcnemar_only_b": 1, "mcnemar_p": 0.625}  # fmt: skip
    comparisons = [
        base | {"kind": "noninferiority", "family": None, "margin": 0.0, "holm_p": None},
        base | {"kind": "superiority", "family": "rq2", "margin": None, "holm_p": 0.5},
    ]
    stats = {"params": _example("bench_summary")["statistics"]["params"], "intervals": intervals,
             "comparisons": comparisons, "not_run": []}  # fmt: skip
    return summary("re2-oracle-rq2-v1", groups, stats), rows


def main() -> None:
    shutil.rmtree(OUT, ignore_errors=True)
    write("re2-oracle-rq1-v1", rq1())
    listed = ("ac_at_k", "avg_at_5", "mrr", "chance", "lift", "cost")
    prior = [
        group(ds, "prior-only", [0.25, 0.5, 0.5, 0.625, 0.75], slate=None, listed=listed)
        for ds in ("re2-ob", "re2-ss", "re2-tt")
    ]
    write(
        "re2-oracle-prior-only-v1",
        summary("re2-oracle-prior-only-v1", prior, "not run: fixture statistics are off"),
    )
    write(
        "re2-detected-rq1-v1",
        summary("re2-detected-rq1-v1", copy.deepcopy(rq1()["groups"]), "not run: dirty"),
        dirty=True,
    )
    write("re3-oracle-rq2-v1", None)  # incomplete: no summary.json
    listed = ("ac_at_k", "permutation_invariance", "cost")
    perm = [group(ds, "veyltrace:brief", [0.5, 0.75, 0.875, 0.875, 1.0], slate=0.875, listed=listed) for ds in ("re2-ob", "re2-ss")]
    write("re2-oracle-permute-v1", summary("re2-oracle-permute-v1", perm, "not run: fixture statistics are off"))
    doc, rows = rq2()
    write("re2-oracle-rq2-v1", doc, rows=rows)
    listed = ("ac_at_k", "retrieval_at_k", "cost", "coverage", "set_size", "risk_coverage", "no_fault_rates")
    rq3 = [
        group(ds, m, [0.5, 0.75, 0.875, 0.875, 1.0], slate=0.875, listed=listed, windows=4)
        for ds in ("re2-ob", "re2-ss", "re2-tt") for m in ("veyltrace:brief", "veyltrace:off")
    ]  # fmt: skip
    write("re2-oracle-rq3-v1", summary("re2-oracle-rq3-v1", rq3, "not run: fixture statistics are off"))
    old = OUT / "re2-oracle-baselines-r05"
    write("re2-oracle-baselines-r05", None)
    textio.write_text(old / "summary.json", json.dumps(R05_SUMMARY, sort_keys=True) + "\n")
    textio.write_text(
        OUT / "not_run.yaml", "fse26-oracle-rq1-v1: stretch dataset not verified (07 §1.1 cut item 2)\n"
    )


if __name__ == "__main__":
    main()
