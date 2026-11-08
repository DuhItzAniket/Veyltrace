"""Argument validation of the predicate library (06 §3.5): `validate`, `CaseDomain`, `read_domain`.

Why: a claim is checked before it is evaluated, so a malformed proposal can never make a predicate
raise or run on an argument outside the pre-registered range. `validate` is pure and reads only the
domain, so Causentra re-derives every rejection reason with it (06 §3.6 step 5) and Relentra prunes
claims with the same rules; the reasons are `proposals_rejected.reason` values (03 §10).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from veyltrace_core.context import RunContext
from veyltrace_faultloom.inputs import EvidenceInputs
from veyltrace_faultloom.predicates import LIBRARY, Args, ArgValue, Predicate

__all__ = ["CaseDomain", "Rejection", "ValidClaim", "domain_of", "read_domain", "validate"]


@dataclass(frozen=True)
class CaseDomain:
    """Argument domains of one case: graph nodes (`service`), series signals (`signal`) and the
    inclusive ranges `predicates.<name>.<param>` of config/faultloom.yaml."""

    nodes: frozenset[str]
    signals: frozenset[str]
    ranges: Mapping[str, Mapping[str, tuple[float, float]]]


@dataclass(frozen=True)
class ValidClaim:
    """A validated claim: its library predicate and canonical args (what `args_json` holds)."""

    predicate: Predicate
    args: Args


@dataclass(frozen=True)
class Rejection:
    """Why a claim gives no atom: a `proposals_rejected.reason` of 03 §10."""

    reason: Literal["unknown_predicate", "unknown_entity", "bad_args"]
    detail: str


def _ranges(section: Mapping[str, Any]) -> Mapping[str, Mapping[str, tuple[float, float]]]:
    cfg: Mapping[str, Mapping[str, Mapping[str, float]]] = section["predicates"]
    return {n: {p: (r["min"], r["max"]) for p, r in sorted(ps.items())} for n, ps in sorted(cfg.items())}


def domain_of(view: EvidenceInputs, faultloom_config: Mapping[str, Any]) -> CaseDomain:
    """The domain from FaultLoom's own input view and config section."""
    return CaseDomain(view.node_names, view.signals, _ranges(faultloom_config))


def read_domain(ctx: RunContext) -> CaseDomain:
    """The domain through any engine's context (Causentra, Relentra): graph.nodes, the
    signal_cube.series signals and the run lock's faultloom section."""
    nodes = ctx.read_table("graph.nodes", columns=("node",)).column("node").to_pylist()
    signals: list[Any] = []
    if ctx.exists("signal_cube.series"):
        signals = ctx.read_table("signal_cube.series", columns=("signal",)).column("signal").to_pylist()
    section = ctx.config.section("faultloom")
    return CaseDomain(frozenset(map(str, nodes)), frozenset(map(str, signals)), _ranges(section))


def _number(value: object, kind: str, bounds: tuple[float, float]) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    if (kind == "int" and not float(value).is_integer()) or not bounds[0] <= value <= bounds[1]:
        return None
    return int(value) if kind == "int" else float(value)


def validate(predicate_name: str, args: object, domain: CaseDomain) -> ValidClaim | Rejection:
    """Validate a claim before evaluation (06 §3.5 steps 1-4); the first failing param decides."""
    predicate = LIBRARY.get(predicate_name)
    if predicate is None:
        return Rejection("unknown_predicate", f"{predicate_name!r} is not in the library")
    names = {p.name for p in predicate.params}
    given = cast("Mapping[object, object]", args) if isinstance(args, Mapping) else None
    if given is None or set(given) != names:  # not an object; missing, extra or a `subject` key
        return Rejection("bad_args", f"{predicate_name} takes exactly {sorted(names)}")
    canonical: dict[str, ArgValue] = {}
    for p in predicate.params:
        value = given[p.name]
        if p.type in ("float", "int"):
            number = _number(value, p.type, domain.ranges[predicate_name][p.name])
            if number is None:
                return Rejection("bad_args", f"{predicate_name}.{p.name} = {value!r} is not a valid {p.type}")
            canonical[p.name] = number
        elif not isinstance(value, str) or (p.type == "signal" and value not in domain.signals):
            return Rejection(
                "bad_args", f"{predicate_name}.{p.name} = {value!r} is not a {p.type} of this case"
            )
        elif p.type == "service" and value not in domain.nodes:
            return Rejection("unknown_entity", f"{predicate_name}.{p.name} = {value!r} is not a graph node")
        else:
            canonical[p.name] = value
    return ValidClaim(predicate, canonical)
