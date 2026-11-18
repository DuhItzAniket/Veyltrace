"""Brief settings and the per-case schema (08 §3.1, §3.4, §4)."""

from __future__ import annotations

import copy
import json
from typing import Any, get_args

import jsonschema
import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_contracts import models
from veyltrace_contracts.predicates import PREDICATES
from veyltrace_core.canonical import canonical_json
from veyltrace_core.errors import ConfigError
from veyltrace_core.hashing import sha256_bytes
from veyltrace_relentra.schema import EMPTY, build_enums, build_schema, schema_sha256
from veyltrace_relentra.settings import BriefSettings, brief_settings

CONFIG: dict[str, Any] = {  # the defaults of 08 §4
    "brief": {"max_proposals": 3},
    "budget": {"max_claims_per_proposal": 4, "max_hypotheses": 5, "max_prompt_tokens": 12288},
    "schema": {"max_signal_enum": 64, "max_bytes": 16384, "exclude_fault_classes": ["unknown"]},
    "cards": {"k": 6, "k_min": 3, "pool_context_n": 10},
    "prompt": {"chars_per_token": 3.5, "include_brief": True, "permute_slate": False},
}
NODES = ["cart", "checkout", "frontend"]
SIGNALS = ["cpu", "latency_p99", "tmpl:abc", "error_rate"]
ATOMS = ["Eaaaaaaaaaa", "Ebbbbbbbbbb"]


@pytest.fixture
def settings() -> BriefSettings:
    return brief_settings(CONFIG)


def _with(dotted: str, value: object) -> dict[str, Any]:
    config = copy.deepcopy(CONFIG)
    *path, last = dotted.split(".")
    node = config
    for part in path:
        node = node[part]
    node[last] = value
    return config


def _reply() -> dict[str, Any]:
    claim = {"predicate": "zscore_above", "signal": "cpu", "other": EMPTY, "x": 3.0, "cites": ATOMS[:1]}
    proposal = {
        "service": "cart", "fault_class": "cpu", "indicator": "cpu", "claims": [claim],
        "requested_trials": ["T1", "T10"], "rationale": "cpu rose first",
    }  # fmt: skip
    return {"proposals": [proposal], "asks": [{"kind": "trial", "target": "T8", "why": "isolate"}]}


def test_enums_are_sorted_closed_and_leave_out_templates(settings: BriefSettings) -> None:
    enums = build_enums(reversed(NODES), SIGNALS, reversed(ATOMS), settings)
    assert enums.nodes == tuple(NODES) and enums.atom_ids == tuple(ATOMS)
    assert enums.signals == ("cpu", "error_rate", "latency_p99")  # no tmpl:*
    assert "unknown" not in enums.fault_classes and "cpu" in enums.fault_classes
    assert set(enums.predicates) == {p.name for p in PREDICATES}  # 03 §7
    assert enums.trials == get_args(models.TrialId) and enums.trials[-1] == "T10"


def test_signal_enum_is_truncated_after_sorting() -> None:
    small = brief_settings(_with("schema.max_signal_enum", 2))
    assert build_enums(NODES, SIGNALS, ATOMS, small).signals == ("cpu", "error_rate")


def test_a_valid_reply_passes_and_invented_values_fail(settings: BriefSettings) -> None:
    schema = build_schema(build_enums(NODES, SIGNALS, ATOMS, settings), settings)
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    assert not list(validator.iter_errors(_reply()))
    for field, bad in (
        ("service", "paymentservice-v2"),
        ("fault_class", "unknown"),
        ("indicator", "cpu_usage"),
        ("requested_trials", ["T11"]),
    ):
        reply = _reply()
        reply["proposals"][0][field] = bad
        assert list(validator.iter_errors(reply)), field
    reply = _reply()
    reply["proposals"][0]["claims"][0]["predicate"] = "made_up"
    reply["proposals"][0]["extra"] = 1
    assert len(list(validator.iter_errors(reply))) == 2


def test_schema_stays_flat(settings: BriefSettings) -> None:
    text = json.dumps(build_schema(build_enums(NODES, SIGNALS, ATOMS, settings), settings))
    assert not any(word in text for word in ("oneOf", "anyOf", "$ref", "patternProperties"))


def test_every_schema_value_is_valid_in_the_contract(settings: BriefSettings) -> None:
    enums = build_enums(NODES, SIGNALS, ATOMS, settings)
    assert set(enums.indicators) == set(get_args(models.Indicator))
    assert set(enums.fault_classes) <= set(get_args(models.FaultClass))
    assert set(enums.predicates) == set(get_args(models.Predicate))


def test_no_atoms_means_no_cites(settings: BriefSettings) -> None:
    schema = build_schema(build_enums(NODES, SIGNALS, [], settings), settings)
    jsonschema.Draft202012Validator.check_schema(schema)
    reply = _reply()
    assert list(jsonschema.Draft202012Validator(schema).iter_errors(reply))
    reply["proposals"][0]["claims"][0]["cites"] = []
    assert not list(jsonschema.Draft202012Validator(schema).iter_errors(reply))


def test_an_oversized_schema_is_a_config_error() -> None:
    small = brief_settings(_with("schema.max_bytes", 100))
    with pytest.raises(ConfigError, match=r"schema\.max_bytes"):
        build_schema(build_enums(NODES, SIGNALS, ATOMS, small), small)


@given(st.permutations(NODES), st.permutations(SIGNALS), st.permutations(ATOMS))
def test_schema_and_hash_do_not_depend_on_input_order(
    nodes: list[str], signals: list[str], atoms: list[str]
) -> None:
    settings = brief_settings(CONFIG)
    base = build_schema(build_enums(NODES, SIGNALS, ATOMS, settings), settings)
    schema = build_schema(build_enums(nodes, signals, atoms, settings), settings)
    assert schema == base and schema_sha256(schema) == sha256_bytes(canonical_json(base))


@pytest.mark.parametrize(
    ("dotted", "value"),
    [
        ("brief.max_proposals", 0),
        ("brief.max_proposals", True),
        ("schema.max_bytes", "big"),
        ("schema.exclude_fault_classes", ["not_a_class"]),
        ("schema.exclude_fault_classes", "unknown"),
        ("cards.k_min", 7),  # above cards.k
        ("cards.pool_context_n", -1),
        ("prompt.chars_per_token", 0),
        ("prompt.include_brief", "yes"),
    ],
)
def test_bad_settings_are_config_errors(dotted: str, value: object) -> None:
    with pytest.raises(ConfigError, match="relentra"):
        brief_settings(_with(dotted, value))


def test_a_missing_key_is_a_config_error() -> None:
    config = copy.deepcopy(CONFIG)
    del config["brief"]["max_proposals"]
    with pytest.raises(ConfigError, match=r"brief\.max_proposals"):
        brief_settings(config)
