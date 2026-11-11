"""Unit and property tests of the shared entry-service rule (05-causalith §3.3, §7)."""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_causalith.entry import (
    EntryConfig,
    call_pairs_from_edges,
    entry_config,
    entry_services,
    run_entry_services,
)
from veyltrace_contracts.models import Alert
from veyltrace_core import io
from veyltrace_core.config import load_section_file
from veyltrace_core.errors import ConfigError

CFG = EntryConfig(hints={"ob": ("frontend",)}, exclude=("load-generator",))
#: The synth toy system's calls (no hint applies: system "other").
TOY = [
    ("checkout", "cart"),
    ("checkout", "payment"),
    ("frontend", "catalog"),
    ("frontend", "checkout"),
    ("frontend", "recommend"),
    ("recommend", "catalog"),
]
SERVICES = ["cart", "catalog", "checkout", "frontend", "payment", "recommend"]


def test_the_configured_rule_matches_the_spec_defaults() -> None:
    cfg = entry_config(load_section_file("causalith"))
    assert cfg.hints == {
        "ob": ("frontend",),
        "otel": ("frontend-proxy",),
        "ss": ("front-end",),
        "tt": ("ts-ui-dashboard",),
    }
    assert cfg.exclude == ("load-generator", "loadgenerator", "locust")


def test_system_hint_wins_when_it_names_a_known_service() -> None:
    assert entry_services([("cart", "frontend")], ["cart", "frontend"], "ob", CFG) == ["frontend"]


def test_a_hint_naming_no_known_service_falls_back_to_call_pairs() -> None:
    assert entry_services(TOY, ["cart", "checkout"], "ob", CFG) == ["frontend"]


def test_call_pairs_give_the_callers_nobody_calls() -> None:
    assert entry_services(TOY, SERVICES, "other", CFG) == ["frontend"]


def test_an_excluded_load_generator_neither_enters_nor_makes_a_callee() -> None:
    pairs = [*TOY, ("load-generator", "frontend"), ("load-generator", "checkout")]
    assert entry_services(pairs, [*SERVICES, "load-generator"], "other", CFG) == ["frontend"]


def test_without_exclusion_the_load_generator_is_the_entry() -> None:
    pairs = [*TOY, ("load-generator", "frontend")]
    assert entry_services(pairs, SERVICES, "other", EntryConfig({}, ())) == ["load-generator"]


def test_several_entries_are_sorted_and_self_pairs_ignored() -> None:
    pairs = [("web", "cart"), ("api", "cart"), ("api", "api")]
    assert entry_services(pairs, [], "other", CFG) == ["api", "web"]


@pytest.mark.parametrize("pairs", [[], [("a", "b"), ("b", "a")]], ids=["no-pairs", "cycle"])
def test_no_hint_and_no_uncalled_caller_gives_no_entry(pairs: list[tuple[str, str]]) -> None:
    assert entry_services(pairs, ["a", "b"], "other", CFG) == []


@pytest.mark.parametrize(
    "section",
    [
        {},
        {"entry": []},
        {"entry": {"exclude": []}},
        {"entry": {"hints": {"ob": "frontend"}, "exclude": []}},
        {"entry": {"hints": {}, "exclude": [""]}},
        {"entry": {"hints": {}}},
    ],
)
def test_malformed_config_is_a_config_error(section: dict[str, Any]) -> None:
    with pytest.raises(ConfigError):
        entry_config(section)


def _edges(rows: list[tuple[str, str, str]]) -> pa.Table:
    data = [
        {"caller": c, "callee": d, "window": w, "calls": 1, "error_rate": 0.0}
        | dict.fromkeys(
            ("p50_caller_ms", "p99_caller_ms", "p50_callee_ms", "p99_callee_ms", "p50_gap_ms", "p99_gap_ms")
        )
        for c, d, w in rows
    ]
    table = pa.Table.from_pylist(data, schema=io.arrow_schema("signal_cube.edges"))
    return io.conform_table("signal_cube.edges", table)


def test_call_pairs_from_edges_cover_both_windows_once() -> None:
    edges = _edges([("b", "c", "incident"), ("a", "b", "baseline"), ("a", "b", "incident")])
    assert call_pairs_from_edges(edges) == [("a", "b"), ("b", "c")]
    assert call_pairs_from_edges(io.empty_table("signal_cube.edges")) == []


def _alert(entry: list[str] | None) -> Alert:
    detector = None if entry is None else {"entry_services": entry, "signal": "latency_p99", "threshold": 3.0}
    return Alert.model_validate(
        {
            "schema_version": "0.1.0",
            "protocol": "oracle" if entry is None else "detected",
            "t_alert_ns": 10,
            "shift_ns": 0,
            "detector": detector,
            "windows": {"baseline": [0, 5], "incident": [5, 20]},
            "clamped": False,
        }
    )


def test_the_alert_detector_entry_set_is_copied_verbatim() -> None:
    edges = _edges([("frontend", "cart", "incident")])
    assert run_entry_services(_alert(["cart"]), edges, SERVICES, "other", CFG) == ["cart"]
    assert run_entry_services(_alert(None), edges, SERVICES, "other", CFG) == ["frontend"]


_names = st.sampled_from(["a", "b", "c", "d", "e", "load-generator"])


@given(st.lists(st.tuples(_names, _names), max_size=12), st.randoms(use_true_random=False))
def test_entries_are_sorted_uncalled_callers_whatever_the_input_order(
    pairs: list[tuple[str, str]], rnd: Any
) -> None:
    found = entry_services(pairs, [], "other", CFG)
    assert found == sorted(set(found))
    for entry in found:
        assert entry != "load-generator"
        assert any(a == entry and b != entry for a, b in pairs)
        assert not any(b == entry and a not in (entry, "load-generator") for a, b in pairs)
    shuffled = list(pairs)
    rnd.shuffle(shuffled)
    assert entry_services(shuffled, [], "other", CFG) == found
