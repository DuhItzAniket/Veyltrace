"""RCAEval-C generator (O-13; 04-causync §3.7): seeded, one row shape, scored by Causync like any change."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_causync.changes import evidence, timeline
from veyltrace_causync.settings import causync_config
from veyltrace_core import duck, io
from veyltrace_core.config import data_root, resolve_config
from veyltrace_decoys.rcaevalc import (
    KINDS,
    TRUE_LEAD_MAX_S,
    DecoySpec,
    SyntheticChange,
    decoy_changes_json,
    events_table,
    generate,
    overlay_path,
    write_overlay,
)

S = 10**9
T_INJECT = 1_700_000_000 * S
SERVICES = ["cart", "catalog", "checkout", "frontend", "payment"]
ROOT = "cart"
GRID = [DecoySpec(pi, rate) for pi in (0.0, 0.5, 1.0) for rate in (0.0, 2.0, 6.0)]  # 04 §5.2
CASES = [f"{i:012x}" for i in range(400)]

case_ids = st.integers(0, 16**12 - 1).map(lambda i: f"{i:012x}")
specs = st.builds(
    DecoySpec,
    pi=st.floats(0, 1),
    rate_per_h=st.floats(0, 20),
    window_s=st.tuples(st.integers(-3600, -1), st.integers(0, 600)),
)


def gen(case_id: str, spec: DecoySpec) -> list[SyntheticChange]:
    return generate(case_id, ROOT, T_INJECT, SERVICES, spec)


@given(case_ids, specs)
def test_same_seed_gives_the_same_changes_whatever_the_service_order(case_id: str, spec: DecoySpec) -> None:
    assert gen(case_id, spec) == gen(case_id, spec)
    assert generate(case_id, ROOT, T_INJECT, SERVICES[::-1], spec) == gen(case_id, spec)


@pytest.mark.parametrize("spec", GRID)
def test_two_runs_write_byte_identical_overlays(spec: DecoySpec, tmp_path: Path) -> None:
    written = []
    for run in ("a", "b"):
        path, sha = write_overlay("rcaevalc-pi05-l2-v1", CASES[7], gen(CASES[7], spec), tmp_path / run)
        written.append((path.read_bytes(), sha))
    assert written[0] == written[1]


@given(case_ids, specs)
def test_true_and_decoy_rows_differ_only_in_time_entity_and_kind(case_id: str, spec: DecoySpec) -> None:
    changes = gen(case_id, spec)
    table = events_table(changes)
    assert table.num_rows == len(changes)
    for column in ("source_system", "detail_json", "actor"):
        assert set(table.column(column).to_pylist()) <= {
            {"source_system": "synthetic", "detail_json": "{}"}.get(column)
        }
    assert set(table.column("kind").to_pylist()) <= set(KINDS)
    io.encode("telemetry.events", table)  # valid against the contract (03 §2.5)


@given(case_ids, specs)
def test_changes_lie_where_the_protocol_puts_them(case_id: str, spec: DecoySpec) -> None:
    changes = gen(case_id, spec)
    true = [c for c in changes if c.is_true]
    assert len(true) <= 1
    for c in true:
        assert c.entity == ROOT
        assert T_INJECT - TRUE_LEAD_MAX_S * S <= c.t_ns <= T_INJECT
    lo, hi = spec.window_s
    for c in changes:
        if not c.is_true:
            assert c.entity in SERVICES and c.entity != ROOT
            assert T_INJECT + lo * S <= c.t_ns <= T_INJECT + hi * S
    assert changes == sorted(changes)


@given(case_ids, st.floats(0, 1), st.floats(0, 1), st.floats(0, 20))
def test_decoys_do_not_depend_on_pi_and_true_changes_nest(
    case_id: str, p: float, q: float, rate: float
) -> None:
    low, high = (gen(case_id, DecoySpec(pi, rate)) for pi in sorted((p, q)))
    assert [c for c in low if not c.is_true] == [c for c in high if not c.is_true]
    assert {c for c in low if c.is_true} <= {c for c in high if c.is_true}


def test_grid_corners() -> None:
    for case_id in CASES[:50]:
        assert gen(case_id, DecoySpec(0.0, 0.0)) == []
        assert [c.is_true for c in gen(case_id, DecoySpec(1.0, 0.0))] == [True]
        assert not any(c.is_true for c in gen(case_id, DecoySpec(0.0, 6.0)))
        assert generate(case_id, ROOT, T_INJECT, [ROOT], DecoySpec(1.0, 6.0)) == gen(
            case_id, DecoySpec(1.0, 0.0)
        )


def test_rates_match_pi_and_lambda() -> None:
    """Over 400 fixed case ids (seeded, so exact repeats): share of true changes ≈ π, decoys per
    case ≈ λ × 35 min, kinds and services close to uniform."""
    spec = DecoySpec(0.5, 6.0)
    runs = [gen(case_id, spec) for case_id in CASES]
    share_true = sum(any(c.is_true for c in run) for run in runs) / len(runs)
    decoys = [c for run in runs for c in run if not c.is_true]
    mean = 6.0 * 2100 / 3600
    assert abs(share_true - 0.5) < 3 * math.sqrt(0.25 / len(runs))
    assert abs(len(decoys) / len(runs) - mean) < 3 * math.sqrt(mean / len(runs))
    for values, k in (
        ([c.kind for c in decoys], len(KINDS)),
        ([c.entity for c in decoys], len(SERVICES) - 1),
    ):
        for value in set(values):
            assert abs(values.count(value) / len(values) - 1 / k) < 0.05
        assert len(set(values)) == k


def test_decoy_changes_json_is_canonical_and_holds_the_truth() -> None:
    changes = gen(CASES[3], DecoySpec(1.0, 6.0))
    text = decoy_changes_json(changes[::-1])
    assert text == decoy_changes_json(changes)
    rows = json.loads(text)
    assert [set(r) for r in rows] == [{"t_ns", "entity", "kind", "is_true"}] * len(changes)
    assert [SyntheticChange(r["t_ns"], r["entity"], r["kind"], r["is_true"]) for r in rows] == changes
    assert sum(r["is_true"] for r in rows) == 1
    assert decoy_changes_json([]) == "[]"


def test_overlay_hides_the_truth_and_stays_under_the_data_root(tmp_path: Path) -> None:
    changes = gen(CASES[3], DecoySpec(1.0, 6.0))
    path, _ = write_overlay("rcaevalc-pi1-l6-v1", CASES[3], changes, tmp_path)
    assert path == tmp_path / "overlays" / "rcaevalc-pi1-l6-v1" / CASES[3] / "events.parquet"
    table = pq.read_table(path)
    assert table.column_names == ["t_ns", "entity", "kind", "source_system", "detail_json", "actor"]
    assert table.num_rows == len(changes)
    for column in ("entity", "kind", "source_system", "detail_json"):
        for value in table.column(column).to_pylist():
            assert "decoy" not in str(value) and "true" not in str(value)

    assert overlay_path("e-1", CASES[0]).is_relative_to(data_root() / "overlays")
    empty, _ = write_overlay("e-1", CASES[0], [], tmp_path)
    assert pq.read_table(empty).num_rows == 0
    for experiment_id, case_id in (("../x", CASES[0]), ("E1", CASES[0]), ("e-1", "synth-04")):
        with pytest.raises(ValueError):
            overlay_path(experiment_id, case_id, tmp_path)


def test_spec_from_protocol() -> None:
    assert DecoySpec.from_protocol({"pi": 0.5, "rate_per_h": 2, "window_s": [-1800, 300]}) == DecoySpec(
        0.5, 2.0
    )
    assert DecoySpec.from_protocol({"pi": 1, "rate_per_h": 0}) == DecoySpec(1.0, 0.0, (-1800, 300))
    ok: dict[str, object] = {"pi": 0.5, "rate_per_h": 2}
    bad: list[dict[str, object]] = [
        {"pi": 0.5},
        {**ok, "seed": 1},
        {**ok, "pi": 1.5},
        {**ok, "pi": "0.5"},
        {**ok, "pi": True},
        {**ok, "rate_per_h": -1},
        {**ok, "window_s": [300, -1800]},
        {**ok, "window_s": [-1800]},
        {**ok, "window_s": [-1800.5, 300]},
    ]
    for decoys in bad:
        with pytest.raises(ValueError):
            DecoySpec.from_protocol(decoys)


def test_causync_scores_synthetic_changes_like_real_ones(tmp_path: Path) -> None:
    """O-13 acceptance: the same times, entities and kinds get the same evidence whether the rows
    are synthetic or look like real k8s events, and a true change is close to the onset."""
    config = resolve_config({}, ai_mode="off").engine("causync")
    cfg = causync_config(config)
    changes = gen(CASES[3], DecoySpec(1.0, 6.0))
    synthetic = events_table(changes)
    real = pa.table(
        {**synthetic.to_pydict(), "source_system": ["k8s"] * len(changes), "actor": ["ci"] * len(changes)},
        schema=synthetic.schema,
    )
    onsets = dict.fromkeys(SERVICES, T_INJECT)
    scored = []
    with duck.connect(config, tmp_path) as con:
        for events in (synthetic, real):
            found = timeline(events, SERVICES, {}, cfg)
            assert [(c.t_ns, c.entity, c.kind, c.scope) for c in found] == [
                (c.t_ns, c.entity, c.kind, "service") for c in changes
            ]
            cols = evidence(con, found, onsets, T_INJECT, 15 * S, cfg)
            scored.append({k: v for k, v in cols.items() if k != "change_id"})
    assert scored[0] == scored[1]
    true_at = [c.is_true for c in changes].index(True)
    assert scored[0]["proximity"][true_at] > 0.5  # within 120 s of the onset, tau 300 s (04-causync §3.6)
