"""The live buffer (06 §3.4; X-10a1): retention by data time, the byte cap, retries buffered once,
contract shape enforced, and the `live.*` settings."""

from __future__ import annotations

import json
from typing import Any

import pyarrow as pa
import pytest

from veyltrace_core.config import load_section_file
from veyltrace_core.errors import ConfigError, ContractValidationError
from veyltrace_core.testing import repo_root
from veyltrace_gateway.buffer import LiveBuffer
from veyltrace_gateway.settings import load_settings, settings_from
from veyltrace_gateway.testing import StubConverter, otlp_gauge, otlp_spans

CONFIG = repo_root() / "config"
T0 = 1_700_000_000_000_000_000
MIN = 60_000_000_000


def _spans(n: int, t: int = T0) -> pa.Table:
    request = otlp_spans("frontend", [(f"{i:032x}", f"{i:016x}", t + i, t + i + 5, i == 0) for i in range(n)])
    return StubConverter().spans(request, {})[0]


def test_retention_by_data_time_and_the_byte_cap_evict_the_oldest() -> None:
    buffer = LiveBuffer(30, 512)
    for minute in (0, 20, 45):  # at 45 min, the batch at 0 is older than 30 min of data time
        assert buffer.add("spans", _spans(2, T0 + minute * MIN), f"d{minute}")
    assert [t.column("start_ns")[0].as_py() for t in buffer.tables("spans")] == [T0 + 20 * MIN, T0 + 45 * MIN]
    tiny = LiveBuffer(30, 1)  # 1 MB: a batch of 20,000 spans (about 3 MB) keeps only itself
    tiny.add("spans", _spans(2), "a")
    tiny.add("spans", _spans(20_000, T0 + MIN), "b")
    assert [t.num_rows for t in tiny.tables("spans")] == [20_000]


def test_a_retried_request_is_buffered_once_and_stats_count_rows() -> None:
    now = [5.0]
    buffer = LiveBuffer(30, 512, clock=lambda: now[0])
    assert buffer.stats().seconds_since_last is None and not buffer.receiving(60)
    assert buffer.add("spans", _spans(3), "same") and not buffer.add("spans", _spans(3), "same")
    gauge = StubConverter().metrics(otlp_gauge("cart", "cpu", [(T0 - MIN, 0.5)]), {})[0]
    assert buffer.add("metrics", gauge, "g")
    now[0] = 7.0
    stats = buffer.stats()
    assert stats.rows == {"metrics": 1, "logs": 0, "spans": 3, "events": 0}
    assert (stats.oldest_ns, stats.newest_ns, stats.seconds_since_last) == (T0 - MIN, T0 + 2, 2.0)
    assert buffer.receiving(2) and not buffer.receiving(1)


def test_a_table_off_the_contract_is_refused() -> None:
    with pytest.raises(ContractValidationError):
        LiveBuffer(30, 512).add("spans", pa.table({"trace_id": ["x"]}), "bad")


@pytest.mark.parametrize(
    ("key", "value"), [("otlp_port", 0), ("otlp_host", ""), ("max_body_mb", 0), ("buffer_max_mb", "512")]
)
def test_bad_live_settings_are_config_errors(key: str, value: object) -> None:
    body: dict[str, Any] = json.loads(
        json.dumps(load_section_file("gateway", config_dir=CONFIG), default=dict)
    )
    body["live"][key] = value
    with pytest.raises(ConfigError, match=rf"live\.{key}"):
        settings_from(body)


def test_default_live_settings_bind_loopback() -> None:
    live = load_settings(CONFIG).live
    assert (live.otlp_host, live.otlp_port, live.buffer_minutes) == ("127.0.0.1", 4319, 30)
