"""Cross-engine checks of the Observe lane (05-causalith §7 "Cross-engine").

Anomara and Causalith share two rules: the entry-service set (both call
`veyltrace_causalith.entry`) and the robust scale floor (Causalith's CI test re-implements Anomara's,
because Causalith must not import Anomara). These tests pin that the two engines agree.
"""

from __future__ import annotations

import json

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from veyltrace_anomara.robust import robust_scale as anomara_scale
from veyltrace_anomara.settings import anomara_config
from veyltrace_causalith.ci import CIConfig
from veyltrace_causalith.ci import robust_scale as causalith_scale
from veyltrace_core import io
from veyltrace_core.config import load_section_file
from veyltrace_core.testing import SYNTH_CASES, VARIANTS, fixture_dir

CASES = (*SYNTH_CASES, *sorted(VARIANTS))


@pytest.mark.parametrize("case", CASES)
def test_onsets_entry_services_equal_the_graph_entry_nodes(case: str) -> None:
    onsets_path = fixture_dir("anomara", case) / "onsets.json"
    nodes_path = fixture_dir("causalith", case) / "graph" / "nodes.parquet"
    if not (onsets_path.is_file() and nodes_path.is_file()):
        pytest.skip(f"{case}: Anomara or Causalith fixtures not committed")
    onsets = json.loads(onsets_path.read_text(encoding="utf-8"))
    nodes = io.read_table("graph.nodes", nodes_path.parents[1]).to_pylist()
    assert onsets["entry_services"] == sorted(str(n["node"]) for n in nodes if n["is_entry"])


RZ = anomara_config(load_section_file("anomara")).robust_z
CI = CIConfig.from_sections(load_section_file("causalith"), load_section_file("anomara"))


@settings(max_examples=100, deadline=None)
@given(
    st.lists(st.floats(-1e6, 1e6, allow_nan=False, allow_infinity=False), min_size=1, max_size=40),
    st.sampled_from(
        [("latency", "ms"), ("cpu", "cores"), ("errors", "ratio"), ("mem", "MB"), ("other", None)]
    ),
)
def test_scale_floor_parity_with_anomara(values: list[float], family_unit: tuple[str, str | None]) -> None:
    family, unit = family_unit
    eps_a, eps_c = RZ.epsilon_for(family, unit), CI.epsilon_for(family, unit)
    assert eps_a == eps_c
    baseline = np.asarray(values, dtype=np.float64)
    assert anomara_scale(baseline, eps_a, RZ) == causalith_scale(baseline, eps_c, CI)
