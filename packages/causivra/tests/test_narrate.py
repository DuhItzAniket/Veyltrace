"""Card narration (10 §3.2, §6, §7 FakeProvider rows): attempts, repair, fallback, the model's input."""

from __future__ import annotations

from collections.abc import Callable
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
    schema,
)
from veyltrace_causivra.placeholders import FillContext, RunnerUp, TableAtom
from veyltrace_contracts import models
from veyltrace_core.canonical import canonical_json
from veyltrace_core.config import load_section_file, resolve_config
from veyltrace_core.errors import ConfigError
from veyltrace_core.testing import repo_root
from veyltrace_llm.client import LLMClient
from veyltrace_llm.fake import FakeProvider, FakeReply
from veyltrace_llm.settings import settings_from as llm_settings

ATOM = "Ea4217049f6"
NODES = frozenset({"payment", "cart", "checkout"})
CHECKER = checker_settings(
    dict(resolve_config({}, config_dir=repo_root() / "config", ai_mode="off").engine("causivra"))
)
SETTINGS = NarrationSettings(max_sentences=5, max_attempts=2, budget_ms=60_000.0)
PARAMS: dict[str, Any] = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "presence_penalty": 1.5,
    "thinking": False, "seed": 1, "max_tokens": 300}  # fmt: skip
GOOD = [
    {"text": "{ROOT} is the most likely root cause.", "cites": [ATOM]},
    {
        "text": "Its {E" + ATOM[1:] + ".label} reached {E" + ATOM[1:] + ".value} {E" + ATOM[1:] + ".unit}.",
        "cites": [ATOM],
    },
]
BAD = [{"text": "Latency rose to 512 ms on payment.", "cites": [ATOM]}, GOOD[0]]


def _ctx() -> FillContext:
    return FillContext(
        status="LIKELY",
        root_service="payment",
        root_fields={"component": "payment", "fault_class": "cpu", "indicator": "cpu", "mode": "resource"},
        runner_up=RunnerUp("cart", "cpu", "latency"),
        conf_level="medium",
        conf_set_size=2,
        conf_margin=0.27,
        table={ATOM: TableAtom(ATOM, "cpu anomaly (incident)", 9.42, "z", "payment", "incident")},
        nodes=NODES,
        onset_ns=None,
        sig_digits=3,
    )


def _client(tmp_path: Path, *replies: FakeReply) -> tuple[LLMClient, FakeProvider]:
    section = dict(load_section_file("llm", config_dir=repo_root() / "config"))
    provider = FakeProvider({PURPOSE: replies})
    client = LLMClient(llm_settings(section, env={}), "record", tmp_path / "cassette", provider=provider)
    return client, provider


@pytest.fixture
def run(
    make_verdict: Callable[..., models.Verdict], tmp_path: Path
) -> Callable[..., tuple[Narration, FakeProvider]]:
    def go(*replies: FakeReply, settings: NarrationSettings = SETTINGS) -> tuple[Narration, FakeProvider]:
        client, provider = _client(tmp_path, *replies)
        narration = narrate(
            verdict=make_verdict("LIKELY"), ctx=_ctx(), kinds={ATOM: "internal_anomaly"},
            path=["checkout", "payment"],
            entities=NODES, client=client, params=PARAMS, settings=settings, checker=CHECKER,
        )  # fmt: skip
        return narration, provider

    return go


def test_a_valid_reply_is_filled(run: Callable[..., tuple[Narration, FakeProvider]]) -> None:
    narration, provider = run(FakeReply.json({"sentences": GOOD}))
    assert narration.narrator == {"path": "llm", "model": "qwen3.5:9b", "attempts": 1, "checker_failures": 0}
    assert (
        narration.summary is not None
        and narration.summary[0]["text"] == "payment is the most likely root cause."
    )
    assert narration.summary[1]["text"] == "Its cpu anomaly (incident) reached 9.42 z."
    (request,) = provider.calls
    assert request.purpose == PURPOSE and canonical_json(request.schema) == canonical_json(
        schema([ATOM], 5, CHECKER.max_chars)
    )
    user = request.messages[1].content
    assert (
        "9.42" not in user
        and "{ROOT}" in user
        and f"{ATOM} | cpu anomaly (incident) | internal_anomaly | z" in user
    )
    assert "Path: {SVC:checkout} -> {SVC:payment}" in user


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
    assert narration.summary is None and narration.narrator["attempts"] == 1


def test_invalid_json_is_a_failed_attempt(run: Callable[..., tuple[Narration, FakeProvider]]) -> None:
    narration, provider = run(FakeReply(content="not json"), FakeReply.json({"sentences": GOOD}))
    assert narration.narrator["path"] == "llm" and narration.narrator["attempts"] == 2
    assert provider.calls[1].messages[3].content.splitlines()[1].startswith("- reply: ")


def test_the_latency_budget_stops_narration(run: Callable[..., tuple[Narration, FakeProvider]]) -> None:
    slow = FakeReply.json({"sentences": GOOD}, latency_ms=SETTINGS.budget_ms + 1)
    narration, _ = run(slow)
    assert narration.summary is None and narration.narrator["attempts"] == 1


def test_narration_settings_are_validated() -> None:
    good = {"narration": {"max_sentences": 5, "max_attempts": 2, "budget_ms": 60000}}
    assert narration_settings(good) == SETTINGS
    for bad in ({"max_sentences": 1}, {"max_attempts": 0}, {"budget_ms": True}):
        with pytest.raises(ConfigError):
            narration_settings({"narration": {**good["narration"], **bad}})
