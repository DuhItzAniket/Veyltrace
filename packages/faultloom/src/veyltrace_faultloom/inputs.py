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
from typing import Final

from veyltrace_contracts import models
from veyltrace_core.context import RunContext
from veyltrace_core.errors import ContractValidationError

__all__ = [
    "BOTH_PASS_TABLES",
    "CLAIM_REQUIRED",
    "EXTERNAL_KIND",
    "MAIN_REQUIRED",
    "EvidenceInputs",
    "GraphNode",
    "load_inputs",
    "missing_required",
    "score_window",
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


@dataclass(frozen=True)
class GraphNode:
    """One graph.nodes row as FaultLoom uses it (06 §2.1: node, kind, is_entry)."""

    node: str
    kind: str
    is_entry: bool


@dataclass(frozen=True)
class EvidenceInputs:
    """What both passes read, plus the shared values of 06 §2.1.

    `rows` holds the row count of every table input that is present; `absent` names the optional
    inputs that are not in the run directory (treated as zero rows, 06 §6). Windows are half-open
    [start_ns, end_ns) like alert.windows (03 §2.6).
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
    rows: Mapping[str, int]
    absent: tuple[str, ...]
    notes: tuple[str, ...]

    @property
    def node_names(self) -> frozenset[str]:
        """Every graph.nodes.node (the `service` parameter domain, 06 §3.5)."""
        return frozenset(n.node for n in self.nodes)


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
    for name in sorted(BOTH_PASS_TABLES):
        if not ctx.exists(name):
            absent.append(name)
            continue
        rows[name] = ctx.read_table(name, columns=BOTH_PASS_TABLES[name]).num_rows
    nodes = _nodes(ctx)

    notes: list[str] = []
    if ctx.exists("alignment"):
        tol_ns = ctx.read_model("alignment", models.Alignment).tolerance_ns
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
        rows=dict(sorted(rows.items())),
        absent=tuple(sorted(absent)),
        notes=tuple(notes),
    )
