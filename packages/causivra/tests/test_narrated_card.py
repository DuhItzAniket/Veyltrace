"""The card step with narration on (10 §3.2, §6; §7 golden row: FakeProvider narration scripted for
one valid and one twice-rejected case), on synth-01's Causentra fixtures."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pyarrow as pa

from veyltrace_causivra.card import TEMPLATE_NARRATOR, run_card
from veyltrace_causivra.narrate import PURPOSE
from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.context import EngineResult
from veyltrace_core.ids import AIMode
from veyltrace_core.testing import fixture_run_dir, golden_file, make_context
from veyltrace_llm.fake import FakeProvider, FakeReply
from veyltrace_llm.request import LLMRequest

CASE = "synth-01"


def _atom(request: LLMRequest) -> str:
    assert request.schema is not None
    return str(request.schema["properties"]["sentences"]["items"]["properties"]["cites"]["items"]["enum"][0])


def _valid(request: LLMRequest) -> FakeReply:
    a = _atom(request)
    return FakeReply.json({"sentences": [
        {"text": "{ROOT} is the leading candidate.", "cites": [a]},
        {"text": f"Its {{{a}.label}} reached {{{a}.value}} {{{a}.unit}}.", "cites": [a]},
    ]})  # fmt: skip


def _rejected(request: LLMRequest) -> FakeReply:
    a = _atom(request)
    return FakeReply.json({"sentences": [{"text": "Latency rose to 512 ms.", "cites": [a]},
        {"text": "{ROOT} is the leading candidate.", "cites": [a]}]})  # fmt: skip


def _run(
    tmp_path: Path,
    mode: AIMode,
    responder: Callable[[LLMRequest], FakeReply] | None = None,
    cassette: Path | None = None,
    overrides: dict[str, Any] | None = None,
    prepare: Callable[[Path], None] | None = None,
) -> tuple[EngineResult, dict[str, Any], FakeProvider]:
    run_dir = fixture_run_dir(CASE, tmp_path, through="causentra")
    if prepare is not None:
        prepare(run_dir)
    ctx = make_context("causivra", run_dir, phase="card", ai_mode=mode, cassette_dir=cassette,
        overrides=overrides or {})  # fmt: skip
    provider = FakeProvider(default=responder)
    result = run_card(ctx, provider=provider if mode == "record" else None)
    card = io.read_model("card", run_dir, models.Card, validate=True).model_dump(mode="json", by_alias=True)
    return result, card, provider


def test_a_valid_narration_fills_the_summary(tmp_path: Path) -> None:
    result, card, provider = _run(tmp_path, "record", _valid)
    assert card["narrator"] == {"path": "llm", "model": "qwen3.5:9b", "attempts": 1, "checker_failures": 0}
    assert card["summary"][0]["text"] == "checkout is the leading candidate."
    assert all("{" not in s["text"] for s in card["summary"]) and len(provider.calls) == 1
    assert provider.calls[0].purpose == PURPOSE
    ai = result.ai_manifest
    assert ai is not None and ai.model == "qwen3.5:9b" and [n for n, _ in ai.schemas] == [PURPOSE]
    assert [n for n, _ in ai.prompts] == ["prompts/narrate.md", "prompts/repair.md", "prompts/system.md"]


def test_replay_reproduces_the_narrated_card(tmp_path: Path) -> None:
    _, recorded, _ = _run(tmp_path / "rec", "record", _valid)
    (cassette,) = (tmp_path / "rec").rglob("cassette")
    _, replayed, _ = _run(tmp_path / "rep", "replay", cassette=cassette)
    assert replayed == recorded and replayed["narrator"]["path"] == "llm"


def test_two_rejections_give_the_template_summary(tmp_path: Path) -> None:
    _, card, provider = _run(tmp_path, "record", _rejected)
    template = json.loads(golden_file("causivra", CASE, "card.json").read_bytes())
    assert card["summary"] == template["summary"] and len(provider.calls) == 2
    assert card["narrator"] == {"path": "template", "model": None, "attempts": 2, "checker_failures": 2}


def test_a_cassette_miss_gives_the_template_summary(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    result, card, _ = _run(tmp_path / "run", "replay", cassette=tmp_path / "empty")
    assert card["narrator"] == {"path": "template", "model": None, "attempts": 1, "checker_failures": 0}
    assert result.ai_manifest is not None


def test_narration_off_keeps_ai_on_cards_template(tmp_path: Path) -> None:
    result, card, provider = _run(tmp_path, "record", _valid, overrides={"causivra.narration.enabled": False})
    assert card["narrator"] == dict(TEMPLATE_NARRATOR) and not provider.calls and result.ai_manifest is None


def _names(component: str) -> Callable[[LLMRequest], FakeReply]:
    """A reply that writes `component` as plain text, outside any placeholder, every time."""

    def reply(request: LLMRequest) -> FakeReply:
        a = _atom(request)
        return FakeReply.json({"sentences": [{"text": f"Errors began in {component}.", "cites": [a]},
            {"text": "{ROOT} is the leading candidate.", "cites": [a]}]})  # fmt: skip

    return reply


def _component(run_dir: Path, name: str) -> None:
    """Give every evidence atom of `cart-0` the plain-word component `name` (not a node or service)."""
    table = io.read("evidence", run_dir)
    assert isinstance(table, pa.Table)
    rows = table.to_pylist()
    assert any(r["component"] == "cart-0" for r in rows)
    io.write(
        "evidence", [{**r, "component": name} if r["component"] == "cart-0" else r for r in rows], run_dir
    )


def test_c6_rejects_an_evidence_component_written_as_plain_text(tmp_path: Path) -> None:
    """Regression (#52 bug bash): the C6 lexicon missed evidence `component` values (10 §3.4), so
    "redis" passed C6 when it is a component but not a graph node or a case service."""
    _, card, provider = _run(tmp_path, "record", _names("redis"), prepare=lambda d: _component(d, "redis"))
    assert card["narrator"] == {"path": "template", "model": None, "attempts": 2, "checker_failures": 2}
    assert len(provider.calls) == 2
    _, plain, _ = _run(tmp_path / "plain", "record", _names("redis"))  # not a component: C6 lets it pass
    assert plain["narrator"]["path"] == "llm"
