"""The live buffer (06 §3.4; X-10a1): retention by data time, a hard byte cap, refused batches
(too large, far future, no time) counted, retries buffered once, contract shape enforced, and
the `live.*` settings."""

from __future__ import annotations

import ast
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


def _buffer(max_mb: int = 512, **clocks: Any) -> LiveBuffer:
    return LiveBuffer(30, max_mb, 300, wall=lambda: T0 + 60 * MIN, **clocks)


def test_retention_by_data_time_and_the_byte_cap_evict_the_oldest() -> None:
    buffer = _buffer()
    for minute in (0, 20, 45):  # at 45 min, the batch at 0 is older than 30 min of data time
        assert buffer.add("spans", _spans(2, T0 + minute * MIN), f"d{minute}") == "accepted"
    assert [t.column("start_ns")[0].as_py() for t in buffer.tables("spans")] == [T0 + 20 * MIN, T0 + 45 * MIN]
    capped = _buffer(1)  # 1 MiB
    for i in range(12):  # about 140 kB each: the oldest go once the total passes 1 MiB
        assert capped.add("spans", _spans(1_000, T0 + i * MIN), f"c{i}") == "accepted"
    kept = capped.tables("spans")
    assert (
        sum(t.nbytes for t in kept) <= 1024 * 1024 and kept[-1].column("start_ns")[0].as_py() == T0 + 11 * MIN
    )
    assert len(kept) < 12


def test_a_batch_over_the_cap_in_the_future_or_without_time_is_refused_and_counted() -> None:
    buffer = _buffer(1)
    assert buffer.add("spans", _spans(2), "a") == "accepted"
    assert buffer.add("spans", _spans(20_000, T0 + MIN), "big") == "too_large"  # about 3 MB alone
    year_2100 = 4_102_444_800 * 1_000_000_000
    assert buffer.add("spans", _spans(1, year_2100), "far") == "future"
    no_time = _spans(1, T0 + 2 * MIN)
    column = no_time.schema.get_field_index("start_ns")
    assert (
        buffer.add("spans", no_time.set_column(column, "start_ns", pa.array([None], pa.int64())), "n")
        == "no_time"
    )
    assert buffer.add("spans", _spans(2, T0 + 3 * MIN), "b") == "accepted"  # later adds still work
    assert [t.num_rows for t in buffer.tables("spans")] == [2, 2]  # nothing was evicted
    assert buffer.stats().dropped == {"too_large": 1, "future": 1, "no_time": 1}


def test_a_retried_request_is_buffered_once_and_stats_count_rows() -> None:
    now = [5.0]
    buffer = _buffer(clock=lambda: now[0])
    assert buffer.stats().seconds_since_last is None and not buffer.receiving(60)
    assert buffer.add("spans", _spans(3), "same") == "accepted"
    assert buffer.add("spans", _spans(3), "same") == "duplicate"
    gauge = StubConverter().metrics(otlp_gauge("cart", "cpu", [(T0 - MIN, 0.5)]), {})[0]
    assert buffer.add("metrics", gauge, "g") == "accepted"
    now[0] = 7.0
    stats = buffer.stats()
    assert stats.rows == {"metrics": 1, "logs": 0, "spans": 3, "events": 0}
    assert (stats.oldest_ns, stats.newest_ns, stats.seconds_since_last) == (T0 - MIN, T0 + 2, 2.0)
    assert buffer.receiving(2) and not buffer.receiving(1) and stats.dropped == {}


def test_a_table_off_the_contract_is_refused() -> None:
    with pytest.raises(ContractValidationError):
        _buffer().add("spans", pa.table({"trace_id": ["x"]}), "bad")


def test_no_runtime_module_imports_the_test_stub() -> None:
    src = repo_root() / "packages" / "gateway" / "src" / "veyltrace_gateway"
    for path in sorted(src.glob("*.py")):
        if path.name == "testing.py":
            continue
        tree = ast.parse(path.read_bytes())
        names = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        names += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert "veyltrace_gateway.testing" not in names, path.name


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("otlp_port", 0),
        ("otlp_host", ""),
        ("max_body_mb", 0),
        ("buffer_max_mb", "512"),
        ("future_tolerance_s", 0),
    ],
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
