"""FaultLoom's input view: every contract 06 §2.1 lists, read through the run context.

Why: both passes start from the same Observe outputs (06 §2.1, "both"), and the shared values of
06 §2.1 (universe U, tol_ns, the analysis windows) must be computed one way for every atom kind and
both passes. The R-00 stub uses this module to prove the wiring (every input read with the exact
fields the spec names; absent optional inputs handled per 06 §6); R-06/R-08 build the atoms on it.

Nothing here reads `telemetry.*`, ground truth or folder names (06 §5), and every collection is
returned sorted so iteration order never depends on file row order.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from veyltrace_contracts import models
from veyltrace_core.canonical import JSONLike
from veyltrace_core.context import RunContext
from veyltrace_core.errors import ContractValidationError
from veyltrace_core.hashing import sha256_json

__all__ = [
    "BOTH_PASS_TABLES",
    "CLAIM_REQUIRED",
    "EXTERNAL_KIND",
    "MAIN_REQUIRED",
    "REF_HEX",
    "AnomalyRow",
    "CallEdge",
    "ChangeRow",
    "CriticalPathRow",
    "EdgeStat",
    "EvidenceInputs",
    "GraphNode",
    "PathRow",
    "ServiceOnset",
    "TemplateRow",
    "align",
    "anomaly_rows",
    "load_inputs",
    "missing_required",
    "row_ref",
    "score_window",
    "service_onsets",
    "universe",
]

#: Inputs whose absence fails the step (06 §6: "later engines cannot run without evidence").
MAIN_REQUIRED: Final[tuple[str, ...]] = ("alert", "anomalies", "case_manifest", "graph.nodes", "onsets")
#: The claim pass also needs the main-pass evidence it carries forward and the slate (06 §2.1, §3.6).
CLAIM_REQUIRED: Final[tuple[str, ...]] = (*MAIN_REQUIRED, "evidence", "slate")

#: Table inputs of both passes and the fields 06 §2.1 says FaultLoom reads from each. Reading by
#: these columns proves the field names exist in the contracts and keeps memory to what is used.
BOTH_PASS_TABLES: Final[Mapping[str, tuple[str, ...]]] = {
    "anomalies": (
        "series_id",
        "service",
        "component",
        "family",
        "klass",
        "source",
        "detector",
        "score",
        "above_threshold",
    ),
    "changes": ("change_id", "entity", "kind", "scope", "delta_to_onset_ms", "proximity", "peer_contrast"),
    "graph.edges": ("src", "dst", "provenance", "weight", "anomalous"),
    "graph.nodes": ("node", "kind", "is_entry"),
    "graph.paths": ("candidate", "path_rank", "nodes", "anomalous_fraction"),
    "signal_cube.critical_path": (
        "window",
        "service",
        "traces",
        "cp_self_ms_p50",
        "cp_self_ms_p99",
        "cp_share_mean",
        "traces_total",
        "traces_slow",
        "cp_share_sum_slow",
    ),
    "signal_cube.edges": ("caller", "callee", "window", "calls", "error_rate", "p50_gap_ms", "p99_gap_ms"),
    "signal_cube.series": (
        "series_id",
        "service",
        "component",
        "signal",
        "family",
        "klass",
        "source",
        "unit",
        "t_ns",
        "value",
    ),
    "signal_cube.templates": ("service", "template_id", "count_baseline", "count_incident", "error_level"),
}

#: Unit conversion of window.score_ms (ms) to the ns of alert.windows.
_NS_PER_MS: Final = 1_000_000

#: graph.nodes.kind of nodes outside U unless core `universe.include_external` (06 §2.1).
EXTERNAL_KIND: Final = "external"
#: Hex digits of a row reference `<table>#<hex>` (06 §3.3).
REF_HEX: Final = 12


def row_ref(table: str, row: Mapping[str, JSONLike]) -> str:
    """`<table>#<first 12 hex of sha256(canonical_json(row))>` for a row without its own id (06 §3.3).

    `row` is the whole contract row (every column), so any consumer can recompute the reference.
    """
    return f"{table}#{sha256_json(row)[:REF_HEX]}"


@dataclass(frozen=True)
class GraphNode:
    """One graph.nodes row as FaultLoom uses it (06 §2.1: node, kind, is_entry)."""

    node: str
    kind: str
    is_entry: bool


@dataclass(frozen=True)
class AnomalyRow:
    """One anomalies row with the fields 06 §2.1 reads (03 §4.1), named as BOTH_PASS_TABLES."""

    series_id: str
    service: str
    component: str
    family: str
    klass: str
    source: str
    detector: str
    score: float
    above_threshold: bool


@dataclass(frozen=True)
class ServiceOnset:
    """One onsets.per_service entry with both onsets aligned (06 §2.1 "Onset of a service").

    `ref` points at the raw entry (06 §3.3: `onsets#<hex>`), so the atom cites what Anomara wrote.
    """

    service: str
    external_ns: int | None
    internal_ns: int | None
    silent: bool
    ref: str

    @property
    def onset_ns(self) -> int | None:
        """onset(s): the smaller non-null aligned onset, or None (06 §2.1)."""
        found = [t for t in (self.internal_ns, self.external_ns) if t is not None]
        return min(found) if found else None


@dataclass(frozen=True)
class CallEdge:
    """One graph.edges row (caller -> callee) as FaultLoom uses it; `ref` cites the whole row."""

    src: str
    dst: str
    anomalous: bool | None
    ref: str


@dataclass(frozen=True)
class PathRow:
    """One graph.paths row (candidate -> ... -> entry); `ref` cites the whole row."""

    candidate: str
    path_rank: int
    anomalous_fraction: float
    ref: str


@dataclass(frozen=True)
class ChangeRow:
    """One changes row with the fields 06 §2.1 reads (03 §5.2)."""

    change_id: str
    entity: str
    kind: str
    scope: str
    delta_to_onset_ms: float | None
    proximity: float
    peer_contrast: float | None


@dataclass(frozen=True)
class TemplateRow:
    """One signal_cube.templates row with the fields 06 §2.1 reads (03 §3.3)."""

    service: str
    template_id: str
    count_baseline: int
    count_incident: int
    error_level: bool


@dataclass(frozen=True)
class CriticalPathRow:
    """One signal_cube.critical_path row (03 §3.4); `ref` cites the whole row."""

    window: str
    service: str
    traces: int
    cp_self_ms_p50: float
    cp_self_ms_p99: float
    cp_share_mean: float
    traces_total: int
    traces_slow: int
    cp_share_sum_slow: float
    ref: str


@dataclass(frozen=True)
class EdgeStat:
    """One signal_cube.edges row (03 §3.2) with the fields 06 §2.1 reads; `ref` cites the whole row."""

    caller: str
    callee: str
    window: str
    calls: int
    error_rate: float
    p50_gap_ms: float | None
    p99_gap_ms: float | None
    ref: str


@dataclass(frozen=True)
class EvidenceInputs:
    """What both passes read, plus the shared values of 06 §2.1.

    `rows` holds the row count of every table input that is present; `absent` names the optional
    inputs that are not in the run directory (treated as zero rows, 06 §6). Windows are half-open
    [start_ns, end_ns) like alert.windows (03 §2.6). `anomalies` holds every anomalies row, sorted
    by the contract key (series_id, detector). `onsets` holds the aligned per-service onsets
    (sorted by service), `edges` and `paths` the graph rows (sorted by key) and `k_anom` is core
    `thresholds.anomaly_z` (06 §2.1). `components` is the component map (service -> components in
    signal_cube.series); `changes`, `templates`, `critical_path` and `edge_stats` (signal_cube.edges)
    are sorted by their contract keys.
    """

    case_id: str
    sources: models.Sources
    services: tuple[str, ...]
    nodes: tuple[GraphNode, ...]
    universe: tuple[str, ...]
    t_onset_ns: int
    tol_ns: int
    w_base: tuple[int, int]
    w_inc: tuple[int, int]
    w_score: tuple[int, int]
    anomalies: tuple[AnomalyRow, ...]
    rows: Mapping[str, int]
    absent: tuple[str, ...]
    notes: tuple[str, ...]
    k_anom: float
    onsets: tuple[ServiceOnset, ...]
    entry_services: tuple[str, ...]
    edges: tuple[CallEdge, ...]
    paths: tuple[PathRow, ...]
    components: Mapping[str, frozenset[str]]
    changes: tuple[ChangeRow, ...]
    templates: tuple[TemplateRow, ...]
    critical_path: tuple[CriticalPathRow, ...]
    edge_stats: tuple[EdgeStat, ...]

    @property
    def node_names(self) -> frozenset[str]:
        """Every graph.nodes.node (the `service` parameter domain, 06 §3.5)."""
        return frozenset(n.node for n in self.nodes)

    @property
    def onset_of(self) -> Mapping[str, ServiceOnset]:
        """onsets.per_service by service."""
        return {o.service: o for o in self.onsets}


def missing_required(ctx: RunContext, names: Iterable[str]) -> tuple[str, ...]:
    """The required contracts of `names` absent from the run directory, sorted."""
    return tuple(sorted(name for name in names if not ctx.exists(name)))


def universe(
    services: Iterable[str], nodes: Iterable[GraphNode], *, include_external: bool
) -> tuple[str, ...]:
    """U = case_manifest.services | {graph.nodes.node with kind ≠ external}, sorted A→Z (06 §2.1).

    External nodes join only when `include_external` (core `universe.include_external`). Python
    str order is code-point order, which equals UTF-8 byte order (the writers' sort order).
    """
    members = set(services)
    members.update(n.node for n in nodes if include_external or n.kind != EXTERNAL_KIND)
    return tuple(sorted(members))


def score_window(t_onset_ns: int, w_inc: tuple[int, int], score_ns: int) -> tuple[int, int]:
    """W_score = [t_onset, min(t_onset + score, end of W_inc)], clamped into W_inc (06 §2.1, §3.9).

    A t_onset outside W_inc still gives a window inside W_inc (06 §3.9: "atoms still emitted").
    """
    start_inc, end_inc = w_inc
    start = min(max(t_onset_ns, start_inc), end_inc)
    end = min(max(t_onset_ns + score_ns, start), end_inc)
    return start, end


type _Offsets = Mapping[tuple[str, str | None], int]


def align(t_ns: int | None, source: str | None, service: str, offsets: _Offsets) -> int | None:
    """Source time -> aligned time: + offset of (source, service), else (source, null), else + 0 (06 §2.1)."""
    if t_ns is None or source is None:
        return t_ns
    return t_ns + offsets.get((source, service), offsets.get((source, None), 0))


def service_onsets(onsets: models.Onsets, offsets: _Offsets) -> tuple[ServiceOnset, ...]:
    """onsets.per_service with each onset aligned by its recorded *_onset_source (03 §4.2, §5.1)."""
    found = (
        ServiceOnset(
            service=e.service,
            external_ns=align(e.external_onset_ns, e.external_onset_source, e.service, offsets),
            internal_ns=align(e.internal_onset_ns, e.internal_onset_source, e.service, offsets),
            silent=e.silent,
            ref=row_ref("onsets", e.model_dump(mode="json")),
        )
        for e in onsets.per_service
    )
    return tuple(sorted(found, key=lambda o: o.service))


#: Signalyth tables whose rows atoms cite by `row_ref`, so they are read with every column (06 §3.3).
_WHOLE_ROWS: Final = ("signal_cube.critical_path", "signal_cube.edges")


def _critical_path(rows: Iterable[Mapping[str, Any]]) -> tuple[CriticalPathRow, ...]:
    fields = BOTH_PASS_TABLES["signal_cube.critical_path"]
    ref = "signal_cube.critical_path"
    found = (CriticalPathRow(**{f: r[f] for f in fields}, ref=row_ref(ref, r)) for r in rows)
    return tuple(sorted(found, key=lambda r: (r.window, r.service)))


def _edge_stats(rows: Iterable[Mapping[str, Any]]) -> tuple[EdgeStat, ...]:
    fields = BOTH_PASS_TABLES["signal_cube.edges"]
    found = (EdgeStat(**{f: r[f] for f in fields}, ref=row_ref("signal_cube.edges", r)) for r in rows)
    return tuple(sorted(found, key=lambda e: (e.caller, e.callee, e.window)))


def _graph_rows(ctx: RunContext, name: str) -> list[dict[str, Any]]:
    """Every column of a graph table, so row_ref hashes the whole row (06 §3.3); [] if absent."""
    return ctx.read_table(name).to_pylist() if ctx.exists(name) else []


def _edges(ctx: RunContext) -> tuple[CallEdge, ...]:
    rows = _graph_rows(ctx, "graph.edges")
    found = (CallEdge(r["src"], r["dst"], r["anomalous"], row_ref("graph.edges", r)) for r in rows)
    return tuple(sorted(found, key=lambda e: (e.src, e.dst)))


def _paths(ctx: RunContext) -> tuple[PathRow, ...]:
    rows = _graph_rows(ctx, "graph.paths")
    found = (
        PathRow(r["candidate"], r["path_rank"], r["anomalous_fraction"], row_ref("graph.paths", r))
        for r in rows
    )
    return tuple(sorted(found, key=lambda p: (p.candidate, p.path_rank)))


def _nodes(ctx: RunContext) -> tuple[GraphNode, ...]:
    table = ctx.read_table("graph.nodes", columns=BOTH_PASS_TABLES["graph.nodes"])
    names = [str(v) for v in table.column("node").to_pylist()]
    kinds = [str(v) for v in table.column("kind").to_pylist()]
    entries = [bool(v) for v in table.column("is_entry").to_pylist()]
    return tuple(
        sorted((GraphNode(n, k, e) for n, k, e in zip(names, kinds, entries, strict=True)), key=_by_node)
    )


def _by_node(node: GraphNode) -> str:
    return node.node


def anomaly_rows(records: Iterable[Mapping[str, Any]]) -> tuple[AnomalyRow, ...]:
    """anomalies records as AnomalyRow, sorted by the contract key (series_id, detector)."""
    found = (AnomalyRow(**{f: r[f] for f in BOTH_PASS_TABLES["anomalies"]}) for r in records)
    return tuple(sorted(found, key=lambda r: (r.series_id, r.detector)))


def load_inputs(ctx: RunContext) -> EvidenceInputs:
    """Read every 06 §2.1 "both"-pass input through `ctx` and derive the shared values.

    The caller has checked MAIN_REQUIRED with `missing_required`; a missing required file here
    raises ArtifactMissing. Optional inputs that are absent are listed in `absent`; a missing
    alignment sets tol_ns to `alignment.missing_tolerance_ns` with a note (06 §6).
    """
    manifest = ctx.read_model("case_manifest", models.CaseManifest)
    if manifest.case_id != ctx.case_id:
        msg = f"case_id {manifest.case_id!r} is not the run's case {ctx.case_id!r}"
        raise ContractValidationError("case_manifest", msg)
    alert = ctx.read_model("alert", models.Alert)
    onsets = ctx.read_model("onsets", models.Onsets)

    rows: dict[str, int] = {}
    absent: list[str] = []
    found: dict[str, list[dict[str, Any]]] = {}
    for name in sorted(BOTH_PASS_TABLES):
        if not ctx.exists(name):
            absent.append(name)
            continue
        columns = (
            ("service", "component", "signal") if name == "signal_cube.series" else BOTH_PASS_TABLES[name]
        )
        table = ctx.read_table(name, columns=None if name in _WHOLE_ROWS else columns)
        rows[name] = table.num_rows
        if name in ("anomalies", "changes", "signal_cube.series", "signal_cube.templates", *_WHOLE_ROWS):
            found[name] = table.to_pylist()
    pairs = {(str(r["service"]), str(r["component"])) for r in found.get("signal_cube.series", [])}
    changes = (ChangeRow(**{f: r[f] for f in BOTH_PASS_TABLES["changes"]}) for r in found.get("changes", []))
    templates = (TemplateRow(**r) for r in found.get("signal_cube.templates", []))
    nodes = _nodes(ctx)

    notes: list[str] = []
    offsets: dict[tuple[str, str | None], int] = {}
    if ctx.exists("alignment"):
        alignment = ctx.read_model("alignment", models.Alignment)
        tol_ns = alignment.tolerance_ns
        offsets = {(o.source, o.service): o.offset_ns for o in alignment.offsets}
    else:
        absent.append("alignment")
        tol_ns = int(ctx.config["alignment"]["missing_tolerance_ns"])
        notes.append(f"alignment absent: tol_ns = {tol_ns} (06 §6)")
    w_inc = alert.windows.incident
    score_ns = int(ctx.config["window"]["score_ms"]) * _NS_PER_MS
    include_external = bool(ctx.config.core["universe"]["include_external"])
    return EvidenceInputs(
        case_id=manifest.case_id,
        sources=manifest.sources,
        services=tuple(sorted(manifest.services)),
        nodes=nodes,
        universe=universe(manifest.services, nodes, include_external=include_external),
        t_onset_ns=onsets.t_onset_ns,
        tol_ns=tol_ns,
        w_base=alert.windows.baseline,
        w_inc=w_inc,
        w_score=score_window(onsets.t_onset_ns, w_inc, score_ns),
        anomalies=anomaly_rows(found.get("anomalies", [])),
        rows=dict(sorted(rows.items())),
        absent=tuple(sorted(absent)),
        notes=tuple(notes),
        k_anom=float(ctx.config.core["thresholds"]["anomaly_z"]),
        onsets=service_onsets(onsets, offsets),
        entry_services=tuple(sorted(onsets.entry_services)),
        edges=_edges(ctx),
        paths=_paths(ctx),
        components={s: frozenset(c for t, c in pairs if t == s) for s in sorted({s for s, _ in pairs})},
        changes=tuple(sorted(changes, key=lambda c: (c.entity, c.change_id))),
        templates=tuple(sorted(templates, key=lambda t: (t.service, t.template_id))),
        critical_path=_critical_path(found.get("signal_cube.critical_path", [])),
        edge_stats=_edge_stats(found.get("signal_cube.edges", [])),
    )
