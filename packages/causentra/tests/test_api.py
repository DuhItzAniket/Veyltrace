"""The Causentra step on a real run directory: inputs read through ctx, verdict written, config."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from veyltrace_causentra import api
from veyltrace_contracts import models
from veyltrace_core import io, plugins, textio
from veyltrace_core.calibration import write_calibration
from veyltrace_core.config import section_sha256
from veyltrace_core.errors import ContractValidationError
from veyltrace_core.hashing import sha256_json
from veyltrace_core.testing import make_context, repo_root

#: Every 09 §4 key with its spec default (the predicates weights are covered by tests/test_workspace).
SPEC_DEFAULTS = {
    "alpha": 0.10,
    "factors.pass": 1.0,
    "factors.untestable_mandatory": 0.85,
    "factors.fail_mandatory": 0.25,
    "factors.untestable_supporting": 1.0,
    "factors.fail_supporting": 0.9,
    "mandatory": ["T1", "T2", "T3", "T4"],
    "claims.clip_low": -0.3,
    "claims.clip_high": 0.3,
    "proposals.max": 5,
    "status.c_high": 0.30,
    "status.c_med": 0.15,
    "status.likely_max_set": 3,
    "trials.T2.min_fraction": 1.0,
    "trials.T3.min_path_anomalous_fraction": 0.5,
    "trials.T5.min_share": 0.30,
    "trials.T6.min_proximity": 0.36787944,
    "trials.T7.min_gap": 3.0,
    "calibration.family": None,
    "calibration.uncalibrated_q_hat": 0.0,
    "no_fault.beta": 0.10,
    "no_fault.detector": "robust_z",
    "no_fault.default_tau": 1.386294361,
    "asks.max": 5,
}


def _verdict(run_dir: Path) -> models.Verdict:
    return io.read_model("verdict", run_dir, models.Verdict)


def test_entry_point_resolves_to_api_run() -> None:
    assert plugins.load_one("veyltrace.engines", "causentra") is api.run


def test_config_declares_every_spec_key_with_its_default(synth01_dir: Path) -> None:
    cfg = make_context("causentra", synth01_dir).config
    for key, default in SPEC_DEFAULTS.items():
        value = cfg.get_path(key)
        assert (list(value) if isinstance(value, tuple) else value) == default, key
    assert list(cfg.get_path("trials.disabled")) == []


def test_run_writes_a_valid_verdict(synth01_dir: Path) -> None:
    ctx = make_context("causentra", synth01_dir)
    result = api.run(ctx)
    assert result.status == "ok"
    assert not any(n.startswith("stub: ") for n in result.notes)
    assert [name for name, _ in result.outputs] == ["verdict"]
    io.read("verdict", synth01_dir, validate=True)
    verdict = _verdict(synth01_dir)
    slate = io.read_model("slate", synth01_dir, models.Slate)
    assert verdict.case_id == ctx.case_id and verdict.run_id == ctx.run_id
    assert verdict.status == "INCONCLUSIVE" and verdict.root is None
    assert [r.service for r in verdict.ranked] == [c.service for c in slate.candidates]
    assert verdict.calibration.family == "uncalibrated"
    assert verdict.calibration.sha256 == sha256_json({"family": "uncalibrated"})
    assert ctx.resolved is not None
    assert verdict.params_sha256 == section_sha256(ctx.resolved, "causentra")


def test_override_changes_params_sha256_and_alpha(synth01_dir: Path) -> None:
    base = make_context("causentra", synth01_dir)
    api.run(base)
    before = _verdict(synth01_dir)
    tuned = make_context("causentra", synth01_dir, overrides={"causentra.alpha": 0.2})
    api.run(tuned)
    after = _verdict(synth01_dir)
    assert after.confidence.alpha == 0.2
    assert after.params_sha256 != before.params_sha256


def test_populated_slate_is_ranked_whole(synth01_dir: Path, example_slate: models.Slate) -> None:
    io.write("slate", example_slate, synth01_dir)
    api.run(make_context("causentra", synth01_dir))
    verdict = _verdict(synth01_dir)
    assert sorted(r.service for r in verdict.ranked) == sorted(c.service for c in example_slate.candidates)
    # No atoms: T1-T4 untestable (0.85 each), so V keeps the slate's order and the leader is rank 1.
    assert [r.service for r in verdict.ranked] == [c.service for c in example_slate.candidates]
    assert [c.service for c in verdict.candidate_set] == [verdict.ranked[0].service]  # uncalibrated q_hat 0
    assert verdict.status == "INCONCLUSIVE" and verdict.confidence.level == "low"
    assert len(verdict.ranks_rcaeval) == len(example_slate.all_scores)


@pytest.mark.parametrize("missing", ["slate", "evidence"])
def test_missing_slate_or_evidence_fails_without_a_verdict(synth01_dir: Path, missing: str) -> None:
    io.path_of(missing, synth01_dir).unlink()
    result = api.run(make_context("causentra", synth01_dir))
    assert result.status == "failed"
    assert result.outputs == ()
    assert not io.exists("verdict", synth01_dir)


def test_slate_for_another_case_is_rejected(synth01_dir: Path, example_slate: models.Slate) -> None:
    io.write("slate", example_slate.model_copy(update={"case_id": "0" * 12}), synth01_dir)
    with pytest.raises(ContractValidationError):
        api.run(make_context("causentra", synth01_dir))


def test_wrong_engine_context_is_refused(synth01_dir: Path) -> None:
    with pytest.raises(ValueError, match="causentra"):
        api.run(make_context("causatrix", synth01_dir))


def test_ai_on_every_proposal_gets_one_outcome(
    synth01_dir: Path, example_proposals: models.Proposals
) -> None:
    io.write("proposals", example_proposals, synth01_dir)
    nodes = set(io.read_table("graph.nodes", synth01_dir, columns=["node"]).column("node").to_pylist())
    result = api.run(make_context("causentra", synth01_dir, ai_mode="record"))
    verdict = _verdict(synth01_dir)
    # No claim_check atom holds yet, so nothing is admitted (09 §3.10 rows 2 and 5).
    assert verdict.proposals_accepted == [] and result.metrics["proposals_admitted"] == 0
    want = {
        p.proposal_id: "unknown_entity" if p.hypothesis.service not in nodes else "claim_false"
        for p in example_proposals.proposals
    }
    assert {r.proposal_id: r.reason for r in verdict.proposals_rejected} == want


def test_calibration_file_sets_family_hash_and_q_hat(
    synth01_dir: Path, tmp_path: Path, example_slate: models.Slate
) -> None:
    config_dir = tmp_path / "config"
    shutil.copytree(repo_root() / "config", config_dir)
    content = stub_calibration("synth.off.oracle.foldA", q_hat=None)
    write_calibration(config_dir / "calibration", content)
    io.write("slate", example_slate, synth01_dir)
    ctx = make_context("causentra", synth01_dir, config_dir=config_dir)
    assert ctx.config.calibration is not None
    api.run(ctx)
    verdict = _verdict(synth01_dir)
    assert verdict.calibration.family == "synth.off.oracle.foldA"
    assert verdict.calibration.sha256 == ctx.config.calibration_sha256
    assert verdict.confidence.q_hat is None  # +inf: the whole decision pool is the set (09 §3.7)
    assert [c.service for c in verdict.candidate_set] == [r.service for r in verdict.ranked]
    assert verdict.status == "INCONCLUSIVE" and verdict.confidence.level == "low"
    # |C| = 5 > status.likely_max_set = 3: the 09 §3.11 priority-4 ask follows the leader's
    # priority-3 asks (its T1-T4 are untestable without atoms).
    assert [a.target.split(":")[0] for a in verdict.asks] == ["T1", "T2", "T3", "T4", "set"]
    assert verdict.asks[-1].why == "candidate set has 5 members"


def test_calibration_fitted_at_another_alpha_fails_the_step(synth01_dir: Path, tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    shutil.copytree(repo_root() / "config", config_dir)
    write_calibration(config_dir / "calibration", stub_calibration("synth.off.oracle.foldA", q_hat=0.25))
    ctx = make_context("causentra", synth01_dir, config_dir=config_dir, overrides={"causentra.alpha": 0.2})
    result = api.run(ctx)
    assert result.status == "failed" and result.outputs == ()
    assert any("alpha=0.1" in note for note in result.notes)
    assert not io.exists("verdict", synth01_dir)


def test_schema_invalid_proposals_count_as_none_and_degrade(synth01_dir: Path) -> None:
    # The same file FaultLoom's claim pass degrades on (06 §6): Causentra must still decide.
    textio.write_bytes(io.path_of("proposals", synth01_dir), b'{"schema_version": "0.1.0"}\n')
    result = api.run(make_context("causentra", synth01_dir, ai_mode="record"))
    assert result.status == "degraded"
    assert any("schema-invalid" in note for note in result.notes)
    assert [name for name, _ in result.outputs] == ["verdict"]
    verdict = _verdict(synth01_dir)
    assert verdict.proposals_accepted == [] and verdict.proposals_rejected == []
    assert result.metrics["proposals"] == 0


@pytest.mark.parametrize("name", ["alignment", "graph.edges", "graph.paths"])
def test_optional_inputs_absent_still_give_a_verdict(synth01_dir: Path, name: str) -> None:
    io.path_of(name, synth01_dir).unlink()
    result = api.run(make_context("causentra", synth01_dir))
    assert result.status == "ok"
    assert any(f"optional input absent: {name}" in note for note in result.notes)
    verdict = _verdict(synth01_dir)
    if name == "graph.edges":  # 09 §6: missing graph edges make T3 untestable
        assert all(
            any(t.id == "T3" and t.reason == "no_graph_edges" for t in r.trials) for r in verdict.ranked
        )


def stub_calibration(family: str, *, q_hat: float | None) -> dict[str, object]:
    """A calibration file body with too few cases (n = 8 < 9, so q_hat = +inf; 09 §7)."""
    return {
        "schema_version": "0.1.0",
        "family": family,
        "ai_arm": "off",
        "alert_protocol": "oracle",
        "alpha": 0.1,
        "n": 8,
        "rank_index": 9,
        "q_hat": q_hat,
        "no_fault": {
            "beta": 0.1,
            "m": 1,
            "rank_index": 2,
            "tau_nf": 1.386294361,
            "calibrated": False,
            "sources": ["synth-05"],
        },
        "split": {"seed": 1, "fold": "foldA", "cases_sha256": "c" * 64},
        "scores_sha256": "d" * 64,
        "config_sha256": "e" * 64,
        "code_commit": "fixture",
        "experiment_id": "test",
    }
