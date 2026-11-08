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
