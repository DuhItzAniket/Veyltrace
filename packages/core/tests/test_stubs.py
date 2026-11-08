"""Bootstrap stubs: every engine step writes schema-valid outputs, the whole pipeline runs end to
end on them, and two runs are byte-identical (M0 lead decision 2026-11-06, bootstrap)."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from pathlib import Path

import pytest

from veyltrace_contracts import models
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import io, stubs
from veyltrace_core.errors import ConfigError
from veyltrace_core.hashing import self_hash, sha256_file, sha256_json
from veyltrace_core.ids import AIMode
from veyltrace_core.ids import case_id as make_case_id
from veyltrace_core.pipeline import RunSummary, run_case
from veyltrace_core.steps import STEPS
from veyltrace_core.testing import make_context

CASE = make_case_id("synth-01")
FIXTURE_COMMIT = "fixture"
STUBS_SOURCE = Path(stubs.__file__)


def _run(root: Path, ai_mode: AIMode = "off", overrides: Mapping[str, object] | None = None) -> RunSummary:
    return run_case(
        "synth", CASE, ai_mode, dict(overrides or {}), runs_root=root / "runs", code_commit=FIXTURE_COMMIT
    )


@pytest.fixture(scope="module")
def off_run(tmp_path_factory: pytest.TempPathFactory) -> RunSummary:
    return _run(tmp_path_factory.mktemp("stub-off"))


def test_pipeline_runs_end_to_end_on_stubs(off_run: RunSummary) -> None:
    assert off_run.outcome == "ok", off_run.reason
    assert off_run.exit_code == 0
    statuses = {record.name: record.status for record in off_run.steps}
    assert statuses["relentra"] == "skipped"  # AI off: the runner skips Relentra
    assert all(status == "ok" for name, status in statuses.items() if name != "relentra")


def test_every_stub_output_is_schema_valid(off_run: RunSummary) -> None:
    for step in STEPS:
        if step.name == "relentra":
            continue
        for name in step.outputs:
            assert io.exists(name, off_run.run_dir), name
            io.read(name, off_run.run_dir, validate=True)


def test_two_stub_runs_are_byte_identical(off_run: RunSummary, tmp_path: Path) -> None:
    again = _run(tmp_path)
    assert again.run_id == off_run.run_id
    assert again.outputs == off_run.outputs
    for name in ("run_manifest", "receipt"):
        assert sha256_file(io.path_of(name, again.run_dir)) == sha256_file(io.path_of(name, off_run.run_dir))


def test_verdict_is_valid_uncalibrated_and_self_hashed(off_run: RunSummary) -> None:
    # Since R-00 (#9) the installed Causentra is the package's own stub (later R-10/R-12), so this
    # pipeline test keeps only contract-level invariants; the engine's behaviour is pinned by
    # packages/causentra/tests and core's own writer by the placeholder test below.
    io.read("verdict", off_run.run_dir, validate=True)
    verdict = io.read_model("verdict", off_run.run_dir, models.Verdict)
    assert verdict.confidence.set_size == len(verdict.candidate_set)
    assert verdict.calibration.family == stubs.UNCALIBRATED_FAMILY
    assert verdict.calibration.sha256 == sha256_json({"family": "uncalibrated"})
    assert verdict.run_id == off_run.run_id
    assert verdict.verdict_hash == self_hash("verdict", verdict)


def test_core_causentra_placeholder_still_writes_the_empty_verdict(
    off_run: RunSummary, tmp_path: Path
) -> None:
    # Core's R-02 writer is kept (STUB_STEPS covers every engine sub-step); called directly it
    # still writes the minimal placeholder: no pool, no set, q_hat null (+inf), uncalibrated.
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for name in ("case_manifest", "slate", "evidence"):
        source = io.path_of(name, off_run.run_dir)
        (run_dir / source.name).write_bytes(source.read_bytes())
    ctx = make_context("causentra", run_dir, case_id=CASE, run_id=off_run.run_id)
    result = stubs.run_stub(ctx, "causentra")
    assert result.notes == (stubs.STUB_NOTE,)
    verdict = io.read_model("verdict", run_dir, models.Verdict)
    assert verdict.status == "INCONCLUSIVE" and verdict.root is None
    assert verdict.candidate_set == [] and verdict.ranked == []
    assert verdict.confidence.level == "none" and verdict.confidence.q_hat is None
    assert verdict.calibration.sha256 == sha256_json({"family": "uncalibrated"})
    assert verdict.verdict_hash == self_hash("verdict", verdict)


def test_card_and_receipt_tie_back_to_the_verdict(off_run: RunSummary) -> None:
    run_dir = off_run.run_dir
    verdict = io.read_model("verdict", run_dir, models.Verdict)
    card = io.read_model("card", run_dir, models.Card)
    receipt = io.read_model("receipt", run_dir, models.Receipt)
    manifest = io.read_model("run_manifest", run_dir, models.RunManifest)
    assert card.verdict_hash == verdict.verdict_hash
    assert card.card_hash == self_hash("card", card)
    assert card.narrator.path == "template"
    md = (run_dir / "card.md").read_bytes()
    assert card.card_hash.encode() in md and b"\r\n" not in md
    assert receipt.subject[0].name == CONTRACTS["verdict"].path
    assert receipt.subject[0].digest.sha256 == sha256_file(io.path_of("verdict", run_dir))
    assert receipt.predicate.verdict_hash == verdict.verdict_hash
    assert receipt.predicate.card_hash == card.card_hash
    assert receipt.predicate.agent_trace_head is None  # AI off: no agent trace
    assert receipt.predicate.run_manifest == manifest


def test_stub_manifest_hint_fits_the_default_windows(off_run: RunSummary) -> None:
    alert = io.read_model("alert", off_run.run_dir, models.Alert)
    manifest = io.read_unredacted("case_manifest", off_run.run_dir)
    assert isinstance(manifest, models.CaseManifest)
    assert manifest.t_alert_hint_ns == stubs.STUB_T0_NS + stubs.STUB_HINT_OFFSET_S * 10**9
    assert alert.t_alert_ns == manifest.t_alert_hint_ns
    assert not alert.clamped  # both default windows lie inside the stub data span
    onsets = io.read_model("onsets", off_run.run_dir, models.Onsets)
    assert onsets.t_onset_ns == alert.t_alert_ns and onsets.method == "t_alert_fallback"


def test_ai_on_stub_relentra_writes_skipped_proposals_and_empty_trace(tmp_path: Path) -> None:
    summary = _run(tmp_path, "record", {"llm.provider": "fake"})
    assert summary.outcome == "ok", summary.reason
    proposals = io.read_model("proposals", summary.run_dir, models.Proposals)
    assert proposals.status == "skipped" and proposals.model is None and proposals.proposals == []
    assert io.read("agent_trace", summary.run_dir) == []
    receipt = io.read_model("receipt", summary.run_dir, models.Receipt)
    assert receipt.predicate.agent_trace_head is None


def test_detected_protocol_needs_an_alert_detector(tmp_path: Path) -> None:
    # Until Anomara registers veyltrace.alert_detectors:default (O-04) this is a config error.
    with pytest.raises(ConfigError):
        _run(tmp_path, "off", {"core.alert.protocol": "detected"})


def test_infralume_stub_blanks_the_hint_under_detected(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    ctx = make_context(
        "infralume", run_dir, case_id=CASE, run_id="0" * 16, overrides={"core.alert.protocol": "detected"}
    )
    result = stubs.run_stub(ctx, "infralume")
    manifest = io.read_model("case_manifest", run_dir, models.CaseManifest)
    assert manifest.t_alert_hint_ns is None and manifest.hint_source == "none"
    assert [name for name, _ in result.outputs] == sorted(stubs.stub_outputs("infralume"))
    assert result.notes == (stubs.STUB_NOTE,)
    # Since R-03 the installed synth adapter supplies the case (no placeholder): real telemetry.
    assert manifest.adapter.name == "synth"
    assert io.read_table("telemetry.spans", run_dir).num_rows > 0


def test_stub_result_lists_every_written_file(off_run: RunSummary) -> None:
    by_step = {record.name: dict(record.outputs) for record in off_run.steps}
    assert set(by_step["causivra.card"]) == {"card.json", "card.md"}
    assert stubs.stub_outputs("causivra", "card") == ("card", "card.md")
    assert stubs.stub_outputs("faultloom", "claim_pass") == ("evidence",)


def test_stub_refuses_a_context_for_another_engine(tmp_path: Path) -> None:
    ctx = make_context("signalyth", tmp_path, case_id=CASE, run_id="0" * 16)
    with pytest.raises(ValueError, match="context for engine 'signalyth'"):
        stubs.run_stub(ctx, "anomara")


def test_stub_refuses_a_phase_the_engine_never_runs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="phase 'card'"):
        stubs.stub_outputs("faultloom", "card")


def test_stub_steps_are_exactly_the_engine_sub_steps() -> None:
    assert tuple(s.name for s in STEPS if s.engine is not None) == stubs.STUB_STEPS


def test_stubs_never_import_test_helpers_or_synth() -> None:
    tree = ast.parse(STUBS_SOURCE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    banned = ("veyltrace_core.testing", "veyltrace_core.synth", "veyltrace_llm")
    assert not [m for m in imported if m.startswith(banned)]


def test_adapter_tables_are_padded_but_required_columns_are_not_invented() -> None:
    import pyarrow as pa

    from veyltrace_core.errors import ContractValidationError

    schema = io.arrow_schema("telemetry.events")
    names = ["t_ns", "entity", "kind", "source_system", "detail_json"]  # nullable actor omitted
    rows = [{"t_ns": 1, "entity": "db", "kind": "restart", "source_system": "k8s", "detail_json": "{}"}]
    table = pa.Table.from_pylist(rows, schema=pa.schema([schema.field(n) for n in names]))
    full = stubs._full_table("telemetry.events", table)  # pyright: ignore[reportPrivateUsage] - unit under test
    assert full.schema.equals(schema, check_metadata=False)
    assert full.column("actor").null_count == 1
    with pytest.raises(ContractValidationError, match="detail_json"):
        stubs._full_table("telemetry.events", table.drop_columns(["detail_json"]))  # pyright: ignore[reportPrivateUsage]
