# Ten engines with fixed roles, trust classes and lanes

- **Status:** Accepted
- **Date:** 2026-10-30
- **Author:** Aniket Kumar (ak)
- **Deciders:** lead
- **Consulted:** all lanes (kickoff)
- **Issue / CCR:** kickoff
- **Supersedes:** none · **Superseded by:** none

## Context

The team's ten engine names (Infralume, Signalyth, Anomara, Causync, Causalith, FaultLoom, Causatrix, Relentra, Causentra, Causivra) are fixed. v2 needs each to have one job, one output contract and one owner, so that three people driving three different AI coding agents can work in parallel. Pull-request pairs from different agents open at the same time conflict 41.7% of the time, against 19.8% for same-agent pairs, and about 42% of conflicts are structural ([multi_agent_dev §Q3][md]). Structural conflicts disappear when no two lanes create or edit the same paths. The propose–verify model ([ADR propose-verify-trust-model](20261030-ak-propose-verify-trust-model.md)) also needs a hard line between packages that may call an LLM and packages that may not.

## Decision drivers

- One engine, one job, one contract, one lane.
- Evidence used by the decision is created in exactly one place, so LLM claims can be re-computed by that code.
- All LLM calls confined to one lane.
- Balanced load across three people for one month.

## Considered options

1. **Roles as in [02 §3](../02-architecture.md)**, grouped into Observe (1–5), Reason (6, 7, 9) and Explain (8, 10) (chosen).
2. **The research report's proposal**: lanes by trust class, with evidence (1–6 plus the lab), decision and evaluation (7, 9, bench), and proposers and product (8, 10, API, UI) ([report][rep], "Lanes, frozen contracts and no shared registries").
3. **Fewer, larger packages** (e.g. merge Anomara into Signalyth, Causync into Causalith).
4. **Reuse the v1 role assignment unchanged.**

## Decision

| # | Engine | Job | Trust class | Lane |
|---|---|---|---|---|
| 1 | Infralume | Ingest any source into canonical telemetry; scrub leakage | deterministic | Observe |
| 2 | Signalyth | Typed signals: series, edges, templates, critical paths | deterministic | Observe |
| 3 | Anomara | Anomaly scores, onsets, incident onset, silence | deterministic (optional TSFM plugin off by default) | Observe |
| 4 | Causync | Clock alignment, change timeline, change evidence | deterministic | Observe |
| 5 | Causalith | Dependency graph, paths, restricted CI test | deterministic | Observe |
| 6 | FaultLoom | Evidence atoms and the symmetric claim pass | deterministic | Reason |
| 7 | Causatrix | Rankers, fusion, slate | deterministic | Reason |
| 8 | Relentra | LLM investigator: proposals only | AI allowed, proposals only | Explain |
| 9 | Causentra | Verifier: trials, decision, conformal set, abstention | deterministic (the decision) | Reason |
| 10 | Causivra | Card under a claim checker, receipt, replay | AI allowed for prose only | Explain |

Boundary rules ([02 §3.1](../02-architecture.md)):

- **Observe turns bytes into facts.** Nothing in engines 1–5 ranks services.
- **FaultLoom is the only creator of decision evidence.** A Relentra claim is valid only if FaultLoom's predicate code can re-compute it. FaultLoom therefore runs twice per case: once to build evidence (step 5), once for the claim pass (step 8).
- **Causatrix ranks; Causentra decides.** Rankers are also reported alone as baselines.
- **Explain holds every LLM call.** With `--ai off`, Relentra is skipped and Causivra writes a template card; the verdict path is unchanged.
- Each engine is one package exposing `run(ctx) -> EngineResult`, registered as an entry point; inputs and outputs only through contract loaders and writers ([AGENTS.md §5](../../AGENTS.md)).

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Report's trust-class lanes (FaultLoom in the evidence lane) | Lanes match import rules exactly | FaultLoom defines the predicates the verifier depends on, so splitting it from Causentra creates the most cross-lane change requests; the evidence lane would carry six engines plus the lab | Coupling between FaultLoom and Causentra is tighter than between FaultLoom and the Observe engines |
| Fewer, larger packages | Fewer contracts to freeze | Names are fixed by the team; larger packages mean two people in one package; fewer golden-fixture seams for parallel work | Parallelism matters more than contract count |
| v1 roles unchanged | Reuses v1 specs | v1 had no proposer/verifier split; the 02 roles were assigned for v2 | Does not support the propose–verify model |

## Consequences

- **Positive:** Each lane can work against the producer's golden fixtures from M0 ([08 §8](../08-collaboration-and-git.md)). Import isolation is checkable per package. Observe can be developed and tested without any LLM.
- **Negative:** Ten contracts plus core, llm and gateway mean 13 Python packages under `packages/` ([08 §3.1](../08-collaboration-and-git.md)). Observe is on the critical path in weeks 1–2 ([07 §1.2](../07-roadmap.md)). Task estimates in [07](../07-roadmap.md) sum to about 24.5 person-days for Reason, 20 for Observe and 23.5 for Explain (plus 2 shared each), as in [08 §2](../08-collaboration-and-git.md), after the decoy generator and statistics module (`bench/decoys/`, `bench/stats/`) moved to Observe; the lead remains the most loaded ([12-risks](../12-risks.md) RK-19).
- **Follow-ups:** each lane writes its engine specs in `docs/engines/` (L-02); the isolation test lists the allowed importers.

## Confirmation

- `tests/test_isolation.py` passes; `scripts/check_lanes.py` passes on every PR.
- `veyltrace diagnose --dataset synth --case synth-01 --ai off` runs end to end on stubs at M0.

## Evidence

- [multi_agent_dev §Q3][md]; [report][rep], "Ten engines fall into three trust classes" (with its 2026-10-30 update note); [02 §3](../02-architecture.md).

[rep]: ../../reports/Veyltrace%20v2%20SOTA%20root%20cause%20analysis.md
[md]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/multi_agent_dev_and_sdlc.md
