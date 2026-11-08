"""The synth toy system, its timing grid and the five cases' fault specifications (synth_spec §1–§4,
amended by M0 lead decision 2026-11-06 §2.11).

Why one module holds both the system and the faults: the generator (`generate`) and the answer keys
(`truth`) must read the same numbers, so the injection parameters written to `answer_key` are the
ones that produced the telemetry. Nothing here is engine-visible: engines are AST-banned from
importing `veyltrace_core.synth` (isolation test), and the generated tables never contain a case
name, a fault id or a parameter name (leakage test).

Every value is a priori (synth_spec; magnitudes tuned once against the golden checklist, then
frozen). Changing any of them changes every producer's fixtures: bump `ADAPTER_VERSION` and
regenerate in pipeline order (synth_spec D-S9).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Literal

__all__ = [
    "ADAPTER_NAME",
    "ADAPTER_VERSION",
    "BASE_CPU_CORES",
    "BASE_MEM_MB",
    "CASES",
    "CASE_NAMES",
    "COMPONENTS",
    "DATASET",
    "DATA_END_NS",
    "DATA_START_NS",
    "EXPECTED_EDGES",
    "EXTERNAL_HOST",
    "GENERATOR_VARIANTS",
    "MS",
    "NS",
    "SERVICES",
    "SYSTEM",
    "T0_NS",
    "T_INJECT_NS",
    "CaseSpec",
    "ChangeEvent",
    "Fault",
    "FaultKind",
    "GeneratorVariant",
    "case_spec",
    "variant_key",
]

NS: Final = 1_000_000_000
MS: Final = 1_000_000

# --- adapter identity (synth_spec §5) -----------------------------------------------------------
DATASET: Final = "synth"
ADAPTER_NAME: Final = "synth"
#: Per-adapter revision (D-21). Bump on any generator change (synth_spec D-S9).
ADAPTER_VERSION: Final = "2"
SYSTEM: Final = "other"
SCRUB_RULES_VERSION: Final = "scrub-1"

# --- time grid (synth_spec §2) --------------------------------------------------------------------
#: 2026-01-01T00:00:00Z; divisible by 10, 15 and 30 s.
T0_NS: Final = 1_767_225_600 * NS
SPAN_S: Final = 1920
DATA_START_NS: Final = T0_NS
#: The last metric scrape lands exactly here (lead §2.11), so data_end_ns = T0 + 1920 s.
DATA_END_NS: Final = T0_NS + SPAN_S * NS
INJECT_OFFSET_S: Final = 1320
#: Injection start and oracle hint (synth-05 uses the same placed alert time).
T_INJECT_NS: Final = T0_NS + INJECT_OFFSET_S * NS
SCRAPE_S: Final = 15
HEARTBEAT_S: Final = 5
HEALTHZ_S: Final = 60
#: The two identical healthz rows sit half a second after each minute (writer tie-break test).
HEALTHZ_OFFSET_NS: Final = 500 * MS
#: Neutral k8s events in every case: "Pulled" early, "Scheduled" late (lead §2.11), so an
#: events-only variant still spans both default windows.
PULLED_OFFSET_S: Final = 30
SCHEDULED_OFFSET_S: Final = 1890

# --- traffic (synth_spec §1; lead §2.11: deterministic scheduling by request index) ------------
REQUESTS_PER_S: Final = 3
FIRST_REQUEST_S: Final = 1
#: No trace starts later than DATA_END - 5 s; the longest trace (synth-02, two 100 ms delays and a
#: retry) stays far below 1 s, so no span ends after the last scrape.
LAST_REQUEST_MARGIN_S: Final = 5
#: Request i calls recommend iff i % RECOMMEND_EVERY == 0 (50%).
RECOMMEND_EVERY: Final = 2
#: Request i calls checkout iff i % CHECKOUT_PERIOD < CHECKOUT_SHARE (30%).
CHECKOUT_PERIOD: Final = 10
CHECKOUT_SHARE: Final = 3
#: The n-th checkout (0-based ordinal) reads cart replica n % 2, so every 10 s bucket gets 4 or 5
#: calls per replica (a split by i % 2 would give 6 and 3; decision recorded in the R-03 PR).
CART_REPLICAS: Final = 2

# --- topology (synth_spec §1; lead §2.11: no payment -> external edge) ---------------------------
SERVICES: Final[tuple[str, ...]] = ("cart", "catalog", "checkout", "frontend", "payment", "recommend")
#: service -> components; cart runs two statefulset replicas for peer contrast.
COMPONENTS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "cart": ("cart-0", "cart-1"),
        "catalog": ("catalog",),
        "checkout": ("checkout",),
        "frontend": ("frontend",),
        "payment": ("payment",),
        "recommend": ("recommend",),
    }
)
EXTERNAL_HOST: Final = "card-gateway.example"
#: Caller -> callee pairs produced by the spans; the external host is a node with no edge.
EXPECTED_EDGES: Final[tuple[tuple[str, str], ...]] = (
    ("checkout", "cart"),
    ("checkout", "payment"),
    ("frontend", "catalog"),
    ("frontend", "checkout"),
    ("frontend", "recommend"),
    ("recommend", "catalog"),
)

# --- durations (synth_spec §1) -------------------------------------------------------------------
#: Median self time per span role, ms (lognormal, sigma below, clipped at +-2.5 sigma).
SELF_MS: Final[Mapping[str, float]] = MappingProxyType(
    {
        "frontend": 5.0,
        "recommend": 6.0,
        "catalog": 10.0,
        "checkout": 4.0,
        "price-order": 8.0,
        "cart": 4.0,
        "payment": 6.0,
        "external": 20.0,
    }
)
SIGMA: Final = 0.15
CLIP_SIGMA: Final = 2.5
#: One-way network gap, symmetric: every child span lies strictly inside its parent.
GAP_MS: Final = 1.0
#: Durations are rounded to whole microseconds, so a last-ulp difference in exp() between libms
#: (Windows laptops vs Linux CI) cannot change an integer nanosecond.
DURATION_QUANTUM_NS: Final = 1_000

# --- metrics (synth_spec §3) ---------------------------------------------------------------------
BASE_CPU_CORES: Final[Mapping[str, float]] = MappingProxyType(
    {
        "cart-0": 0.11,
        "cart-1": 0.11,
        "catalog": 0.14,
        "checkout": 0.15,
        "frontend": 0.12,
        "payment": 0.13,
        "recommend": 0.10,
    }
)
BASE_MEM_MB: Final[Mapping[str, float]] = MappingProxyType(
    {
        "cart-0": 160.0,
        "cart-1": 160.0,
        "catalog": 200.0,
        "checkout": 250.0,
        "frontend": 300.0,
        "payment": 220.0,
        "recommend": 180.0,
    }
)
MB: Final = 1_000_000
#: Multiplicative noise U[0.97, 1.03] on every metric increment and gauge.
NOISE_LOW: Final = 0.97
NOISE_HIGH: Final = 1.03
#: Counters start above zero (nothing is ever 0); cpu seconds, request and error counts.
CPU_COUNTER_START_S: Final = 100.0
REQUEST_COUNTER_START: Final = 10_000.0
ERROR_COUNTER_START: Final = 3.0


# --- faults (synth_spec §4; lead §2.11) ---------------------------------------------------------
FaultKind = Literal["cpu", "delay", "exception", "change", "none"]


@dataclass(frozen=True)
class Fault:
    """One case's injection: what the generator does at t_inject, and the answer-key truth."""

    kind: FaultKind
    fault_id: str
    root_service: str | None
    fault_class: str | None
    indicator: str | None
    mode: str | None
    params: Mapping[str, float | int | str] = field(default_factory=lambda: MappingProxyType({}))
    root_component: str | None = None


@dataclass(frozen=True)
class ChangeEvent:
    """A change-kind event planted in a case (true change or decoy)."""

    offset_s: int
    entity: str
    kind: str
    detail: Mapping[str, str]
    #: True for the change that causes the fault; None for events outside the answer key's
    #: decoy list (synth-03's early config event, which only gives topology provenance).
    is_true: bool | None


@dataclass(frozen=True)
class CaseSpec:
    name: str
    fault: Fault
    changes: tuple[ChangeEvent, ...] = ()


@dataclass(frozen=True)
class GeneratorVariant:
    """A data variant of a base case (testing.VARIANTS `generator`), used only as a fixture."""

    name: str
    base_case: str
    #: The component whose telemetry stops at t_inject.
    silent_component: str
    fault: Fault


CASES: Final[Mapping[str, CaseSpec]] = MappingProxyType(
    {
        "synth-01": CaseSpec(
            "synth-01",
            Fault(
                kind="cpu",
                fault_id="cpu-hog",
                root_service="checkout",
                fault_class="cpu",
                indicator="cpu",
                mode="resource",
                # R-03 tuning of lead §2.11 (its 8 -> 12 ms left no external symptom: frontend
                # robust z 2.3 < 3, no alert breach, no self_time_share atom). price-order
                # 8 -> 20 ms makes the hog visible at the entry (frontend z ~5.6, breach ~+10 s);
                # 3.5 cores keeps cpu the top internal family by >= 2x over self time even under
                # Anomara's 's/s' fallback epsilon 0.1 (z ~34 vs ~16.5), so the expectation does
                # not depend on Observe's 's/s' -> cores normalisation (critic gap, lead §2.11).
                params=MappingProxyType(
                    {
                        "cpu_cores_from": 0.15,
                        "cpu_cores_to": 3.5,
                        "price_order_ms_from": 8.0,
                        "price_order_ms_to": 20.0,
                    }
                ),
            ),
        ),
        "synth-02": CaseSpec(
            "synth-02",
            Fault(
                kind="delay",
                fault_id="network-delay",
                root_service="recommend",
                fault_class="delay",
                indicator="latency",
                mode="network",
                # Added to recommend's egress: responses to frontend and requests to catalog.
                params=MappingProxyType({"egress_delay_ms": 100.0}),
            ),
        ),
        "synth-03": CaseSpec(
            "synth-03",
            Fault(
                kind="exception",
                fault_id="card-exception",
                root_service="payment",
                fault_class="exception",
                indicator="error",
                mode="code",
                # 60% of payment requests throw; checkout retries once (both fail 36%).
                params=MappingProxyType({"throw_share": 0.6, "retries": 1}),
            ),
            changes=(
                # Topology provenance for recommend -> catalog, outside both windows.
                ChangeEvent(
                    60, "recommend", "config", {"key": "CATALOG_ADDR", "value": "catalog:3550"}, None
                ),
                # Decoy: component-scope deploy on cart-1, 240 s before injection (lead §2.11);
                # a minor bump like synth-04's true change, so the version step is no label cue.
                ChangeEvent(
                    INJECT_OFFSET_S - 240,
                    "cart-1",
                    "deploy",
                    {"from": "cart:2.3.1", "image": "registry.local/cart", "to": "cart:2.4.0"},
                    False,
                ),
            ),
        ),
        "synth-04": CaseSpec(
            "synth-04",
            Fault(
                kind="change",
                fault_id="deploy-regression",
                root_service="catalog",
                fault_class="mem",
                indicator="mem",
                mode="change",
                params=MappingProxyType(
                    {
                        "mem_mb_from": 200.0,
                        "mem_mb_to": 520.0,
                        "self_ms_from": 10.0,
                        "self_ms_to": 40.0,
                        "deploy_lead_s": 60,
                    }
                ),
            ),
            changes=(
                # Exactly one change-kind event, no decoy (synth_spec D-S3).
                ChangeEvent(
                    INJECT_OFFSET_S - 60,
                    "catalog",
                    "deploy",
                    {"from": "catalog:1.4.2", "image": "registry.local/catalog", "to": "catalog:1.5.0"},
                    True,
                ),
            ),
        ),
        "synth-05": CaseSpec(
            "synth-05",
            Fault(
                kind="none",
                fault_id="none",
                root_service=None,
                fault_class=None,
                indicator=None,
                mode=None,
            ),
        ),
    }
)
CASE_NAMES: Final[tuple[str, ...]] = tuple(sorted(CASES))

#: Separator of testing.VARIANTS names; a generator variant's canonical key is "<base>@<name>".
VARIANT_SEPARATOR: Final = "@"

GENERATOR_VARIANTS: Final[Mapping[str, GeneratorVariant]] = MappingProxyType(
    {
        # synth-05@silent: cart-1 stops all telemetry at t_inject (critic gap; lead §2.10).
        "synth-05@silent": GeneratorVariant(
            "silent",
            "synth-05",
            "cart-1",
            Fault(
                kind="none",
                fault_id="replica-silence",
                root_service="cart",
                # Telemetry loss, not a pod failure: checkout's calls to cart-1 still succeed, so
                # 'availability' (03 §1: pod kill, restart, failure) would be a false label and
                # fault_class_hit is not scored (R-03 review). The variant tests silence handling.
                fault_class=None,
                indicator=None,
                mode=None,
                params=MappingProxyType({"silent_component": "cart-1"}),
                root_component="cart-1",
            ),
        ),
    }
)


def variant_key(base_case: str, variant: str) -> str:
    """Canonical key of a generator variant: the testing.VARIANTS fixture name."""
    return f"{base_case}{VARIANT_SEPARATOR}{variant}"


def case_spec(key: str) -> tuple[CaseSpec, GeneratorVariant | None]:
    """The base case spec and generator variant (or None) of a canonical key."""
    if key in CASES:
        return CASES[key], None
    if key in GENERATOR_VARIANTS:
        variant = GENERATOR_VARIANTS[key]
        return CASES[variant.base_case], variant
    known = ", ".join((*CASE_NAMES, *sorted(GENERATOR_VARIANTS)))
    msg = f"unknown synth case {key!r}; expected one of {known}"
    raise KeyError(msg)
