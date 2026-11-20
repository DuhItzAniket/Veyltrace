"""Tests of decision steps 1–3, 6 and the set (09 §3.2–§3.7, the §3.14 example) and the 09 §7
property tests: order invariance, AI cannot remove, monotone claims, clip, and the conformal rule.

The coverage check runs Causentra's own membership rule (`decision.in_set`) on simulated
exchangeable scores, with q̂ from the 09 §3.7 finite-sample rule. It checks the rule's
implementation, not the R-12 acceptance, which bench measures on held-out RE2 cases once R-13
has fitted q̂."""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from veyltrace_causatrix.views import Atom, evidence_view, graph_view
from veyltrace_causentra.config import config_from
from veyltrace_causentra.decision import claim_sum, decide, in_set, trial_factor, verified
from veyltrace_causentra.inputs import DECIMALS, CausentraInputs, Claim, load_inputs
from veyltrace_causentra.trials import TrialResult
from veyltrace_contracts import models
from veyltrace_core.config import load_section_file
from veyltrace_core.rng import rng
from veyltrace_core.testing import make_context, repo_root

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
    # T10 is mandatory for proposal origin only (09 §3.4, #226); slate candidates never write it.
    t10 = [_tr("T10", "fail")], [_tr("T10", "untestable")]
    assert [trial_factor(t, CFG, "proposal") for t in t10] == [0.25, 0.85]
    assert [trial_factor(t, CFG, "slate") for t in t10] == [0.9, 1.0]


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
        {"schema_version": "1.0.0", "case_id": CASE, "k": k, "rankers_active": ["prism_m"], "fusion": fusion}
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
        {"schema_version": "1.0.0", "case_id": CASE, "status": "complete", "mode": "external", "model": None}
        | {"budget_used": budget, "proposals": items, "asks": []}
    )


@pytest.fixture
def base(synth01_dir: Path) -> CausentraInputs:
    ctx = make_context("causentra", synth01_dir)
    return load_inputs(ctx, config_from(ctx.config, ctx.config.core))


def _case(base: CausentraInputs, atoms: list[Atom], k: int = 2, **changes: Any) -> CausentraInputs:
    """Three services a, b, c, the call a → b, and no events: T6 is untestable (factor 1.0, 09 §3.4)."""
    scores = {"a": 0.0480, "b": 0.0460, "c": 0.0300}
    sources = base.manifest.sources.model_copy(update={"events": False})
    graph = graph_view(
        list(scores),
        [(s, "service") for s in scores],
        [{"src": "a", "dst": "b", "weight": 1.0, "provenance": ["traces"]}],
        include_external=False,
    )
    return replace(
        base,
        manifest=base.manifest.model_copy(update={"sources": sources}),
        slate=_slate(scores, k),
        ev=evidence_view(atoms, graph.universe),
        graph=graph,
        graph_nodes=frozenset(scores),
        domain=replace(base.domain, nodes=frozenset(scores), signals=frozenset({"cpu"})),
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


def test_q_hat_just_below_a_9_decimal_s_is_read_at_9_decimals(
    base: CausentraInputs, synth01_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # s(b) = 0.041666667 at 9 decimals; an unrounded q_hat of 1/24 sits just below it (09 §5).
    atoms, raw = [*_i("a", 9.0), *_i("b", 4.0)], 1 / 24
    assert [c.service for c in decide(_case(base, atoms, q_hat=raw), CFG).candidate_set] == ["a"]
    example = json.loads((repo_root() / "contracts" / "examples" / "calibration.example.json").read_text())
    unrounded = models.Calibration.model_validate(example | {"q_hat": raw})  # files hold 9 decimals
    ctx = make_context("causentra", synth01_dir)
    monkeypatch.setattr(type(ctx.config), "calibration", property(lambda _: unrounded))
    read = load_inputs(ctx, config_from(ctx.config, ctx.config.core)).q_hat
    assert read == 0.041666667
    assert [c.service for c in decide(_case(base, atoms, q_hat=read), CFG).candidate_set] == ["a", "b"]


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


def test_t9_skips_a_proposal_origin_candidate_outside_the_top_k(base: CausentraInputs) -> None:
    """T9 presupposes the unablated top K: c, admitted from outside the slate, gets no T9 entry and
    no T9 factor, while the slate candidates are tested (#364 lead review)."""
    args = '{"k":4.0,"signal":"cpu"}'
    proposals = _proposals(("P00000001", "c", "zscore_above", {"k": 4.0, "signal": "cpu"}))
    claims = tuple(_claim(s, "zscore_above", True, args) for s in ("a", "b", "c"))
    inp = _case(base, [*_i("a", 9.0), *_i("b", 4.0), *_i("c", 5.0)], proposals=proposals, claims=claims)
    assert sum(getattr(inp.manifest.sources, s) for s in ("metrics", "logs", "traces", "events")) >= 2
    trials = {c.service: [t.id for t in c.trials] for c in decide(inp, CFG).ranked}
    assert "T9" not in trials["c"] and "T10" in trials["c"]
    assert all("T9" in trials[s] for s in ("a", "b"))


def test_claims_match_on_validated_args(base: CausentraInputs) -> None:
    # The claim pass stores validate()'s canonical args (06 §3.5 step 4): an int k finds the atom
    # of 4.0 (#216). A claim validate() rejects (a `subject` key, an unknown signal) never holds.
    claims = (_claim("c", "zscore_above", True, '{"k":4.0,"signal":"cpu"}'),)
    as_int = _proposals(("P00000001", "c", "zscore_above", {"k": 4, "signal": "cpu"}))
    inp = _case(base, _i("c", 5.0), proposals=as_int, claims=claims)
    assert decide(inp, CFG).admitted == frozenset({"P00000001"})
    for args in ({"k": 4, "signal": "cpu", "subject": "c"}, {"k": 4, "signal": "mem"}):
        bad = _proposals(("P00000001", "c", "zscore_above", args))
        assert not decide(replace(inp, proposals=bad), CFG).admitted


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


PREDICATES = ("zscore_above", "silent", "onset_before", "edge_anomalous", "error_rate_above")
SERVICES = ("a", "b", "c")
_SLOW = settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=25)


def _claims(draw: Any) -> list[Any]:
    rows = draw(
        st.lists(
            st.tuples(
                st.sampled_from(SERVICES), st.sampled_from(PREDICATES), st.integers(0, 3), st.booleans()
            ),
            max_size=12,
            unique_by=lambda r: r[:3],
        )
    )
    return [_claim(s, p, holds, f'{{"k":{k}}}') for s, p, k, holds in rows]


def _v(inp: CausentraInputs) -> dict[str, float]:
    return {c.service: c.v for c in decide(inp, CFG).ranked}


@_SLOW
@given(data=st.data())
def test_ai_cannot_remove_a_slate_candidate(base: CausentraInputs, data: st.DataObject) -> None:
    """Proposals and claims only add to the decision pool (09 §3.2; AGENTS Never 5)."""
    specs = data.draw(
        st.lists(
            st.tuples(
                st.sampled_from(("P00000001", "P00000002", "P00000003")),
                st.sampled_from((*SERVICES, "unknown")),
                st.sampled_from(PREDICATES),
            ),
            max_size=3,
            unique_by=lambda s: s[0],
        )
    )
    proposals = _proposals(*((pid, svc, pred, {}) for pid, svc, pred in specs))
    inp = _case(base, [*_i("a", 9.0), *_i("b", 4.0)], proposals=proposals, claims=tuple(_claims(data.draw)))
    ranked = {c.service for c in decide(inp, CFG).ranked}
    assert {c.service for c in inp.slate.candidates} <= ranked


@_SLOW
@given(data=st.data(), k=st.integers(4, 9))
def test_a_supporting_claim_that_holds_only_for_c_is_monotone(
    base: CausentraInputs, data: st.DataObject, k: int
) -> None:
    """Adding a holding supporting claim for c never lowers V(c) and leaves every other V alone."""
    claims = _claims(data.draw)
    inp = _case(base, [*_i("a", 9.0), *_i("b", 4.0), *_i("c", 5.0)], k=3, claims=tuple(claims))
    target = data.draw(st.sampled_from(SERVICES))
    extra = _claim(target, "zscore_above", True, f'{{"k":{k}}}')  # k ≥ 4: a pair not drawn above
    before, after = _v(inp), _v(replace(inp, claims=(*inp.claims, extra)))
    assert after[target] >= before[target]
    assert {s: v for s, v in after.items() if s != target} == {s: v for s, v in before.items() if s != target}


@_SLOW
@given(data=st.data())
def test_the_claim_term_never_moves_v_beyond_the_clip(base: CausentraInputs, data: st.DataObject) -> None:
    """V(c) / V_without_claims(c) stays within [1 + clip_low, 1 + clip_high] (09 §3.5)."""
    atoms = [*_i("a", 9.0), *_i("b", 4.0), *_i("c", 5.0)]
    plain = _v(_case(base, atoms, k=3))
    claimed = _v(_case(base, atoms, k=3, claims=tuple(_claims(data.draw))))
    for s, v in plain.items():
        low = round(v * (1.0 + CFG.clip_low), DECIMALS)
        high = round(v * (1.0 + CFG.clip_high), DECIMALS)
        assert low <= claimed[s] <= high


def reference_q_hat(scores: np.ndarray, alpha: float) -> float:
    """The 09 §3.7 fitting rule: the ⌈(n + 1)(1 − alpha)⌉-th smallest score, +∞ if that index > n.

    Bench owns fitting (R-13); this copy only drives the coverage check of the set rule."""
    n = scores.size
    index = math.ceil((n + 1) * (1.0 - alpha))
    return math.inf if index > n else float(np.sort(scores)[index - 1])


def test_q_hat_index_arithmetic() -> None:
    """09 §7: n = 8 → index 9 > n → q̂ = +∞ (serialised null); n = 89 → the 81st smallest."""
    assert reference_q_hat(np.arange(8, dtype=float), 0.10) == math.inf
    assert reference_q_hat(np.arange(1, 90, dtype=float), 0.10) == 81.0
    assert not in_set(1.0, 0.0) and in_set(0.0, 0.0) and in_set(1.0, None)  # None is +∞ (03 §10)


@pytest.mark.parametrize(("alpha", "n"), [(0.10, 89), (0.10, 20), (0.05, 40), (0.20, 15)])
def test_conformal_set_covers_exchangeable_roots(alpha: float, n: int) -> None:
    """Marginal coverage of {s ≤ q̂} over 2,000 simulated cases is ≥ 1 − alpha − 0.02 (09 §7).

    Each simulated case draws n calibration scores and one test score from the same law: a root
    outside the decision pool (score +∞, never covered) with probability 0.02, else a 9-decimal s
    in [0, 1] with a point mass at 0 (the root leads)."""
    gen = rng(CASE, f"conformal-coverage alpha={alpha} n={n}")
    trials = 2000
    raw = gen.beta(0.7, 2.0, size=(trials, n + 1)).round(DECIMALS)
    raw[gen.random(size=raw.shape) < 0.30] = 0.0
    raw[gen.random(size=raw.shape) < 0.02] = math.inf
    covered = 0
    for row in raw:
        q = reference_q_hat(row[:n], alpha)
        q_hat = None if math.isinf(q) else round(q, DECIMALS)  # +∞ reads as None, as load_inputs does
        covered += bool(math.isfinite(row[n]) and in_set(float(row[n]), q_hat))
    assert covered / trials >= 1.0 - alpha - 0.02
