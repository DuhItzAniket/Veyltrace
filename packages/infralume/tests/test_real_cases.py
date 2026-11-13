"""Real-case smoke (01 §7): one fetched case per RCAEval suite, skipped without `${VEYLTRACE_DATA}`.

Per case: the tables fit their contracts, `sources` match the suite (Sock Shop has no traces, RE1
has metrics only), no folder token, deny-listed key or fault-tool row survives (01 §3.6 a–c, the
real directory names as tokens), conversion takes ≤ 10 s (O-01), and two conversions encode to
identical bytes. Fetch first: `uv run veyltrace data fetch rcaeval --suite <suite> --cases 1`.
"""

from __future__ import annotations

import json
import time

import pytest

from veyltrace_core import io
from veyltrace_core.adapters import TELEMETRY_CONTRACTS, CanonicalCase
from veyltrace_core.config import EngineConfig, data_root
from veyltrace_infralume.adapters.rcaeval import RcaevalAdapter
from veyltrace_infralume.cache import full_table
from veyltrace_infralume.index import read_index
from veyltrace_infralume.scrub import ScrubRules, folder_tokens

pytestmark = pytest.mark.real_data

#: Suite → sources a case of it has (rcaeval_facts §Datasets and telemetry per system).
SUITES = {
    "re1-ob": {"metrics"}, "re2-ob": {"metrics", "logs", "traces"}, "re2-ss": {"metrics", "logs"},
    "re2-tt": {"metrics", "logs", "traces"}, "re3-ob": {"metrics", "logs", "traces"},
}  # fmt: skip
CONVERT_BUDGET_S = 10.0  # O-01 acceptance: ≤ 10 s per case


def _encode(case: CanonicalCase) -> dict[str, bytes]:
    return {c: io.encode(c, full_table(c, getattr(case.tables, s))) for s, c in TELEMETRY_CONTRACTS.items()}


@pytest.mark.parametrize("suite", sorted(SUITES))
def test_real_case(suite: str, infralume_cfg: EngineConfig) -> None:
    index = read_index(data_root(), suite)
    if not index:
        pytest.skip(f"no {suite} case fetched under {data_root()}")
    case_id, rel = sorted(index.items())[0]
    adapter = RcaevalAdapter()
    ref = adapter.resolve(suite, case_id, data_root())
    started = time.perf_counter()
    case = adapter.convert(ref, infralume_cfg)
    elapsed = time.perf_counter() - started
    assert elapsed <= CONVERT_BUDGET_S, f"{suite} {case_id}: convert took {elapsed:.1f} s"
    encoded = _encode(case)  # raises if a table breaks its contract
    assert {s for s, on in case.sources_present.items() if on} == SUITES[suite]
    rules, tokens = ScrubRules.from_config(infralume_cfg), folder_tokens(ref.canonical_key, rel)
    for source, table in case.tables.items():
        for name in table.column_names:
            if table.schema.field(name).type == "string":
                values = {v.lower() for v in table.column(name).unique().to_pylist() if isinstance(v, str)}
                assert not [v for v in values for t in tokens if t in v], (source, name)
        for name in ("service", "component"):
            if name in table.column_names:
                assert not set(table.column(name).to_pylist()) & rules.drop_services
    for attrs in case.tables.logs.column("attrs_json").to_pylist():
        assert attrs is None or not [k for k in json.loads(attrs) if rules.denied(k)]
    assert _encode(adapter.convert(ref, infralume_cfg)) == encoded  # deterministic
