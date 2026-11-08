"""Unit tests of the R-00 stub: both passes, required/optional inputs, claim-pass carry-forward."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from veyltrace_contracts import models
from veyltrace_core import io, textio
from veyltrace_core.cli import STUB_MARK
from veyltrace_core.hashing import sha256_file
from veyltrace_core.testing import content_lines, make_context
from veyltrace_core.testing.fixtures import repo_root
from veyltrace_faultloom.api import run
from veyltrace_faultloom.inputs import CLAIM_REQUIRED, MAIN_REQUIRED
from veyltrace_faultloom.stub import STUB_NOTE, claim_pool


def _example(name: str) -> Any:
    path = repo_root() / "contracts" / "examples" / f"{name}.example.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _remove(name: str, run_dir: Path) -> None:
    path = io.path_of(name, run_dir)
    if path.is_dir():
        raise AssertionError(f"{name} is a directory")
    path.unlink()


# --- engine pass ------------------------------------------------------------------------------
def test_main_writes_an_empty_schema_valid_evidence_table(main_dir: Path) -> None:
    ctx = make_context("faultloom", main_dir)
    result = run(ctx)
    assert result.status == "ok"
    assert result.outputs == (("evidence", sha256_file(io.path_of("evidence", main_dir))),)
    table = io.read_table("evidence", main_dir, validate=True)
    assert table.num_rows == 0
    assert table.schema.equals(io.arrow_schema("evidence"), check_metadata=False)
    assert result.metrics["atoms"] == 0 and result.metrics["universe"] == 6
    assert result.notes == (STUB_NOTE,)


def test_stub_note_carries_the_cli_stub_mark() -> None:
    # diagnose warns about "placeholder outputs" for every note starting with cli.STUB_MARK.
    assert STUB_NOTE.startswith(STUB_MARK)


@pytest.mark.parametrize("name", MAIN_REQUIRED)
def test_main_fails_without_a_required_input(main_dir: Path, name: str) -> None:
    _remove(name, main_dir)
    result = run(make_context("faultloom", main_dir, case_id="59e0d31bcc42"))
    assert result.status == "failed" and result.outputs == ()
    assert any(name in note for note in result.notes)
    assert not io.exists("evidence", main_dir)


def test_main_is_degradation_free_without_optional_inputs(main_dir: Path) -> None:
    for name in ("alignment", "changes", "graph.paths", "signal_cube.critical_path"):
        _remove(name, main_dir)
    result = run(make_context("faultloom", main_dir))
    assert result.status == "ok"
    assert result.metrics["inputs_absent"] == 4
    assert any("alignment absent" in note for note in result.notes)
    assert any("signal_cube.critical_path" in note for note in result.notes)


def test_main_output_does_not_depend_on_the_run_id(main_dir: Path) -> None:
    first = run(make_context("faultloom", main_dir, run_id="0" * 16)).outputs
    second = run(make_context("faultloom", main_dir, run_id="f" * 16)).outputs
    assert first == second


# --- claim pass -------------------------------------------------------------------------------
def test_claim_pass_rewrites_the_main_evidence_byte_identical(claim_dir: Path) -> None:
    before = sha256_file(io.path_of("evidence", claim_dir))
    result = run(make_context("faultloom", claim_dir, phase="claim_pass"))
    assert result.status == "ok"
    assert result.outputs == (("evidence", before),)
    assert sha256_file(io.path_of("evidence", claim_dir)) == before
    assert result.metrics["atoms.claim_check"] == 0 and result.metrics["claims.seen"] == 0


def test_claim_pass_carries_engine_atoms_forward_unchanged(claim_dir: Path) -> None:
    # Main-pass evidence with real rows (the contract example): the claim pass adds nothing and
    # changes nothing (06 §2.2: engine atoms are read back, never recomputed).
    rows = [r for r in _example("evidence") if r["origin"] == "engine"]
    assert rows, "the evidence example should hold engine atoms"
    before = io.write("evidence", rows, claim_dir)
    expected = content_lines("evidence", io.path_of("evidence", claim_dir))
    result = run(make_context("faultloom", claim_dir, phase="claim_pass"))
    assert result.outputs == (("evidence", before),)
    assert content_lines("evidence", io.path_of("evidence", claim_dir)) == expected
    assert result.metrics["atoms"] == len(rows)


@pytest.mark.parametrize("name", sorted(set(CLAIM_REQUIRED) - set(MAIN_REQUIRED)))
def test_claim_pass_fails_without_evidence_or_slate(claim_dir: Path, name: str) -> None:
    _remove(name, claim_dir)
    result = run(make_context("faultloom", claim_dir, phase="claim_pass"))
    assert result.status == "failed"
    assert any(name in note for note in result.notes)


def _write_proposals(run_dir: Path, **changes: Any) -> models.Proposals:
    data = {**_example("proposals"), **changes}
    io.write("proposals", data, run_dir)
    return io.read_model("proposals", run_dir, models.Proposals)


def test_claim_pass_with_claims_is_degraded_and_adds_no_atom(claim_dir: Path) -> None:
    proposals = _write_proposals(claim_dir)
    claims = sum(len(p.claims) for p in proposals.proposals)
    assert claims > 0
    before = sha256_file(io.path_of("evidence", claim_dir))
    result = run(make_context("faultloom", claim_dir, phase="claim_pass", ai_mode="record"))
    assert result.status == "degraded"
    assert result.metrics["claims.seen"] == claims and result.metrics["claims.evaluated"] == 0
    assert any("R-08" in note for note in result.notes)
    assert result.outputs == (("evidence", before),)


def test_claim_pass_with_skipped_proposals_is_ok(claim_dir: Path) -> None:
    _write_proposals(claim_dir, status="skipped", model=None, proposals=[], asks=[])
    result = run(make_context("faultloom", claim_dir, phase="claim_pass", ai_mode="record"))
    assert result.status == "ok" and result.metrics["claims.seen"] == 0


def test_schema_invalid_proposals_skip_the_claims_and_degrade(claim_dir: Path) -> None:
    textio.write_bytes(io.path_of("proposals", claim_dir), b'{"schema_version": "0.1.0"}\n')
    before = sha256_file(io.path_of("evidence", claim_dir))
    result = run(make_context("faultloom", claim_dir, phase="claim_pass", ai_mode="record"))
    assert result.status == "degraded"
    assert any("schema-invalid" in note for note in result.notes)
    assert result.outputs == (("evidence", before),)


def test_claim_pool_is_slate_plus_proposed_graph_nodes() -> None:
    slate = models.Slate.model_validate(_example("slate"))
    proposals = models.Proposals.model_validate(_example("proposals"))
    slate_services = {c.service for c in slate.candidates}
    proposed = {p.hypothesis.service for p in proposals.proposals}
    nodes = frozenset({"checkout"})
    assert claim_pool(slate, proposals, nodes) == tuple(sorted(slate_services | (proposed & nodes)))
    assert claim_pool(slate, None, nodes) == tuple(sorted(slate_services))
    # A proposed service that is not a graph node stays out of the pool (06 §3.6 step 2).
    outsider = proposals.model_copy(
        update={
            "proposals": [
                p.model_copy(update={"hypothesis": p.hypothesis.model_copy(update={"service": "ghost"})})
                for p in proposals.proposals
            ]
        }
    )
    assert "ghost" not in claim_pool(slate, outsider, frozenset({"ghost-not"}))


def test_claim_pass_reports_the_pool_size(claim_dir: Path) -> None:
    io.write("slate", {**_example("slate"), "case_id": "59e0d31bcc42"}, claim_dir)
    result = run(make_context("faultloom", claim_dir, phase="claim_pass"))
    assert result.metrics["pool"] == len(_example("slate")["candidates"])


# --- entry point ------------------------------------------------------------------------------
def test_run_rejects_other_phases_and_engines(main_dir: Path) -> None:
    ctx = make_context("faultloom", main_dir)
    with pytest.raises(ValueError, match="phase"):
        run(dataclasses.replace(ctx, phase="card"))
    with pytest.raises(ValueError, match="engine"):
        run(dataclasses.replace(ctx, engine="causatrix"))
