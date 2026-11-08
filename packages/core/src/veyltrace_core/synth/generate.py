"""Generate the canonical telemetry of one synth case: metrics, logs, spans and events.

How the data is built (synth_spec §1–§4; M0 lead decision 2026-11-06 §2.11):
- **Schedule is arithmetic.** Request i starts at T0 + 1 s + i/3 s; it calls recommend iff
  i % 2 == 0 and checkout iff i % 10 < 3; the n-th checkout reads cart replica n % 2. So every
  10 s bucket holds exactly 30 frontend, 45 catalog, 15 recommend and 9 checkout/cart/payment
  server spans, whatever the seed.
- **Noise is seeded.** Durations (lognormal, sigma 0.15, clipped at 2.5 sigma) and metric noise
  (U[0.97, 1.03]) come from `veyltrace_core.rng.rng(case_id, purpose)` keyed by the *base* case, so
  a generator variant (synth-05@silent) equals its base case everywhere its change does not apply.
  Each trace owns fixed draw slots, so a span's duration never depends on which other spans exist.
- **Faults are steps at t_inject**, applied to traces that start at or after it and to metric
  scrapes at or after it; they persist to the end of the data.

Engine-visible text never names the case, the fault or a parameter: log bodies, operations and
event details are written as a real system would write them (leakage test in test_synth.py).
"""

from __future__ import annotations

import bisect
import functools
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np
import pyarrow as pa

from veyltrace_core import io
from veyltrace_core.canonical import canonical_json_str
from veyltrace_core.ids import case_id as make_case_id
from veyltrace_core.io import TelemetryTables
from veyltrace_core.rng import rng
from veyltrace_core.synth import layout as lay

__all__ = ["SynthTelemetry", "generate"]

#: Duration draws per trace: one fixed slot per span role (see _Slot).
_SLOTS: Final = 11
#: Log bodies: numbers are the variable parts a template miner masks.
_HEALTHZ_BODY: Final = "GET /healthz 200"
_STACK_FRAME: Final = "\n    at com.shop.Pay.validate(Pay.java:42)"
#: A payment attempt throws on a low-discrepancy (Beatty) pattern: attempt 1 of checkout ordinal n
#: iff floor((n + 1) * 3/5) > floor(n * 3/5), the retry by the same rule over the retry ordinal j.
#: That is 60% of first attempts and 36% of checkouts, spread so that every 10 s bucket holds
#: failures (a block pattern such as n % 5 < 3, (n // 5) % 5 < 3 leaves ~11 s failure-free gaps
#: that break 3-bucket persistence; R-03 review).
_THROW_PERIOD: Final = 5
#: Baseline WARN lines (no error-lexicon word): every 40th catalog and every 20th checkout request.
_CATALOG_WARN_EVERY: Final = 40
_CHECKOUT_WARN_EVERY: Final = 20


class _Slot:
    FRONTEND = 0
    CATALOG = 1
    RECOMMEND = 2
    CATALOG_VIA_RECOMMEND = 3
    CHECKOUT = 4
    PRICE_ORDER = 5
    CART = 6
    PAYMENT_1 = 7
    EXTERNAL_1 = 8
    PAYMENT_2 = 9
    EXTERNAL_2 = 10


@dataclass(frozen=True)
class SynthTelemetry:
    """The generated tables of one canonical key (a case or a generator variant)."""

    key: str
    case_id: str
    tables: TelemetryTables


@dataclass
class _Server:
    """Server spans of one component, for the metrics derived from them."""

    starts: list[int] = field(default_factory=lambda: [])
    durations_ms: list[float] = field(default_factory=lambda: [])
    error_starts: list[int] = field(default_factory=lambda: [])


def _columns(contract: str) -> dict[str, list[Any]]:
    return {name: [] for name in io.arrow_schema(contract).names}


def _table(contract: str, columns: Mapping[str, list[Any]]) -> pa.Table:
    return pa.Table.from_pydict(dict(columns), schema=io.arrow_schema(contract))


def _ms(ns: int) -> int:
    """Whole milliseconds for log text."""
    return ns // lay.MS


class _Generator:
    def __init__(self, key: str) -> None:
        spec, variant = lay.case_spec(key)
        self.key = key
        self.spec = spec
        self.fault = spec.fault
        self.params = spec.fault.params
        self.silent = variant.silent_component if variant is not None else None
        self.base_id = make_case_id(spec.name)
        self.spans = _columns("telemetry.spans")
        self.logs = _columns("telemetry.logs")
        self.server: dict[str, _Server] = {c: _Server() for cs in lay.COMPONENTS.values() for c in cs}
        self.catalog_requests = 0
        self.retries = 0
        gen = rng(self.base_id, "synth.ids")
        self.trace_prefix = f"{int(gen.bit_generator.random_raw()) & 0xFFFFFFFF:08x}"
        self.n_traces = (
            lay.SPAN_S - lay.LAST_REQUEST_MARGIN_S - lay.FIRST_REQUEST_S
        ) * lay.REQUESTS_PER_S + 1
        z = rng(self.base_id, "synth.durations").standard_normal((self.n_traces, _SLOTS))
        self.factor = np.exp(lay.SIGMA * np.clip(z, -lay.CLIP_SIGMA, lay.CLIP_SIGMA))
        self.gap = round(lay.GAP_MS * lay.MS)

    # --- helpers ----------------------------------------------------------------------------
    def _visible(self, component: str, t_ns: int) -> bool:
        return not (component == self.silent and t_ns >= lay.T_INJECT_NS)

    def _dur(self, ms: float, trace: int, slot: int) -> int:
        quantum = lay.DURATION_QUANTUM_NS
        return round(ms * float(self.factor[trace, slot]) * lay.MS / quantum) * quantum

    def _span(
        self,
        trace_id: str,
        span_id: str,
        parent: str | None,
        component: str,
        operation: str,
        kind: str,
        start: int,
        end: int,
        *,
        error: bool = False,
        status: str | None = None,
        attrs: Mapping[str, str] | None = None,
    ) -> None:
        if not self._visible(component, start):
            return
        service = _service_of(component)
        row = self.spans
        row["trace_id"].append(trace_id)
        row["span_id"].append(span_id)
        row["parent_span_id"].append(parent)
        row["service"].append(service)
        row["component"].append(component)
        row["operation"].append(operation)
        row["kind"].append(kind)
        row["start_ns"].append(start)
        row["end_ns"].append(end)
        if status == "unset":
            row["status"].append("unset")
            row["status_code"].append(None)
        else:
            row["status"].append("error" if error else "ok")
            row["status_code"].append(500 if error else 200)
        row["attrs_json"].append(None if attrs is None else canonical_json_str(dict(attrs)))
        if kind == "server":
            srv = self.server[component]
            srv.starts.append(start)
            srv.durations_ms.append((end - start) / lay.MS)
            if error:
                srv.error_starts.append(start)

    def _log(
        self,
        component: str,
        t_ns: int,
        severity: str,
        body: str,
        trace_id: str | None = None,
        span_id: str | None = None,
    ) -> None:
        if not self._visible(component, t_ns):
            return
        row = self.logs
        row["t_ns"].append(t_ns)
        row["service"].append(_service_of(component))
        row["component"].append(component)
        row["severity"].append(severity)
        row["body"].append(body)
        row["trace_id"].append(trace_id)
        row["span_id"].append(span_id)
        row["attrs_json"].append(None)

    # --- one trace ----------------------------------------------------------------------------
    def _catalog(
        self, i: int, tid: str, sid: _Ids, parent: str, call_start: int, slot: int, delay: int
    ) -> int:
        """Catalog's server span for a client span starting at call_start; returns its end."""
        cat_ms = lay.SELF_MS["catalog"]
        if self.fault.kind == "change" and self._faulted(i):
            cat_ms = float(self.params["self_ms_to"])
        span = sid.next()
        start = call_start + self.gap + delay
        duration = self._dur(cat_ms, i, slot)
        end = start + duration
        n = self.catalog_requests
        self.catalog_requests += 1
        mid = start + duration // 2
        self._log("catalog", mid, "INFO", f"listed {12 + n % 30} items for query {n % 97}", tid, span)
        if n % _CATALOG_WARN_EVERY == _CATALOG_WARN_EVERY - 1:
            self._log("catalog", mid, "WARN", f"slow index scan on items took {_ms(duration)}ms", tid, span)
        self._span(tid, span, parent, "catalog", "GET /items", "server", start, end)
        return end

    def _faulted(self, i: int) -> bool:
        return self._start(i) >= lay.T_INJECT_NS

    def _start(self, i: int) -> int:
        return lay.T0_NS + lay.FIRST_REQUEST_S * lay.NS + (i * lay.NS) // lay.REQUESTS_PER_S

    def _payment(
        self,
        i: int,
        tid: str,
        sid: _Ids,
        parent: str,
        call_start: int,
        attempt: int,
        throws: bool,
        order: int,
    ) -> int:
        """checkout -> payment call (and payment -> external host); returns the client span end."""
        slot_self, slot_ext = (
            (_Slot.PAYMENT_1, _Slot.EXTERNAL_1) if attempt == 1 else (_Slot.PAYMENT_2, _Slot.EXTERNAL_2)
        )
        client, server = sid.next(), sid.next()
        start = call_start + self.gap
        self_ns = self._dur(lay.SELF_MS["payment"], i, slot_self)
        half = self_ns // 2
        if throws:
            end = start + self_ns
            body = f"CardValidationException: invalid token for order {order}{_STACK_FRAME}"
            self._log("payment", start + half, "ERROR", body, tid, server)
        else:
            ext = sid.next()
            ext_start = start + half
            ext_end = ext_start + self._dur(lay.SELF_MS["external"], i, slot_ext)
            self._span(
                tid, ext, server, "payment", "POST /v1/charge", "client", ext_start, ext_end,
                attrs={"server.address": lay.EXTERNAL_HOST},
            )  # fmt: skip
            self._log("payment", ext_start, "INFO", f"tokenized card for order {order}", tid, server)
            end = ext_end + (self_ns - half)
            self._log(
                "payment",
                end,
                "INFO",
                f"charged order {order} amount {1500 + order % 900} cents",
                tid,
                server,
            )
        self._span(tid, server, client, "payment", "POST /charge", "server", start, end, error=throws)
        client_end = end + self.gap
        self._span(
            tid, client, parent, "checkout", "POST /charge", "client", call_start, client_end, error=throws
        )
        return client_end

    def _checkout(
        self, i: int, n: int, tid: str, sid: _Ids, parent: str, call_start: int
    ) -> tuple[int, bool]:
        """frontend -> checkout call; returns (client span end, whether the checkout failed)."""
        client, server = sid.next(), sid.next()
        order = 100_000 + n
        start = call_start + self.gap
        self_ns = self._dur(lay.SELF_MS["checkout"], i, _Slot.CHECKOUT)
        half = self_ns // 2
        self._log(
            "checkout", start + half, "INFO", f"placed order {order} with {1 + n % 5} items", tid, server
        )
        if n % _CHECKOUT_WARN_EVERY == _CHECKOUT_WARN_EVERY - 1:
            self._log(
                "checkout", start + half, "WARN", f"stock reservation queued for order {order}", tid, server
            )
        price_ms = lay.SELF_MS["price-order"]
        if self.fault.kind == "cpu" and self._faulted(i):
            price_ms = float(self.params["price_order_ms_to"])
        price = sid.next()
        price_start = start + half
        price_end = price_start + self._dur(price_ms, i, _Slot.PRICE_ORDER)
        self._span(
            tid, price, server, "checkout", "price-order", "internal", price_start, price_end, status="unset"
        )
        self._log(
            "checkout",
            price_end,
            "INFO",
            f"priced order {order} in {_ms(price_end - price_start)}ms",
            tid,
            price,
        )
        # cart, on replica n % 2
        replica = lay.COMPONENTS["cart"][n % lay.CART_REPLICAS]
        cart_client, cart_server = sid.next(), sid.next()
        cart_start = price_end + self.gap
        cart_ns = self._dur(lay.SELF_MS["cart"], i, _Slot.CART)
        cart_end = cart_start + cart_ns
        self._log(
            replica,
            cart_start + cart_ns // 2,
            "INFO",
            f"cart {order} holds {1 + n % 5} items",
            tid,
            cart_server,
        )
        self._span(tid, cart_server, cart_client, replica, "GET /cart", "server", cart_start, cart_end)
        cart_client_end = cart_end + self.gap
        self._span(tid, cart_client, server, "checkout", "GET /cart", "client", price_end, cart_client_end)
        # payment, with one retry when an attempt throws
        throwing = self.fault.kind == "exception" and self._faulted(i)
        share = round(float(self.params["throw_share"]) * _THROW_PERIOD) if throwing else 0
        throws_1 = throwing and _beatty(n, share, _THROW_PERIOD)
        last = self._payment(i, tid, sid, server, cart_client_end, 1, throws_1, order)
        failed = throws_1
        if throws_1:
            self._log("checkout", last, "WARN", f"retrying charge for order {order} attempt 2", tid, server)
            failed = _beatty(self.retries, share, _THROW_PERIOD)
            self.retries += 1
            last = self._payment(i, tid, sid, server, last, 2, failed, order)
            if failed:
                self._log("checkout", last, "WARN", f"charge gave up for order {order}", tid, server)
        end = last + (self_ns - half)
        self._span(tid, server, client, "checkout", "POST /checkout", "server", start, end, error=failed)
        client_end = end + self.gap
        self._span(
            tid, client, parent, "frontend", "POST /checkout", "client", call_start, client_end, error=failed
        )
        return client_end, failed

    def _recommend(self, i: int, tid: str, sid: _Ids, parent: str, call_start: int) -> int:
        """frontend -> recommend call (recommend -> catalog uses kind unspecified); returns its end."""
        delay = 0
        if self.fault.kind == "delay" and self._faulted(i):
            delay = round(float(self.params["egress_delay_ms"]) * lay.MS)
        client, server, outgoing = sid.next(), sid.next(), sid.next()
        start = call_start + self.gap
        self_ns = self._dur(lay.SELF_MS["recommend"], i, _Slot.RECOMMEND)
        half = self_ns // 2
        out_start = start + half
        catalog_end = self._catalog(i, tid, sid, outgoing, out_start, _Slot.CATALOG_VIA_RECOMMEND, delay)
        out_end = catalog_end + self.gap
        self._span(tid, outgoing, server, "recommend", "GET /items", "unspecified", out_start, out_end)
        body = f"GET http://catalog:3550/items {_ms(out_end - out_start)}ms"
        self._log("recommend", out_end, "INFO", body, tid, server)
        end = out_end + (self_ns - half)
        product = 1000 + (i * 37) % 900
        self._log(
            "recommend",
            out_start,
            "INFO",
            f"served {3 + i % 4} recommendations for product {product}",
            tid,
            server,
        )
        self._span(tid, server, client, "recommend", "GET /recommendations", "server", start, end)
        client_end = end + self.gap + delay
        self._span(tid, client, parent, "frontend", "GET /recommendations", "client", call_start, client_end)
        return client_end

    def _trace(self, i: int, checkouts: int) -> None:
        tid = f"{self.trace_prefix}{i:024x}"
        sid = _Ids(i)
        root = sid.next()
        start = self._start(i)
        self_ns = self._dur(lay.SELF_MS["frontend"], i, _Slot.FRONTEND)
        half = self_ns // 2
        t = start + half
        # frontend -> catalog
        client = sid.next()
        catalog_end = self._catalog(i, tid, sid, client, t, _Slot.CATALOG, 0)
        self._span(tid, client, root, "frontend", "GET /items", "client", t, catalog_end + self.gap)
        t = catalog_end + self.gap
        if i % lay.RECOMMEND_EVERY == 0:
            t = self._recommend(i, tid, sid, root, t)
        failed = False
        if i % lay.CHECKOUT_PERIOD < lay.CHECKOUT_SHARE:
            call_start = t
            t, failed = self._checkout(i, checkouts, tid, sid, root, t)
            body = f"upstream checkout:8080 responded in {_ms(t - call_start)}ms"
            self._log("frontend", t, "INFO", body, tid, root)
        end = t + (self_ns - half)
        product = 1000 + (i * 37) % 900
        body = f"request GET /product/{product} took {_ms(end - start)}ms"
        self._log("frontend", start + half, "INFO", body, tid, root)
        self._span(tid, root, None, "frontend", "GET /product", "server", start, end, error=failed)

    # --- whole case ---------------------------------------------------------------------------
    def _heartbeats(self) -> None:
        components = sorted(c for cs in lay.COMPONENTS.values() for c in cs)
        beats = lay.SPAN_S // lay.HEARTBEAT_S + 1  # T0 .. T0 + 1920 s inclusive
        for idx, component in enumerate(components):
            for k in range(beats):
                t = lay.T0_NS + k * lay.HEARTBEAT_S * lay.NS
                body = f"cache stats hits={800 + (k * 53 + idx * 17) % 200} misses={5 + (k * 7 + idx) % 20}"
                self._log(component, t, "INFO", body)
        for k in range(lay.SPAN_S // lay.HEALTHZ_S + 1):
            t = lay.T0_NS + k * lay.HEALTHZ_S * lay.NS + lay.HEALTHZ_OFFSET_NS
            if t > lay.DATA_END_NS:
                break
            self._log("frontend", t, "INFO", _HEALTHZ_BODY)
            self._log("frontend", t, "INFO", _HEALTHZ_BODY)  # identical twin row: writer tie-break

    def _metrics(self) -> pa.Table:
        cols = _columns("telemetry.metrics")
        components = sorted(c for cs in lay.COMPONENTS.values() for c in cs)
        scrapes = lay.SPAN_S // lay.SCRAPE_S + 1  # the last one exactly at T0 + 1920 s
        noise = rng(self.base_id, "synth.metrics").uniform(
            lay.NOISE_LOW, lay.NOISE_HIGH, size=(len(components), 2, scrapes)
        )
        window = lay.SCRAPE_S * lay.NS

        def add(component: str, name: str, metric_type: str, unit: str, t: int, value: float) -> None:
            if not self._visible(component, t):
                return
            cols["t_ns"].append(t)
            cols["service"].append(_service_of(component))
            cols["component"].append(component)
            cols["name"].append(name)
            cols["metric_type"].append(metric_type)
            cols["attrs_json"].append(None)
            cols["value"].append(value)
            cols["unit"].append(unit)
            cols["source_system"].append("prom")

        for idx, component in enumerate(components):
            srv = self.server[component]
            order = sorted(range(len(srv.starts)), key=lambda j: srv.starts[j])
            starts = [srv.starts[j] for j in order]
            durations = [srv.durations_ms[j] for j in order]
            errors = sorted(srv.error_starts)
            cpu = lay.CPU_COUNTER_START_S + 10.0 * idx
            for k in range(scrapes):
                t = lay.T0_NS + k * window
                if k:
                    cpu += self._cpu_cores(component, t - window) * lay.SCRAPE_S * float(noise[idx, 0, k])
                add(component, "container_cpu_usage_seconds_total", "counter", "s", t, round(cpu, 6))
                mem = self._mem_mb(component, t) * lay.MB * float(noise[idx, 1, k])
                add(component, "container_memory_working_set_bytes", "gauge", "bytes", t, float(round(mem)))
                handled = bisect.bisect_left(starts, t)
                add(component, "http_requests_total", "counter", "1", t, lay.REQUEST_COUNTER_START + handled)
                failed = bisect.bisect_left(errors, t)
                add(
                    component, "http_server_errors_total", "counter", "1", t, lay.ERROR_COUNTER_START + failed
                )
                recent = durations[bisect.bisect_left(starts, t - window) : handled]
                if recent:
                    p99 = float(np.percentile(np.asarray(recent, dtype=np.float64), 99, method="linear"))
                    add(component, "http_server_duration_p99", "gauge", "ms", t, round(p99, 3))
        return _table("telemetry.metrics", cols)

    def _cpu_cores(self, component: str, interval_start: int) -> float:
        if (
            self.fault.kind == "cpu"
            and component == self.fault.root_service
            and interval_start >= lay.T_INJECT_NS
        ):
            return float(self.params["cpu_cores_to"])
        return lay.BASE_CPU_CORES[component]

    def _mem_mb(self, component: str, t: int) -> float:
        if self.fault.kind == "change" and component == self.fault.root_service and t >= lay.T_INJECT_NS:
            return float(self.params["mem_mb_to"])
        return lay.BASE_MEM_MB[component]

    def _events(self) -> pa.Table:
        cols = _columns("telemetry.events")
        rows: list[tuple[int, str, str, Mapping[str, str]]] = [
            (lay.PULLED_OFFSET_S, "frontend", "k8s_event", {"reason": "Pulled"}),
            (lay.SCHEDULED_OFFSET_S, "frontend", "k8s_event", {"reason": "Scheduled"}),
        ]
        rows += [(c.offset_s, c.entity, c.kind, c.detail) for c in self.spec.changes]
        for offset_s, entity, kind, detail in rows:
            cols["t_ns"].append(lay.T0_NS + offset_s * lay.NS)
            cols["entity"].append(entity)
            cols["kind"].append(kind)
            cols["source_system"].append("k8s")
            cols["detail_json"].append(canonical_json_str(dict(detail)))
            cols["actor"].append(None)
        return _table("telemetry.events", cols)

    def run(self) -> TelemetryTables:
        checkouts = 0
        for i in range(self.n_traces):
            self._trace(i, checkouts)
            if i % lay.CHECKOUT_PERIOD < lay.CHECKOUT_SHARE:
                checkouts += 1
        self._heartbeats()
        return TelemetryTables(
            metrics=self._metrics(),
            logs=_table("telemetry.logs", self.logs),
            spans=_table("telemetry.spans", self.spans),
            events=self._events(),
        )


class _Ids:
    """16-hex span ids: 10 hex of the trace index, 6 hex of the span's position in the trace."""

    def __init__(self, trace: int) -> None:
        self.trace = trace
        self.n = 0

    def next(self) -> str:
        self.n += 1
        return f"{self.trace:010x}{self.n:06x}"


def _beatty(k: int, num: int, den: int) -> bool:
    """True for a share num/den of ordinals k, as evenly spread as integers allow."""
    return ((k + 1) * num) // den > (k * num) // den


def _service_of(component: str) -> str:
    for service in lay.SERVICES:
        if component in lay.COMPONENTS[service]:
            return service
    msg = f"unknown synth component {component!r}"
    raise KeyError(msg)


@functools.lru_cache(maxsize=8)
def generate(key: str) -> SynthTelemetry:
    """Telemetry of the synth case or generator variant `key` (e.g. "synth-01", "synth-05@silent").

    Pure and deterministic: the same key gives byte-identical tables on every run and machine.
    Results are cached per process (tables are immutable); `generate.cache_clear()` drops them.
    """
    tables = _Generator(key).run()
    return SynthTelemetry(key=key, case_id=make_case_id(key), tables=tables)
