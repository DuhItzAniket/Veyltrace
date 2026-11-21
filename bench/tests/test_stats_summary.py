"""summary.json `statistics` (04 §8, #357) on handmade RE2-shaped cases with the frozen rq1 YAML."""

from __future__ import annotations

import json
import random
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from veyltrace_bench.experiment import load_experiment
from veyltrace_bench.metrics import CaseScore, MethodOutput, Truth, score_case
from veyltrace_bench.stats_summary import POOLED_REASON, Case
from veyltrace_bench.stats_summary import statistics as _statistics
from veyltrace_bench.summary import summarize
from veyltrace_core import io, textio
from veyltrace_core.canonical import canonical_json
from veyltrace_stats.exact import holm

REPO = Path(__file__).resolve().parents[2]
RQ1 = load_experiment(REPO / "bench" / "experiments" / "re2-oracle-rq1-v1.yaml")
EXAMPLE = REPO / "contracts" / "examples" / "bench_summary.example.json"
#: Hit rate per (system, method) over 18 cases: baro is the best baseline on ob, simplerca on ss, and
#: nsigma ties baro on tt, so the earlier listed (nsigma) wins there.
HITS = {
    "ob": {"veyltrace:off": 12, "rcaeval:nsigma": 6, "rcaeval:baro": 9, "simplerca": 3},
    "ss": {"veyltrace:off": 10, "rcaeval:nsigma": 4, "rcaeval:baro": 5, "simplerca": 8},
    "tt": {"veyltrace:off": 9, "rcaeval:nsigma": 7, "rcaeval:baro": 7, "simplerca": 2},
}


def statistics(exp: Any, cases: list[Case]) -> Any:
    """The statistics object as JSON-like data (Any), so tests index it freely."""
    return _statistics(exp, cases)


def _score(hit: bool) -> CaseScore:
    return score_case(
        Truth("checkout", "cpu", "cpu", "resource"), MethodOutput(ranks=("checkout" if hit else "cart",))
    )


def _cases() -> list[Case]:
    cases: list[Case] = []
    for system, methods in HITS.items():
        for method, hits in methods.items():
            for i in range(18):  # 6 clusters of 3 repetitions, as RE2's (system, root, fault)
                cluster = (system, f"svc{i // 3}", "cpu")
                cases.append(
                    Case(f"{system}{i:010d}", f"re2-{system}", system, method, cluster, _score(i < hits))
                )
    return cases


def test_intervals_match_the_summary_and_cover_every_group() -> None:
    got = statistics(RQ1, _cases())
    ac1 = {(r["dataset"], r["method"]): r for r in got["intervals"] if r["metric"] == "ac_at_1"}
    assert len(ac1) == 12
    for system, methods in HITS.items():
        for method, hits in methods.items():
            rows = [c.score for c in _cases() if c.system == system and c.method == method]
            assert ac1[(f"re2-{system}", method)]["estimate"] == summarize(rows)["ac_at_1"] == hits / 18
            assert ac1[(f"re2-{system}", method)]["n_clusters"] == 6
    metrics = {r["metric"] for r in got["intervals"]}
    assert metrics >= {"ac_at_1", "ac_at_5", "mrr", "avg_at_5"}
    assert not any(m.startswith(("chance", "lift", "rerank")) for m in metrics)  # n_i unknown: Chance@k null


def test_rq1_comparisons_pick_the_best_baseline_and_holm_over_pooled_plus_systems() -> None:
    got = statistics(RQ1, _cases())
    rows = got["comparisons"]
    best = {r["system"]: r["method_b"] for r in rows if r["kind"] == "noninferiority"}
    assert best == {
        "ob": "rcaeval:baro",
        "ss": "simplerca",
        "tt": "rcaeval:nsigma",
    }  # tt: tie, earlier listed
    assert all(r["margin"] == 0.0 and r["family"] is None and r["holm_p"] is None
               for r in rows if r["kind"] == "noninferiority")  # fmt: skip
    family = [r for r in rows if r["family"] == "rq1"]
    assert [(r["dataset"], r["system"]) for r in family] == [
        ("re2", None),
        ("re2-ob", "ob"),
        ("re2-ss", "ss"),
        ("re2-tt", "tt"),
    ]
    pooled = family[0]
    assert pooled["low"] is None and pooled["high"] is None and pooled["sign_flip_p"] is not None
    assert pooled["n_pairs"] == 54 and pooled["method_b"] == "rcaeval:baro"  # 21/54 beats 19/54 and 13/54
    assert [r["holm_p"] for r in family] == holm([r["sign_flip_p"] for r in family])
    ob = next(r for r in family if r["system"] == "ob")
    assert ob["difference"] == (12 - 9) / 18 and ob["low"] <= ob["difference"] <= ob["high"]
    assert ob["mcnemar_only_a"] == 3 and ob["mcnemar_only_b"] == 0  # hits are nested: 0..8 and 0..11
    assert got["not_run"] == [{"scope": "re2 pooled intervals", "reason": POOLED_REASON}]


def test_statistics_never_depend_on_row_order() -> None:
    cases = _cases()
    shuffled = cases[:]
    random.Random(7).shuffle(shuffled)
    assert canonical_json(statistics(RQ1, shuffled)) == canonical_json(statistics(RQ1, cases))


def test_mcnemar_is_null_when_the_experiment_turns_it_off() -> None:
    exp = RQ1.model_copy(update={"statistics": RQ1.statistics.model_copy(update={"mcnemar": False})})
    assert all(r["mcnemar_p"] is None for r in statistics(exp, _cases())["comparisons"])


def test_the_statistics_object_validates_as_bench_summary_1_1(tmp_path: Path) -> None:
    doc: dict[str, Any] = json.loads(textio.read_text(EXAMPLE))
    doc["statistics"] = statistics(RQ1, _cases())
    path = tmp_path / "summary.json"
    textio.write_bytes(path, canonical_json(doc) + b"\n")
    assert (
        cast(Any, io.read_path("bench_summary", path, validate=True)).statistics.params.cluster_by
        == "system/root_service/fault"
    )


def test_decoy_ranked_first_is_the_share_over_decoyed_rows() -> None:
    plain = _score(True)
    rows = [
        replace(plain, decoy_present=True, decoy_ranked_first=first) for first in (True, False, False, False)
    ]
    rows += [replace(plain, decoy_present=False), plain]  # no decoy, no planted changes: outside the share
    got = summarize(rows, ["decoy_ranked_first"])
    assert (got["decoy_ranked_first"], got["n_decoy"]) == (0.25, 4)


def test_a_seeded_arm_pairs_on_per_case_seed_means() -> None:
    """04 §8 "LLM arms": brief (3 seeds) vs off is paired per case on the seed mean; n_pairs counts
    cases, and McNemar is not run because the means are not binary (known answer below)."""
    rq2 = load_experiment(REPO / "bench" / "experiments" / "re2-oracle-rq2-v1.yaml")
    brief = {0: (1, 1, 0), 1: (0, 0, 0), 2: (1, 1, 1)}  # per-case seed hits: means 2/3, 0, 1
    off = {0: 1, 1: 0, 2: 0}
    cases: list[Case] = []
    for i in range(3):
        cid, cluster = f"ob{i:010d}", ("ob", f"svc{i}", "cpu")
        cases.append(Case(cid, "re2-ob", "ob", "veyltrace:off", cluster, _score(off[i] == 1)))
        for seed, hit in zip((1, 2, 3), brief[i], strict=True):
            cases.append(Case(cid, "re2-ob", "ob", "veyltrace:brief", cluster, _score(hit == 1), seed))
    got = statistics(rq2, cases)
    row = next(r for r in got["comparisons"] if r["system"] == "ob" and r["kind"] == "noninferiority")
    assert (row["method_a"], row["method_b"], row["n_pairs"], row["n_clusters"]) == (
        "veyltrace:brief", "veyltrace:off", 3, 3,
    )  # fmt: skip
    assert abs(row["difference"] - (-1 / 3 + 0 + 1) / 3) < 1e-12  # mean of the per-case differences
    assert (row["mcnemar_only_a"], row["mcnemar_p"]) == (None, None)
    reasons = {r["reason"] for r in got["not_run"] if r["scope"].startswith("mcnemar ")}
    assert reasons == {"seeded method: per-case seed means are not binary"}
