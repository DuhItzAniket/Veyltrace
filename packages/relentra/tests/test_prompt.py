"""Prompts, system briefs and the prompt fit (08 §3.2, §3.5)."""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import Any, get_args

import pytest

import veyltrace_relentra
from veyltrace_contracts import models
from veyltrace_core.hashing import sha256_text_lf
from veyltrace_llm.request import Message
from veyltrace_relentra.prompt import (
    estimate_tokens,
    fit_prompt,
    load_prompt_files,
    pool_context,
    render_messages,
    repair_messages,
)
from veyltrace_relentra.settings import brief_settings

SETTINGS = brief_settings(
    {
        "brief": {"max_proposals": 3},
        "budget": {"max_claims_per_proposal": 4, "max_hypotheses": 5, "max_prompt_tokens": 100},
        "schema": {"max_signal_enum": 64, "max_bytes": 16384, "exclude_fault_classes": ["unknown"]},
        "cards": {"k": 6, "k_min": 3, "pool_context_n": 2},
        "prompt": {"chars_per_token": 4, "include_brief": True, "permute_slate": False},
    }
)
PACKAGE = Path(veyltrace_relentra.__file__).parent
SYSTEMS = get_args(models.System)
MAX_BRIEF_CHARS = 1500  # 08 §3.5
#: Words a brief must not contain (package rule 6): the fault vocabulary and injection tooling.
BANNED = {*get_args(models.FaultClass), "fault", "inject", "injection", "chaos", "stress", "flag", "flagd"}
SCHEMA = {"type": "object", "properties": {"b": 1, "a": 2}}


def _slate() -> Any:
    class Item:
        def __init__(self, service: str, fused_score: float = 0.0) -> None:
            self.service, self.fused_score = service, fused_score

    class Slate:
        candidates = (Item("cart"),)
        all_scores = (Item("cart", 0.9), Item("frontend", 0.51234), Item("redis", 0.2), Item("ad", 0.1))

    return Slate()


@pytest.mark.parametrize("system", SYSTEMS)
def test_every_system_has_a_brief_of_architecture_only(system: str) -> None:
    brief = load_prompt_files(system, "synth", ["cart", "frontend"], SETTINGS).brief
    assert brief and len(brief) <= MAX_BRIEF_CHARS
    assert not BANNED & set(re.findall(r"[a-z_]+", brief.lower())), system


def test_the_generated_brief_lists_the_graph_nodes() -> None:
    for system, dataset in (("other", "synth"), ("ob", "live")):
        assert "cart, frontend" in load_prompt_files(system, dataset, ["frontend", "cart"], SETTINGS).brief


def test_messages_hold_every_section_in_order_and_are_stable() -> None:
    files = load_prompt_files("ob", "synth", [], SETTINGS)
    deck = "#1 cart costs $5 and $name\n"  # data may hold template characters
    system, user = render_messages(files, deck, "redis fused=0.2", SCHEMA)
    assert system.role == "system" and "JSON" in system.content
    positions = [
        user.content.index(s) for s in ("Online Boutique", "#1 cart", "redis fused", '{"properties"')
    ]
    assert positions == sorted(positions) and "$5 and $name" in user.content
    assert (system, user) == render_messages(files, deck, "redis fused=0.2", SCHEMA)


def test_without_the_brief_no_brief_file_is_read() -> None:
    files = load_prompt_files("ob", "synth", [], replace(SETTINGS, include_brief=False))
    assert files.brief == "" and not any(name.startswith("briefs/") for name, _ in files.hashes)


def test_hashes_cover_the_files_read_with_lf_line_endings() -> None:
    files = load_prompt_files("ss", "synth", [], SETTINGS)
    assert [n for n, _ in files.hashes] == [
        "prompts/system.md", "prompts/brief_user.md", "prompts/repair.md", "briefs/ss.md",
    ]  # fmt: skip
    assert all(digest == sha256_text_lf(PACKAGE / name) for name, digest in files.hashes)


def test_pool_context_skips_the_cards_and_stops_at_n() -> None:
    assert pool_context(_slate(), 2) == "frontend fused=0.512\nredis fused=0.2"
    assert pool_context(_slate(), 0) == "(none)"


def test_tokens_are_estimated_from_utf8_bytes() -> None:
    assert estimate_tokens([Message("user", "abcd"), Message("user", "é")], 4) == 2  # 6 bytes / 4


def test_the_prompt_shrinks_until_it_fits_and_stops_at_k_min() -> None:
    seen: list[int] = []

    def build(k: int) -> list[Message]:
        seen.append(k)
        return [Message("user", "x" * (k * 100))]  # 25 tokens per k: fits at k = 4

    fitted = fit_prompt(build, SETTINGS)
    assert fitted is not None and (fitted.k, fitted.tokens) == (4, 100) and seen == [6, 5, 4]
    assert fit_prompt(lambda k: [Message("user", "x" * 1000)], SETTINGS) is None


def test_the_repair_turn_adds_the_output_and_the_errors() -> None:
    files = load_prompt_files("ob", "synth", [], SETTINGS)
    first = render_messages(files, "deck", "pool", SCHEMA)
    messages = repair_messages(files, first, '{"bad": 1}', ["proposals[0]: unknown service 'x'"])
    assert messages[:2] == first and [m.role for m in messages[2:]] == ["assistant", "user"]
    assert (
        messages[2].content == '{"bad": 1}' and "- proposals[0]: unknown service 'x'" in messages[3].content
    )
