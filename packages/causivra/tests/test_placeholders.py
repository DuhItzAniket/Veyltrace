"""Number formatting and the placeholder grammar and filler (10 §3.3, C1–C3 of §3.4; 10 §7 unit row)."""

from __future__ import annotations

import math
import re
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_causivra.fmt import format_margin, format_number, format_time_utc
from veyltrace_causivra.placeholders import (
    FillContext,
    PlaceholderError,
    RunnerUp,
    TableAtom,
    fill,
    placeholders,
)

ATOM = "Ea4217049f6"
OTHER = "E18da98df6a"


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (None, "n/a"),
        (float("nan"), "n/a"),
        (float("inf"), "n/a"),
        (0, "0"),
        (0.0, "0"),
        (7, "7"),
        (999_999, "999999"),
        (1_234_567, "1.23e+06"),
        (9.42, "9.42"),
        (1.0, "1.00"),
        (0.274390244, "0.274"),
        (1234.5, "1230"),
        (0.0012345, "0.00123"),
        (0.0001234, "0.000123"),
        (2.675, "2.68"),  # 2.675 is 2.67499999… in binary; repr() is "2.675", rounded half-even on decimals
        (-3.14159, "-3.14"),
        (1_200_000.0, "1.2e+06"),
    ],
)
def test_format_number_table(value: Any, text: str) -> None:
    assert format_number(value, 3) == text


@given(st.floats(min_value=0.001, max_value=999_999, allow_nan=False))
def test_plain_range_never_uses_scientific_notation(x: float) -> None:
    out = format_number(x, 3)
    assert "e" not in out and out == format_number(x, 3)
    assert math.isclose(float(out), x, rel_tol=5e-3)


@given(st.floats(allow_nan=True, allow_infinity=True))
def test_format_number_is_total_and_deterministic(x: float) -> None:
    assert format_number(x, 3) == format_number(x, 3)


def test_margin_and_time() -> None:
    assert format_margin(0.274390244) == "0.27"
    assert format_margin(0.125) == "0.12"  # half-even
    assert format_margin(0.0) == "0.00"
    assert format_time_utc(1_767_226_800_000_000_000) == "00:20:00 UTC"
    assert format_time_utc(1_767_225_599_000_000_000) == "23:59:59 UTC"


def _ctx(**changes: Any) -> FillContext:
    fields: dict[str, Any] = {
        "status": "LIKELY",
        "root_service": "payment",
        "root_fields": {
            "component": "payment-1",
            "fault_class": "cpu",
            "indicator": "cpu",
            "mode": "resource",
        },
        "runner_up": RunnerUp("cart", "cpu", "latency"),
        "conf_level": "medium",
        "conf_set_size": 2,
        "conf_margin": 0.274390244,
        "table": {
            ATOM: TableAtom(ATOM, "payment cpu anomaly (incident)", 9.42, "z", "payment", "incident"),
            OTHER: TableAtom(OTHER, "payment onset before dependents (onset)", 1.0, None, "payment", "onset"),
        },
        "nodes": frozenset({"payment", "cart", "checkout", "frontend"}),
        "onset_ns": 1_767_226_830_000_000_000,
        "sig_digits": 3,
    }
    fields.update(changes)
    return FillContext(**fields)


@pytest.mark.parametrize(
    ("text", "cites", "filled"),
    [
        ("{ROOT} leads.", [], "payment leads."),
        (
            "{ROOT.component} / {ROOT.fault_class} / {ROOT.indicator} / {ROOT.mode}",
            [],
            "payment-1 / cpu / cpu / resource",
        ),
        ("{RUNNER_UP} {RUNNER_UP.fault_class} {RUNNER_UP.indicator}", [], "cart cpu latency"),
        ("{CONF.level} {CONF.set_size} {CONF.margin} {STATUS}", [], "medium 2 0.27 LIKELY"),
        ("onset at {ONSET}", [], "onset at 00:20:30 UTC"),
        ("{SVC:checkout}", [], "checkout"),
        (
            f"{{{ATOM}.label}} at {{{ATOM}.value}} {{{ATOM}.unit}}",
            [ATOM],
            "payment cpu anomaly (incident) at 9.42 z",
        ),
        (f"{{{OTHER}.unit}}|{{{OTHER}.candidate}}|{{{OTHER}.window}}", [OTHER], "|payment|onset"),
        ("no placeholders at all.", [], "no placeholders at all."),
    ],
)
def test_fill_accepts(text: str, cites: list[str], filled: str) -> None:
    assert fill(text, cites, _ctx()) == filled


def test_component_falls_back_to_the_service_via_root_fields() -> None:
    ctx = _ctx(
        root_fields={"component": "payment", "fault_class": "cpu", "indicator": "cpu", "mode": "resource"}
    )
    assert fill("{ROOT.component}", [], ctx) == "payment"


@pytest.mark.parametrize(
    ("text", "cites", "ctx_changes", "rule"),
    [
        ("{ROOT", [], {}, "C1"),
        ("ROOT}", [], {}, "C1"),
        ("{{ROOT}}", [], {}, "C1"),
        ("{ROOT.service}", [], {}, "C1"),
        ("{root}", [], {}, "C1"),
        ("{E0000000000.value}", [], {}, "C2"),  # 10 §7: unknown atom
        ("{E0000000000.value}", ["E0000000000"], {}, "C3"),  # its cite is not in the table either
        (f"{{{ATOM}.value}}", [], {}, "C3"),  # atom placeholder without its cite
        ("{SVC:paymentservice-v2}", [], {}, "C2"),
        (
            "{ROOT} is fine.",
            [],
            {"root_service": None, "status": "NO_FAULT"},
            "C2",
        ),  # 10 §7: {ROOT} under NO_FAULT
        ("{RUNNER_UP}", [], {"runner_up": None}, "C2"),
        ("{ONSET}", [], {"onset_ns": None}, "C2"),
        ("{E1234567890.label}", [], {}, "C2"),
        ("{Ea4217049F6.value}", [], {}, "C1"),  # uppercase hex is not the grammar
    ],
)
def test_fill_rejects_with_its_rule(
    text: str, cites: list[str], ctx_changes: dict[str, Any], rule: str
) -> None:
    with pytest.raises(PlaceholderError) as exc:
        fill(text, cites, _ctx(**ctx_changes))
    assert exc.value.rule == rule


def test_placeholders_lists_bodies_in_order() -> None:
    assert placeholders("{ROOT} then {SVC:cart} then {CONF.level}.") == ["ROOT", "SVC:cart", "CONF.level"]


def test_filled_numbers_come_only_from_placeholders() -> None:
    text = f"Signal {{{ATOM}.label}} reached {{{ATOM}.value}} {{{ATOM}.unit}}; margin {{CONF.margin}}."
    out = fill(text, [ATOM], _ctx())
    assert re.findall(r"\d+(?:\.\d+)?", re.sub(r"\{[^}]*\}", "", text)) == []
    assert "9.42" in out and "0.27" in out
