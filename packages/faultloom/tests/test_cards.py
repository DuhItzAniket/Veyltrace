"""`evidence_cards` (06 §3.7, §7) on the hand-made cpu-hog case: content, determinism and budget."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from veyltrace_contracts import models
from veyltrace_core import io
from veyltrace_core.hashing import sha256_json
from veyltrace_core.testing import make_context
from veyltrace_core.testing.fixtures import repo_root
from veyltrace_faultloom.cards import deck_dict, evidence_cards


@pytest.fixture
def slate(cpu_hog: tuple[Any, Any]) -> models.Slate:
    ctx = cpu_hog[0]
    example = json.loads((repo_root() / "contracts/examples/slate.example.json").read_text("utf-8"))
    template = example["candidates"][0]
    services = ("checkout", "frontend", "payment")
    candidates = [
        {**template, "rank": i + 1, "service": s, "component": None} for i, s in enumerate(services)
    ]
    scores = [{"service": s, "fused_score": 0.1 - i / 100} for i, s in enumerate((*services, "redis"))]
    data = {**example, "case_id": ctx.case_id, "k": 3, "candidates": candidates, "all_scores": scores}
    io.write("slate", data, ctx.run_dir)
    return io.read_model("slate", ctx.run_dir, models.Slate)


def _ctx(run_dir: Path, **overrides: Any) -> Any:
    # Relentra calls the cards with its own context; the faultloom section comes from the lock.
    return make_context(
        "relentra", run_dir, dataset="handmade", overrides={f"faultloom.{k}": v for k, v in overrides.items()}
    )


def test_cards_show_the_priority_atoms_path_change_and_against_facts(
    cpu_hog: tuple[Any, Any], slate: models.Slate
) -> None:
    deck = evidence_cards(slate, ctx=_ctx(cpu_hog[0].run_dir))
    checkout, frontend, payment = deck.candidates
    assert [a["kind"] for a in checkout["atoms"]] == [
        "internal_anomaly",
        "external_anomaly",
        "onset_precedence",
        "change_proximity",
        "self_time_share",
        "spectrum",
    ]  # k_default = 6, in the 06 §3.7 priority order
    assert checkout["path"] == ["checkout", "frontend"]
    assert checkout["change"] == {"event_kind": "deploy", "ms_before_onset": 60_000.0}
    assert checkout["against"] == []
    assert frontend["against"] == ["callee checkout has internal z=9.1 >= 0"]  # frontend is a victim
    assert payment["against"] == ["precedes only 0 of its anomalous dependents"]
    line = next(x for x in deck.text.splitlines() if " internal_anomaly cpu/metrics " in x)
    assert line.strip().endswith("z=9.1") and line.strip().split()[0] == checkout["atoms"][0]["atom_id"]
    assert deck.case["t_onset_s"] == 300.0 and deck.case["sources"] == ["events", "logs", "metrics", "traces"]
    assert [o["service"] for o in deck.case["onsets"]] == ["checkout", "frontend", "payment"]
    assert (
        len(deck.library) == 10 and "check zscore_above(signal:signal, k:float[1,100]) supports" in deck.text
    )


def test_cards_are_deterministic_and_hashed(cpu_hog: tuple[Any, Any], slate: models.Slate) -> None:
    first = evidence_cards(slate, ctx=_ctx(cpu_hog[0].run_dir))
    second = evidence_cards(slate, ctx=_ctx(cpu_hog[0].run_dir))
    assert first.text == second.text and first.deck_sha256 == second.deck_sha256
    assert first.deck_sha256 == sha256_json(deck_dict(first))
    assert first.approx_tokens == math.ceil(len(first.text.encode("utf-8")) / 4)  # cards.bytes_per_token
    assert not first.truncated


def test_order_sets_the_card_order_and_must_be_a_permutation(
    cpu_hog: tuple[Any, Any], slate: models.Slate
) -> None:
    ctx = _ctx(cpu_hog[0].run_dir)
    deck = evidence_cards(slate, ctx=ctx, order=["payment", "checkout", "frontend"])
    assert [c["service"] for c in deck.candidates] == ["payment", "checkout", "frontend"]
    with pytest.raises(ValueError, match="permutation"):
        evidence_cards(slate, ctx=ctx, order=["payment", "checkout"])


def test_budget_shrinks_k_then_onsets_then_drops_cards(cpu_hog: tuple[Any, Any], slate: models.Slate) -> None:
    run_dir = cpu_hog[0].run_dir
    small = evidence_cards(slate, 2, ctx=_ctx(run_dir))
    fitted = evidence_cards(slate, ctx=_ctx(run_dir, **{"cards.max_tokens": small.approx_tokens}))
    assert fitted.text == small.text and not fitted.truncated  # k 6 -> 2, nothing dropped
    assert max(len(c["atoms"]) for c in fitted.candidates) == 2 and fitted.case["onsets"]
    tiny = evidence_cards(slate, ctx=_ctx(run_dir, **{"cards.max_tokens": 1}))
    assert tiny.truncated and tiny.candidates == () and tiny.case["onsets"] == []
    assert tiny.text.startswith("case: ")  # the case header is never cut
