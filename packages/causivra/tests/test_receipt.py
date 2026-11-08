"""Step 10b, the receipt (10 §3.8 steps 1–5; 03 §11.2; 10 §7 "Receipt" row)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from veyltrace_causivra import api
from veyltrace_causivra.receipt import PREDICATE_TYPE, STATEMENT_TYPE
from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.errors import ArtifactMissing, ChainBroken, ContractValidationError
from veyltrace_core.hashing import sha256_file
from veyltrace_core.testing import SYNTH_CASES, VARIANTS, assert_golden, fixture_run_dir, make_context

CASES = (*SYNTH_CASES, *sorted(VARIANTS))
#: The receipt runs after core's manifest step (02 §6.10).
THROUGH = "manifest"


def _run_dir(case: str, tmp_path: Path) -> Path:
    try:
        return fixture_run_dir(case, tmp_path, through=THROUGH)
    except ArtifactMissing as exc:
        pytest.skip(f"upstream fixtures for {case} are not committed yet: {exc}")


def _receipt(case: str, run_dir: Path) -> models.Receipt:
    variant = VARIANTS.get(case)
    ctx = make_context(
        "causivra",
        run_dir,
        phase="receipt",
        ai_mode=variant.ai_mode if variant is not None else "off",
        overrides=variant.overrides if variant is not None else {},
    )
    result = api.run(ctx)
    assert result.status == "ok"
    return io.read_model("receipt", run_dir, models.Receipt, validate=True)


@pytest.mark.parametrize("case", CASES)
def test_receipt_matches_golden(case: str, tmp_path: Path) -> None:
    run_dir = _run_dir(case, tmp_path)
    _receipt(case, run_dir)
    assert_golden(io.read("receipt", run_dir), "receipt", case)


def test_receipt_fields(tmp_path: Path) -> None:
    run_dir = _run_dir("synth-01", tmp_path)
    receipt = _receipt("synth-01", run_dir)
    raw = json.loads(io.path_of("receipt", run_dir).read_text(encoding="utf-8"))
    assert raw["_type"] == STATEMENT_TYPE and raw["predicateType"] == PREDICATE_TYPE
    assert [s["name"] for s in raw["subject"]] == ["verdict.json"]
    assert receipt.subject[0].digest.sha256 == sha256_file(io.path_of("verdict", run_dir))
    manifest = io.read_model("run_manifest", run_dir, models.RunManifest)
    assert receipt.predicate.run_manifest == manifest
    verdict = io.read_model("verdict", run_dir, models.Verdict)
    card = io.read_model("card", run_dir, models.Card)
    assert receipt.predicate.verdict_hash == verdict.verdict_hash
    assert receipt.predicate.card_hash == card.card_hash
    assert receipt.predicate.agent_trace_head is None  # AI off: no trace


def test_two_receipts_are_byte_identical(tmp_path: Path) -> None:
    blobs = []
    for sub in ("a", "b"):
        run_dir = _run_dir("synth-01", tmp_path / sub)
        _receipt("synth-01", run_dir)
        blobs.append(io.path_of("receipt", run_dir).read_bytes())
    assert blobs[0] == blobs[1]


def test_tampered_verdict_is_refused(tmp_path: Path) -> None:
    run_dir = _run_dir("synth-01", tmp_path)
    path = io.path_of("verdict", run_dir)
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ContractValidationError, match="changed after the manifest"):
        _receipt("synth-01", run_dir)


def test_manifest_without_card_outputs_is_refused(tmp_path: Path) -> None:
    run_dir = _run_dir("synth-01", tmp_path)
    raw = json.loads(io.path_of("run_manifest", run_dir).read_text(encoding="utf-8"))
    raw["outputs"] = [o for o in raw["outputs"] if o["name"] != "card.md"]
    io.write("run_manifest", raw, run_dir)
    with pytest.raises(ContractValidationError, match=r"card\.md"):
        _receipt("synth-01", run_dir)


def test_broken_agent_trace_is_refused(tmp_path: Path) -> None:
    run_dir = _run_dir("synth-01", tmp_path)
    line = {
        "seq": 0,
        "type": "state",
        "prev_hash": "0" * 64,
        "line_hash": "f" * 64,
        "request_sha256": None,
        "response_sha256": None,
        "tool": None,
        "args": None,
        "result_sha256": None,
        "summary": None,
        "state": "start",
        "detail": None,
    }
    io.path_of("agent_trace", run_dir).write_bytes(json.dumps(line).encode("utf-8") + b"\n")
    with pytest.raises(ChainBroken):
        _receipt("synth-01", run_dir)
