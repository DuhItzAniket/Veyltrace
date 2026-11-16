"""Causync's engine step (04 §7): goldens, the O-06 acceptance check, decoy blindness."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from veyltrace_causync.api import run
from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.errors import ArtifactMissing
from veyltrace_core.testing import SYNTH_CASES, VARIANTS, assert_golden, golden, make_context
from veyltrace_core.testing.rundir import fixture_run_dir

CASES = (*SYNTH_CASES, *sorted(VARIANTS))
OUTPUTS = ("alignment", "changes")
SCORES = ("latest_before_onset", "delta_to_onset_ms", "proximity", "peer_contrast")


def _run(case: str, tmp_path: Path) -> Path:
    try:
        run_dir = fixture_run_dir(case, tmp_path, through="anomara")
    except ArtifactMissing as exc:
        pytest.skip(f"upstream fixtures for {case} are not committed yet: {exc}")
    variant = VARIANTS.get(case)
    ctx = make_context(
        "causync",
        run_dir,
        ai_mode=variant.ai_mode if variant else "off",
        overrides=variant.overrides if variant else {},
    )
    assert run(ctx).status == "ok"
    return run_dir


def _changes(case: str) -> list[dict[str, Any]]:
    table = golden("changes", case)
    assert isinstance(table, pa.Table)
    return table.to_pylist()


@pytest.mark.parametrize("case", CASES)
def test_matches_golden(tmp_path: Path, case: str) -> None:
    run_dir = _run(case, tmp_path)
    for contract in OUTPUTS:
        assert_golden(io.path_of(contract, run_dir), contract, case)


def test_synth_04_change_is_found_close_to_the_onset() -> None:
    """O-06 acceptance: synth-04 holds one change, so no answer key is needed (04 §7)."""
    (change,) = _changes("synth-04")
    assert change["proximity"] > 0.5
    assert change["latest_before_onset"] is True
    assert change["scope"] == "service"
    assert change["delta_to_onset_ms"] < 0


def test_cases_without_change_events_abstain() -> None:
    for case in ("synth-01", "synth-02", "synth-05", "synth-01@noevents"):
        assert _changes(case) == []  # k8s_event rows are symptoms, not changes


def test_synth_alignment_reports_no_skew() -> None:
    for case in SYNTH_CASES:
        alignment = golden("alignment", case)
        assert isinstance(alignment, models.Alignment)
        assert alignment.reference == "traces"
        assert all(o.offset_ns == 0 for o in alignment.offsets)  # the generator plants none
        assert alignment.tolerance_ns > 0
        logged = sorted(o.service for o in alignment.offsets if o.source == "logs" and o.service)
        assert logged  # synth log lines carry span ids: one log_span_join row per logging service
        assert all(o.method == "log_span_join" for o in alignment.offsets if o.source == "logs")
        keys = [(o.source, o.service is not None, o.service or "") for o in alignment.offsets]
        assert keys == sorted(keys)  # (source, service) with the source-level row first


def test_component_change_gets_a_peer_contrast() -> None:
    by_scope = {c["scope"]: c for c in _changes("synth-03")}
    assert by_scope["component"]["peer_contrast"] is not None  # a replica against its peer
    assert by_scope["service"]["peer_contrast"] is None  # its service has no replicas in synth-03


def test_scores_ignore_source_system_and_actor(tmp_path: Path) -> None:
    """A decoy and a true change must look the same here (04 §3.6; package rule)."""
    plain = _run("synth-03", tmp_path / "a")
    relabelled = fixture_run_dir("synth-03", tmp_path / "b", through="anomara")
    events = io.read("telemetry.events", relabelled)
    assert isinstance(events, pa.Table)
    columns = {name: events.column(name).to_pylist() for name in events.schema.names}
    columns["source_system"] = ["synthetic"] * events.num_rows
    columns["actor"] = ["someone"] * events.num_rows
    io.write("telemetry.events", io.conform_table("telemetry.events", pa.table(columns)), relabelled)
    run(make_context("causync", relabelled))
    before, after = (io.read("changes", d) for d in (plain, relabelled))
    assert isinstance(before, pa.Table)
    assert isinstance(after, pa.Table)
    assert before.num_rows == after.num_rows > 0
    for column in ("t_ns", "entity", "kind", "scope", *SCORES):
        assert after.column(column).to_pylist() == before.column(column).to_pylist()
    assert after.column("change_id").to_pylist() != before.column("change_id").to_pylist()
