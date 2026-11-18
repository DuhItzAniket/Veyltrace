"""Number formatting and the placeholder grammar and filler (10 §3.3, C1–C3 of §3.4; 10 §7 unit row)."""

from __future__ import annotations

import math
import re
from typing import Any, cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_causivra.fmt import (
    format_count,
    format_margin,
    format_number,
    format_numbers_in,
    format_time_utc,
    format_value,
)
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
        (1.0, "1"),  # trailing zeros stripped, like %g (#330 c)
        (1.2, "1.2"),
        (0.274390244, "0.274"),
        (1234.5, "1230"),
        (0.0012345, "0.00123"),
        (0.0001234, "0.000123"),
        (2.675, "2.68"),  # 2.675 is 2.67499999… in binary; repr() is "2.675", rounded half-even on decimals
        (-3.14159, "-3.14"),
        (1_200_000.0, "1.2e+06"),
        # The notation follows the rounded value (#330 b), at both thresholds.
        (999_500.0, "1e+06"),
        (999_499.0, "999000"),
        (-999_999.9, "-1e+06"),
        (0.0009995, "0.001"),
        (0.0009994, "0.000999"),
        (9.995, "10"),
        (100.0, "100"),
        (1.5e-05, "1.5e-05"),
        (5e-324, "5e-324"),  # decimal, so no binary detour (a float would print 4.94e-324)
    ],
)
def test_format_number_table(value: Any, text: str) -> None:
    assert format_number(value, 3) == text


@given(st.floats(min_value=0.001, max_value=999_499, allow_nan=False))
def test_values_that_round_into_the_plain_range_are_plain(x: float) -> None:
    out = format_number(x, 3)
    assert "e" not in out and out == format_number(x, 3)
    assert math.isclose(float(out), x, rel_tol=5e-3)


@given(st.floats(min_value=999_500, max_value=1e300, allow_nan=False))
def test_values_that_round_to_a_million_or_more_are_scientific(x: float) -> None:
    out = format_number(x, 3)
    assert "e+" in out and math.isclose(float(out), x, rel_tol=5e-3)  # #330 b


@given(st.floats(allow_nan=False, allow_infinity=False).filter(lambda x: x != 0))
def test_one_precision_rule_without_trailing_zeros(x: float) -> None:
    mantissa = format_number(x, 3).split("e")[0]
    assert not ("." in mantissa and mantissa.endswith("0")) and not mantissa.endswith(".")  # #330 c
    assert len(mantissa.lstrip("-0.").replace(".", "").rstrip("0")) <= 3


@given(st.floats(allow_nan=True, allow_infinity=True))
def test_format_number_is_total_and_deterministic(x: float) -> None:
    assert format_number(x, 3) == format_number(x, 3)


def test_margin_and_time() -> None:
    assert format_margin(0.274390244) == "0.27"
    assert format_margin(0.125) == "0.12"  # half-even
    assert format_margin(0.0) == "0.00"
    assert format_time_utc(1_767_226_800_000_000_000) == "00:20:00 UTC"
    assert format_time_utc(1_767_225_599_000_000_000) == "23:59:59 UTC"


@pytest.mark.parametrize(
    ("margin", "text"),
    [
        (float("nan"), "n/a"),
        (float("inf"), "n/a"),
        (float("-inf"), "n/a"),
        (-0.0, "0.00"),
        (-0.004, "0.00"),  # rounds to zero: no "-0.00"
        (-0.006, "-0.01"),
        (1.0, "1.00"),
    ],
)
def test_format_margin_edges(margin: float, text: str) -> None:
    assert format_margin(margin) == text


@given(st.floats(allow_nan=True, allow_infinity=True))
def test_format_margin_is_total(x: float) -> None:
    out = format_margin(x)
    assert out != "-0.00"
    assert out == "n/a" if not math.isfinite(x) else len(out.split(".")[1]) == 2


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
        ("{CONF.level} {CONF.set_size} {CONF.margin} {STATUS}", [], "medium 2 services 0.27 LIKELY"),
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
        ("{E0000000000.value}", ["E0000000000"], {}, "C2"),  # also a bad cite (C3), but C2 comes first
        ("{ROOT} leads.", ["E0000000000"], {}, "C3"),  # cite not in the evidence table
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


NO_ROOT: dict[str, Any] = {"root_service": None, "status": "NO_FAULT"}


@pytest.mark.parametrize(
    ("text", "cites", "ctx_changes", "rule", "token"),
    [
        ("{ROOT} {bogus}", [], NO_ROOT, "C1", "bogus"),  # an earlier C2 placeholder loses to C1
        ("{ROOT", ["E0000000000"], {}, "C1", "{ROOT"),  # unbalanced brace beats a bad cite
        ("{SVC:nope} {Ea4217049F6.value}", [], {}, "C1", "Ea4217049F6.value"),  # uppercase hex: C1
        (f"{{{ATOM}.value}} {{ROOT}}", [], NO_ROOT, "C2", "ROOT"),  # an earlier C3 placeholder loses to C2
        ("{SVC:nope}", ["E0000000000"], {}, "C2", "SVC:nope"),  # unknown node beats a bad cite
        (f"{{{ATOM}.value}} {{{OTHER}.value}}", [OTHER], {}, "C3", f"{ATOM}.value"),
    ],
)
def test_a_sentence_breaking_two_rules_reports_the_earlier_rule(
    text: str, cites: list[str], ctx_changes: dict[str, Any], rule: str, token: str
) -> None:
    with pytest.raises(PlaceholderError) as exc:
        fill(text, cites, _ctx(**ctx_changes))
    assert (exc.value.rule, exc.value.token) == (rule, token)


def test_placeholders_lists_bodies_in_order() -> None:
    assert placeholders("{ROOT} then {SVC:cart} then {CONF.level}.") == ["ROOT", "SVC:cart", "CONF.level"]


def test_filled_numbers_come_only_from_placeholders() -> None:
    text = f"Signal {{{ATOM}.label}} reached {{{ATOM}.value}} {{{ATOM}.unit}}; margin {{CONF.margin}}."
    out = fill(text, [ATOM], _ctx())
    assert re.findall(r"\d+(?:\.\d+)?", re.sub(r"\{[^}]*\}", "", text)) == []
    assert "9.42" in out and "0.27" in out


@pytest.mark.parametrize(
    ("count", "text"),
    [(0, "0 services"), (1, "1 service"), (2, "2 services"), (12, "12 services")],
)
def test_format_count_agrees_with_the_number(count: int, text: str) -> None:
    assert format_count(count, "service") == text


def test_format_count_takes_an_irregular_plural_and_rejects_a_non_int() -> None:
    assert (format_count(1, "body", "bodies"), format_count(3, "body", "bodies")) == ("1 body", "3 bodies")
    with pytest.raises(TypeError):
        format_count(True, "service")
    with pytest.raises(TypeError):
        format_count(cast(Any, 2.0), "service")  # the runtime check is under test


def test_set_size_placeholder_carries_its_counted_noun() -> None:
    one = _ctx(conf_set_size=1)
    assert fill("The set has {CONF.set_size}.", [], one) == "The set has 1 service."
    assert fill("The set has {CONF.set_size}.", [], _ctx()) == "The set has 2 services."


@pytest.mark.parametrize(
    ("why", "text"),
    [
        # Causentra's ask texts (09 §3.11): margins read as {CONF.margin}, other numbers at 3 sig. digits.
        ("runner-up within margin 0.015249896", "runner-up within margin 0.02"),
        (
            "no status rule met at set size 2 and margin 0.03",
            "no status rule met at set size 2 and margin 0.03",
        ),
        ("margin -0.004", "margin 0.00"),
        ("score 0.123456 and 2e-05", "score 0.123 and 2e-05"),
        # Integers and digits inside identifiers stay as they are.
        ("mandatory trial T1 failed: no_internal_anomaly", "mandatory trial T1 failed: no_internal_anomaly"),
        ("candidate set has 5 members", "candidate set has 5 members"),
        ("synth-01 v2.0.1 x1.5", "synth-01 v2.0.1 x1.5"),
        ("premargin 0.5", "premargin 0.5"),  # one precision rule (#330 c)
    ],
)
def test_format_numbers_in_upstream_text(why: str, text: str) -> None:
    assert format_numbers_in(why, 3) == text


@pytest.mark.parametrize(
    ("value", "unit", "text"),
    [
        (12.0, "count", "12"),  # #330 d: by the unit, not by the float
        (1234.0, "count", "1234"),  # a count keeps every digit
        (2.5, "count", "2"),  # half-even
        (12.0, "z", "12"),
        (1234.0, "ms", "1230"),
        (None, "count", "n/a"),
        (float("nan"), "count", "n/a"),
    ],
)
def test_format_value_prints_counts_as_integers(value: float | None, unit: str, text: str) -> None:
    assert format_value(value, unit, 3) == text


def test_c3_does_not_require_cites_in_the_template_filler() -> None:
    # #330 a: "cites empty" is enforced on the LLM path (X-09); a template sentence without an atom
    # placeholder may have empty cites (10 §3.5), and the module says where the rule lives.
    import veyltrace_causivra.placeholders as module

    assert fill("The leading candidate is {ROOT}.", [], _ctx()) == "The leading candidate is payment."
    assert module.__doc__ is not None and "cites empty" in module.__doc__ and "X-09" in module.__doc__
