"""Fault catalog for the `ob` profile (05 §6): F01, F02, F04–F08, F11 and F13.

Parameters are the catalog's a-priori L1/L2 levels; every value used is written into the answer
key's ``injection_json``. Not here yet: F03 (IOChaos needs a mounted volume), F09 (HTTPChaos has
no request percentage, so the 10% / 50% levels cannot be expressed), F12 (needs locally built
images), F14–F16 (no-fault, multi-fault and noise cases are plan-level, not single faults).
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
#: The datastore target of F13 (and F03 later).
DATASTORES = ("redis-cart",)
#: Container name per Deployment (root_component in the answer key).
CONTAINER = {**{s: "server" for s in OB_SERVICES}, "redis-cart": "redis"}
CHAOS_API = "chaos-mesh.org/v1alpha1"
#: Chaos Mesh kinds the campaign may leave behind; reset deletes them all (05 §8.1).
CHAOS_KINDS = "stresschaos,networkchaos,podchaos,schedules.chaos-mesh.org"
#: Repeat period of the L2 kill faults (05 §6 F06/F07: "every 120 s").
REPEAT_S = 120


@dataclass(frozen=True)
class Fault:
    fault_id: str
    fault_class: str  # 03 §1 fault_class vocabulary
    indicator: str  # 03 §1 indicator vocabulary
    mode: str | None  # 03 §1 mode vocabulary by mechanism (synth's pairs); None: no value fits
    tool: str  # "chaos-mesh/<Kind>" or "kubectl/set-resources"
    levels: Mapping[str, Mapping[str, Any]]
    targets: tuple[str, ...] = OB_SERVICES


CATALOG: Mapping[str, Fault] = {
    f.fault_id: f
    for f in (
        Fault("F01", "cpu", "cpu", "resource", "chaos-mesh/StressChaos",
              {"L1": {"workers": 2, "load": 80}, "L2": {"workers": 2, "load": 100}}),
        Fault("F02", "mem", "mem", "resource", "chaos-mesh/StressChaos",
              {"L1": {"workers": 1, "size_mb": 256}, "L2": {"workers": 1, "size_mb": 512}}),
        Fault("F04", "delay", "latency", "network", "chaos-mesh/NetworkChaos",
              {"L1": {"latency_ms": 200, "jitter_pct": 10}, "L2": {"latency_ms": 1000, "jitter_pct": 10}}),
        Fault("F05", "loss", "error", "network", "chaos-mesh/NetworkChaos",
              {"L1": {"loss_pct": 10}, "L2": {"loss_pct": 50}}),
        Fault("F06", "availability", "error", None, "chaos-mesh/PodChaos",
              {"L1": {"action": "pod-kill", "repeat_s": 0},
               "L2": {"action": "pod-kill", "repeat_s": REPEAT_S}}),
        Fault("F07", "availability", "error", None, "chaos-mesh/PodChaos",
              {"L1": {"action": "container-kill", "repeat_s": 0},
               "L2": {"action": "container-kill", "repeat_s": REPEAT_S}}),
        Fault("F08", "availability", "error", None, "chaos-mesh/PodChaos",
              {"L1": {"action": "pod-failure", "duration_s": 200},
               "L2": {"action": "pod-failure", "duration_s": 600}}),
        Fault("F11", "config", "cpu", "change", "kubectl/set-resources",
              {"L1": {"cpu_divisor": 4}, "L2": {"cpu_divisor": 10}}),
        Fault("F13", "dependency", "latency", "dependency", "chaos-mesh/NetworkChaos",
              {"L1": {"latency_ms": 200, "jitter_pct": 10}, "L2": {"latency_ms": 1000, "jitter_pct": 10}},
              targets=DATASTORES),
    )
}  # fmt: skip


def get_fault(fault_id: str, target: str, severity: str) -> Fault:
    """The catalog entry, after checking that target and severity are allowed."""
    if fault_id not in CATALOG:
        raise ValueError(f"fault {fault_id!r} is not in the catalog (have {sorted(CATALOG)})")
    fault = CATALOG[fault_id]
    if target not in fault.targets:
        raise ValueError(f"target {target!r} is not allowed for {fault_id} (allowed: {list(fault.targets)})")
    if severity not in fault.levels:
        raise ValueError(f"severity {severity!r} not in {sorted(fault.levels)} for {fault_id}")
    return fault


@dataclass(frozen=True)
class Injection:
    """How to inject and remove one fault: Chaos Mesh objects to apply, or kubectl argument lists."""

    manifests: tuple[dict[str, Any], ...]
    apply_args: tuple[tuple[str, ...], ...]
    revert_args: tuple[tuple[str, ...], ...]


def _selector(namespace: str, target: str) -> dict[str, Any]:
    return {"namespaces": [namespace], "labelSelectors": {"app": target}}


def _delay(params: Mapping[str, Any]) -> dict[str, str]:
    latency = int(params["latency_ms"])
    return {"latency": f"{latency}ms", "jitter": f"{latency * int(params['jitter_pct']) // 100}ms",
            "correlation": "0"}  # fmt: skip


def _chaos_spec(
    fault: Fault, target: str, params: Mapping[str, Any], namespace: str, duration_s: int
) -> dict[str, Any]:
    spec: dict[str, Any] = {"mode": "all", "selector": _selector(namespace, target)}
    if fault.fault_id in {"F01", "F02"}:
        spec["containerNames"] = [CONTAINER[target]]
        spec["stressors"] = (
            {"cpu": {"workers": params["workers"], "load": params["load"]}}
            if fault.fault_id == "F01"
            else {"memory": {"workers": params["workers"], "size": f"{params['size_mb']}MB"}}
        )
    elif fault.fault_id in {"F04", "F13"}:
        spec |= {"action": "delay", "direction": "to", "delay": _delay(params)}
    elif fault.fault_id == "F05":
        spec |= {
            "action": "loss",
            "direction": "to",
            "loss": {"loss": str(params["loss_pct"]), "correlation": "0"},
        }
    else:  # PodChaos F06-F08
        spec["action"] = params["action"]
        if params["action"] == "container-kill":
            spec["containerNames"] = [CONTAINER[target]]
        if params["action"] == "pod-failure":
            duration_s = min(duration_s, int(params["duration_s"]))
    # One-shot kills have no duration; everything else ends by itself even if the orchestrator dies.
    if fault.fault_id not in {"F06", "F07"}:
        spec["duration"] = f"{duration_s}s"
    return spec


def cpu_millicores(limit: str) -> int:
    """'200m' -> 200, '1' -> 1000, '0.5' -> 500."""
    return int(limit[:-1]) if limit.endswith("m") else round(float(limit) * 1000)


def injection(
    fault: Fault,
    *,
    target: str,
    severity: str,
    name: str,
    namespace: str,
    duration_s: int,
    cpu_limit: str | None = None,
) -> Injection:
    """The injection for one plan entry. ``cpu_limit`` is the target's limit in the vendored
    manifest, which F11 cuts and later restores."""
    params = fault.levels[severity]
    if fault.tool == "kubectl/set-resources":
        if cpu_limit is None:
            raise ValueError("F11 needs the target's CPU limit")
        cut = max(1, cpu_millicores(cpu_limit) // int(params["cpu_divisor"]))
        deploy, container = f"deploy/{target}", f"--containers={CONTAINER[target]}"
        return Injection(
            (),
            (("-n", namespace, "set", "resources", deploy, container, f"--limits=cpu={cut}m"),),
            (("-n", namespace, "set", "resources", deploy, container, f"--limits=cpu={cpu_limit}"),),
        )
    kind = fault.tool.split("/", 1)[1]
    spec = _chaos_spec(fault, target, params, namespace, duration_s)
    objects = [(kind, name, spec)]
    if int(params.get("repeat_s", 0)):
        # A Schedule fires first one period after it is created (measured 2026-11-09: 120 s), so the
        # one-shot object above kills at t_inject and the Schedule repeats it; the Schedule owns (and
        # deletes) the PodChaos objects it creates.
        every = f"@every {params['repeat_s']}s"
        repeat = {"schedule": every, "type": "PodChaos", "historyLimit": 1, "concurrencyPolicy": "Forbid",
                  "podChaos": spec}  # fmt: skip
        objects.append(("Schedule", f"{name}-r", repeat))
    manifests = tuple(
        {"apiVersion": CHAOS_API, "kind": k, "metadata": {"name": n, "namespace": namespace}, "spec": s}
        for k, n, s in objects
    )
    reverts = tuple(
        ("-n", namespace, "delete", "schedules.chaos-mesh.org" if k == "Schedule" else k.lower(), n,
         "--ignore-not-found")
        for k, n, _ in reversed(objects)
    )  # fmt: skip
    return Injection(manifests, (), reverts)
