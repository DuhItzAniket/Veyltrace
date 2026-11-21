"""Tests of the T8 intervention atoms (06 §3.4, §3.6 step 6): decision pool, limit, atom shape."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from veyltrace_causalith.ci import CIConfig, CIResult, intervention_test
from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.hashing import sha256_json
from veyltrace_core.testing import fixture_run_dir, make_context, repo_root
from veyltrace_faultloom.api import run
from veyltrace_faultloom.atoms import Atom
from veyltrace_faultloom.intervention import (
    EDGE_COLUMNS,
    SERIES_COLUMNS,
    candidate_rows,
    ci_config,
    decision_pool,
    intervention_atom,
    series_rows,
    target_series,
)
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


def _both(
    series: pa.Table, edges: pa.Table, alert: models.Alert, cfg: CIConfig, c: str, t: str | None
) -> tuple[str, str]:
    """repr of intervention_test on the whole table and on candidate_rows' slice (repr: NaN == NaN)."""
    rows_by_id, ids_by_service = series_rows(
        series.column("series_id").to_pylist(), series.column("service").to_pylist()
    )
    rows = candidate_rows(c, edges.select(["src", "dst"]).to_pylist(), rows_by_id, ids_by_service)
    full = intervention_test(series, edges, alert, c, cfg, t)
    return repr(full), repr(
        intervention_test(series.take(rows) if rows else series.slice(0, 0), edges, alert, c, cfg, t)
    )


@pytest.mark.parametrize("case", ["synth-01", "synth-02", "synth-03", "synth-04", "synth-05"])
def test_the_slice_gives_the_whole_table_result_for_every_node(case: str, tmp_path: Path) -> None:
    run_dir = fixture_run_dir(case, tmp_path, through="faultloom.claim_pass")
    ctx = make_context("faultloom", run_dir, phase="claim_pass")
    series = ctx.read_table("signal_cube.series", columns=list(SERIES_COLUMNS))
    edges = ctx.read_table("graph.edges", columns=list(EDGE_COLUMNS))
    alert = ctx.read_model("alert", models.Alert)
    cfg = ci_config(ctx.with_config("causalith").config, ctx.with_config("anomara").config)
    engine = io.read_table("evidence", run_dir).to_pylist()
    nodes = sorted({str(s) for s in series.column("service").to_pylist()} | {"no-such-service"})
    tested = 0
    for c in nodes:
        for target in (None, target_series(c, engine), "x|x|cpu|metrics"):  # default, atom's, foreign
            full, part = _both(series, edges, alert, cfg, c, target)
            assert part == full, (c, target)
            tested += "reason=None" in full
    assert tested > 0  # some results are testable, not only untestable ones


def test_a_series_is_kept_whole_with_all_its_rows() -> None:
    def rows(sid: str, service: str, signal: str, n: int) -> list[dict[str, object]]:
        base: dict[str, object] = {"series_id": sid, "service": service, "signal": signal, "family": "cpu"}
        return [
            base | {"source": "metrics", "unit": None, "t_ns": t * 1_000_000_000, "value": float(t % 7)}
            for t in range(n)
        ]

    table = pa.Table.from_pylist(
        rows("a|cpu", "a", "cpu", 4)
        + rows("mixed", "z", "cpu", 2)
        + rows("mixed", "a", "cpu", 2)
        + rows("b|cpu", "b", "cpu", 3)
        + rows("z|cpu", "z", "cpu", 5)
    )
    by_id, by_service = series_rows(
        table.column("series_id").to_pylist(), table.column("service").to_pylist()
    )
    links = [{"src": "a", "dst": "b"}, {"src": "b", "dst": "z"}]
    assert candidate_rows("a", links, by_id, by_service) == list(range(11))  # all of "mixed", not z|cpu
    assert candidate_rows("b", links, by_id, by_service) == list(
        range(4, 16)
    )  # b, its callee z, all of "mixed"
    assert candidate_rows("q", links, by_id, by_service) == []  # no series: no_target either way
