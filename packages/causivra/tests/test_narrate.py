"""Card narration (10 §3.2, §6, §7 FakeProvider rows): attempts, repair, fallback, the model's input."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from veyltrace_causivra.checker import checker_settings
from veyltrace_causivra.narrate import (
    PURPOSE,
    Narration,
    NarrationSettings,
    narrate,
    narration_settings,
    sampler_params,
    schema,
)
from veyltrace_causivra.placeholders import FillContext, RunnerUp, TableAtom
from veyltrace_contracts import models
from veyltrace_core.canonical import canonical_json
from veyltrace_core.config import load_section_file, resolve_config
from veyltrace_core.errors import ConfigError
from veyltrace_core.ids import AIMode
from veyltrace_core.rng import seed_int
from veyltrace_core.testing import repo_root
from veyltrace_llm.client import LLMClient
from veyltrace_llm.fake import FakeProvider, FakeReply
from veyltrace_llm.settings import settings_from as llm_settings

ATOM = "Ea4217049f6"
NODES = frozenset({"payment", "cart", "checkout"})
CHECKER = checker_settings(
    dict(resolve_config({}, config_dir=repo_root() / "config", ai_mode="off").engine("causivra"))
)
SETTINGS = NarrationSettings(
    enabled=True, max_sentences=5, max_attempts=2, max_tokens=300, budget_ms=60_000.0, show_values=False
)
CONFIG = resolve_config({}, config_dir=repo_root() / "config", ai_mode="record")
PARAMS: dict[str, Any] = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "presence_penalty": 1.5,
    "thinking": False, "seed": 1, "max_tokens": 300}  # fmt: skip
GOOD = [
    {"text": "{ROOT} is the most likely root cause.", "cites": [ATOM]},
    {"text": f"Its {{{ATOM}.label}} reached {{{ATOM}.value}} {{{ATOM}.unit}}.", "cites": [ATOM]},
]
BAD = [{"text": "Latency rose to 512 ms on payment.", "cites": [ATOM]}, GOOD[0]]


def _ctx() -> FillContext:
    return FillContext(
        status="LIKELY", root_service="payment",
        root_fields={"component": "payment", "fault_class": "cpu", "indicator": "cpu", "mode": "resource"},
        runner_up=RunnerUp("cart", "cpu", "latency"), conf_level="medium", conf_set_size=2, conf_margin=0.27,
        table={ATOM: TableAtom(ATOM, "cpu anomaly (incident)", 9.42, "z", "payment", "incident")},
        nodes=NODES, onset_ns=None, sig_digits=3,
    )  # fmt: skip


def _client(tmp_path: Path, *replies: FakeReply, mode: AIMode = "record") -> tuple[LLMClient, FakeProvider]:
    section = dict(load_section_file("llm", config_dir=repo_root() / "config"))
    provider = FakeProvider({PURPOSE: replies})
    settings = llm_settings(section, env={})
    client = LLMClient(settings, mode, tmp_path / "cassette", provider=provider, force_record=True)
    return client, provider


@pytest.fixture
def run(
    make_verdict: Callable[..., models.Verdict], tmp_path: Path
) -> Callable[..., tuple[Narration, FakeProvider]]:
    def go(
        *replies: FakeReply, mode: AIMode = "record", ctx: FillContext | None = None, seed: int = 1,
        settings: NarrationSettings = SETTINGS,
    ) -> tuple[Narration, FakeProvider]:  # fmt: skip
        client, provider = _client(tmp_path, *replies, mode=mode)
        narration = narrate(
            verdict=make_verdict("LIKELY"), ctx=ctx or _ctx(), kinds={ATOM: "internal_anomaly"},
            path=["checkout", "payment"], entities=NODES, client=client,
            params={**PARAMS, "seed": seed}, settings=settings, checker=CHECKER,
        )  # fmt: skip
        return narration, provider

    return go


def test_a_valid_reply_is_filled(run: Callable[..., tuple[Narration, FakeProvider]]) -> None:
    narration, provider = run(FakeReply.json({"sentences": GOOD}))
    assert narration.narrator == {"path": "llm", "model": "qwen3.5:9b", "attempts": 1, "checker_failures": 0}
    texts = [s["text"] for s in narration.summary or []]
    assert texts == ["payment is the most likely root cause.", "Its cpu anomaly (incident) reached 9.42 z."]
    (request,) = provider.calls
    assert request.purpose == PURPOSE and canonical_json(request.schema) == canonical_json(
        schema([ATOM], 5, CHECKER.max_chars)
    )
    user = request.messages[1].content
    assert "9.42" not in user and f"{ATOM} | cpu anomaly (incident) | internal_anomaly | z" in user
    assert "Path: {SVC:checkout} -> {SVC:payment}" in user
    assert "{" + ATOM + ".value}" in user and "{E<" not in user and "{E<" not in request.messages[0].content


def test_a_rejected_reply_is_repaired_once(run: Callable[..., tuple[Narration, FakeProvider]]) -> None:
    narration, provider = run(FakeReply.json({"sentences": BAD}), FakeReply.json({"sentences": GOOD}))
    assert narration.narrator == {"path": "llm", "model": "qwen3.5:9b", "attempts": 2, "checker_failures": 1}
    repair = provider.calls[1].messages
    assert [m.role for m in repair] == ["system", "user", "assistant", "user"]
    assert "- sentence 1: C4 at '512': raw digits outside placeholders" in repair[3].content


def test_two_rejections_give_template_prose(run: Callable[..., tuple[Narration, FakeProvider]]) -> None:
    narration, _ = run(FakeReply.json({"sentences": BAD}), FakeReply.json({"sentences": BAD}))
    assert narration.summary is None
    assert narration.narrator == {"path": "template", "model": None, "attempts": 2, "checker_failures": 2}


def test_a_provider_error_gives_template_prose(run: Callable[..., tuple[Narration, FakeProvider]]) -> None:
    narration, _ = run(FakeReply.failure("timeout"))
    assert narration.summary is None
    assert narration.narrator == {"path": "template", "model": None, "attempts": 1, "checker_failures": 0}
    narration, _ = run(FakeReply.json({"sentences": BAD}), FakeReply.failure("timeout"))
    assert narration.narrator == {"path": "template", "model": None, "attempts": 2, "checker_failures": 1}


def test_an_empty_table_makes_no_call(run: Callable[..., tuple[Narration, FakeProvider]]) -> None:
    narration, provider = run(FakeReply.json({"sentences": GOOD}), ctx=replace(_ctx(), table={}))
    assert narration.summary is None and narration.narrator["attempts"] == 0 and not provider.calls


def test_a_malformed_sentence_is_not_a_checker_failure(
    run: Callable[..., tuple[Narration, FakeProvider]],
) -> None:
    narration, _ = run(
        FakeReply.json({"sentences": [{"text": 1, "cites": []}, GOOD[0]]}),
        FakeReply.json({"sentences": GOOD}),
    )
    assert narration.narrator == {"path": "llm", "model": "qwen3.5:9b", "attempts": 2, "checker_failures": 0}


def test_replay_reproduces_the_record(run: Callable[..., tuple[Narration, FakeProvider]]) -> None:
    recorded, _ = run(FakeReply.json({"sentences": BAD}), FakeReply.json({"sentences": GOOD}))
    replayed, provider = run(mode="replay")
    assert replayed == recorded and not provider.calls and not replayed.cassette_miss


def test_a_cassette_miss_gives_template_prose(run: Callable[..., tuple[Narration, FakeProvider]]) -> None:
    run(FakeReply.json({"sentences": GOOD}))
    narration, _ = run(mode="replay", seed=2)
    assert narration.summary is None and narration.cassette_miss
    assert narration.narrator == {"path": "template", "model": None, "attempts": 1, "checker_failures": 0}


def test_invalid_json_is_a_failed_attempt(run: Callable[..., tuple[Narration, FakeProvider]]) -> None:
    narration, provider = run(FakeReply(content="not json"), FakeReply.json({"sentences": GOOD}))
    assert narration.narrator["path"] == "llm" and narration.narrator["attempts"] == 2
    assert provider.calls[1].messages[3].content.splitlines()[1].startswith("- reply: ")


def test_the_latency_budget_stops_narration(run: Callable[..., tuple[Narration, FakeProvider]]) -> None:
    slow = FakeReply.json({"sentences": GOOD}, latency_ms=SETTINGS.budget_ms + 1)
    narration, _ = run(slow)
    assert narration.summary is None and narration.narrator["attempts"] == 1


def test_narration_settings_are_validated() -> None:
    good = dict(CONFIG.engine("causivra"))
    assert narration_settings(good) == SETTINGS
    bad_values = ({"max_sentences": 1}, {"max_attempts": 0}, {"max_tokens": 0}, {"budget_ms": True},
        {"enabled": "yes"}, {"show_values": None}, {"scope": "all"})  # fmt: skip
    for bad in bad_values:
        with pytest.raises(ConfigError):
            narration_settings({"narration": {**good["narration"], **bad}})


def test_the_sampler_is_relentras_with_causivras_seed() -> None:
    relentra = dict(CONFIG.engine("relentra"))
    params = sampler_params(relentra, "a1b2c3d4e5f6", 300)
    seed = seed_int("a1b2c3d4e5f6", "causivra.seed/0")
    assert params == {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "presence_penalty": 1.5,
        "thinking": False, "seed": seed, "max_tokens": 300}  # fmt: skip
    with pytest.raises(ConfigError):
        sampler_params({"sampler": {"temperature": 0.7}}, "a1b2c3d4e5f6", 300)


def test_show_values_adds_the_value_column(run: Callable[..., tuple[Narration, FakeProvider]]) -> None:
    shown = replace(SETTINGS, show_values=True)
    _, provider = run(FakeReply.json({"sentences": GOOD}), settings=shown)
    user = provider.calls[0].messages[1].content
    assert (
        "unit | value)" in user and f"{ATOM} | cpu anomaly (incident) | internal_anomaly | z | 9.42" in user
    )
