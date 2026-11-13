"""Infralume's leakage scrubbing rules (01 §3.6)."""

from __future__ import annotations

import json
from typing import Any

import pyarrow as pa
import pytest
from hypothesis import given
from hypothesis import strategies as st

from veyltrace_infralume.scrub import CASE_TOKEN, Scrubber, ScrubRules, folder_tokens

# The 01 §4 defaults, written out so the rules are tested without the YAML.
CFG: dict[str, Any] = {
    "scrub": {
        "rules_version": "scrub-1",
        "deny_key_patterns": ["feature_flag.*", "chaos*", "fault*", "inject*"],
        "drop_services": ["flagd", "flagd-ui", "chaos-daemon"],
    },
}
SCRUB = ScrubRules.from_config(CFG)


# --- scrubbing (01 §3.6) -----------------------------------------------------------------------
@pytest.mark.parametrize(
    ("key", "denied"),
    [
        ("feature_flag.key", True),
        ("k8s.Chaos.kind", True),
        ("fault_type", True),
        ("injected", True),
        ("http.route", False),
        ("default", False),  # "fault" inside a segment is not a segment prefix
        ("flag", False),
    ],
)
def test_deny_list(key: str, denied: bool) -> None:
    assert SCRUB.denied(key) is denied


def test_folder_tokens_longest_first() -> None:
    tokens = folder_tokens("re2ob_cartservice_cpu_1", "RE2/RE2-OB/cartservice_cpu/1")
    assert tokens == ("re2/re2-ob/cartservice_cpu/1", "re2ob_cartservice_cpu_1", "cartservice_cpu")


def test_scrubber_text_attrs_rows_and_events() -> None:
    s = Scrubber(SCRUB, folder_tokens("re2ob_cartservice_cpu_1", "rcaeval/hf/re2ob_cartservice_cpu_1"))
    assert s.text("read RE2OB_CARTSERVICE_CPU_1/x") == f"read {CASE_TOKEN}/x"
    col = s.text_column(pa.array(["in rcaeval/hf/re2ob_cartservice_cpu_1 now", None]))
    assert col.to_pylist() == [f"in {CASE_TOKEN} now", None]
    attrs = s.attrs_json(
        json.dumps({"fault.kind": "cpu", "req": {"injected": 1, "p": "/re2ob_cartservice_cpu_1"}})
    )
    assert attrs == json.dumps({"req": {"p": f"/{CASE_TOKEN}"}}, separators=(",", ":"))
    assert s.attrs({"chaos": 1}) is None
    table = pa.table({"service": ["flagd", "cart", "cart"], "component": ["flagd", "cart", "chaos-daemon"]})
    assert s.drop_rows(table, ["service", "component"]).column("service").to_pylist() == ["cart"]
    assert s.event_detail("k8s_event", {"reason": "ChaosMeshInjected"}) is None
    flag = json.loads(s.event_detail("flag", {"flag": "cartFailure", "from": "off", "to": "on"}) or "{}")
    assert flag["flag"] != "cartFailure" and len(flag["flag"]) == 8
    assert s.event_detail("flag", flag) == json.dumps(flag, sort_keys=True, separators=(",", ":"))
    assert s.counts == ("scrub-1", 3, 3)


_JSON = st.recursive(
    st.one_of(st.none(), st.integers(), st.text(max_size=12)),
    lambda inner: st.dictionaries(
        st.sampled_from(["a", "fault.x", "chaos", "k.inject", "p"]), inner, max_size=4
    ),
    max_leaves=10,
)


@given(
    st.dictionaries(st.sampled_from(["a", "feature_flag.b", "x.chaos", "re2ob_c_cpu_1"]), _JSON, max_size=5)
)
def test_scrub_is_idempotent(attrs: dict[str, Any]) -> None:
    s = Scrubber(SCRUB, folder_tokens("re2ob_c_cpu_1", "rcaeval/hf/re2ob_c_cpu_1"))
    once = s.attrs(attrs)
    assert s.attrs_json(once) == once
