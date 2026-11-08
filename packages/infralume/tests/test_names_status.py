"""Infralume's name normalisation and span error-status rule (01 §3.4, §3.5)."""

from __future__ import annotations

from typing import Any

import pyarrow as pa
import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_infralume.names import InvalidName, NameRules, Normalised, strip_pod_suffix
from veyltrace_infralume.status import StatusRules, span_status

# The 01 §4 defaults, written out so the rules are tested without the YAML.
CFG: dict[str, Any] = {
    "normalise": {
        "aliases": {"ob": {"frontendservice": "frontend"}},
        "component_suffixes": ["-db"],
        "drop_containers": ["istio-proxy", "istio-init", "POD"],
    },
    "status": {"otel_code_set": [0, 1, 2], "http_error_min": 500},
}
OB = NameRules.from_config(CFG, "ob")
SS = NameRules.from_config(CFG, "ss")
STATUS = StatusRules.from_config(CFG)


# --- names (01 §3.4) ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("pod", "base"),
    [
        ("frontend-7d4b9c8f6d-x2kqz", "frontend"),  # Deployment
        ("fluentd-x7k2p", "fluentd"),  # DaemonSet / Job
        ("redis-cart-0", "redis-cart"),  # StatefulSet
        ("frontend-proxy", "frontend-proxy"),  # vowels: not a generated suffix
        ("ts-ui-dashboard", "ts-ui-dashboard"),
    ],
)
def test_pod_suffixes(pod: str, base: str) -> None:
    assert strip_pod_suffix(pod) == base


def test_normalise_steps() -> None:
    assert OB.normalise("  FrontendService ") == Normalised("frontend", "frontend")
    assert SS.normalise("frontendservice") == Normalised("frontendservice", "frontendservice")  # OB only
    assert SS.normalise("carts-db") == Normalised("carts", "carts-db")
    assert SS.normalise("user_db") == Normalised("user", "user-db")  # steps 4-6 to a fixed point
    assert OB.normalise("cartservice-6f9c7b5d4c-x2kqz", pod=True) == Normalised(
        "cartservice", "cartservice-6f9c7b5d4c-x2kqz"
    )
    assert OB.normalise("istio-proxy") is None
    assert OB.normalise("POD") is None
    with pytest.raises(InvalidName):
        OB.normalise("-bad name")


_NAMES = st.text(alphabet="abcdefgkmnopsxyz019_-.", min_size=1, max_size=24)


@given(_NAMES, st.booleans())
def test_normalisation_is_idempotent(raw: str, pod: bool) -> None:
    try:
        once = SS.normalise(raw, pod=pod)
    except InvalidName:
        return
    if once is not None:
        assert SS.normalise(once.service) == Normalised(once.service, once.service)


# --- span error-status rule (01 §3.5) ----------------------------------------------------------
def _status(codes: list[int | None]) -> list[str]:
    return [str(s) for s in span_status(pa.array(codes, type=pa.int64()), STATUS).to_pylist()]


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        ([0, 2, None], ["unset", "error", "unset"]),  # rule 1: OTel
        ([0, 1, 2], ["unset", "ok", "error"]),
        ([0, 2, 14], ["ok", "error", "error"]),  # rule 2: gRPC 2 and 14 are errors
        ([200, 503, 0], ["ok", "error", "ok"]),  # HTTP: only >= 500 errors; 0 never
        ([404, None, 499, 500], ["ok", "unset", "ok", "error"]),
        ([None, None], ["unset", "unset"]),
    ],
)
def test_error_status_rule(codes: list[int | None], expected: list[str]) -> None:
    assert _status(codes) == expected


@given(st.lists(st.one_of(st.none(), st.integers(0, 999)), min_size=1, max_size=30))
def test_error_status_properties(codes: list[int | None]) -> None:
    status = _status(codes)
    for code, s in zip(codes, status, strict=True):
        if code is None or code == 0:
            assert s != "error"
        if code is not None and code >= 500 and any(c is not None and c >= 100 for c in codes):
            assert s == "error"
