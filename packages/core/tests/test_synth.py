"""veyltrace_core.synth: deterministic, schema-valid, leakage-free telemetry with the faults of
synth_spec §4 as amended by M0 lead decision 2026-11-06 §2.11.

The per-case properties are checked on the raw telemetry (what Signalyth, Anomara and Causync will
see): server-span counts per bucket, edges, nesting, replica split, events, and the onset and
magnitude of each fault. The engine-level golden expectations (synth_spec §6) are the owning
lanes' tests once their engines replace the stubs.
"""

from __future__ import annotations

import functools
import itertools
import json
import os
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest

from veyltrace_core import io
from veyltrace_core.adapters import Adapter, CanonicalCase, adapter_for
from veyltrace_core.config import load_config
from veyltrace_core.context import RunPlan
from veyltrace_core.errors import UsageError
from veyltrace_core.hashing import sha256_bytes
from veyltrace_core.ids import case_id as make_case_id
from veyltrace_core.pipeline import execute
from veyltrace_core.synth import CASE_KEYS, SynthAdapter, generate, resolve_key
from veyltrace_core.synth import layout as lay
from veyltrace_core.testing import SYNTH_CASES, VARIANTS

NS = lay.NS
MS = lay.MS
T0 = lay.T0_NS
T_INJECT = lay.T_INJECT_NS
#: Default windows around the oracle hint (config/core.yaml windows; 02 §5.1).
BASELINE = (T0 + 120 * NS, T0 + 1200 * NS)
INCIDENT = (T0 + 1200 * NS, T0 + 1800 * NS)
BEFORE = (T0 + 120 * NS, T_INJECT)
AFTER = (T_INJECT, T0 + 1800 * NS)
#: Full 10 s buckets holding traces (the first request starts at T0 + 1 s, the last ~T0 + 1915 s).
FULL_BUCKETS = range(1, 191)
GENERATOR_VARIANTS = sorted(name for name, v in VARIANTS.items() if v.generator is not None)


# --- helpers ----------------------------------------------------------------------------------
@functools.cache
def rows(key: str, source: str) -> list[dict[str, Any]]:
    table: pa.Table = getattr(generate(key).tables, source)
    return table.to_pylist()  # pyright: ignore[reportReturnType]


def hashes(key: str) -> dict[str, str]:
    """sha256 of every table as the io writer would write it (validated, sorted, stamped)."""
    return {
        source: sha256_bytes(io.encode(io.TELEMETRY[source], table))
        for source, table in generate(key).tables.items()
    }


def servers(key: str, component: str | None = None, service: str | None = None) -> list[dict[str, Any]]:
    return [
        s
        for s in rows(key, "spans")
        if s["kind"] == "server"
        and (component is None or s["component"] == component)
        and (service is None or s["service"] == service)
    ]


def within(t: int, window: tuple[int, int]) -> bool:
    return window[0] <= t < window[1]


def metric(key: str, component: str, name: str) -> list[tuple[int, float]]:
    return sorted(
        (r["t_ns"], r["value"])
        for r in rows(key, "metrics")
        if r["component"] == component and r["name"] == name
    )


def rates(points: list[tuple[int, float]]) -> list[tuple[int, float]]:
    """Counter -> per-second rate at the later point (Signalyth §3.2 step 3)."""
    return [(t2, (v2 - v1) / ((t2 - t1) / NS)) for (t1, v1), (t2, v2) in itertools.pairwise(points)]


def mean_in(points: Iterable[tuple[int, float]], window: tuple[int, int]) -> float:
    return statistics.fmean(v for t, v in points if within(t, window))


def durations_ms(spans: Iterable[Mapping[str, Any]], window: tuple[int, int]) -> list[float]:
    return [(s["end_ns"] - s["start_ns"]) / MS for s in spans if within(s["start_ns"], window)]


def gaps_ms(key: str, caller: str, callee: str, window: tuple[int, int]) -> list[float]:
    """client - child duration for caller -> callee pairs (Signalyth edge gap)."""
    by_id = {(s["trace_id"], s["span_id"]): s for s in rows(key, "spans")}
    out: list[float] = []
    for child in servers(key, service=callee):
        parent = by_id.get((child["trace_id"], child["parent_span_id"]))
        if parent is not None and parent["service"] == caller and within(parent["start_ns"], window):
            gap = (parent["end_ns"] - parent["start_ns"]) - (child["end_ns"] - child["start_ns"])
            out.append(gap / MS)
    return out


# --- determinism ------------------------------------------------------------------------------
@pytest.mark.parametrize("key", CASE_KEYS)
def test_two_generations_are_byte_identical(key: str) -> None:
    first = hashes(key)
    generate.cache_clear()
    rows.cache_clear()
    assert hashes(key) == first


def test_generation_is_identical_in_a_fresh_process() -> None:
    """Another interpreter with another hash seed and working directory gives the same bytes."""
    code = (
        "import json\nfrom veyltrace_core import io\nfrom veyltrace_core.hashing import sha256_bytes\n"
        "from veyltrace_core.synth import CASE_KEYS, generate\n"
        "print(json.dumps({k: {s: sha256_bytes(io.encode(io.TELEMETRY[s], t))"
        " for s, t in generate(k).tables.items()} for k in CASE_KEYS}))"
    )
    env = {**os.environ, "PYTHONHASHSEED": "12345", "TZ": "Asia/Kolkata"}
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, cwd=Path(__file__).parent, capture_output=True, check=True
    )
    assert json.loads(out.stdout) == {key: hashes(key) for key in CASE_KEYS}


def test_cases_differ_and_variant_keeps_base_noise() -> None:
    digests = [hashes(key)["spans"] for key in CASE_KEYS]
    assert len(set(digests)) == len(digests)
    # rng is keyed by the base case: before t_inject the silent variant equals synth-05 exactly.
    for source in ("metrics", "logs", "spans"):
        column = "start_ns" if source == "spans" else "t_ns"
        base = [r for r in rows("synth-05", source) if r[column] < T_INJECT]
        silent = [r for r in rows("synth-05@silent", source) if r[column] < T_INJECT]
        assert base == silent, source


# --- schema and shape ---------------------------------------------------------------------------
@pytest.mark.parametrize("key", CASE_KEYS)
def test_tables_are_schema_valid_with_all_sources(key: str) -> None:
    tables = generate(key).tables
    for source, table in tables.items():
        contract = io.TELEMETRY[source]
        assert table.schema.equals(io.arrow_schema(contract), check_metadata=False)
        io.encode(contract, table)  # validates nulls, NaN/inf, enums, patterns and unique keys
        assert table.num_rows > 0, source
    metrics = rows(key, "metrics")
    assert all(r["value"] > 0 for r in metrics)  # nothing is ever 0
    assert {r["source_system"] for r in metrics} == {"prom"}
    spans = rows(key, "spans")
    assert {r["service"] for r in spans} == set(lay.SERVICES)
    assert all(r["parent_span_id"] != "" for r in spans)


@pytest.mark.parametrize("key", CASE_KEYS)
def test_data_span_and_grid(key: str) -> None:
    times = [r["t_ns"] for r in rows(key, "metrics")]
    times += [r["t_ns"] for r in rows(key, "logs")] + [r["t_ns"] for r in rows(key, "events")]
    times += [r["end_ns"] for r in rows(key, "spans")]
    assert min(times) == lay.DATA_START_NS == T0
    assert max(times) == lay.DATA_END_NS == T0 + 1920 * NS
    scrapes = {t for t, _ in metric(key, "frontend", "container_cpu_usage_seconds_total")}
    assert scrapes == {T0 + k * 15 * NS for k in range(129)}  # last scrape exactly at T0 + 1920 s
    assert all(r["t_ns"] % (15 * NS) == 0 for r in rows(key, "metrics"))


def test_case_ids_and_names_resolve() -> None:
    adapter = SynthAdapter()
    assert isinstance(adapter, Adapter) and adapter.cacheable is False
    assert adapter.version == lay.ADAPTER_VERSION and adapter.datasets == ("synth",)
    assert make_case_id("synth-01") == "59e0d31bcc42"
    for key in CASE_KEYS:
        cid = make_case_id(key)
        for name in (key, cid):
            ref = adapter.resolve("synth", name, Path("unused"))
            assert (ref.case_id, ref.canonical_key, ref.location) == (cid, key, None)
        assert resolve_key(cid) == key
    assert adapter.list_cases("synth", Path("unused")) == sorted(make_case_id(c) for c in SYNTH_CASES)
    assert set(GENERATOR_VARIANTS) <= set(CASE_KEYS)  # every testing.VARIANTS generator variant exists
    with pytest.raises(UsageError):
        adapter.resolve("synth", "synth-06", Path("unused"))
    with pytest.raises(UsageError):
        adapter.resolve("synth", "abcdefabcdef", Path("unused"))
    with pytest.raises(UsageError):
        adapter.resolve("re2-ob", "synth-01", Path("unused"))


def test_entry_points_are_registered() -> None:
    from veyltrace_core import plugins

    assert isinstance(adapter_for("synth"), SynthAdapter)
    from veyltrace_core.synth.fetch import fetch

    assert plugins.load_one(plugins.FETCHERS, "synth") is fetch


@pytest.mark.parametrize("key", CASE_KEYS)
def test_convert_gives_the_canonical_case(key: str) -> None:
    adapter = SynthAdapter()
    ref = adapter.resolve("synth", key, Path("unused"))
    case = adapter.convert(ref, load_config("infralume"))
    assert isinstance(case, CanonicalCase)
    assert case.system == "other" and case.inputs == ()
    assert dict(case.sources_present) == {"metrics": True, "logs": True, "traces": True, "events": True}
    assert (case.adapter_name, case.adapter_version) == ("synth", lay.ADAPTER_VERSION)
    assert case.scrub == ("scrub-1", 0, 0)
    assert (case.t_alert_hint_ns, case.hint_source) == (T_INJECT, "oracle")
    assert adapter.alert_hint(ref) == (T_INJECT, "oracle")


@pytest.mark.parametrize("key", CASE_KEYS)
def test_pipeline_ingests_the_case(key: str, tmp_path: Path) -> None:
    """Through the pipeline (stub Infralume + core alert): manifest per synth_spec §5, oracle alert."""
    summary = execute(
        RunPlan(
            dataset="synth", case=key, to_step="alert", runs_root=tmp_path / "runs", code_commit="fixture"
        )
    )
    assert summary.outcome == "ok", (summary.failed_step, summary.reason, summary.error)
    assert summary.case_id == make_case_id(key)
    manifest = json.loads((summary.run_dir / "case_manifest.json").read_bytes())
    assert manifest["dataset"] == "synth" and manifest["system"] == "other"
    assert manifest["services"] == sorted(lay.SERVICES)  # the external host is not a service
    assert (manifest["data_start_ns"], manifest["data_end_ns"]) == (lay.DATA_START_NS, lay.DATA_END_NS)
    assert (manifest["t_alert_hint_ns"], manifest["hint_source"]) == (T_INJECT, "oracle")
    assert manifest["inputs"] == [] and manifest["adapter"] == {
        "name": "synth",
        "version": lay.ADAPTER_VERSION,
    }
    assert manifest["scrub"] == {"rules_version": "scrub-1", "dropped_attributes": 0, "dropped_rows": 0}
    assert all(manifest["sources"].values())
    alert = json.loads((summary.run_dir / "alert.json").read_bytes())
    assert alert["t_alert_ns"] == T_INJECT and alert["clamped"] is False
    assert alert["windows"] == {"baseline": list(BASELINE), "incident": list(INCIDENT)}
    for source, contract in io.TELEMETRY.items():
        written = io.read_table(contract, summary.run_dir)
        assert written.num_rows == getattr(generate(key).tables, source).num_rows


# --- leakage (01 §3.6 scrub-equivalent) ------------------------------------------------------------
def _leak_tokens() -> list[str]:
    tokens = [*CASE_KEYS, "synth-0", "inject", "fault", "chaos", "hog", "decoy", "answer", "truth", "oracle"]
    for key in CASE_KEYS:
        spec, variant = lay.case_spec(key)
        fault = variant.fault if variant is not None else spec.fault
        if fault.root_service is not None:
            tokens.append(fault.fault_id)
        tokens += list(fault.params)  # parameter names
    return sorted(set(tokens))


@pytest.mark.parametrize("key", CASE_KEYS)
def test_no_leakage_in_engine_visible_tables(key: str) -> None:
    tokens = _leak_tokens()
    deny_key = re.compile(r"(^feature_flag\.|(^|\.)(chaos|fault|inject)[^.]*)", re.IGNORECASE)
    for source in ("metrics", "logs", "spans", "events"):
        for row in rows(key, source):
            for column, value in row.items():
                if not isinstance(value, str):
                    continue
                low = value.lower()
                hits = [tok for tok in tokens if tok.lower() in low]
                assert not hits, (source, column, value, hits)
                if column in ("attrs_json", "detail_json"):
                    assert not any(deny_key.search(k) for k in json.loads(value)), (source, value)


def test_no_leakage_in_the_manifest(tmp_path: Path) -> None:
    summary = execute(
        RunPlan(
            dataset="synth", case="synth-03", to_step="infralume", runs_root=tmp_path, code_commit="fixture"
        )
    )
    text = (summary.run_dir / "case_manifest.json").read_text(encoding="utf-8")
    assert "synth-0" not in text
    assert not any(tok.lower() in text.lower() for tok in _leak_tokens() if tok != "oracle")


# --- topology, traffic and nesting (synth_spec §1; lead §2.11) ---------------------------------
@pytest.mark.parametrize("key", CASE_KEYS)
def test_topology_and_nesting(key: str) -> None:
    spans = rows(key, "spans")
    by_id = {(s["trace_id"], s["span_id"]): s for s in spans}
    edges: set[tuple[str, str]] = set()
    roots: Counter[str] = Counter()
    external = 0
    for s in spans:
        if s["parent_span_id"] is None:
            assert s["service"] == "frontend" and s["kind"] == "server"
            roots[s["trace_id"]] += 1
            continue
        parent = by_id[(s["trace_id"], s["parent_span_id"])]
        assert parent["start_ns"] <= s["start_ns"] < s["end_ns"] <= parent["end_ns"]
        if s["kind"] == "server":  # strictly inside: 1 ms gap each way
            assert parent["start_ns"] < s["start_ns"] and s["end_ns"] < parent["end_ns"]
        if parent["service"] != s["service"]:
            edges.add((parent["service"], s["service"]))
            assert parent["kind"] in ("client", "unspecified") and s["kind"] == "server"
        if s["attrs_json"] is not None:
            assert json.loads(s["attrs_json"]) == {"server.address": lay.EXTERNAL_HOST}
            assert s["service"] == "payment" and s["kind"] == "client"
            external += 1
    assert sorted(edges) == list(lay.EXPECTED_EDGES)  # no payment -> external edge (lead §2.11)
    assert set(roots.values()) == {1}
    # recommend's outgoing spans are kind=unspecified with exactly one child (client inference).
    children: Counter[tuple[str, str]] = Counter((s["trace_id"], s["parent_span_id"]) for s in spans)
    unspecified = [s for s in spans if s["kind"] == "unspecified"]
    assert unspecified and all(s["service"] == "recommend" for s in unspecified)
    assert all(children[(s["trace_id"], s["span_id"])] == 1 for s in unspecified)
    # The external host gets >= 10 client spans per window; no span ever has it as a service.
    for window in (BASELINE, INCIDENT):
        n = sum(1 for s in spans if s["attrs_json"] is not None and within(s["start_ns"], window))
        assert n >= 10
    assert external > 0


@pytest.mark.parametrize("key", ["synth-01", "synth-02", "synth-04", "synth-05"])
def test_server_span_counts_per_bucket_are_exact(key: str) -> None:
    per: dict[str, Counter[int]] = defaultdict(Counter)
    for s in servers(key):
        per[s["component"]][(s["start_ns"] - T0) // (10 * NS)] += 1
    expected = {"frontend": 30, "catalog": 45, "recommend": 15, "checkout": 9, "payment": 9}
    for component, n in expected.items():
        assert {per[component][b] for b in FULL_BUCKETS} == {n}, component
    cart = {per["cart-0"][b] + per["cart-1"][b] for b in FULL_BUCKETS}
    assert cart == {9}
    # Replicas alternate per checkout: 4 or 5 calls each per bucket, never below 4.
    assert {per["cart-0"][b] for b in FULL_BUCKETS} <= {4, 5}
    assert {per["cart-1"][b] for b in FULL_BUCKETS} <= {4, 5}


@pytest.mark.parametrize("key", CASE_KEYS)
def test_replicas_and_per_component_metrics(key: str) -> None:
    components = {r["component"] for r in rows(key, "metrics") if r["service"] == "cart"}
    assert components == {"cart-0", "cart-1"}
    names = {r["name"] for r in rows(key, "metrics")}
    assert names == {
        "container_cpu_usage_seconds_total",
        "container_memory_working_set_bytes",
        "http_requests_total",
        "http_server_duration_p99",
        "http_server_errors_total",
    }
    cpu = [r for r in rows(key, "metrics") if r["name"] == "container_cpu_usage_seconds_total"]
    assert {(r["metric_type"], r["unit"]) for r in cpu} == {
        ("counter", "s")
    }  # cpu stays a counter (lead §2.11)


@pytest.mark.parametrize("key", CASE_KEYS)
def test_logs(key: str) -> None:
    logs = rows(key, "logs")
    spans = {(s["trace_id"], s["span_id"]): s for s in rows(key, "spans")}
    for log in logs:
        if log["trace_id"] is not None:
            span = spans[(log["trace_id"], log["span_id"])]
            assert span["start_ns"] <= log["t_ns"] <= span["end_ns"]
    # log_rate > 0 in every 10 s bucket of every component (heartbeats every 5 s).
    silent = "cart-1" if key == "synth-05@silent" else None
    buckets: dict[str, set[int]] = defaultdict(set)
    for log in logs:
        buckets[log["component"]].add((log["t_ns"] - T0) // (10 * NS))
    for component in sorted(buckets):
        last = (T_INJECT - T0) // (10 * NS) if component == silent else 192
        assert set(range(last)) <= buckets[component], component
    healthz = Counter(log["t_ns"] for log in logs if log["body"] == "GET /healthz 200")
    assert healthz and set(healthz.values()) == {2}  # identical twin rows
    mentions = Counter(log["service"] for log in logs if "checkout:8080" in log["body"])
    assert set(mentions) == {"frontend"} and mentions["frontend"] >= 3
    mentions = Counter(log["service"] for log in logs if "http://catalog:3550" in log["body"])
    assert set(mentions) == {"recommend"} and mentions["recommend"] >= 3
    lexicon = re.compile(r"error|fail|timeout|refused|\b5\d\d\b", re.IGNORECASE)
    for log in logs:
        if log["severity"] in ("INFO", "WARN"):
            assert not lexicon.search(log["body"]), log["body"]
    if key != "synth-03":
        assert {log["severity"] for log in logs} <= {"INFO", "WARN"}


@pytest.mark.parametrize("key", CASE_KEYS)
def test_events(key: str) -> None:
    events = rows(key, "events")
    neutral = sorted((e["t_ns"], e["entity"], e["detail_json"]) for e in events if e["kind"] == "k8s_event")
    assert neutral == [
        (T0 + 30 * NS, "frontend", '{"reason":"Pulled"}'),
        (T0 + 1890 * NS, "frontend", '{"reason":"Scheduled"}'),  # lead §2.11: in every case
    ]
    changes = sorted((e["t_ns"], e["entity"], e["kind"]) for e in events if e["kind"] != "k8s_event")
    expected: dict[str, list[tuple[int, str, str]]] = {
        "synth-03": [(T0 + 60 * NS, "recommend", "config"), (T_INJECT - 240 * NS, "cart-1", "deploy")],
        "synth-04": [(T_INJECT - 60 * NS, "catalog", "deploy")],
    }
    assert changes == expected.get(key, [])
    assert {e["source_system"] for e in events} == {"k8s"}
    assert all(e["actor"] is None for e in events)


# --- per-case faults: onset at t_inject and magnitude -------------------------------------------
def _flat(key: str, component: str, name: str, *, counter: bool, tol: float = 0.06) -> None:
    points = metric(key, component, name)
    series = rates(points) if counter else points
    before, after = mean_in(series, BEFORE), mean_in(series, AFTER)
    assert abs(after - before) <= tol * before, (key, component, name, before, after)


def test_synth01_cpu_hog_on_checkout() -> None:
    key = "synth-01"
    cpu = rates(metric(key, "checkout", "container_cpu_usage_seconds_total"))
    assert all(abs(v - 0.15) <= 0.15 * 0.031 for t, v in cpu if t <= T_INJECT)
    assert all(abs(v - 3.5) <= 3.5 * 0.031 for t, v in cpu if t > T_INJECT)  # step at t_inject
    price = [s for s in rows(key, "spans") if s["operation"] == "price-order"]
    assert statistics.median(durations_ms(price, BEFORE)) == pytest.approx(8.0, rel=0.03)
    assert statistics.median(durations_ms(price, AFTER)) == pytest.approx(20.0, rel=0.03)
    # The hog reaches the entry: frontend's p99 rises by more than 3 x its ~3 ms baseline scale.
    frontend = servers(key, "frontend")
    p99 = [
        statistics.quantiles(durations_ms(frontend, window), n=100, method="inclusive")[98]
        for window in (BEFORE, AFTER)
    ]
    assert p99[1] - p99[0] >= 10.0, p99
    for component in ("cart-0", "cart-1", "catalog", "frontend", "payment", "recommend"):
        _flat(key, component, "container_cpu_usage_seconds_total", counter=True)
    for component in ("cart-0", "payment"):  # callees unchanged
        for window in (BEFORE, AFTER):
            assert statistics.median(durations_ms(servers(key, component), window)) == pytest.approx(
                4.0 if component == "cart-0" else 26.0, rel=0.05
            )
    assert not any(s["status"] == "error" for s in rows(key, "spans"))


def test_synth02_delay_on_recommend_egress() -> None:
    key = "synth-02"
    for caller, callee in (("frontend", "recommend"), ("recommend", "catalog")):
        assert statistics.median(gaps_ms(key, caller, callee, BEFORE)) == pytest.approx(2.0, abs=0.01)
        assert statistics.median(gaps_ms(key, caller, callee, AFTER)) == pytest.approx(102.0, abs=0.01)
        assert min(gaps_ms(key, caller, callee, AFTER)) >= 100.0
    assert statistics.median(gaps_ms(key, "frontend", "catalog", AFTER)) == pytest.approx(2.0, abs=0.01)
    catalog = servers(key, "catalog")
    assert statistics.median(durations_ms(catalog, AFTER)) == pytest.approx(
        statistics.median(durations_ms(catalog, BEFORE)), rel=0.03
    )  # catalog server spans flat
    for name, counter in (
        ("container_cpu_usage_seconds_total", True),
        ("container_memory_working_set_bytes", False),
    ):
        _flat(key, "recommend", name, counter=counter)
        _flat(key, "catalog", name, counter=counter)


def test_synth03_exception_on_payment() -> None:
    key = "synth-03"

    def error_share(service: str, window: tuple[int, int]) -> float:
        spans = [s for s in servers(key, service=service) if within(s["start_ns"], window)]
        return sum(s["status"] == "error" for s in spans) / len(spans)

    assert error_share("payment", BEFORE) == 0.0
    assert error_share("payment", AFTER) == pytest.approx(0.6, abs=0.01)
    assert error_share("checkout", AFTER) == pytest.approx(0.36, abs=0.01)
    assert error_share("frontend", AFTER) == pytest.approx(0.108, abs=0.005)
    assert error_share("cart", AFTER) == error_share("catalog", AFTER) == 0.0
    # Failures are spread evenly: every 10 s bucket after t_inject has 8-10 failed payment calls
    # (first attempts and retries) and 3-4 failed checkouts, so 3-bucket persistence holds from
    # t_inject (R-03 review).
    for service, low, high in (("payment", 8, 10), ("checkout", 3, 4)):
        per_bucket: dict[int, int] = {}
        for s in servers(key, service=service):
            if within(s["start_ns"], AFTER):
                bucket = (s["start_ns"] - T_INJECT) // (10 * NS)
                per_bucket[bucket] = per_bucket.get(bucket, 0) + (s["status"] == "error")
        counts = [per_bucket[b] for b in sorted(per_bucket)[:-1]]  # the last bucket may be partial
        assert counts and all(low <= c <= high for c in counts), (service, counts)
    errored = [s for s in servers(key, service="payment") if s["status"] == "error"]
    assert min(s["start_ns"] for s in errored) >= T_INJECT
    assert {s["status_code"] for s in errored} == {500}
    errors = [log for log in rows(key, "logs") if log["severity"] == "ERROR"]
    assert errors and {log["service"] for log in errors} == {"payment"}
    assert min(log["t_ns"] for log in errors) >= T_INJECT
    assert all(
        log["body"].startswith("CardValidationException: invalid token for order ")
        and log["body"].endswith("\n    at com.shop.Pay.validate(Pay.java:42)")
        for log in errors
    )
    retries = [
        log for log in rows(key, "logs") if log["body"].startswith(("retrying charge", "charge gave up"))
    ]
    assert retries and {(log["service"], log["severity"]) for log in retries} == {("checkout", "WARN")}
    assert min(log["t_ns"] for log in retries) >= T_INJECT
    # The decoy is a minor bump like synth-04's true change: the version step is no label cue.
    (decoy,) = [e for e in rows(key, "events") if e["kind"] == "deploy"]
    assert json.loads(decoy["detail_json"]) == {
        "from": "cart:2.3.1", "image": "registry.local/cart", "to": "cart:2.4.0"
    }  # fmt: skip
    # The decoy deploy on cart-1 has no effect on cart-1.
    for name, counter in (
        ("container_cpu_usage_seconds_total", True),
        ("container_memory_working_set_bytes", False),
    ):
        _flat(key, "cart-1", name, counter=counter)


def test_synth04_change_regression_on_catalog() -> None:
    key = "synth-04"
    mem = metric(key, "catalog", "container_memory_working_set_bytes")
    assert all(abs(v - 200e6) <= 200e6 * 0.031 for t, v in mem if t < T_INJECT)
    assert all(abs(v - 520e6) <= 520e6 * 0.031 for t, v in mem if t >= T_INJECT)
    catalog = servers(key, "catalog")
    assert statistics.median(durations_ms(catalog, BEFORE)) == pytest.approx(10.0, rel=0.03)
    assert statistics.median(durations_ms(catalog, AFTER)) == pytest.approx(40.0, rel=0.03)
    deploys = [e for e in rows(key, "events") if e["kind"] == "deploy"]
    assert [e["t_ns"] for e in deploys] == [T_INJECT - 60 * NS]
    assert json.loads(deploys[0]["detail_json"]) == {
        "from": "catalog:1.4.2", "image": "registry.local/catalog", "to": "catalog:1.5.0"
    }  # fmt: skip
    _flat(key, "catalog", "container_cpu_usage_seconds_total", counter=True)


def test_synth05_is_stationary() -> None:
    key = "synth-05"
    components = sorted({r["component"] for r in rows(key, "metrics")})
    for component in components:
        _flat(key, component, "container_cpu_usage_seconds_total", counter=True)
        _flat(key, component, "container_memory_working_set_bytes", counter=False)
        _flat(key, component, "http_requests_total", counter=True, tol=0.02)
        before = statistics.median(durations_ms(servers(key, component), BEFORE))
        assert statistics.median(durations_ms(servers(key, component), AFTER)) == pytest.approx(
            before, rel=0.05
        )
    assert not any(s["status"] == "error" for s in rows(key, "spans"))
    assert not [e for e in rows(key, "events") if e["kind"] != "k8s_event"]


def test_silent_variant_stops_cart1_at_t_inject() -> None:
    key = "synth-05@silent"
    for source, column in (("metrics", "t_ns"), ("logs", "t_ns"), ("spans", "start_ns")):
        cart1 = [r[column] for r in rows(key, source) if r.get("component") == "cart-1"]
        assert cart1 and max(cart1) < T_INJECT, source
        cart0 = [r[column] for r in rows(key, source) if r.get("component") == "cart-0"]
        assert max(cart0) >= T0 + 1900 * NS, source
    # checkout still calls cart: client spans whose cart-1 child is gone.
    spans = rows(key, "spans")
    parents = {(s["trace_id"], s["parent_span_id"]) for s in spans}
    orphan_calls = [
        s
        for s in spans
        if s["operation"] == "GET /cart"
        and s["kind"] == "client"
        and (s["trace_id"], s["span_id"]) not in parents
    ]
    assert orphan_calls and min(s["start_ns"] for s in orphan_calls) >= T_INJECT
    assert {s["service"] for s in spans} == set(lay.SERVICES)
