"""Tests of the T8 intervention atoms (06 §3.4, §3.6 step 6): decision pool, limit, atom shape."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from veyltrace_causalith.ci import CIResult
from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.hashing import sha256_json
from veyltrace_core.testing import fixture_run_dir, make_context, repo_root
from veyltrace_faultloom.api import run
from veyltrace_faultloom.atoms import Atom
from veyltrace_faultloom.intervention import decision_pool, intervention_atom, target_series
from veyltrace_faultloom.validation import CaseDomain

ARGS = '{"k":4.0,"signal":"cpu"}'


def _example(name: str) -> Any:
    return json.loads((repo_root() / "contracts" / "examples" / f"{name}.example.json").read_text("utf-8"))


def _slate(services: list[str], k: int) -> models.Slate:
    data = _example("slate")
    template = data["candidates"][0]
    data["candidates"] = [template | {"rank": i, "service": s} for i, s in enumerate(services[:k], 1)]
    data["all_scores"] = [{"service": s, "fused_score": 1.0 / (i + 2)} for i, s in enumerate(services)]
    return models.Slate.model_validate(data | {"k": k})


def _proposals(*specs: tuple[str, str, str], args: str = ARGS) -> models.Proposals:
    """(proposal_id, service, predicate) per proposal, one claim with `args` each."""
    data = _example("proposals")
    template = data["proposals"][0]
    data["proposals"] = [
        template
        | {
            "proposal_id": pid,
            "hypothesis": template["hypothesis"] | {"service": svc},
            "claims": [{"claim_id": f"{pid}-1", "predicate": pred, "args": json.loads(args), "cites": []}],
        }
        for pid, svc, pred in specs
    ]
    return models.Proposals.model_validate(data)


def _claim_row(candidate: str, holds: bool | None) -> Atom:
    return {"candidate": candidate, "predicate": "zscore_above", "args_json": ARGS, "holds": holds}


#: The case domain: four graph nodes, one signal, and the zscore_above / edge_anomalous ranges.
DOMAIN = CaseDomain(
    frozenset({"a", "b", "c", "d"}),
    frozenset({"cpu"}),
    {"zscore_above": {"k": (1.0, 100.0)}, "edge_anomalous": {}},
)


def test_decision_pool_is_the_slate_plus_admitted_proposals_in_score_order() -> None:
    slate = _slate(["a", "b", "c", "d"], k=2)
    assert decision_pool(slate, None, [], DOMAIN, DOMAIN.nodes) == ("a", "b")
    proposals = _proposals(("P00000001", "d", "zscore_above"), ("P00000002", "c", "zscore_above"))
    rows = [_claim_row("d", True), _claim_row("c", False)]  # c's supporting claim is false
    assert decision_pool(slate, proposals, rows, DOMAIN, DOMAIN.nodes) == ("a", "b", "d")
    ghost = _proposals(("P00000003", "zz", "zscore_above"))  # not a graph node (06 §3.6 step 2)
    assert decision_pool(slate, ghost, [_claim_row("zz", True)], DOMAIN, DOMAIN.nodes) == ("a", "b")
    unscored = _slate(["b", "a"], k=2)  # every service has a score; any other sorts last, A→Z
    assert decision_pool(unscored, proposals, rows, DOMAIN, DOMAIN.nodes) == ("b", "a", "d")


def test_a_refuting_claim_never_admits() -> None:
    slate = _slate(["a", "b"], k=1)
    callee = '{"callee":"a"}'  # valid args: only the refuting polarity keeps c out
    refuting = _proposals(("P00000001", "c", "edge_anomalous"), args=callee)
    rows: list[Atom] = [{"candidate": "c", "predicate": "edge_anomalous", "args_json": callee, "holds": True}]
    assert decision_pool(slate, refuting, rows, DOMAIN, DOMAIN.nodes) == ("a",)


def _z(n: int, candidate: str, value: float, refs: list[str], detector: str = "robust_z") -> Atom:
    args = {"detector": detector, "family": "cpu", "source": "metrics", "window": "incident"}
    return {"atom_id": f"E{n:010x}", "candidate": candidate, "kind": "internal_anomaly"} | {
        "args_json": json.dumps(args, sort_keys=True, separators=(",", ":")),
        "value": value,
        "refs": refs,
    }


def test_target_is_the_top_robust_z_series() -> None:
    engine = [
        _z(1, "c", 4.0, ["c|c|mem|metrics"]),
        _z(2, "c", 9.0, ["c|c|cpu|metrics", "c|c|cpu2|metrics"]),
        _z(3, "c", 99.0, ["c|c|lat|metrics"], detector="nsigma"),  # only robust_z counts
        _z(4, "d", 50.0, ["d|d|cpu|metrics"]),
    ]
    assert target_series("c", engine) == "c|c|cpu2|metrics"  # top atom; its first ref, sorted
    assert target_series("x", engine) is None  # None: Causalith picks its default target


def _result(reason: str | None, stat: float = 4.2) -> CIResult:
    parents = ("d|d|cpu|metrics", "c|c|rps|metrics")
    return CIResult("c", "c|c|cpu|metrics", parents, 30, 10, 6.0, stat, 0.3, 0.01, False, reason)


def test_atom_shape_and_untestable_results() -> None:
    atom = intervention_atom(_result(None))
    assert atom is not None
    assert (atom["kind"], atom["candidate"], atom["origin"], atom["unit"], atom["window"]) == (
        "intervention",
        "c",
        "engine",
        "z",
        "incident",
    )
    args = json.loads(str(atom["args_json"]))
    parents_hash = sha256_json(["d|d|cpu|metrics", "c|c|rps|metrics"])[:12]
    assert args == {"parents_hash": parents_hash, "series_id": "c|c|cpu|metrics", "window": "incident"}
    assert atom["value"] == 4.2
    assert atom["refs"] == sorted(["c|c|cpu|metrics", "d|d|cpu|metrics", "c|c|rps|metrics"])
    assert intervention_atom(_result("short_baseline")) is None
    assert intervention_atom(_result(None, float("nan"))) is None


def test_claim_pass_tests_at_most_max_candidates(tmp_path: Path) -> None:
    run_dir = fixture_run_dir("synth-01", tmp_path, through="faultloom.claim_pass")
    one = make_context(
        "faultloom", run_dir, phase="claim_pass", overrides={"faultloom.intervention.max_candidates": 1}
    )
    assert run(one).metrics["atoms.intervention"] == 1  # the top of all_scores, checkout, is testable
    rows = [r for r in io.read_table("evidence", run_dir).to_pylist() if r["kind"] == "intervention"]
    assert [r["candidate"] for r in rows] == ["checkout"] and rows[0]["value"] > 3.0  # the CPU hog
    none = make_context(
        "faultloom", run_dir, phase="claim_pass", overrides={"faultloom.intervention.max_candidates": 0}
    )
    assert run(none).metrics["atoms.intervention"] == 0
