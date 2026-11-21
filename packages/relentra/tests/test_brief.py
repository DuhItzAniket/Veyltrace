"""`brief` mode end to end on synth-01 with a scripted FakeProvider (08 §3.2, §5, §6, §7)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.context import RunContext
from veyltrace_core.hashing import verify_chain
from veyltrace_core.testing import VARIANTS, fixture_run_dir, make_context
from veyltrace_llm.cassette import CassetteMiss
from veyltrace_llm.fake import FakeProvider, FakeReply
from veyltrace_relentra import api
from veyltrace_relentra.brief import PURPOSE, run_brief

CASE = "synth-01@fake"
THROUGH = "causatrix"


def _run_dir(tmp_path: Path) -> Path:
    return fixture_run_dir(CASE, tmp_path, through=THROUGH)


def _ctx(run_dir: Path, ai_mode: Any = "record", **overrides: object) -> RunContext:
    context = make_context(
        "relentra", run_dir, ai_mode=ai_mode, overrides={**VARIANTS[CASE].overrides, **overrides}
    )
    assert context.cassette_dir is None or context.cassette_dir.name == "cassette"
    return context


def _service(run_dir: Path) -> str:
    return io.read_model("slate", run_dir, models.Slate).candidates[0].service


def _reply(service: str, **changes: Any) -> dict[str, Any]:
    claim = {"predicate": "silent", "signal": "", "other": "", "x": 0, "cites": []}
    proposal = {
        "service": service,
        "fault_class": "cpu",
        "indicator": "cpu",
        "claims": [claim],
        "requested_trials": ["T1"],
        "rationale": "it started first",
        **changes,
    }
    return {"proposals": [proposal], "asks": []}


def _script(*replies: FakeReply) -> FakeProvider:
    return FakeProvider({PURPOSE: replies})


def _proposals(run_dir: Path) -> models.Proposals:
    return io.read_model("proposals", run_dir, models.Proposals, validate=True)


def _states(run_dir: Path) -> list[str]:
    lines = io.read_lines("agent_trace", run_dir, models.AgentTraceLine, validate=True)
    verify_chain(lines)
    return [line.state or line.type for line in lines]


def test_a_valid_reply_becomes_proposals(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    provider = _script(FakeReply.json(_reply(_service(run_dir))))
    result = run_brief(_ctx(run_dir), provider)
    proposals = _proposals(run_dir)
    assert result.status == "ok" and proposals.status == "complete" and proposals.mode == "brief"
    assert len(proposals.proposals) == 1 and proposals.proposals[0].claims[0].predicate == "silent"
    assert (proposals.budget_used.turns, proposals.budget_used.tokens_in) == (1, 100)
    assert proposals.budget_used.wall_ms == 10.0
    assert proposals.model is not None and proposals.model.provider == "fake"
    assert _states(run_dir) == ["start", "cards_built", "prompt_built", "llm_call", "validated", "done"]
    assert result.ai_manifest is not None and result.ai_manifest.schemas[0][0] == PURPOSE
    assert any(name == "prompts/system.md" for name, _ in result.ai_manifest.prompts)


def test_the_request_is_constrained_and_carries_the_evidence(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    provider = _script(FakeReply.json({"proposals": [], "asks": []}))
    run_brief(_ctx(run_dir), provider)
    (request,) = provider.calls
    assert request.purpose == PURPOSE and request.schema is not None
    assert _service(run_dir) in request.messages[1].content
    assert _proposals(run_dir).status == "complete"  # no proposals is a valid answer


def test_an_invalid_reply_is_repaired_once(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    service = _service(run_dir)
    bad = FakeReply.json(_reply("paymentservice-v2"))
    provider = _script(bad, FakeReply.json(_reply(service)))
    run_brief(_ctx(run_dir), provider)
    assert _proposals(run_dir).status == "complete" and _proposals(run_dir).budget_used.turns == 2
    assert "unknown service 'paymentservice-v2'" in provider.calls[1].messages[-1].content
    assert [m.role for m in provider.calls[1].messages[-2:]] == ["assistant", "user"]
    assert "repair" in _states(run_dir) and "drop_proposal" not in _states(run_dir)


def test_salvage_keeps_the_valid_part_after_a_failed_repair(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    reply = _reply(_service(run_dir))
    reply["proposals"].append(_reply("paymentservice-v2")["proposals"][0])
    run_brief(_ctx(run_dir), _script(FakeReply.json(reply), FakeReply.json(reply)))
    proposals = _proposals(run_dir)
    assert proposals.status == "complete" and len(proposals.proposals) == 1
    assert "drop_proposal" in _states(run_dir) and _states(run_dir)[-1] == "done"


@pytest.mark.parametrize("content", ["not json", '{"proposals": [{"service": "nope"}], "asks": []}'])
def test_nothing_usable_is_a_failed_run_that_continues(tmp_path: Path, content: str) -> None:
    run_dir = _run_dir(tmp_path)
    result = run_brief(_ctx(run_dir), _script(FakeReply(content=content), FakeReply(content=content)))
    proposals = _proposals(run_dir)
    assert result.status == "degraded" and proposals.status == "failed" and proposals.proposals == []
    assert _states(run_dir)[-1] == "failed" and proposals.budget_used.turns == 2


def test_a_provider_error_is_recorded_and_not_retried(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    provider = _script(FakeReply.failure("timeout"))
    result = run_brief(_ctx(run_dir), provider)
    assert result.status == "degraded" and _proposals(run_dir).status == "failed"
    assert len(provider.calls) == 1 and "provider_error" in _states(run_dir)


def test_a_prompt_that_cannot_fit_makes_no_call(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    provider = _script()
    result = run_brief(_ctx(run_dir, **{"relentra.budget.max_prompt_tokens": 10}), provider)
    assert result.status == "ok" and _proposals(run_dir).status == "budget_exhausted"
    assert provider.calls == [] and _states(run_dir) == ["start", "budget_context", "done"]


def test_replay_reproduces_the_recording_byte_for_byte(tmp_path: Path) -> None:
    first = _run_dir(tmp_path / "record")
    reply = FakeReply.json(_reply("paymentservice-v2"))
    run_brief(_ctx(first), _script(reply, FakeReply.json(_reply(_service(first)))))
    second = _run_dir(tmp_path / "replay")
    context = _ctx(second, "replay")
    replayed = dataclasses.replace(context, cassette_dir=first / "cassette")
    run_brief(replayed)
    for name in ("proposals", "agent_trace"):
        assert io.path_of(name, first).read_bytes() == io.path_of(name, second).read_bytes()


def test_replay_without_the_recording_is_a_cassette_miss(tmp_path: Path) -> None:
    first = _run_dir(tmp_path / "record")
    run_brief(_ctx(first), _script(FakeReply.json({"proposals": [], "asks": []})))
    second = _run_dir(tmp_path / "replay")
    context = _ctx(second, "replay", **{"relentra.sampler.seed_index": 1})
    context = dataclasses.replace(context, cassette_dir=first / "cassette")
    with pytest.raises(CassetteMiss):
        run_brief(context)


def test_the_engine_entry_runs_brief_mode_and_writes_valid_json(tmp_path: Path) -> None:
    run_dir = _run_dir(tmp_path)
    result = api.run(_ctx(run_dir))  # the configured fake provider answers `unscripted`
    assert result.status == "degraded" and _proposals(run_dir).status == "failed"
    assert json.loads(io.path_of("proposals", run_dir).read_text("utf-8"))["model"]["params"]["seed"] >= 0
