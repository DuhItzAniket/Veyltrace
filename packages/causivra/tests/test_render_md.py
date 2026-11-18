"""card.md rendering (10 §3.7): every section, empty sets shown as empty, no render-time state."""

from __future__ import annotations

from typing import Any

from veyltrace_causivra.render_md import render_card

CARD: dict[str, Any] = {
    "title": "LIKELY · payment · cpu",
    "status": "LIKELY",
    "confidence": {"level": "medium", "margin": 0.274390244, "alpha": 0.1, "q_hat": 0.29, "set_size": 2},
    "candidate_set": [
        {"service": "payment", "component": "payment-1"},
        {"service": "cart", "component": None},
    ],
    "summary": [{"text": "payment is the most likely root cause.", "cites": ["Ea4217049f6"]}],
    "timeline": [{"t_ns": 1_767_226_830_000_000_000, "label": "incident onset", "cites": []}],
    "path": ["payment", "checkout", "frontend"],
    "evidence_table": [
        {"atom_id": "Ea4217049f6", "label": "payment a|b anomaly (incident)", "value": 9.4213, "unit": "z"}
    ],
    "why_not": [
        {"service": "cart", "text": "cart started after its dependents (failed T2, precedence).", "cites": []}
    ],
    "asks": [{"text": "telemetry: events — T6 untestable without events"}],
    "next_steps": [{"text": "Compare payment with its replicas.", "playbook_id": "PB-CPU-01"}],
    "narrator": {"path": "template", "model": None, "attempts": 0, "checker_failures": 0},
    "verdict_hash": "a" * 64,
    "card_hash": "b" * 64,
}


def test_sections_in_order() -> None:
    text = render_card(CARD, 3)
    heads = [line for line in text.splitlines() if line.startswith("#")]
    assert heads == [
        "# LIKELY · payment · cpu",
        "## Summary",
        "## Candidate set",
        "## Evidence",
        "## Timeline",
        "## Path",
        "## Why not",
        "## Asks",
        "## Next steps",
    ]
    assert "**LIKELY** · confidence: medium · candidate set size: 2 · margin: 0.27" in text
    assert "- payment is the most likely root cause. (cites: Ea4217049f6)" in text
    assert "- payment (payment-1)\n- cart\n" in text
    assert "| Ea4217049f6 | payment a\\|b anomaly (incident) | 9.42 | z |" in text
    assert "- 00:20:30 UTC — incident onset" in text
    assert "payment → checkout → frontend" in text
    assert "- **cart**: cart started after its dependents (failed T2, precedence)." in text
    assert "- Compare payment with its replicas. (PB-CPU-01)" in text
    assert "prose: template" in text
    assert text.endswith("replay: `uv run veyltrace replay <run dir>/receipt.json`\n")
    assert "%" not in text and "probability" not in text


def test_empty_card_says_empty_and_none() -> None:
    empty = {
        **CARD,
        "candidate_set": [],
        "evidence_table": [],
        "path": [],
        "why_not": [],
        "asks": [],
        "timeline": [],
    }
    text = render_card(empty, 3)
    assert "## Candidate set\n\n- empty\n" in text
    assert "## Evidence\n\n- none\n" in text and "## Path\n\nnone\n" in text
    assert "## Why not\n\n- none\n" in text


def test_llm_narrator_line_and_stability() -> None:
    llm = {**CARD, "narrator": {"path": "llm", "model": "qwen3.5:9b", "attempts": 1, "checker_failures": 0}}
    assert "prose: LLM qwen3.5:9b, checked" in render_card(llm, 3)
    assert render_card(CARD, 3) == render_card(CARD, 3)
