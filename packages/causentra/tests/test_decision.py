"""Tests of decision steps 1–3, 6 and the uncalibrated set (09 §3.2–§3.7, the §3.14 example)."""

from __future__ import annotations

import itertools
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from veyltrace_causatrix.views import Atom, evidence_view, graph_view
from veyltrace_causentra.config import config_from
from veyltrace_causentra.decision import claim_sum, decide, trial_factor, verified
from veyltrace_causentra.inputs import CausentraInputs, Claim, load_inputs
from veyltrace_causentra.trials import TrialResult
from veyltrace_contracts import models
from veyltrace_core.config import load_section_file
from veyltrace_core.testing import make_context

CFG = config_from(load_section_file("causentra"), load_section_file("core"))
CASE = "59e0d31bcc42"
_IDS = itertools.count(1)


def _tr(tid: str, result: str) -> TrialResult:
    return TrialResult(tid, result, None if result == "pass" else "x", ())


def test_09_3_14_arithmetic() -> None:
    passes = [_tr(t, "pass") for t in ("T1", "T2", "T3", "T4")]
    supporting_untestable = [_tr("T6", "untestable"), _tr("T8", "untestable")]
    a = verified(1.0, [*passes, *supporting_untestable], 0.10, CFG)
    b = verified(0.0460 / 0.0480, [*passes, _tr("T5", "fail"), *supporting_untestable], 0.0, CFG)
    c_trials = [
        _tr("T1", "pass"),
        _tr("T2", "untestable"),
        _tr("T3", "pass"),
        _tr("T4", "pass"),
        _tr("T5", "fail"),
    ]
    c_trials += [*supporting_untestable, _tr("T9", "fail")]
    assert trial_factor(c_trials, CFG) == pytest.approx(0.6885)
    c = verified(0.0300 / 0.0480, c_trials, 0.20, CFG)
    assert (a, b, c) == (1.1, 0.8625, 0.516375)
    assert (round(1 - b / a, 9), round(1 - c / a, 9)) == (0.215909091, 0.530568182)
    assert round(1 - b / verified(1.0, passes, 0.0, CFG), 9) == 0.1375  # the same case with AI off
    assert trial_factor([_tr("T1", "fail")], CFG) == 0.25
    assert trial_factor([_tr("T1", "fail")], replace(CFG, disabled=("T1",))) == 1.0


def _claim(cand: str, predicate: str, holds: bool | None, args: str = "{}") -> Claim:
    return Claim(f"E{next(_IDS):010x}", cand, predicate, args, holds)


def test_claim_sum_counts_true_claims_with_polarity_and_clips() -> None:
    claims = [
        _claim("a", "zscore_above", True),
        _claim("a", "silent", True),
        _claim("a", "onset_before", False),
    ]
    claims += [
        _claim("a", "edge_anomalous", True),
        _claim("a", "error_rate_above", None),
        _claim("b", "silent", True),
    ]
    assert claim_sum("a", claims, CFG) == pytest.approx(0.10)  # 0.10 + 0.10 - 0.10 (edge_anomalous refutes)
    many = [_claim("a", "zscore_above", True, f'{{"k":{k}}}') for k in range(5)]
    assert claim_sum("a", many, CFG) == 0.3
    against = [_claim("a", "edge_anomalous", True, f'{{"callee":"x{k}"}}') for k in range(5)]
    assert claim_sum("a", against, CFG) == -0.3


def _i(cand: str, z: float) -> list[Atom]:
    """Atoms that make T1–T4 pass for `cand` (internal z, self onset, entry reached, not silent)."""
    z_args = {"detector": "robust_z", "family": "cpu", "source": "metrics", "window": "incident"}
    specs: list[tuple[str, float, dict[str, Any]]] = [
        ("internal_anomaly", z, z_args),
        ("onset_precedence", 0.0, {"scope": "self", "window": "onset"}),
        ("propagation", 1.0, {"scope": "entry", "window": "incident"}),
        ("silence", 0.0, {"window": "incident"}),
    ]
    return [Atom(f"E{next(_IDS):010x}", cand, None, kind, args, v) for kind, v, args in specs]


def _slate(scores: dict[str, float], k: int) -> models.Slate:
    order = sorted(scores, key=lambda s: (-round(scores[s], 9), s))
    base = {
        "component": None,
        "indicator": "cpu",
        "mode": "resource",
        "fault_class": "cpu",
        "ranker_ranks": {},
    }
    cands = [
        {**base, "rank": i, "service": s, "fused_score": scores[s], "ranker_scores": {}}
        for i, s in enumerate(order[:k], 1)
    ]
    fusion = {"method": "rrf", "k": 60, "weights": {"prism_m": 1.0}}
    all_scores = [{"service": s, "fused_score": scores[s]} for s in order]
    return models.Slate.model_validate(
        {"schema_version": "0.1.0", "case_id": CASE, "k": k, "rankers_active": ["prism_m"], "fusion": fusion}
        | {"candidates": cands, "all_scores": all_scores}
    )


def _proposals(*specs: tuple[str, str, str, dict[str, Any]]) -> models.Proposals:
    """(proposal_id, service, predicate, args) per proposal, one claim each."""
    items = [
        {
            "proposal_id": pid,
            "hypothesis": {"service": svc, "component": None, "fault_class": "cpu", "indicator": None},
            "claims": [{"claim_id": f"{pid}-1", "predicate": pred, "args": args, "cites": []}],
            "requested_trials": [],
            "rationale": "",
        }
        for pid, svc, pred, args in specs
    ]
    budget = {"turns": 1, "tokens_in": 1, "tokens_out": 1, "wall_ms": 1.0}
    return models.Proposals.model_validate(
        {"schema_version": "0.1.0", "case_id": CASE, "status": "complete", "mode": "external", "model": None}
        | {"budget_used": budget, "proposals": items, "asks": []}
    )


@pytest.fixture
def base(synth01_dir: Path) -> CausentraInputs:
    ctx = make_context("causentra", synth01_dir)
    return load_inputs(ctx, config_from(ctx.config, ctx.config.core))


def _case(base: CausentraInputs, atoms: list[Atom], k: int = 2, **changes: Any) -> CausentraInputs:
    scores = {"a": 0.0480, "b": 0.0460, "c": 0.0300}
    graph = graph_view(
        list(scores),
        [(s, "service") for s in scores],
        [{"src": "a", "dst": "b", "weight": 1.0, "provenance": ["traces"]}],
        include_external=False,
    )
    return replace(
        base,
        slate=_slate(scores, k),
        ev=evidence_view(atoms, graph.universe),
        graph=graph,
        graph_nodes=frozenset(scores),
        **changes,
    )


def test_ai_off_pool_scores_order_and_set(base: CausentraInputs) -> None:
    d = decide(_case(base, [*_i("a", 9.0), *_i("b", 4.0)]), CFG)
    assert [(c.service, c.origin, c.v) for c in d.ranked] == [
        ("a", "slate", 1.0),
        ("b", "slate", 0.958333333),
    ]
    assert d.leader is not None and d.leader.service == "a"
    assert (d.nonconformity, d.margin) == ({"a": 0.0, "b": 0.041666667}, 0.041666667)
    assert [c.service for c in d.candidate_set] == ["a"]  # uncalibrated q_hat = 0
    wide = decide(_case(base, [*_i("a", 9.0), *_i("b", 4.0)], q_hat=None), CFG)
    assert [c.service for c in wide.candidate_set] == ["a", "b"]


def test_admission_needs_a_supporting_claim_that_holds(base: CausentraInputs) -> None:
    args = '{"k":4.0,"signal":"cpu"}'
    proposals = _proposals(
        ("P00000001", "c", "zscore_above", {"k": 4.0, "signal": "cpu"}),
        ("P00000002", "b", "zscore_above", {"k": 4.0, "signal": "cpu"}),
        ("P00000003", "zz", "silent", {}),
    )
    claims = (
        _claim("a", "zscore_above", True, args),
        _claim("b", "zscore_above", True, args),
        _claim("c", "zscore_above", True, args),
    )
    d = decide(
        _case(base, [*_i("a", 9.0), *_i("b", 4.0), *_i("c", 5.0)], proposals=proposals, claims=claims), CFG
    )
    assert d.admitted == frozenset({"P00000001", "P00000002"})  # zz is not a graph node
    assert {c.service: (c.origin, c.s0) for c in d.ranked}["c"] == ("proposal", 0.625)
    assert {c.service: c.origin for c in d.ranked}["b"] == "slate"  # a slate service keeps origin slate
    refuting = _proposals(("P00000004", "c", "edge_anomalous", {"callee": "a"}))
    refutes = (_claim("c", "edge_anomalous", True, '{"callee":"a"}'),)
    assert not decide(_case(base, _i("c", 5.0), proposals=refuting, claims=refutes), CFG).admitted
    false_claim = (_claim("c", "zscore_above", False, args),)
    assert not decide(_case(base, _i("c", 5.0), proposals=proposals, claims=false_claim), CFG).admitted
    budget = replace(CFG, proposals_max=0)
    assert not decide(_case(base, _i("c", 5.0), proposals=proposals, claims=claims), budget).admitted


def test_no_leader_and_exact_ties(base: CausentraInputs) -> None:
    calm = decide(
        _case(base, [], q_hat=None), replace(CFG, factors=replace(CFG.factors, untestable_mandatory=0.0))
    )
    assert calm.leader is None and set(calm.nonconformity.values()) == {1.0} and calm.margin == 0.0
    tied = _case(base, [*_i("a", 9.0), *_i("b", 8.0)])  # b = 9 would explain its caller a (T1 fails)
    tied = replace(tied, slate=_slate({"a": 0.05, "b": 0.05, "c": 0.01}, 2))
    d = decide(tied, CFG)
    assert d.margin == 0.0 and [c.service for c in d.candidate_set] == ["a", "b"]  # ties: name order


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=25)
@given(data=st.data())
def test_proposal_and_claim_order_never_matter(base: CausentraInputs, data: st.DataObject) -> None:
    args = '{"k":4.0,"signal":"cpu"}'
    specs = [
        ("P00000001", "c", "zscore_above", {"k": 4.0, "signal": "cpu"}),
        ("P00000002", "a", "silent", {}),
    ]
    claims = [
        _claim("a", "zscore_above", True, args),
        _claim("c", "zscore_above", True, args),
        _claim("a", "silent", False),
    ]
    inp = _case(base, [*_i("a", 9.0), *_i("c", 5.0)], proposals=_proposals(*specs), claims=tuple(claims))
    shuffled = replace(
        inp,
        proposals=_proposals(*data.draw(st.permutations(specs))),
        claims=tuple(data.draw(st.permutations(claims))),
    )
    assert decide(shuffled, CFG) == decide(inp, CFG)
