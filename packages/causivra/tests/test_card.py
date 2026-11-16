"""Playbooks, template prose and the assembled card (10 §3.1 steps 8–11, §3.5, §3.6; 10 §7 unit row)."""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_args

import pytest

from veyltrace_causivra import assemble, sections
from veyltrace_causivra.assemble import CardSettings
from veyltrace_causivra.card import build_card
from veyltrace_causivra.playbooks import load_playbooks, next_steps, select
from veyltrace_causivra.prose import SENTENCES, strongest, summary
from veyltrace_contracts import models
from veyltrace_core.errors import ConfigError
from veyltrace_core.hashing import self_hash
from veyltrace_core.schemacheck import validate_json_schema

MakeVerdict = Callable[..., models.Verdict]
T0 = 1_767_225_600_000_000_000
S = 1_000_000_000
ALERT = models.Alert.model_validate(
    {
        "schema_version": "0.1.0",
        "protocol": "oracle",
        "t_alert_ns": T0 + 1320 * S,
        "shift_ns": 0,
        "detector": None,
        "windows": {"baseline": [T0 + 120 * S, T0 + 1200 * S], "incident": [T0 + 1200 * S, T0 + 1800 * S]},
        "clamped": False,
    }
)
#: Light stand-in for checker rules C4 (digits) and C5 (%) until the X-09 checker: outside
#: placeholders, digits only inside trial ids T1…T10.
_TRIAL_ID = re.compile(r"(?<![A-Za-z0-9])T(?:10|[1-9])(?![0-9])")
_RAW_DIGIT = re.compile(r"\d|%")


def _with(verdict: models.Verdict, **root: Any) -> models.Verdict:
    assert verdict.root is not None
    return verdict.model_copy(update={"root": verdict.root.model_copy(update=root)})


def test_playbooks_file_is_valid_and_covers_every_fault_class() -> None:
    playbooks = load_playbooks()
    covered = {c for p in playbooks.values() for c in p.fault_classes}
    assert covered == set(get_args(models.FaultClass))  # 02 §6.10: a playbook per fault class
    owners = [c for p in playbooks.values() for c in p.fault_classes]
    assert len(owners) == len(set(owners))  # no class is claimed twice


@pytest.mark.parametrize("entry", ["PB-CPU-01", ["PB-CPU-01"], 7])
def test_a_playbook_entry_that_is_not_a_mapping_is_a_config_error(tmp_path: Path, entry: object) -> None:
    path = tmp_path / "playbooks.yaml"
    path.write_text(json.dumps({"playbooks": [entry]}), encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_playbooks(path)


@pytest.mark.parametrize("fault_class", sorted(get_args(models.FaultClass)))
def test_every_fault_class_selects_its_own_playbook(make_verdict: MakeVerdict, fault_class: str) -> None:
    playbooks = load_playbooks()
    (pb_id,) = select(_with(make_verdict("LIKELY", True), fault_class=fault_class), playbooks)
    assert fault_class in playbooks[pb_id].fault_classes


@pytest.mark.parametrize(
    ("status", "with_root", "changes", "expected"),
    [
        ("NO_FAULT", False, {}, ["PB-NOFAULT-01"]),
        ("INCONCLUSIVE", True, {}, ["PB-INCONC-01"]),
        ("INCONCLUSIVE", False, {}, ["PB-INCONC-01"]),
        ("LIKELY", True, {}, ["PB-CPU-01"]),
        ("CONFIRMED", True, {"fault_class": "delay"}, ["PB-DELAY-01"]),
        ("CONFIRMED", True, {"fault_class": "socket"}, ["PB-SOCK-01"]),
        ("CONFIRMED", True, {"fault_class": "availability"}, ["PB-AVAIL-01"]),
        ("LIKELY", True, {"fault_class": "unknown"}, ["PB-UNK-01"]),
        ("LIKELY", True, {"mode": "change", "fault_class": "config"}, ["PB-CONFIG-01", "PB-CHANGE-01"]),
    ],
)
def test_playbook_selection(
    make_verdict: MakeVerdict, status: str, with_root: bool, changes: dict[str, str], expected: list[str]
) -> None:
    verdict = make_verdict(status, with_root)
    if changes:
        verdict = _with(verdict, **changes)
    assert select(verdict, load_playbooks()) == expected


def test_a_root_that_passed_t6_adds_the_change_playbook(make_verdict: MakeVerdict) -> None:
    verdict = make_verdict()
    leader = verdict.ranked[0]
    t6 = models.VerdictRankedTrials(id="T6", result="pass", reason=None, atoms=[])
    ranked = [leader.model_copy(update={"trials": [*leader.trials, t6]}), *verdict.ranked[1:]]
    assert select(verdict.model_copy(update={"ranked": ranked}), load_playbooks()) == [
        "PB-CPU-01",
        "PB-CHANGE-01",
    ]


def _ctx(verdict: models.Verdict, scenario: SimpleNamespace, settings: CardSettings) -> Any:
    table = assemble.evidence_table(verdict, scenario.evidence, settings)
    return assemble.fill_context(
        verdict, assemble.table_atoms(table, scenario.evidence), scenario.nodes, None, 3
    )


def test_next_steps_fill_the_root(
    make_verdict: MakeVerdict, scenario: SimpleNamespace, card_settings: CardSettings
) -> None:
    verdict = make_verdict()
    steps = next_steps(verdict, _ctx(verdict, scenario, card_settings), load_playbooks())
    assert steps[0] == {
        "text": "Compare CPU use with the limit and check throttling on payment.",
        "playbook_id": "PB-CPU-01",
    }
    assert all("{" not in s["text"] for s in steps)


_TELEMETRY = "Collect the telemetry named in the asks."
_TRIAL = "Check the trials named in the asks (failed or untestable)."
_CONTEXT = "Inspect the named service, or the ranked slate, around the incident onset."
_INCONC_TAIL = [
    "Inspect each member of the candidate set.",
    "Run the diagnosis again once the asks are answered.",
]


def _inconclusive_steps(
    make_verdict: MakeVerdict,
    scenario: SimpleNamespace,
    settings: CardSettings,
    asks: list[tuple[models.AskKind, str]],
) -> list[str]:
    verdict = make_verdict("INCONCLUSIVE", False).model_copy(
        update={"asks": [models.VerdictAsks(kind=k, target=t, why="why") for k, t in asks]}
    )
    steps = next_steps(verdict, _ctx(verdict, scenario, settings), load_playbooks())
    assert {s["playbook_id"] for s in steps} == {"PB-INCONC-01"}
    return [s["text"] for s in steps]


def test_inconclusive_first_steps_follow_each_ask_kind_in_ask_order(
    make_verdict: MakeVerdict, scenario: SimpleNamespace, card_settings: CardSettings
) -> None:
    # 10 §3.6: one line per ask kind present, in first-occurrence order; a repeated kind adds none.
    asks: list[tuple[models.AskKind, str]] = [
        ("context", "slate"),
        ("telemetry", "events"),
        ("trial", "T6"),
        ("telemetry", "logs"),
    ]
    texts = _inconclusive_steps(make_verdict, scenario, card_settings, asks)
    assert texts == [_CONTEXT, _TELEMETRY, _TRIAL, *_INCONC_TAIL]


def test_a_context_only_inconclusive_shows_only_the_context_step(
    make_verdict: MakeVerdict, scenario: SimpleNamespace, card_settings: CardSettings
) -> None:
    # Asks rows 6b and 7 (09 §3.11, #204) are context asks: no telemetry or trial advice.
    texts = _inconclusive_steps(make_verdict, scenario, card_settings, [("context", "slate")])
    assert texts == [_CONTEXT, *_INCONC_TAIL]


@pytest.mark.parametrize(
    "steps",
    [
        [{"ask_kind": "logs", "text": "Collect the logs."}],
        [{"ask_kind": "trial"}],
        [{"ask_kind": "trial", "text": "Check the trials.", "extra": "x"}],
        [{"ask_kind": "trial", "text": "Check the trials."}, {"ask_kind": "trial", "text": "Again."}],
    ],
)
def test_a_bad_ask_tied_step_is_a_config_error(tmp_path: Path, steps: list[object]) -> None:
    path = tmp_path / "playbooks.yaml"
    path.write_text(
        json.dumps({"playbooks": [{"id": "PB-INCONC-01", "fault_classes": [], "steps": steps}]}),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"ask.kind"):
        load_playbooks(path)


def _kinds(scenario: SimpleNamespace) -> dict[str, str]:
    return {r["atom_id"]: r["kind"] for r in scenario.evidence}


@pytest.mark.parametrize(
    ("status", "with_root", "texts"),
    [
        (
            "LIKELY",
            True,
            [
                "payment is the most likely root cause; the candidate set has 2 services.",
                "Its strongest internal signal was payment cpu anomaly (incident) at 9.42 z.",
                "Confidence is medium; its verified score leads cart by a relative margin of 0.27.",
            ],
        ),
        (
            "INCONCLUSIVE",
            False,
            [
                "No single root cause could be established; the candidate set has 2 services.",
                "The asks below list the telemetry or trials that would settle it.",
            ],
        ),
        (
            "NO_FAULT",
            False,
            [
                "No anomaly above threshold was found at the entry service or inside any service.",
                "The candidate set is empty and no root cause is named.",
            ],
        ),
    ],
)
def test_template_summary(
    make_verdict: MakeVerdict,
    scenario: SimpleNamespace,
    card_settings: CardSettings,
    status: str,
    with_root: bool,
    texts: list[str],
) -> None:
    verdict = make_verdict(status, with_root)
    rows = summary(verdict, _ctx(verdict, scenario, card_settings), _kinds(scenario))
    assert [r["text"] for r in rows] == texts
    if status == "LIKELY":
        assert rows[1]["cites"] == [scenario.a_int]
        assert all(rows[i]["cites"] for i in (0, 2))
    if status == "NO_FAULT":
        assert all(r["cites"] == [] for r in rows)


def test_signal_sentence_is_skipped_without_an_internal_atom(
    make_verdict: MakeVerdict, scenario: SimpleNamespace, card_settings: CardSettings
) -> None:
    verdict = make_verdict("CONFIRMED")
    rows = summary(verdict, _ctx(verdict, scenario, card_settings), {})
    assert [r["text"][:16] for r in rows] == ["payment is the o", "Confidence is hi"]


def _with_internal(ctx: Any, atom_id: str, value: float, label: str, scenario: SimpleNamespace) -> Any:
    """ctx with a second internal atom on the root, placed first in table order."""
    extra = dataclasses.replace(ctx.table[scenario.a_int], atom_id=atom_id, value=value, label=label)
    return dataclasses.replace(ctx, table={atom_id: extra, **ctx.table})


def test_signal_sentence_names_the_strongest_internal_atom(
    make_verdict: MakeVerdict, scenario: SimpleNamespace, card_settings: CardSettings
) -> None:
    verdict = make_verdict("LIKELY")
    weak = "E0000000001"
    ctx = _with_internal(
        _ctx(verdict, scenario, card_settings), weak, 2.5, "payment memory anomaly (incident)", scenario
    )
    assert next(iter(ctx.table)) == weak  # first in table order, but weaker than A_INT (9.42)
    kinds = {**_kinds(scenario), weak: "internal_anomaly"}
    rows = summary(verdict, ctx, kinds)
    assert rows[1] == {
        "text": "Its strongest internal signal was payment cpu anomaly (incident) at 9.42 z.",
        "cites": [scenario.a_int],
    }


def test_strongest_breaks_ties_by_atom_id(
    make_verdict: MakeVerdict, scenario: SimpleNamespace, card_settings: CardSettings
) -> None:
    verdict = make_verdict("LIKELY")
    tie = "Effffffffff"  # sorts after A_INT, so A_INT wins the tie
    ctx = _with_internal(_ctx(verdict, scenario, card_settings), tie, 9.42, "payment cpu anomaly", scenario)
    assert strongest([tie, scenario.a_int], ctx) == scenario.a_int
    low = "E0000000001"
    ctx = _with_internal(_ctx(verdict, scenario, card_settings), low, 9.42, "payment cpu anomaly", scenario)
    assert strongest([scenario.a_int, low], ctx) == low
    assert strongest([], ctx) is None


def test_every_template_is_free_of_raw_numbers() -> None:
    texts = [t for sentences in SENTENCES.values() for t in sentences]
    texts += [*sections.WHY_NOT_FAILED.values(), sections.WHY_NOT_PASSED, sections.WHY_NOT_UNTESTED]
    texts += [s for p in load_playbooks().values() for s in p.steps]
    for text in texts:
        outside = _TRIAL_ID.sub("", re.sub(r"\{[^{}]*\}", "", text))
        assert not _RAW_DIGIT.search(outside), text
        assert outside.rstrip().endswith("."), text


def _card(verdict: models.Verdict, scenario: SimpleNamespace, settings: CardSettings) -> dict[str, Any]:
    return build_card(
        verdict=verdict,
        evidence=scenario.evidence,
        alert=ALERT,
        onsets=None,
        changes=[],
        paths=[],
        nodes=scenario.nodes,
        settings=settings,
        playbooks=load_playbooks(),
    )


@pytest.mark.parametrize(
    ("status", "with_root"),
    [("CONFIRMED", True), ("LIKELY", True), ("INCONCLUSIVE", False), ("NO_FAULT", False)],
)
def test_card_is_valid_copies_the_verdict_and_hashes_itself(
    make_verdict: MakeVerdict,
    scenario: SimpleNamespace,
    card_settings: CardSettings,
    status: str,
    with_root: bool,
) -> None:
    verdict = make_verdict(status, with_root)
    card = _card(verdict, scenario, card_settings)
    validate_json_schema("card", card)
    v = verdict.model_dump(mode="json")
    assert (card["status"], card["root"], card["confidence"]) == (v["status"], v["root"], v["confidence"])
    assert [c["service"] for c in card["candidate_set"]] == [c["service"] for c in v["candidate_set"]]
    assert card["verdict_hash"] == verdict.verdict_hash
    assert card["case_id"] == verdict.case_id
    assert card["card_hash"] == self_hash("card", card)
    assert card["narrator"] == {"path": "template", "model": None, "attempts": 0, "checker_failures": 0}
    assert card == _card(verdict, scenario, card_settings)  # pure function of its inputs
    if status == "NO_FAULT":
        assert card["candidate_set"] == [] and card["why_not"] == []
