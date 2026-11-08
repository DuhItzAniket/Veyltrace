"""Argument validation of the predicate library (06 §3.5 steps 1-4) on the hand-made cpu-hog case."""

from __future__ import annotations

import math
from typing import Any

import pytest

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
