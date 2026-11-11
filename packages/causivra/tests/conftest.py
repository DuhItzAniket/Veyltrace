"""A hand-made incident for the card tests: the synth fixtures are still stub verdicts (INCONCLUSIVE,
no atoms), so every other status is exercised on this scenario.

payment is the leader (cpu, resource): T1–T4 pass with an internal-anomaly and an onset atom, and a
holding claim check. cart failed T2, checkout has a mandatory trial untestable, frontend passed
every mandatory trial. The alert, onsets, changes and paths of the scenario live in test_sections.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, get_args

import pytest

from veyltrace_causivra.assemble import CardSettings, settings_from
from veyltrace_contracts import models
from veyltrace_core.config import resolve_config
from veyltrace_core.testing import repo_root

A_INT, A_ONSET, A_CART, A_CLAIM, A_CHANGE, A_FALSE = (
    "Ea4217049f6",
    "E18da98df6a",
    "Ee7cb346376",
    "E7148e3dd27",
    "Ec0ffee0001",
    "Ebad0000001",
)
CHANGE_ID = "C1234567890"
T0 = 1_767_225_600_000_000_000
S = 1_000_000_000


def _trial(
    tid: str, result: str, atoms: list[str] | None = None, reason: str | None = None
) -> dict[str, Any]:
    if result != "pass" and reason is None:
        reason = "dependent_earlier" if result == "fail" else "no_onset"
    return {"id": tid, "result": result, "reason": reason, "atoms": atoms or []}


def _ranked(rank: int, service: str, trials: list[dict[str, Any]], v: float) -> dict[str, Any]:
    return {
        "rank": rank,
        "service": service,
        "component": None,
        "indicator": "cpu" if service == "payment" else "latency",
        "fault_class": "cpu" if service == "payment" else "delay",
        "v": v,
        "nonconformity": 0.0,
        "fused_score": 0.5,
        "origin": "slate",
        "trials": trials,
    }


def verdict_dict(status: str = "LIKELY", with_root: bool = True) -> dict[str, Any]:
    path = repo_root() / "contracts" / "examples" / "verdict.example.json"
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    passed = [_trial(t, "pass") for t in ("T3", "T4")]
    raw["ranked"] = [
        _ranked(1, "payment", [_trial("T1", "pass", [A_INT]), _trial("T2", "pass", [A_ONSET]), *passed], 1.2),
        _ranked(2, "cart", [_trial("T1", "pass"), _trial("T2", "fail", [A_CART]), *passed], 0.8),
        _ranked(3, "checkout", [_trial("T1", "pass"), _trial("T2", "untestable"), *passed], 0.7),
        _ranked(4, "frontend", [_trial(t, "pass") for t in ("T1", "T2", "T3", "T4")], 0.6),
    ]
    raw["status"] = status
    raw["root"] = (
        {
            "service": "payment",
            "component": "payment-1",
            "indicator": "cpu",
            "fault_class": "cpu",
            "mode": "resource",
        }
        if with_root and status != "NO_FAULT"
        else None
    )
    raw["candidate_set"] = [] if status == "NO_FAULT" else raw["candidate_set"]
    if status == "NO_FAULT":
        raw["confidence"] = {**raw["confidence"], "level": "none", "set_size": 0}
    return raw


def atom(
    atom_id: str, kind: str, candidate: str, args: dict[str, Any], value: float, **extra: Any
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "atom_id": atom_id,
        "candidate": candidate,
        "component": None,
        "kind": kind,
        "predicate": None,
        "args_json": json.dumps(args, sort_keys=True, separators=(",", ":")),
        "value": value,
        "unit": None,
        "window": args.get("window", "incident"),
        "refs": [],
        "origin": "engine",
        "holds": None,
        "producer": "faultloom@0",
    }
    row.update(extra)
    return row


EVIDENCE = [
    atom(
        A_INT,
        "internal_anomaly",
        "payment",
        {"detector": "robust_z", "family": "cpu", "source": "metrics", "window": "incident"},
        9.42,
        unit="z",
    ),
    atom(A_ONSET, "onset_precedence", "payment", {"scope": "self", "window": "onset"}, 1.0),
    atom(A_CART, "onset_precedence", "cart", {"scope": "dependents", "window": "onset"}, 0.0),
    atom(
        A_CLAIM,
        "claim_check",
        "payment",
        {"k": 4.0, "signal": "cpu"},
        9.42,
        origin="claim_check",
        holds=True,
        predicate="zscore_above",
        unit="z",
    ),
    atom(
        A_FALSE,
        "claim_check",
        "payment",
        {"k": 50.0, "signal": "cpu"},
        9.42,
        origin="claim_check",
        holds=False,
        predicate="zscore_above",
    ),
    atom(
        A_CHANGE,
        "change_proximity",
        "payment",
        {"change_id": CHANGE_ID, "event_kind": "deploy", "window": "onset"},
        0.8,
    ),
]

NODES = ["cart", "checkout", "frontend", "payment"]


@pytest.fixture
def make_verdict() -> Callable[..., models.Verdict]:
    def make(status: str = "LIKELY", with_root: bool = True) -> models.Verdict:
        return models.Verdict.model_validate(verdict_dict(status, with_root))

    return make


#: The card section the tests use: the label templates under test, a generic one for every other
#: kind (the repo's config/causivra.yaml arrives with the package-owned card step, #20).
CARD_SECTION: dict[str, Any] = {
    "card": {"evidence_max": 20},
    "why_not": {"max": 3},
    "format": {"sig_digits": 3},
    "labels": {
        **{
            kind: "{candidate} " + kind.replace("_", " ") + " ({window})"
            for kind in get_args(models.AtomKind)
        },
        "internal_anomaly": "{candidate} {family} anomaly ({window})",
        "onset_precedence": "{candidate} onset precedence over {scope} ({window})",
        "claim_check": "claim: {candidate} {predicate} {args} ({window})",
    },
    "asks": {kind: "{kind}: {target} — {why}" for kind in get_args(models.AskKind)},
}


@pytest.fixture
def card_settings() -> CardSettings:
    causentra = resolve_config({}, config_dir=repo_root() / "config", ai_mode="off").engine("causentra")
    return settings_from(CARD_SECTION, causentra)


@pytest.fixture
def scenario() -> SimpleNamespace:
    """The scenario's rows and ids (test modules cannot import conftest under importlib mode)."""
    return SimpleNamespace(
        evidence=EVIDENCE,
        nodes=NODES,
        change_id=CHANGE_ID,
        a_int=A_INT,
        a_onset=A_ONSET,
        a_cart=A_CART,
        a_claim=A_CLAIM,
        a_change=A_CHANGE,
        a_false=A_FALSE,
        t0=T0,
        s=S,
    )
