"""Timeline, path, why-not and asks (10 §3.1 steps 4–7) on the hand-made scenario (conftest).

A deploy change on payment lies inside the windows; a config change on redis (not in the decision
pool) and a restart before the baseline window do not reach the timeline.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from veyltrace_causivra import assemble, sections
from veyltrace_causivra.assemble import CardSettings
from veyltrace_contracts import models

MakeVerdict = Callable[..., models.Verdict]
T0 = 1_767_225_600_000_000_000
S = 1_000_000_000
CHANGE_ID = "C1234567890"

ALERT = {
    "schema_version": "0.1.0",
    "protocol": "oracle",
    "t_alert_ns": T0 + 1320 * S,
    "shift_ns": 0,
    "detector": None,
    "windows": {
        "baseline": [T0 + 120 * S, T0 + 1200 * S],
        "incident": [T0 + 1200 * S, T0 + 1800 * S],
    },
    "clamped": False,
}

ONSETS = {
    "schema_version": "0.1.0",
    "t_onset_ns": T0 + 1230 * S,
    "method": "second_external",
    "slo_breach_ns": None,
    "entry_services": ["frontend"],
    "per_service": [
        {
            "service": "cart",
            "external_onset_ns": None,
            "external_onset_source": None,
            "internal_onset_ns": None,
            "internal_onset_source": None,
            "silent": False,
        },
        {
            "service": "payment",
            "external_onset_ns": T0 + 1230 * S,
            "external_onset_source": "traces",
            "internal_onset_ns": T0 + 1200 * S,
            "internal_onset_source": "metrics",
            "silent": False,
        },
    ],
}

CHANGES = [
    {"change_id": CHANGE_ID, "t_ns": T0 + 1100 * S, "entity": "payment", "kind": "deploy"},
    {"change_id": "C0000000002", "t_ns": T0 + 1150 * S, "entity": "redis", "kind": "config"},
    {
        "change_id": "C0000000003",
        "t_ns": T0 + 60 * S,
        "entity": "payment",
        "kind": "restart",
    },  # before the windows
]

PATHS = [
    {"candidate": "payment", "path_rank": 2, "nodes": ["payment", "frontend"], "anomalous_fraction": 0.5},
    {
        "candidate": "payment",
        "path_rank": 1,
        "nodes": ["payment", "checkout", "frontend"],
        "anomalous_fraction": 1.0,
    },
]


@pytest.fixture
def alert() -> models.Alert:
    return models.Alert.model_validate(ALERT)


@pytest.fixture
def onsets() -> models.Onsets:
    return models.Onsets.model_validate(ONSETS)


def _table(
    verdict: models.Verdict, scenario: SimpleNamespace, settings: CardSettings
) -> list[dict[str, Any]]:
    return assemble.evidence_table(verdict, scenario.evidence, settings)


def test_timeline(
    make_verdict: MakeVerdict, scenario: SimpleNamespace, alert: models.Alert, onsets: models.Onsets
) -> None:
    entries = sections.timeline(make_verdict(), alert, onsets, CHANGES, scenario.evidence)
    t0, s = T0, S
    assert [(e["t_ns"], e["label"], e["cites"]) for e in entries] == [
        (t0 + 1100 * s, "payment deploy change", [scenario.a_change]),
        (t0 + 1200 * s, "payment internal onset", [scenario.a_onset]),
        (t0 + 1230 * s, "incident onset", []),
        (t0 + 1230 * s, "payment external onset", [scenario.a_onset]),
        (t0 + 1320 * s, "alert (oracle)", []),
    ]


def test_timeline_without_onsets_holds_the_alert_only(make_verdict: MakeVerdict, alert: models.Alert) -> None:
    clamped = alert.model_copy(update={"clamped": True})
    entries = sections.timeline(make_verdict(), clamped, None, [], [])
    assert entries == [{"t_ns": alert.t_alert_ns, "label": "alert (oracle, windows clamped)", "cites": []}]


def test_path(make_verdict: MakeVerdict, scenario: SimpleNamespace) -> None:
    assert sections.path(make_verdict(), PATHS) == ["payment", "checkout", "frontend"]
    assert sections.path(make_verdict("INCONCLUSIVE", with_root=False), PATHS) == []
    assert sections.path(make_verdict(), []) == []


def _ctx(
    verdict: models.Verdict, scenario: SimpleNamespace, settings: CardSettings, onsets: models.Onsets | None
) -> Any:
    table = assemble.table_atoms(_table(verdict, scenario, settings), scenario.evidence)
    return assemble.fill_context(verdict, table, scenario.nodes, onsets, settings.sig_digits)


def test_why_not(
    make_verdict: MakeVerdict, scenario: SimpleNamespace, card_settings: CardSettings, onsets: models.Onsets
) -> None:
    verdict = make_verdict()
    rows = sections.why_not(verdict, _ctx(verdict, scenario, card_settings, onsets), card_settings)
    assert [(r["service"], r["text"]) for r in rows] == [
        ("cart", "cart started after its dependents (failed T2, precedence)."),
        (
            "checkout",
            "checkout failed no trial, but some of its mandatory trials were untestable, "
            "and its verified score did not exceed the leader's.",
        ),
        (
            "frontend",
            "frontend passed the mandatory trials but its verified score did not exceed the leader's.",
        ),
    ]
    assert rows[0]["cites"] == [scenario.a_cart]  # cart's failing T2 atom is in the table (D2)
    assert rows[1]["cites"] == rows[2]["cites"] == []  # no failed trial and no table atom of their own


def test_why_not_respects_max_and_no_fault(
    make_verdict: MakeVerdict, scenario: SimpleNamespace, card_settings: CardSettings, onsets: models.Onsets
) -> None:
    verdict = make_verdict()
    one = replace(card_settings, why_not_max=1)
    assert [r["service"] for r in sections.why_not(verdict, _ctx(verdict, scenario, one, onsets), one)] == [
        "cart"
    ]
    no_fault = make_verdict("NO_FAULT")
    assert sections.why_not(no_fault, _ctx(no_fault, scenario, card_settings, onsets), card_settings) == []


def test_why_not_cites_the_failing_trial_when_its_atom_is_in_the_table(
    make_verdict: MakeVerdict, scenario: SimpleNamespace, card_settings: CardSettings, onsets: models.Onsets
) -> None:
    verdict = make_verdict("INCONCLUSIVE", with_root=False)  # three leaders: cart's T2 atom is in the table
    rows = sections.why_not(verdict, _ctx(verdict, scenario, card_settings, onsets), card_settings)
    assert rows[0]["cites"] == [scenario.a_cart]


def test_spec_lists_every_why_not_template() -> None:
    spec = (Path(__file__).parents[3] / "docs/engines/10-causivra.md").read_text(encoding="utf-8")
    templates = [*sections.WHY_NOT_FAILED.values(), sections.WHY_NOT_PASSED, sections.WHY_NOT_UNTESTED]
    assert [t for t in templates if f"| {t} |" not in spec] == []  # 10 §3.1 step 6 table


def test_asks(make_verdict: MakeVerdict, card_settings: CardSettings) -> None:
    assert sections.asks(make_verdict(), card_settings) == [
        {"text": "telemetry: events — T6 untestable without events"}
    ]
