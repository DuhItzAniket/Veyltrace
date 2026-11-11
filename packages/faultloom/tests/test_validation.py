"""Argument validation of the predicate library (06 §3.5 steps 1-4) on the hand-made cpu-hog case."""

from __future__ import annotations

import dataclasses
import math
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_core.config import load_config
from veyltrace_faultloom.predicates import LIBRARY, ClaimView
from veyltrace_faultloom.validation import Rejection, ValidClaim, domain_of, read_domain, validate


def test_the_domain_comes_from_the_case_and_config(cpu_hog: tuple[Any, ClaimView]) -> None:
    ctx, view = cpu_hog
    domain = read_domain(ctx)
    assert domain == domain_of(view.inputs, load_config("faultloom"))
    assert domain.ranges["zscore_above"] == {"k": (1.0, 100.0)}
    assert domain.ranges["template_new_in_incident"] == {"min_count": (1, 1000000)}
    assert "cpu" in domain.signals and "card-gateway.example" in domain.nodes


@pytest.mark.parametrize(
    ("name", "args", "reason"),
    [
        ("zscore_below", {"signal": "cpu", "k": 4}, "unknown_predicate"),
        ("zscore_above", {"signal": "cpu"}, "bad_args"),  # missing
        ("zscore_above", {"signal": "cpu", "k": 4, "q": 1}, "bad_args"),  # extra
        ("zscore_above", {"subject": "checkout", "signal": "cpu", "k": 4}, "bad_args"),  # 03 §9.1
        ("zscore_above", ["cpu", 4], "bad_args"),  # not an object
        ("zscore_above", {"signal": "cpu", "k": "4"}, "bad_args"),  # wrong type
        ("zscore_above", {"signal": "cpu", "k": True}, "bad_args"),  # booleans are not numbers
        ("zscore_above", {"signal": "cpu", "k": 0.5}, "bad_args"),  # below [1, 100]
        ("zscore_above", {"signal": "cpu", "k": 100.5}, "bad_args"),  # above
        ("zscore_above", {"signal": "cpu", "k": math.nan}, "bad_args"),
        ("zscore_above", {"signal": "cpu", "k": math.inf}, "bad_args"),
        ("zscore_above", {"signal": "cpu", "k": 10**400}, "bad_args"),  # no OverflowError
        ("template_new_in_incident", {"min_count": -(10**400)}, "bad_args"),
        ("zscore_above", {"signal": "gpu", "k": 4}, "bad_args"),  # signal not in this case
        ("zscore_above", {"signal": 3, "k": 4}, "bad_args"),
        ("template_new_in_incident", {"min_count": 2.5}, "bad_args"),  # int must be integral
        ("template_new_in_incident", {"min_count": 0}, "bad_args"),
        ("onset_before", {"other_service": 7}, "bad_args"),
        ("onset_before", {"other_service": "ghost"}, "unknown_entity"),
        ("silent", {"x": 1}, "bad_args"),
    ],
)
def test_validate_rejects(cpu_hog: tuple[Any, ClaimView], name: str, args: object, reason: str) -> None:
    got = validate(name, args, read_domain(cpu_hog[0]))
    assert isinstance(got, Rejection) and got.reason == reason and got.detail


def test_validate_accepts_and_canonicalises(cpu_hog: tuple[Any, ClaimView]) -> None:
    domain = read_domain(cpu_hog[0])
    k = validate("zscore_above", {"k": 4, "signal": "cpu"}, domain)
    count = validate("template_new_in_incident", {"min_count": 3.0}, domain)
    edge = validate("edge_anomalous", {"callee": "card-gateway.example"}, domain)  # any graph node
    assert isinstance(k, ValidClaim) and k.args == {"k": 4.0, "signal": "cpu"} and type(k.args["k"]) is float
    assert (
        isinstance(count, ValidClaim)
        and count.args == {"min_count": 3}
        and type(count.args["min_count"]) is int
    )
    assert isinstance(edge, ValidClaim) and edge.predicate is LIBRARY["edge_anomalous"]
    assert validate("silent", {}, domain) == ValidClaim(LIBRARY["silent"], {})
    assert validate("zscore_above", {"signal": "cpu", "k": 1}, domain) == validate(
        "zscore_above", {"signal": "cpu", "k": 1.0}, domain
    )  # bounds are inclusive; 1 and 1.0 are one claim


def test_validated_args_evaluate(cpu_hog: tuple[Any, ClaimView]) -> None:
    ctx, view = cpu_hog
    claim = validate("zscore_above", {"signal": "cpu", "k": 4}, read_domain(ctx))
    assert isinstance(claim, ValidClaim)
    assert claim.predicate.evaluate(view, "checkout", claim.args).holds is True


def test_a_missing_range_is_bad_args(cpu_hog: tuple[Any, ClaimView]) -> None:
    domain = read_domain(cpu_hog[0])
    ranges = {k: v for k, v in domain.ranges.items() if k != "zscore_above"}
    got = validate("zscore_above", {"signal": "cpu", "k": 4}, dataclasses.replace(domain, ranges=ranges))
    assert isinstance(got, Rejection) and got.reason == "bad_args" and "no configured range" in got.detail


_LEAF = st.none() | st.booleans() | st.integers(-(2**2000), 2**2000) | st.floats() | st.text(max_size=8)
_JSON = st.recursive(
    _LEAF, lambda c: st.lists(c, max_size=3) | st.dictionaries(st.text(max_size=8), c, max_size=3)
)
_PARAMS = st.sampled_from(sorted({q.name for p in LIBRARY.values() for q in p.params}))


@given(
    name=st.sampled_from(sorted(LIBRARY)) | st.text(max_size=12),
    args=_JSON | st.dictionaries(_PARAMS | st.text(max_size=6), _JSON, max_size=4),
)
def test_validate_never_raises_on_any_json_args(hm: Any, name: str, args: object) -> None:
    # 06 §3.5: validate parses LLM output, so anything JSON gives a ValidClaim or a Rejection.
    domain = domain_of(hm.view(signals=frozenset({"cpu"})), load_config("faultloom"))
    assert isinstance(validate(name, args, domain), ValidClaim | Rejection)
