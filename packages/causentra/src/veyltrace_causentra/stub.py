"""R-00 Causentra stub: a schema-valid, stub-honest verdict from the real inputs (09 §10, R-00).

Why it exists: the pipeline, the e2e test and the determinism gate need Causentra's own step (not
core's R-02 placeholder) to read every 09 §2.1 input through the contract loaders and to write a
verdict that downstream engines can consume, before the trials and the decision function exist.

What it claims: nothing about the root cause. No trial is evaluated, so no candidate has verified
support: every slate candidate is listed in `ranked` (Causentra never drops one) with V = 0, which
is the 09 §3.15 "all V = 0" case: no leader, nonconformity 1.0 for all, status INCONCLUSIVE, root
null, confidence level none. The candidate set follows the 09 §3.7 rule with the q_hat the run
actually has (uncalibrated: `calibration.uncalibrated_q_hat`). The only trial results written are
the 09 §3.4 `untestable` ones that an existence fact of the inputs already fixes (e.g. T2
`no_onset`: the candidate has no onset_precedence{self} atom); the only asks are the 09 §3.11 ones
that follow from the verdict itself (priority 4, |C| too large; priority 6, no leader, written only
while the evidence holds no anomaly atom so its text stays true). Proposal outcomes are given only
where they need no claim evaluation (09 §3.10 rows 1-2: `budget`, `unknown_entity`); every other
proposal is left undecided until R-10 evaluates its claims. R-10 (T1-T4, decision steps 1-3, 5-6)
and R-12 (T5-T10, conformal set, NO_FAULT, asks) replace this module.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

from veyltrace_contracts import models
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core.context import EngineResult, RunContext
from veyltrace_core.errors import ContractValidationError
from veyltrace_core.hashing import self_hash, sha256_json

__all__ = [
    "ENGINE",
    "STUB_NOTE",
    "EvidenceFacts",
    "StubSettings",
    "alpha_mismatch",
    "build_verdict",
    "calibration_entry",
    "evidence_facts",
    "proposal_outcomes",
    "run",
    "settings_from_config",
    "stub_asks",
    "stub_trials",
]

ENGINE: Final = "causentra"
#: EngineResult.notes entry of every stub result, so bench and reviewers can tell stub runs apart.
STUB_NOTE: Final = "stub: R-00 Causentra stub (no trial evaluated, no decision; verdict is not analysis)"

#: The verdict status of a stub: it verified nothing, so it never confirms, never says LIKELY and
#: never says NO_FAULT (09 §3.9: INCONCLUSIVE "otherwise").
STUB_STATUS: Final = "INCONCLUSIVE"
#: Confidence level of INCONCLUSIVE without a leader (03 §10; 09 §3.9).
NO_LEADER_LEVEL: Final = "none"
#: Margin with no leader (09 §3.9, §11 Q10).
NO_LEADER_MARGIN: Final = 0.0
#: Verified score of a candidate no trial has examined: the stub adds no verified support.
UNVERIFIED_V: Final = 0.0
#: Nonconformity of every candidate when there is no leader (09 §3.7).
NO_LEADER_NONCONFORMITY: Final = 1.0
#: Indicator of a universe service outside the decision pool: the stub does not run Causatrix's
#: classify() (09 §3.12), and "unknown" is the indicator vocabulary's word for "not classified".
UNCLASSIFIED_INDICATOR: Final = "unknown"
#: Decimals every verdict float is compared at (09 §5; 03 §1 canonical JSON).
ROUND_DECIMALS: Final = 9
#: proposals.status values whose proposals may enter the decision pool (09 §3.2).
ELIGIBLE_PROPOSAL_STATUSES: Final = frozenset({"complete", "budget_exhausted"})
#: Rejection reasons the stub can decide from bookkeeping alone (09 §3.10 rows 1-2).
REASON_BUDGET: Final = "budget"
REASON_UNKNOWN_ENTITY: Final = "unknown_entity"

#: Atom origin of FaultLoom's engine atoms (03 §7); claim_check atoms never fix a trial here.
ORIGIN_ENGINE: Final = "engine"
#: Detector whose internal_anomaly atoms define T1's series (09 §3.4; 07 §2.1 I(s)).
ROBUST_Z: Final = "robust_z"
#: Atom kinds that are anomaly evidence for the 09 §3.11 priority-6 text "no anomaly evidence in
#: any source" (07 §6 "anomaly atoms", plus silence, a symptom per 03 §7).
ANOMALY_KINDS: Final = frozenset({"internal_anomaly", "external_anomaly", "silence"})
#: Result of every trial the stub writes (03 common trial_result).
UNTESTABLE: Final = "untestable"
#: Services named in the priority-4 ask target "set:<first three services of C>" (09 §3.11).
SET_ASK_SERVICES: Final = 3
#: 09 §3.11 ask priorities the stub can trigger from its own verdict.
ASK_SET_TOO_LARGE: Final = 4
ASK_NO_LEADER: Final = 6

#: Inputs whose absence fails the step (09 §6: "slate or evidence: status failed; no verdict").
_REQUIRED_FOR_VERDICT: Final = ("slate", "evidence")
#: evidence columns the existence facts use (09 §2.1 reads all columns; these decide the facts).
_FACT_COLUMNS: Final = ["candidate", "kind", "args_json", "origin"]
#: graph.* columns Causentra reads (09 §2.1).
_NODE_COLUMNS: Final = ["node", "kind", "is_entry"]
_EDGE_COLUMNS: Final = ["src", "dst", "provenance"]
_PATH_COLUMNS: Final = ["candidate", "path_rank"]
_VERDICT_VERSION: Final = CONTRACTS["verdict"].version


@dataclass(frozen=True)
class StubSettings:
    """The config values the stub uses, read once from ctx.config (09 §4)."""

    #: Conformal miscoverage level recorded in confidence.alpha (`alpha`).
    alpha: float
    #: The run's conformal threshold; None means +inf (03 §10: canonical_json maps inf to null).
    q_hat: float | None
    #: Proposals eligible by proposal_id order (`proposals.max`).
    proposals_max: int
    #: |C| above which the priority-4 ask fires (`status.likely_max_set`, 09 §3.11).
    likely_max_set: int
    #: Maximum number of asks (`asks.max`, 09 §3.11).
    asks_max: int


def settings_from_config(ctx: RunContext) -> StubSettings:
    """Read the keys the stub uses; q_hat comes from the calibration when one applies.

    Calibration arrives only through ctx.config (09 §3.7); core's loader already refused a file for
    another ai_arm or alert_protocol (09 §3.15), so the stub does not re-check it.
    """
    cfg = ctx.config
    calibration = cfg.calibration
    q_hat = (
        float(cfg.get_path("calibration.uncalibrated_q_hat"))
        if calibration is None
        else (None if calibration.q_hat is None else float(calibration.q_hat))
    )
    return StubSettings(
        alpha=float(cfg.get_path("alpha")),
        q_hat=q_hat,
        proposals_max=int(cfg.get_path("proposals.max")),
        likely_max_set=int(cfg.get_path("status.likely_max_set")),
        asks_max=int(cfg.get_path("asks.max")),
    )


def alpha_mismatch(ctx: RunContext, alpha: float) -> str | None:
    """Why the calibration's q_hat cannot be used at `alpha`, or None if it can.

    q_hat is the ceil((n+1)(1-alpha))-th score at the file's own alpha (09 §3.7; 03 §12.1), so a
    run at another causentra.alpha (the 09 §9 alpha ablation) would record an alpha its set was not
    built at. Treated like the ai_arm/alert_protocol mismatch of 09 §3.15: the step fails.
    """
    calibration = ctx.config.calibration
    if calibration is None:
        return None
    fitted = round(float(calibration.alpha), ROUND_DECIMALS)
    if fitted == round(alpha, ROUND_DECIMALS):
        return None
    return (
        f"calibration {ctx.config.calibration_family} was fitted at alpha={fitted}, the run's "
        f"causentra.alpha is {alpha}: its q_hat does not apply (09 §3.7, §3.15)"
    )


def calibration_entry(ctx: RunContext) -> dict[str, str]:
    """verdict.calibration: the family id and file hash, or the uncalibrated sentinel (03 §10)."""
    return {"family": ctx.config.calibration_family, "sha256": ctx.config.calibration_sha256}


@dataclass(frozen=True)
class EvidenceFacts:
    """Existence facts of the inputs that fix a trial as untestable without evaluating it (09 §3.4).

    Each service set names the candidates with at least one engine atom of that sort; the flags
    are facts of evidence, graph.edges and case_manifest.sources.
    """

    #: Services with an internal_anomaly robust_z atom (T1 `no_internal_series` needs neither this
    #: nor a silence atom).
    internal_series: frozenset[str]
    #: Services with a silence atom (T1; T4 `no_silence_status`).
    silence: frozenset[str]
    #: Services with an onset_precedence{self} atom (T2 `no_onset`).
    self_onset: frozenset[str]
    #: Services with a self_time_share atom (T5 `no_latency_increase`).
    self_time_share: frozenset[str]
    #: Services with an intervention atom (T8 `intervention_unavailable`).
    intervention: frozenset[str]
    #: Any internal_anomaly, external_anomaly or silence engine atom (ask priority 6).
    anomaly_atoms: bool
    #: graph.edges has at least one row (T3/T4 `no_graph_edges`).
    graph_edges: bool
    #: case_manifest.sources.traces (T5 applies only with traces).
    traces: bool
    #: case_manifest.sources.events (T6 `no_events`).
    events: bool


def _args(raw: object) -> Mapping[str, Any]:
    loaded: object = json.loads(str(raw))
    return cast(Mapping[str, Any], loaded) if isinstance(loaded, dict) else {}


def evidence_facts(
    rows: Iterable[Mapping[str, Any]], *, graph_edges: int, sources: models.Sources
) -> EvidenceFacts:
    """The EvidenceFacts of evidence rows (candidate, kind, args_json, origin); order-free (sets)."""
    internal: set[str] = set()
    silence: set[str] = set()
    onset: set[str] = set()
    share: set[str] = set()
    intervention: set[str] = set()
    anomaly = False
    for row in rows:
        if row["origin"] != ORIGIN_ENGINE:
            continue
        kind, service = str(row["kind"]), str(row["candidate"])
        anomaly = anomaly or kind in ANOMALY_KINDS
        if kind == "internal_anomaly" and _args(row["args_json"]).get("detector") == ROBUST_Z:
            internal.add(service)
        elif kind == "silence":
            silence.add(service)
        elif kind == "onset_precedence" and _args(row["args_json"]).get("scope") == "self":
            onset.add(service)
        elif kind == "self_time_share":
            share.add(service)
        elif kind == "intervention":
            intervention.add(service)
    return EvidenceFacts(
        internal_series=frozenset(internal),
        silence=frozenset(silence),
        self_onset=frozenset(onset),
        self_time_share=frozenset(share),
        intervention=frozenset(intervention),
        anomaly_atoms=anomaly,
        graph_edges=graph_edges > 0,
        traces=sources.traces,
        events=sources.events,
    )


def stub_trials(service: str, facts: EvidenceFacts) -> list[dict[str, Any]]:
    """The trials of `service` whose result an existence fact fixes as untestable (09 §3.4).

    A trial is written only when it is applicable and its untestable precondition holds, with the
    09 §3.4 reason (the first listed one when two hold). Every other trial needs R-10/R-12's
    evaluation and is omitted, so in an R-00 verdict an omitted trial means "not evaluated", not
    "not applicable" (T7 without a peer_contrast atom and T10 for slate candidates are the only
    omissions that are truly non-applicable). The order is T1..T10 (03 §10 x-sort).
    """
    found: list[tuple[str, str]] = []
    if service not in facts.internal_series and service not in facts.silence:
        found.append(("T1", "no_internal_series"))
    if service not in facts.self_onset:
        found.append(("T2", "no_onset"))
    if not facts.graph_edges:
        found.append(("T3", "no_graph_edges"))
    if service not in facts.silence:
        found.append(("T4", "no_silence_status"))
    elif not facts.graph_edges:
        found.append(("T4", "no_graph_edges"))
    if facts.traces and service not in facts.self_time_share:
        found.append(("T5", "no_latency_increase"))
    if not facts.events:
        found.append(("T6", "no_events"))
    if service not in facts.intervention:
        found.append(("T8", "intervention_unavailable"))
    return [{"id": tid, "result": UNTESTABLE, "reason": reason, "atoms": []} for tid, reason in found]


def stub_asks(
    candidate_set: Sequence[Mapping[str, Any]], facts: EvidenceFacts, settings: StubSettings
) -> list[dict[str, str]]:
    """The 09 §3.11 asks that follow from the stub's own verdict, sorted, de-duplicated, truncated.

    The stub never has a leader, so priorities 1-3 and 5 (about the leader and its runner-up)
    cannot fire. Priority 4 is a fact of the set the stub writes. Priority 6 ("no leader") is
    written only while the evidence has no anomaly atom, so its text "no anomaly evidence in any
    source" is true; with anomaly atoms the missing leader is the stub's, not the case's.
    """
    found: set[tuple[int, str, str, str]] = set()
    if len(candidate_set) > settings.likely_max_set:
        first = ",".join(str(c["service"]) for c in candidate_set[:SET_ASK_SERVICES])
        why = f"candidate set has {len(candidate_set)} members"
        found.add((ASK_SET_TOO_LARGE, "trial", f"set:{first}", why))
    if not facts.anomaly_atoms:
        found.add((ASK_NO_LEADER, "telemetry", "all", "no anomaly evidence in any source"))
    ordered = sorted(found)[: settings.asks_max]
    return [{"kind": kind, "target": target, "why": why} for _, kind, target, why in ordered]


def proposal_outcomes(
    proposals: models.Proposals | None, graph_nodes: frozenset[str], proposals_max: int
) -> tuple[list[str], list[dict[str, str]], int]:
    """(accepted ids, rejected entries, undecided count) from bookkeeping only (09 §3.10 rows 1-2).

    Why only these rows: rows 3-6 need FaultLoom's validate() and the claim-pass atoms evaluated
    against the decision rule (R-10). The stub accepts nothing (accepting is a verified claim) and
    rejects only for reasons that are facts of the input files, so it never states a false reason.
    """
    if proposals is None:
        return [], [], 0
    ordered = sorted(proposals.proposals, key=lambda p: p.proposal_id)
    eligible = proposals.status in ELIGIBLE_PROPOSAL_STATUSES
    rejected: list[dict[str, str]] = []
    undecided = 0
    for index, proposal in enumerate(ordered):
        if not eligible or index >= proposals_max:
            rejected.append({"proposal_id": proposal.proposal_id, "reason": REASON_BUDGET})
        elif proposal.hypothesis.service not in graph_nodes:
            rejected.append({"proposal_id": proposal.proposal_id, "reason": REASON_UNKNOWN_ENTITY})
        else:
            undecided += 1
    return [], rejected, undecided


def _ranks_rcaeval(ranked: Iterable[Mapping[str, Any]], all_scores: Iterable[models.SlateScore]) -> list[str]:
    """The decision pool in ranked order, then the rest of slate.all_scores in order (09 §3.12)."""
    out: list[str] = []
    seen: set[str] = set()
    for entry in ranked:
        service = str(entry["service"])
        if service not in seen:
            seen.add(service)
            out.append(f"{service}_{entry['indicator']}")
    for score in all_scores:
        if score.service not in seen:
            seen.add(score.service)
            out.append(f"{score.service}_{UNCLASSIFIED_INDICATOR}")
    return out


def _universe_order(all_scores: Iterable[models.SlateScore]) -> list[models.SlateScore]:
    """slate.all_scores in its contract order (fused_score at 9 decimals desc, then service A-Z).

    The writer already guarantees this order; re-sorting makes the verdict a function of the set
    of scores, not of the row order a caller hands in (09 §5 permutation invariance).
    """
    return sorted(all_scores, key=lambda s: (-round(s.fused_score, ROUND_DECIMALS), s.service))


def _in_set(nonconformity: float, q_hat: float | None) -> bool:
    """09 §3.7: c is in C iff s(c) <= q_hat (q_hat None is +inf)."""
    return q_hat is None or nonconformity <= q_hat


def build_verdict(
    *,
    case_id: str,
    run_id: str,
    slate: models.Slate,
    proposals: models.Proposals | None,
    graph_nodes: frozenset[str],
    facts: EvidenceFacts,
    settings: StubSettings,
    calibration: Mapping[str, str],
    params_sha256: str,
) -> dict[str, Any]:
    """The stub verdict as a contract mapping, verdict_hash included (pure; no I/O).

    The decision pool is the slate's candidates (no proposal is admitted before R-10), in slate
    rank order; the 09 §3.6 tie-break needs trial-time quantities the stub does not compute.
    """
    fused = {score.service: score.fused_score for score in slate.all_scores}
    ranked: list[dict[str, Any]] = []
    pool = sorted(slate.candidates, key=lambda c: (c.rank, c.service))
    for position, candidate in enumerate(pool, start=1):
        ranked.append(
            {
                "rank": position,
                "service": candidate.service,
                "component": candidate.component,
                "indicator": candidate.indicator,
                "fault_class": candidate.fault_class,
                "v": UNVERIFIED_V,
                "nonconformity": NO_LEADER_NONCONFORMITY,
                # 09 §2.2: from slate.all_scores; the candidate's own value if U lacks it.
                "fused_score": float(fused.get(candidate.service, candidate.fused_score)),
                "origin": "slate",
                "trials": stub_trials(candidate.service, facts),
            }
        )
    candidate_set = [
        {
            "service": entry["service"],
            "component": entry["component"],
            "v": entry["v"],
            "nonconformity": entry["nonconformity"],
        }
        for entry in ranked
        if _in_set(float(entry["nonconformity"]), settings.q_hat)
    ]
    accepted, rejected, _undecided = proposal_outcomes(proposals, graph_nodes, settings.proposals_max)
    verdict: dict[str, Any] = {
        "schema_version": _VERDICT_VERSION,
        "case_id": case_id,
        "run_id": run_id,
        "status": STUB_STATUS,
        "root": None,
        "candidate_set": candidate_set,
        "ranked": ranked,
        "confidence": {
            "level": NO_LEADER_LEVEL,
            "margin": NO_LEADER_MARGIN,
            "alpha": settings.alpha,
            "q_hat": settings.q_hat,
            "set_size": len(candidate_set),
        },
        "asks": stub_asks(candidate_set, facts, settings),
        "ranks_rcaeval": _ranks_rcaeval(ranked, _universe_order(slate.all_scores)),
        "proposals_accepted": accepted,
        "proposals_rejected": rejected,
        "calibration": dict(calibration),
        "params_sha256": params_sha256,
    }
    verdict["verdict_hash"] = self_hash("verdict", verdict)
    return verdict


def _check_case(name: str, found: str, expected: str) -> None:
    if found != expected:
        raise ContractValidationError(name, f"case_id {found!r} does not match the run's {expected!r}")


def _read_proposals(ctx: RunContext) -> tuple[models.Proposals | None, tuple[str, ...]]:
    """proposals.json, or None with the reason: absent (AI off, 09 §6) or schema-invalid (06 §6:
    "Causentra treats the case as having no valid proposals")."""
    if not ctx.exists("proposals"):
        return None, ()
    try:
        proposals = ctx.read_model("proposals", models.Proposals, validate=True)
    except ContractValidationError as exc:
        return None, (f"proposals.json is schema-invalid: no valid proposals (06 §6): {exc}",)
    _check_case("proposals", proposals.case_id, ctx.case_id)
    return proposals, ()


def _optional_rows(ctx: RunContext, name: str, columns: list[str]) -> int | None:
    """Row count of an optional table read with its 09 §2.1 columns; None if it is absent."""
    return ctx.read_table(name, columns=columns).num_rows if ctx.exists(name) else None


def run(ctx: RunContext) -> EngineResult:
    """Read every 09 §2.1 input, write the stub verdict, report it (R-00 note).

    A missing slate or evidence fails the step without a verdict (09 §6), and so does a calibration
    fitted at another alpha. graph.edges, graph.paths and alignment are optional (zero rows / no
    tolerance, with a note: 09 §6, 06 §6); case_manifest, graph.nodes and onsets are required by
    FaultLoom's main pass (06 §6), so an absent one raises ArtifactMissing. A schema-invalid
    proposals.json counts as no proposals and the step is `degraded` (06 §6).
    """
    missing = [name for name in _REQUIRED_FOR_VERDICT if not ctx.exists(name)]
    if missing:
        notes = (STUB_NOTE, f"missing input(s) {', '.join(missing)}: no verdict (09 §6)")
        return EngineResult(engine=ENGINE, status="failed", notes=notes)
    settings = settings_from_config(ctx)
    mismatch = alpha_mismatch(ctx, settings.alpha)
    if mismatch is not None:
        return EngineResult(engine=ENGINE, status="failed", notes=(STUB_NOTE, mismatch))
    manifest = ctx.read_model("case_manifest", models.CaseManifest)
    _check_case("case_manifest", manifest.case_id, ctx.case_id)
    if manifest.dataset != ctx.dataset:
        raise ContractValidationError("case_manifest", f"dataset {manifest.dataset!r} is not {ctx.dataset!r}")
    slate = ctx.read_model("slate", models.Slate)
    _check_case("slate", slate.case_id, ctx.case_id)
    evidence = ctx.read_table("evidence")
    proposals, problems = _read_proposals(ctx)
    nodes = ctx.read_table("graph.nodes", columns=_NODE_COLUMNS)
    edges = _optional_rows(ctx, "graph.edges", _EDGE_COLUMNS)
    paths = _optional_rows(ctx, "graph.paths", _PATH_COLUMNS)
    onsets = ctx.read_model("onsets", models.Onsets)
    alignment = ctx.read_model("alignment", models.Alignment) if ctx.exists("alignment") else None
    node_names: list[Any] = nodes.column("node").to_pylist()
    graph_nodes = frozenset(str(n) for n in node_names)
    facts = evidence_facts(
        evidence.select(_FACT_COLUMNS).to_pylist(), graph_edges=edges or 0, sources=manifest.sources
    )
    verdict = build_verdict(
        case_id=manifest.case_id,
        run_id=ctx.run_id,
        slate=slate,
        proposals=proposals,
        graph_nodes=graph_nodes,
        facts=facts,
        settings=settings,
        calibration=calibration_entry(ctx),
        # 09 §2.2: sha256 of the canonical effective causentra section.
        params_sha256=sha256_json(dict(ctx.config)),
    )
    digest = ctx.write("verdict", verdict)
    _accepted, _rejected, undecided = proposal_outcomes(proposals, graph_nodes, settings.proposals_max)
    metrics: dict[str, int | float] = {
        "slate_candidates": len(slate.candidates),
        "universe_services": len(slate.all_scores),
        "evidence_atoms": evidence.num_rows,
        "graph_nodes": nodes.num_rows,
        "graph_edges": edges or 0,
        "graph_paths": paths or 0,
        "entry_services": len(onsets.entry_services),
        "sources_present": sum(1 for present in manifest.sources.model_dump().values() if present),
        "proposals": 0 if proposals is None else len(proposals.proposals),
        "proposals_undecided": undecided,
        "trials_untestable": sum(len(entry["trials"]) for entry in verdict["ranked"]),
        "asks": len(verdict["asks"]),
    }
    if alignment is not None:
        metrics["alignment_tolerance_ns"] = alignment.tolerance_ns
    absent = [name for name, rows in (("graph.edges", edges), ("graph.paths", paths)) if rows is None]
    if alignment is None:
        absent.append("alignment")
    notes: tuple[str, ...] = (
        STUB_NOTE,
        *problems,
        *(f"optional input absent: {name} (zero rows; 09 §6, 06 §6)" for name in sorted(absent)),
    )
    if undecided:
        notes = (*notes, f"{undecided} proposal(s) left undecided: claims are not evaluated before R-10")
    return EngineResult(
        engine=ENGINE,
        status="degraded" if problems else "ok",
        outputs=(("verdict", digest),),
        metrics=metrics,
        notes=notes,
    )
