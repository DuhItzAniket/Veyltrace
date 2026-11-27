"""scripts/rq3_intervals.py (#555): RQ3 cluster-bootstrap intervals and the literal-τ sensitivity."""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from veyltrace_bench.summary import aurc
from veyltrace_stats.cluster import cluster_bootstrap

ROOT = Path(__file__).resolve().parents[1]


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rq3_intervals", ROOT / "scripts" / "rq3_intervals.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while the class is built
    spec.loader.exec_module(module)
    return module


rq3 = _script()


def _row(i: int, *, system: str = "ob", fault: bool = True, **kw: Any) -> Any:
    base = dict(
        dataset=f"re2-{system}", system=system, case_id=f"c{i:03d}", variant="" if fault else "shift-510",
        fold="foldA" if i % 2 else "foldB", root_service=f"svc{i % 5}", fault_label="cpu", fault=fault,
        hit_at_1=fault and i % 3 == 0, in_set=fault and i % 4 != 0, status="INCONCLUSIVE",
        margin=0.1 * (i % 7), leader_fused=0.01 * (i % 11), m=2.0 + i % 9, silent=False, run_id=f"r{i:03d}",
    )  # fmt: skip
    base.update(kw)
    return rq3.Row(**base)


def test_no_fault_is_causentras_rule() -> None:
    r = _row(1, fault=False, m=1.3862943614)
    assert r.no_fault_at(1.386294361)  # equal at 9 decimals (09 §3.8)
    assert not replace(r, silent=True).no_fault_at(100.0)  # a silent service rules NO_FAULT out
    assert not replace(r, m=None).no_fault_at(100.0)  # no robust_z atom: never NO_FAULT


def test_literal_tau_leaves_never_windows_out_of_m() -> None:
    windows = [_row(i, fault=False, m=float(i)) for i in range(1, 11)]
    windows += [replace(_row(90, fault=False), silent=True), replace(_row(91, fault=False), m=None)]
    got = rq3.literal_tau(windows, 0.1)
    # fitted rule: m = 12, index ceil(13 * 0.9) = 12 > 10 finite windows, so it lands on +inf
    assert got["m_fitted"] == 12 and got["rank_index_fitted"] == 12 and got["lands_on_infinity"]
    # literal: m = 10, index ceil(11 * 0.9) = 10, the largest finite M
    assert got["m_literal"] == 10 and got["rank_index_literal"] == 10 and got["tau_nf_literal"] == 10.0
    assert got["n_never"] == 2


def test_proportions_use_the_cluster_bootstrap_of_the_summary() -> None:
    rows = [_row(i) for i in range(40)]
    got = rq3.mean_interval(rows, lambda r: r.in_set, seed=1, resamples=200, pooled=False)
    want = cluster_bootstrap([1.0 if r.in_set else 0.0 for r in rows], [r.cluster for r in rows],
                             seed=1, resamples=200)  # fmt: skip
    assert got == {"estimate": round(want.estimate, 9), "low": round(want.low, 9),
                   "high": round(want.high, 9), "n": 40, "n_clusters": want.n_clusters}  # fmt: skip


def test_aurc_estimates_equal_the_summary_and_are_seeded() -> None:
    rows = [_row(i, system=s) for i in range(30) for s in ("ob", "tt")]
    rows += [_row(100 + i, fault=False) for i in range(5)]  # normal windows: not in the AURC
    a = rq3.aurc_intervals(rows, seed=1, resamples=100)
    assert a == rq3.aurc_intervals(rows, seed=1, resamples=100)
    fault = [r for r in rows if r.fault]
    v = aurc((r.verified_key(), not r.hit_at_1) for r in fault)
    f = aurc((r.fused_key(), not r.hit_at_1) for r in fault)
    assert v is not None and f is not None
    assert a["aurc_verdict"]["estimate"] == round(v, 9) and a["aurc_fused"]["estimate"] == round(f, 9)
    assert a["aurc_difference"]["estimate"] == round(v - f, 9)
    for entry in a.values():
        assert entry["low"] <= entry["high"]
        assert entry["n"] == 60 and entry["n_clusters"] == 10  # 5 root services x 2 systems


def test_sensitivity_fits_each_fold_on_the_other_folds_windows() -> None:
    normal = [_row(i, fault=False, m=float(i)) for i in range(1, 21)]  # odd i in foldA, even in foldB
    fault = [_row(100 + i, m=1.0) for i in range(10)]  # M below every tau: all wrong NO_FAULT
    got = rq3.sensitivity(normal + fault, 0.1, seed=1, resamples=50)
    # foldA's held-out rows use the tau fit on foldB's windows (M = 2, 4, ..., 20)
    assert got["held_out_fold"]["foldA"]["tau_nf_literal"] == 20.0
    assert got["held_out_fold"]["foldB"]["tau_nf_literal"] == 19.0
    assert got["pooled"]["wrong_no_fault_rate"]["estimate"] == 1.0
    # foldA windows (M odd, 1..19) are all <= 20; of foldB's (M even, 2..20) only M = 20 > 19 alarms
    assert got["ob"]["false_alarm_rate"]["estimate"] == pytest.approx(1 / 20)


def test_loso_fits_each_held_out_system_on_the_other_systems_windows() -> None:
    # re2-oracle-loso-off-v1 has three folds, one per held-out system (#635)
    rows = [
        _row(i, system=s, fault=False, m=float(i), fold=f"loso-{s}")
        for s, ms in (("ob", range(1, 11)), ("ss", range(11, 21)), ("tt", range(21, 31)))
        for i in ms
    ]
    got = rq3.sensitivity(rows, 0.1, seed=1, resamples=50)
    held = got["held_out_fold"]
    assert sorted(held) == ["loso-ob", "loso-ss", "loso-tt"]
    assert {h["fit_on"] for h in held.values()} == {"the other folds"}
    # 20 windows each: the ceil(21 * 0.9) = 19th smallest of the other two systems' M
    assert held["loso-ob"]["m_literal"] == 20 and held["loso-ob"]["tau_nf_literal"] == 29.0
    assert held["loso-ss"]["tau_nf_literal"] == 29.0
    assert held["loso-tt"]["tau_nf_literal"] == 19.0
    # tt windows (M 21..30) against tau 19: every one alarms; ob and ss windows are all <= 29
    assert got["tt"]["false_alarm_rate"]["estimate"] == 1.0
    assert got["ob"]["false_alarm_rate"]["estimate"] == 0.0


def test_one_fold_is_refused() -> None:
    rows = [_row(i, fault=False, m=float(i), fold="all") for i in range(1, 11)]
    with pytest.raises(SystemExit, match="at least two folds"):
        rq3.sensitivity(rows, 0.1, seed=1, resamples=10)


def test_find_run_needs_exactly_one_matching_verdict(tmp_path: Path) -> None:
    for name, h in (("a", "h1"), ("b", "h2"), ("c", "h2")):
        (tmp_path / name).mkdir()
        (tmp_path / name / "verdict.json").write_text(json.dumps({"verdict_hash": h}), encoding="utf-8")
    assert rq3.find_run(tmp_path, "h1").name == "a"
    with pytest.raises(SystemExit):
        rq3.find_run(tmp_path, "h2")
    with pytest.raises(SystemExit):
        rq3.find_run(tmp_path, "h3")


def test_a_summary_that_disagrees_is_refused() -> None:
    est = {"estimate": 0.5}
    mine = {"ob": {k: est for k in ("coverage", "false_alarm_rate", "wrong_no_fault_rate",
                                     "aurc_verdict", "aurc_fused")}}  # fmt: skip
    metrics = {
        "coverage": {"coverage": 0.5},
        "no_fault_rates": {"false_alarm_rate": 0.5, "wrong_no_fault_rate": 0.5},
        "risk_coverage": {"aurc_verdict": 0.5, "aurc_fused": 0.5},
    }
    rq3.check_against_summary(mine, {"groups": [{"system": "ob", "metrics": metrics}]})
    metrics["coverage"]["coverage"] = 0.6
    with pytest.raises(SystemExit):
        rq3.check_against_summary(mine, {"groups": [{"system": "ob", "metrics": metrics}]})


def test_without_risk_coverage_there_is_no_aurc_to_compute_or_check() -> None:
    # re2-oracle-loso-off-v1 does not pre-register risk_coverage, so its summary has none (#635)
    rows = [_row(i) for i in range(10)] + [_row(100 + i, fault=False) for i in range(5)]
    got = rq3.group(rows, seed=1, resamples=20, pooled=False, with_aurc=False)
    assert sorted(got) == ["coverage", "false_alarm_rate", "wrong_no_fault_rate"]
    assert "aurc_difference" in rq3.group(rows, seed=1, resamples=20, pooled=False, with_aurc=True)
    est = {"estimate": 0.5}
    mine = {"ob": {k: est for k in ("coverage", "false_alarm_rate", "wrong_no_fault_rate")}}
    metrics = {
        "coverage": {"coverage": 0.5},
        "no_fault_rates": {"false_alarm_rate": 0.5, "wrong_no_fault_rate": 0.5},
        "risk_coverage": None,
    }
    rq3.check_against_summary(mine, {"groups": [{"system": "ob", "metrics": metrics}]})


def test_rows_csv_has_opaque_clusters_and_no_truth_labels(tmp_path: Path) -> None:
    rows = [_row(i) for i in range(10)] + [_row(i, system="tt") for i in range(3)]
    rq3.write_rows(tmp_path / "rows.csv", rows)
    text = (tmp_path / "rows.csv").read_text(encoding="utf-8")
    header = text.splitlines()[0].split(",")
    assert header[0] == "cluster" and "root_service" not in header and "fault_label" not in header
    assert "svc" not in text  # no root service name anywhere
    clusters = {line.split(",")[0] for line in text.splitlines()[1:]}
    assert clusters == {"ob-01", "ob-02", "ob-03", "ob-04", "ob-05", "tt-01", "tt-02", "tt-03"}
