"""R-00 stub of Causatrix: the real wiring of step 6 with no ranker implemented yet.

Why: the end-to-end run, the determinism gate and the downstream fixtures (Relentra, Causentra,
Causivra) need a slate that is built from the case's own inputs (07 §2.1), names the case's real
candidate universe U and is honest about what it knows. R-09 replaces the ranking and the rule
table; the reading, the universe, the tie-break order and the writing stay.

What it claims: nothing algorithmic. No ranker is implemented, so none votes: `rankers_active`
is empty, every enabled ranker's rank and score is null, every fused score is 0.0 (an RRF sum over
no voters), and every candidate is classified by the fallback rule R6 (`unknown` / `unknown`) with
the `other` family's indicator. The slate lists the first `slate.k` services of U in the 07 §3.1
step-5 tie-break order, which, with every F equal, reduces to internal-anomaly-first, earliest
onset, then name. Inputs are read only through the run context; nothing depends on case names,
answer keys, `bench/` or `lab/`.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

from veyltrace_causatrix.config import config_from
from veyltrace_contracts import models
from veyltrace_core.context import EngineResult, RunContext
from veyltrace_core.errors import ConfigError

__all__ = [
    "ENGINE",
    "FUSION_METHODS",
    "STUB_NOTE",
    "Atom",
    "ServiceFacts",
    "Settings",
    "build_slate",
    "engine_atoms",
    "order_universe",
    "run_stub",
    "service_facts",
    "settings_from",
    "universe",
]

ENGINE: Final = "causatrix"
#: EngineResult.notes entry of this stub, so bench and reviewers can tell stub runs apart.
STUB_NOTE: Final = "stub: R-00 Causatrix slate (no ranker implemented; R-09 replaces it)"
#: slate.fusion.method values (03 §8; 07 §9: rrf is the default, the others are ablations).
FUSION_METHODS: Final[tuple[str, ...]] = ("rrf", "combsum_minmax", "borda")
#: Fallback rule R6 of 07 §3.5: what classify() returns when no rule matched. The stub evaluates
#: no rule, so every candidate gets it (03 common `mode` / `fault_class` enum values).
FALLBACK_MODE: Final = "unknown"
FALLBACK_FAULT_CLASS: Final = "unknown"
#: indicator_map key of 07 §3.6 step 4 ("else other"), the indicator of a candidate with no
#: classified evidence.
FALLBACK_FAMILY: Final = "other"
#: graph.nodes.kind that joins U only with core.universe.include_external (06 §2.1).
EXTERNAL_KIND: Final = "external"
#: The robust-z detector whose atoms define I(s) and E(s) (07 §2.1).
ROBUST_Z: Final = "robust_z"
INTERNAL: Final = "internal_anomaly"
EXTERNAL: Final = "external_anomaly"
ONSET: Final = "onset_precedence"
ORIGIN_ENGINE: Final = "engine"
#: Fused score of a service no ranker voted on: the RRF sum over an empty set of voters (07 §3.1).
NO_VOTE_SCORE: Final = 0.0
#: Rounding of fused scores in the tie-break key and in all_scores' order (07 §3.1 step 5; 03 §8).
FUSED_DECIMALS: Final = 9

#: Evidence columns this step reads (07 §2.1; atom_id breaks topI/topE ties, origin selects
#: engine atoms).
EVIDENCE_COLUMNS: Final = ("atom_id", "candidate", "component", "kind", "args_json", "value", "origin")
NODE_COLUMNS: Final = ("node", "kind")
EDGE_COLUMNS: Final = ("src", "dst", "weight", "provenance")


# --- configuration ------------------------------------------------------------------------------
@dataclass(frozen=True)
class Settings:
    """The config keys the stub reads (config/causatrix.yaml, 07 §4) and the shared core values."""

    k: int
    rankers: tuple[str, ...]
    method: str
    rrf_k: int
    weights: tuple[tuple[str, float], ...]
    fallback_indicator: str
    k_anom: float
    include_external: bool

    @property
    def fusion_k(self) -> int | None:
        """slate.fusion.k: the RRF constant for method rrf, null for methods without one (03 §8)."""
        return self.rrf_k if self.method == "rrf" else None


def _int(value: object, key: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        msg = f"causatrix.{key} must be an integer >= {minimum}, got {value!r}"
        raise ConfigError(msg)
    return value


def _number(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        msg = f"{key} must be a finite number, got {value!r}"
        raise ConfigError(msg)
    return float(value)


def _rankers(value: object) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        msg = f"causatrix.rankers.enabled must be a list of ranker names, got {value!r}"
        raise ConfigError(msg)
    names = cast(Sequence[object], value)
    if not all(isinstance(n, str) and n for n in names):
        msg = f"causatrix.rankers.enabled must hold non-empty strings, got {list(names)!r}"
        raise ConfigError(msg)
    found = tuple(sorted(cast(Sequence[str], names)))
    if len(set(found)) != len(found):
        msg = f"causatrix.rankers.enabled lists a ranker twice: {list(found)!r}"
        raise ConfigError(msg)
    return found


def _get(section: Mapping[str, Any], name: str, dotted: str) -> Any:
    """`section[a][b]…` for dotted `a.b…`; ConfigError naming `<name>.<dotted>` if absent."""
    node: Any = section
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            msg = f"{name}.{dotted}: no such config key (add it to config/{name}.yaml)"
            raise ConfigError(msg)
        node = cast(Mapping[str, Any], node)[part]
    return node


def settings_from(cfg: Mapping[str, Any], core: Mapping[str, Any]) -> Settings:
    """Validate and collect the keys the stub uses; ConfigError names the offending key.

    `cfg` is the causatrix section (ctx.config), `core` the core section (ctx.config.core).
    """
    rankers = _rankers(_get(cfg, ENGINE, "rankers.enabled"))
    method = _get(cfg, ENGINE, "fusion.method")
    if method not in FUSION_METHODS:
        msg = f"causatrix.fusion.method must be one of {FUSION_METHODS}, got {method!r}"
        raise ConfigError(msg)
    raw_weights = cast(Mapping[str, object], _get(cfg, ENGINE, "rrf.weights"))
    missing = [r for r in rankers if r not in raw_weights]
    if missing:
        msg = f"causatrix.rrf.weights has no weight for enabled ranker(s) {missing}"
        raise ConfigError(msg)
    weights = tuple((r, _number(raw_weights[r], f"causatrix.rrf.weights.{r}")) for r in rankers)
    indicator_map = cast(Mapping[str, object], _get(cfg, ENGINE, "indicator_map"))
    fallback = indicator_map.get(FALLBACK_FAMILY)
    if not isinstance(fallback, str):
        msg = f"causatrix.indicator_map.{FALLBACK_FAMILY} must name an indicator, got {fallback!r}"
        raise ConfigError(msg)
    include_external = _get(core, "core", "universe.include_external")
    if not isinstance(include_external, bool):
        msg = f"core.universe.include_external must be a boolean, got {include_external!r}"
        raise ConfigError(msg)
    return Settings(
        k=_int(_get(cfg, ENGINE, "slate.k"), "slate.k", 1),
        rankers=rankers,
        method=str(method),
        rrf_k=_int(_get(cfg, ENGINE, "rrf.k"), "rrf.k", 1),
        weights=weights,
        fallback_indicator=fallback,
        k_anom=_number(_get(core, "core", "thresholds.anomaly_z"), "core.thresholds.anomaly_z"),
        include_external=include_external,
    )


# --- inputs -------------------------------------------------------------------------------------
def universe(
    services: Iterable[str], nodes: Iterable[tuple[str, str]], *, include_external: bool
) -> tuple[str, ...]:
    """U = case_manifest.services plus graph.nodes of kind != external (06 §2.1), sorted A→Z.

    External nodes join only when `include_external` (core.universe.include_external) is true.
    """
    members = set(services)
    members.update(node for node, kind in nodes if include_external or kind != EXTERNAL_KIND)
    return tuple(sorted(members))


@dataclass(frozen=True)
class Atom:
    """The fields of one engine evidence atom that the stub uses."""

    atom_id: str
    candidate: str
    component: str | None
    kind: str
    args: Mapping[str, Any]
    value: float


def engine_atoms(rows: Iterable[Mapping[str, Any]]) -> tuple[Atom, ...]:
    """Engine atoms (`origin = engine`) of evidence rows, sorted by (candidate, kind, atom_id).

    claim_check atoms do not exist at step 6 and are ignored if present (07 §2.1).
    """
    atoms: list[Atom] = []
    for row in rows:
        if row["origin"] != ORIGIN_ENGINE:
            continue
        args = json.loads(str(row["args_json"]))
        component = row["component"]
        atoms.append(
            Atom(
                atom_id=str(row["atom_id"]),
                candidate=str(row["candidate"]),
                component=None if component is None else str(component),
                kind=str(row["kind"]),
                args=cast(Mapping[str, Any], args) if isinstance(args, dict) else {},
                value=float(row["value"]),
            )
        )
    return tuple(sorted(atoms, key=lambda a: (a.candidate, a.kind, a.atom_id)))


@dataclass(frozen=True)
class ServiceFacts:
    """What the tie-break key and the candidate's component need about one service (07 §2.1).

    `internal` is I(s) (0 without atoms), `onset_ms` is onset_ms(s) (+inf if absent) and
    `component` is the component of topI(s), else of topE(s), None if absent or equal to s.
    """

    internal: float = 0.0
    onset_ms: float = math.inf
    component: str | None = None


def _top(atoms: Sequence[Atom]) -> Atom | None:
    """The atom with the largest value; ties go to the smallest atom_id (07 §2.1 topI/topE)."""
    if not atoms:
        return None
    return min(atoms, key=lambda a: (-a.value, a.atom_id))


def service_facts(atoms: Iterable[Atom], members: Iterable[str]) -> dict[str, ServiceFacts]:
    """ServiceFacts for every service in `members`; atoms about other candidates are ignored."""
    by_service: dict[str, list[Atom]] = {s: [] for s in members}
    for atom in atoms:
        if atom.candidate in by_service:
            by_service[atom.candidate].append(atom)
    facts: dict[str, ServiceFacts] = {}
    for service in sorted(by_service):
        own = by_service[service]
        robust = [a for a in own if a.args.get("detector") == ROBUST_Z]
        internal = [a for a in robust if a.kind == INTERNAL]
        external = [a for a in robust if a.kind == EXTERNAL]
        onsets = [a.value for a in own if a.kind == ONSET and a.args.get("scope") == "self"]
        top = _top(internal) or _top(external)
        component = top.component if top is not None and top.component != service else None
        facts[service] = ServiceFacts(
            internal=max((a.value for a in internal), default=0.0),
            onset_ms=min(onsets, default=math.inf),
            component=component,
        )
    return facts


# --- slate --------------------------------------------------------------------------------------
def order_universe(
    members: Iterable[str], fused: Mapping[str, float], facts: Mapping[str, ServiceFacts], k_anom: float
) -> tuple[str, ...]:
    """U in the 07 §3.1 step-5 order: (−round(F, 9), internal-first, onset_ms, name)."""

    def key(service: str) -> tuple[float, int, float, str]:
        f = facts.get(service, ServiceFacts())
        return (
            -round(fused[service], FUSED_DECIMALS),
            0 if f.internal >= k_anom else 1,
            f.onset_ms,
            service,
        )

    return tuple(sorted(members, key=key))


def build_slate(
    case_id: str, members: Sequence[str], facts: Mapping[str, ServiceFacts], settings: Settings
) -> dict[str, Any]:
    """The stub slate over `members` (= U): no votes, every service listed in all_scores."""
    fused = {s: NO_VOTE_SCORE for s in members}
    ordered = order_universe(members, fused, facts, settings.k_anom)
    abstained: dict[str, None] = dict.fromkeys(settings.rankers)
    candidates = [
        {
            "rank": i + 1,
            "service": service,
            "component": facts.get(service, ServiceFacts()).component,
            "indicator": settings.fallback_indicator,
            "mode": FALLBACK_MODE,
            "fault_class": FALLBACK_FAULT_CLASS,
            "fused_score": fused[service],
            "ranker_ranks": dict(abstained),
            "ranker_scores": dict(abstained),
        }
        for i, service in enumerate(ordered[: settings.k])
    ]
    all_scores = [
        {"service": s, "fused_score": fused[s]}
        for s in sorted(members, key=lambda s: (-round(fused[s], FUSED_DECIMALS), s))
    ]
    return {
        "case_id": case_id,
        "k": settings.k,
        "rankers_active": [],
        "fusion": {"method": settings.method, "k": settings.fusion_k, "weights": dict(settings.weights)},
        "candidates": candidates,
        "all_scores": all_scores,
    }


# --- engine -------------------------------------------------------------------------------------
def _failed(note: str) -> EngineResult:
    return EngineResult(engine=ENGINE, status="failed", notes=(STUB_NOTE, note))


def run_stub(ctx: RunContext) -> EngineResult:
    """Read the 07 §2.1 inputs, write the stub slate (07 §6: absent evidence or graph.nodes fails)."""
    for required in ("evidence", "graph.nodes"):
        if not ctx.exists(required):
            return _failed(f"{required} is absent (07 §6)")
    config_from(ctx.config, ctx.config.core)  # every 07 §4 key is validated, even unused ones
    settings = settings_from(ctx.config, ctx.config.core)
    manifest = ctx.read_model("case_manifest", models.CaseManifest)
    rows = ctx.read_table("evidence", columns=EVIDENCE_COLUMNS).to_pylist()
    node_rows = ctx.read_table("graph.nodes", columns=NODE_COLUMNS).to_pylist()
    edge_rows = (
        ctx.read_table("graph.edges", columns=EDGE_COLUMNS).to_pylist() if ctx.exists("graph.edges") else []
    )
    nodes = [(str(r["node"]), str(r["kind"])) for r in node_rows]
    members = universe(manifest.services, nodes, include_external=settings.include_external)
    atoms = engine_atoms(rows)
    facts = service_facts(atoms, members)
    slate = build_slate(manifest.case_id, members, facts, settings)
    in_u = set(members)
    edges_in_u = sum(1 for e in edge_rows if e["src"] != e["dst"] and {e["src"], e["dst"]} <= in_u)
    digest = ctx.write("slate", slate)
    return EngineResult(
        engine=ENGINE,
        status="ok",
        outputs=(("slate", digest),),
        metrics={
            "universe": len(members),
            "engine_atoms": len(atoms),
            "graph_edges_in_u": edges_in_u,
            "candidates": len(slate["candidates"]),
        },
        notes=(STUB_NOTE,),
    )
