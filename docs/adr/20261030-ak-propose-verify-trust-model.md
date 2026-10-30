# AI proposes, code decides: the propose–verify trust model

- **Status:** Accepted
- **Date:** 2026-10-30
- **Author:** Aniket Kumar (ak)
- **Deciders:** lead
- **Consulted:** all lanes (kickoff read-in)
- **Issue / CCR:** kickoff (no issue yet; created at L-00)
- **Supersedes:** the v1 rule "AI may only explain" (see [ADR hackday-v1-archived](20261030-ak-hackday-v1-archived.md)) · **Superseded by:** none

## Context

v1 kept AI out of the decision path entirely: the LLM could only write explanations. The 2026 literature makes that rule too strict and its opposite too risky:

- Simple harnesses around 2026 frontier cloud models reach a mean PR@1 of 72.8% (SQL agent) and 77.2% (Codex harness), averaged over three models, on the 90-case RCAtlas set (preprint), against 38.9% for the best non-LLM method; a one-shot call over an evidence package scored 65.3% ([sota_methods §Q2][sota]; [verified_agents §Q1][va]). One listwise LLM call over a deterministic shortlist added 7–18 points in DecompRCA ([sota_methods §Q3][sota]). Excluding LLMs leaves this on the table.
- The same agents fail in ways a user cannot see: the exact root-cause set is recovered in 20.7% of OpenRCA 2.0 cases; live agents fall from 63.7% to 17.9% on unseen failures; one planted false sentence made models name a decoy first in 21–42% of flagged RCAEval cases ([sota_methods §Q2][sota]; [benchmarks_and_testbed §Q2][bt]).
- Fabricated causes outside the label space were 82% of one strong model's failed runs; untested propagation edges and "silence treated as health" were common for both strong and weak models ([verified_agents §Q2][va]).
- Explicit verification helps: DiagGuard raised Acc@1 in all 14 configurations by 3.5–35.1 pp. But its verifier is itself an LLM, and "semantics misread" errors did not improve (11.8% → 13.6%) ([verified_agents §Q2][va]). No paper isolates a purely deterministic verifier ([02 §2 P1](../02-architecture.md)); checks of meaning belong in code, and measuring that is part of our contribution.
- We found no paper that evaluates a model of ≤ 10B parameters as the investigating RCA agent (ThinkFL fine-tunes lightweight LLMs of unconfirmed size); our model is local and small ([verified_agents §Q1][va]; [sota_methods §Q2][sota]). Raw LLM self-confidence is badly calibrated ([report][rep], "Proposals are data; predicates are code").

## Decision drivers

- The verdict must be deterministic and replayable on any laptop.
- An unproven local model must be able to help without being trusted.
- The effect of the LLM must be measurable as a clean AI-on minus AI-off difference.
- No LLM-as-judge in the decision path ([02 §11](../02-architecture.md)).

## Considered options

1. **LLM decides** (agent-only, as in the RCAtlas harnesses or GALA+).
2. **Code only** (the v1 rule: LLM writes prose, nothing else).
3. **LLM verifier** (DiagGuard / SpecRCA style: a model checks hypotheses).
4. **Propose–verify with asymmetric checks** (re-check only the claims on the candidate the LLM proposed).
5. **Propose–verify with symmetric claim evaluation** (chosen).

## Decision

We adopt principles P1 and P2 of [02 §2](../02-architecture.md):

1. **Only Causentra sets the verdict**, through the fixed decision function in [02 §6.9](../02-architecture.md). ML and LLM outputs enter only as proposals or as evidence that code recomputed.
2. **Proposals are closed-vocabulary data.** A hypothesis names a service from the graph's nodes, a fault class from the taxonomy and an indicator; a claim names a predicate from FaultLoom's library with arguments. These are JSON-schema enums at decode time, so causes outside the label space cannot be expressed ([03 §9.1](../03-contracts.md)).
3. **The LLM never supplies a number.** It chooses which checks are worth running; FaultLoom's code runs them.
4. **Symmetric evaluation.** Every predicate the LLM cites is evaluated for every candidate in the claim-pass pool (slate ∪ all proposed candidates), and only those code results, weighted by fixed per-predicate weights and polarities, enter V(c). The total claim effect is clipped to ±0.3 as a multiplier ([02 §6.9](../02-architecture.md)). The LLM can surface discriminating evidence but cannot argue for its favourite.
5. **Proposers can only add candidates.** The decision pool is the deterministic slate plus proposed candidates (in `graph.nodes`) with at least one supporting claim that holds; T10 is a mandatory trial for those proposal-origin candidates only, so a false claim never lowers a slate candidate. Turning AI off cannot lower recall below the deterministic slate.
6. **Confidence is computed, never generated**: status and candidate set come from trials and conformal calibration ([ADR conformal-abstention](20261030-ak-conformal-abstention.md)).
7. **Import isolation enforces it.** Engines 1–7 and 9 cannot import any LLM, HTTP or socket library; only Relentra, Causivra and the gateway may import `veyltrace_llm` ([02 §9](../02-architecture.md)).

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| LLM decides | Highest published service-level accuracy with frontier models | Evidence is for cloud frontier models only; weaker models lose 10–20 points ([sota_methods §Q2][sota]); not replayable; can be steered by decoy text; violates [02 §11](../02-architecture.md) | Unverifiable and unproven at ≤ 10B on a laptop |
| Code only (v1) | Simplest; fully deterministic | Forfeits documented LLM gains; no way to study what a local model adds | Too conservative for a research system |
| LLM verifier | Documented gains (DiagGuard; SpecRCA's 3B verifier) | Did not fix semantic misreading; puts a model in the decision path; non-deterministic | Checks of meaning belong in code |
| Asymmetric claim checks | Cheaper: fewer predicate evaluations | The LLM can advocate: true-but-irrelevant facts about its favourite raise only that candidate | Breaks the "cannot advocate" property |
| Learned fusion of LLM and ranker scores | Could raise accuracy | ML in the decision path; tiny training data; overfitting risk ([novel_building_blocks §Q8][nb]) | Ablation only |

## Consequences

- **Positive:** AI-on minus AI-off differences are fully attributable to code-verified evidence the AI chose to request ([02 §6.9](../02-architecture.md)). Verdicts replay from recorded proposals (Tier 1). Decoy resistance becomes a measurable property (RQ2).
- **Negative:** The LLM's influence is bounded, so lift may be small or zero. Expressiveness is limited by the predicate library; adding a predicate needs a CCR after M1. The claim pass costs (predicates requested × pool size) evaluations per case. Strict mandatory trials may abstain often, especially on network faults.
- **Follow-ups:** permutation test (verdict depends on the set of proposals, not their order or wording); planted-decoy test; proposer-off baseline in every RQ2 table (task R-16).

## Confirmation

- CI isolation test passes for engines 1–7 and 9.
- With `--ai off`, the claim term is empty and `verdict_hash` matches the deterministic path.
- RQ2 reports proposer lift, decoy-rejection rate and permutation invariance ([11 §3](../11-research-paper-plan.md)).

## Evidence

- [sota_methods §Q2–Q3][sota]; [verified_agents §Q1–Q2, §Q6][va]; [benchmarks_and_testbed §Q2][bt]; [report][rep], "A deterministic verifier lets unproven local models help safely".

[rep]: ../../reports/Veyltrace%20v2%20SOTA%20root%20cause%20analysis.md
[sota]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/sota_methods_2026.md
[bt]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/benchmarks_and_testbed.md
[va]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/verified_agents_local_llms.md
[nb]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/novel_building_blocks.md
