"""Card settings, title and evidence table (10 §3.1 steps 1–3) on the hand-made scenario (conftest)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from veyltrace_causivra import assemble
from veyltrace_causivra.assemble import CardSettings
from veyltrace_contracts import models
from veyltrace_core.errors import ConfigError, ContractValidationError

MakeVerdict = Callable[..., models.Verdict]


@pytest.mark.parametrize(
    ("status", "with_root", "expected"),
    [
        ("CONFIRMED", True, "CONFIRMED · payment · cpu"),
        ("LIKELY", True, "LIKELY · payment · cpu"),
        ("INCONCLUSIVE", True, "INCONCLUSIVE · leading candidate payment"),
        ("INCONCLUSIVE", False, "INCONCLUSIVE · no single root cause"),
        ("NO_FAULT", False, "NO_FAULT · no fault detected in the incident window"),
    ],
)
def test_title_by_status(make_verdict: MakeVerdict, status: str, with_root: bool, expected: str) -> None:
    assert assemble.title(make_verdict(status, with_root)) == expected


def _table(
    verdict: models.Verdict, scenario: SimpleNamespace, settings: CardSettings
) -> list[dict[str, Any]]:
    return assemble.evidence_table(verdict, scenario.evidence, settings)


def test_table_takes_trial_atoms_then_holding_claims(
    make_verdict: MakeVerdict, scenario: SimpleNamespace, card_settings: CardSettings
) -> None:
    table = _table(make_verdict(), scenario, card_settings)
    assert [r["atom_id"] for r in table] == [
        scenario.a_claim,
        scenario.a_int,
        scenario.a_onset,
    ]  # (candidate, kind, id)
    labels = {r["atom_id"]: r["label"] for r in table}
    assert labels[scenario.a_int] == "payment cpu anomaly (incident)"  # family, not signal (#62 note)
    assert labels[scenario.a_onset] == "payment onset precedence over self (onset)"
    assert labels[scenario.a_claim] == "claim: payment zscore_above k=4.00, signal=cpu (incident)"
    assert scenario.a_false not in labels  # holds = false is not shown as evidence
    assert next(r for r in table if r["atom_id"] == scenario.a_int)["value"] == 9.42


def test_table_without_root_uses_three_leaders_and_the_cap(
    make_verdict: MakeVerdict, scenario: SimpleNamespace, card_settings: CardSettings
) -> None:
    table = _table(make_verdict("INCONCLUSIVE", with_root=False), scenario, card_settings)
    assert scenario.a_cart in [r["atom_id"] for r in table]  # cart is ranked[1], inside ranked[0…2]
    capped = _table(make_verdict(), scenario, replace(card_settings, evidence_max=1))
    assert [r["atom_id"] for r in capped] == [scenario.a_int]  # the first trial atom survives the cap


def test_table_refuses_a_verdict_citing_unknown_atoms(
    make_verdict: MakeVerdict, card_settings: CardSettings
) -> None:
    with pytest.raises(ContractValidationError):
        assemble.evidence_table(make_verdict(), [], card_settings)


def test_settings_validation(card_settings: CardSettings) -> None:
    assert (card_settings.evidence_max, card_settings.why_not_max, card_settings.sig_digits) == (20, 3, 3)
    assert card_settings.mandatory == frozenset({"T1", "T2", "T3", "T4"})
    section: dict[str, Any] = {
        "card": {"evidence_max": 20},
        "why_not": {"max": 3},
        "format": {"sig_digits": 3},
        "labels": dict(card_settings.labels),
        "asks": dict(card_settings.asks),
    }
    del section["labels"]["silence"]
    with pytest.raises(ConfigError, match="silence"):
        assemble.settings_from(section, {"mandatory": ["T1"]})
    with pytest.raises(ConfigError):
        assemble.settings_from({**section, "card": {"evidence_max": 0}}, {"mandatory": ["T1"]})


def test_table_atoms_take_display_fields_from_the_table_and_the_rest_from_the_row(
    make_verdict: MakeVerdict, scenario: SimpleNamespace, card_settings: CardSettings
) -> None:
    table = _table(make_verdict(), scenario, card_settings)
    atoms = assemble.table_atoms(table, scenario.evidence)
    assert list(atoms) == [r["atom_id"] for r in table]  # one per table row, in table order
    a = atoms[scenario.a_int]
    assert (a.atom_id, a.label, a.value, a.unit) == (
        scenario.a_int,
        "payment cpu anomaly (incident)",
        9.42,
        "z",
    )
    assert (a.candidate, a.window) == ("payment", "incident")  # from the evidence row


def test_fill_context_copies_the_verdict(
    make_verdict: MakeVerdict, scenario: SimpleNamespace, card_settings: CardSettings
) -> None:
    verdict = make_verdict()
    table = assemble.table_atoms(_table(verdict, scenario, card_settings), scenario.evidence)
    ctx = assemble.fill_context(verdict, table, scenario.nodes, None, card_settings.sig_digits)
    assert (ctx.status, ctx.root_service) == ("LIKELY", "payment")
    assert ctx.root_fields == {
        "component": "payment-1",
        "fault_class": "cpu",
        "indicator": "cpu",
        "mode": "resource",
    }
    assert ctx.runner_up is not None and (ctx.runner_up.service, ctx.runner_up.fault_class) == (
        "cart",
        "delay",
    )
    assert (ctx.conf_level, ctx.conf_set_size, ctx.conf_margin) == (
        verdict.confidence.level,
        verdict.confidence.set_size,
        verdict.confidence.margin,
    )
    assert ctx.table is table and ctx.nodes == frozenset(scenario.nodes) and ctx.onset_ns is None
    no_component = verdict.model_copy(
        update={"root": verdict.root.model_copy(update={"component": None}) if verdict.root else None}
    )
    assert assemble.fill_context(no_component, table, [], None, 3).root_fields["component"] == "payment"
    alone = verdict.model_copy(update={"ranked": verdict.ranked[:1]})
    assert assemble.fill_context(alone, table, [], None, 3).runner_up is None  # {RUNNER_UP} needs ranked[1]
    no_root = assemble.fill_context(make_verdict("NO_FAULT", False), {}, [], None, 3)
    assert no_root.root_service is None and no_root.root_fields == {}


def test_settings_need_every_ask_template(card_settings: CardSettings) -> None:
    section: dict[str, Any] = {
        "card": {"evidence_max": 20},
        "why_not": {"max": 3},
        "format": {"sig_digits": 3},
        "labels": dict(card_settings.labels),
        "asks": {k: v for k, v in card_settings.asks.items() if k != "telemetry"},
    }
    with pytest.raises(ConfigError, match="telemetry"):
        assemble.settings_from(section, {"mandatory": ["T1"]})
    with pytest.raises(ConfigError, match="mandatory"):
        assemble.settings_from({**section, "asks": dict(card_settings.asks)}, {"mandatory": "T1"})
