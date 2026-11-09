"""Fault catalog entries F01 (CPU hog) and F04 (network delay) for the `ob` profile (05 §6).

Parameters are the catalog's a-priori L1/L2 levels; every value used is written into the answer
key's ``injection_json``. The remaining entries arrive with X-06.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: OB application services that may be fault targets (05 §6 "Targets"; loadgenerator never is).
OB_SERVICES = (
    "adservice",
    "cartservice",
    "checkoutservice",
    "currencyservice",
    "emailservice",
    "frontend",
    "paymentservice",
    "productcatalogservice",
    "recommendationservice",
    "shippingservice",
)
#: Container name of every OB application Deployment (root_component in the answer key).
OB_CONTAINER = "server"
CHAOS_API = "chaos-mesh.org/v1alpha1"


@dataclass(frozen=True)
class Fault:
    fault_id: str
    fault_class: str  # 03 §1 fault_class vocabulary
    indicator: str  # 03 §1 indicator vocabulary
    mode: str | None  # 03 §1 mode vocabulary, by the fault's mechanism (synth uses the same pairs)
    chaos_kind: str
    levels: Mapping[str, Mapping[str, int]]


CATALOG: Mapping[str, Fault] = {
    # 05 §6 F01: 2 workers at 80% / 100% load.
    "F01": Fault("F01", "cpu", "cpu", "resource", "StressChaos",
                 {"L1": {"workers": 2, "load": 80}, "L2": {"workers": 2, "load": 100}}),
    # 05 §6 F04: 200 ms / 1,000 ms, jitter 10%.
    "F04": Fault("F04", "delay", "latency", "network", "NetworkChaos",
                 {"L1": {"latency_ms": 200, "jitter_pct": 10}, "L2": {"latency_ms": 1000, "jitter_pct": 10}}),
}  # fmt: skip


def get_fault(fault_id: str, target: str, severity: str) -> Fault:
    """The catalog entry, after checking that target and severity are allowed."""
    if fault_id not in CATALOG:
        raise ValueError(f"fault {fault_id!r} is not in the catalog yet (have {sorted(CATALOG)})")
    if target not in OB_SERVICES:
        raise ValueError(f"target {target!r} is not an OB application service")
    fault = CATALOG[fault_id]
    if severity not in fault.levels:
        raise ValueError(f"severity {severity!r} not in {sorted(fault.levels)} for {fault_id}")
    return fault


def chaos_manifest(
    fault: Fault, *, target: str, severity: str, name: str, namespace: str, duration_s: int
) -> dict[str, Any]:
    """The Chaos Mesh object that injects ``fault`` into every pod of ``target``.

    ``duration`` equals the fault window, so Chaos Mesh ends the fault by itself even if the
    orchestrator dies before the recovery phase deletes the object.
    """
    params = fault.levels[severity]
    spec: dict[str, Any] = {
        "mode": "all",
        "selector": {"namespaces": [namespace], "labelSelectors": {"app": target}},
        "duration": f"{duration_s}s",
    }
    if fault.chaos_kind == "StressChaos":
        spec["containerNames"] = [OB_CONTAINER]
        spec["stressors"] = {"cpu": {"workers": params["workers"], "load": params["load"]}}
    else:
        latency = params["latency_ms"]
        spec["action"] = "delay"
        spec["direction"] = "to"
        spec["delay"] = {
            "latency": f"{latency}ms",
            "jitter": f"{latency * params['jitter_pct'] // 100}ms",
            "correlation": "0",
        }
    return {
        "apiVersion": CHAOS_API,
        "kind": fault.chaos_kind,
        "metadata": {"name": name, "namespace": namespace},
        "spec": spec,
    }
