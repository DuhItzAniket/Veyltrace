# Split-conformal candidate sets, statuses and a calibrated NO_FAULT

- **Status:** Accepted (calibration family split confirmed at M2, per [02 §12](../02-architecture.md))
- **Date:** 2026-10-30
- **Author:** Aniket Kumar (ak)
- **Deciders:** lead
- **Consulted:** Explain lane (card and console show the set and status)
- **Issue / CCR:** kickoff; tasks R-12, R-13
- **Supersedes:** none · **Superseded by:** none

## Context

- Principle P4: abstain honestly; a candidate set, not a single guess, is the primary output ([02 §2](../02-architecture.md)).
- Every PetShop method produced false root causes during normal operation ([novel_building_blocks §Q7][nb]). RCAtlas scores abstentions as wrong and reports no calibration ([sota_methods §Q6][sota]).
- Raw LLM confidence is badly calibrated: LM-PACE needed retrieval plus a learned transformation to cut calibration error to 31% of direct prompting ([verified_agents §Q6][va]). Practitioners found numeric confidence values hard to interpret (Westermo report, snippet only, [verified_agents §Q6][va]).
- Searches up to October 2026 found no microservice RCA paper using conformal sets or risk–coverage curves; this is absence of evidence, hedged the same way in [02 §2 P4](../02-architecture.md). LM-PACE calibrates RCA confidence (not sets), and two possibly close works were seen only as snippets: CONCH/CROC (conformal sets for offline root-cause localisation, arXiv 2607.26481) and an OSDI'26 abstention protocol for network RCA ([verified_agents §Q6][va]; [novel_building_blocks §Q7][nb]).
- Split conformal needs at least 1/α − 1 calibration cases per stratum, and its guarantee assumes exchangeable cases, which breaks across systems ([novel_building_blocks §Q7][nb]).
- RCAEval has only fault cases. RE2 has 90 cases per system in 30 clusters; repetitions within a cluster are not independent ([benchmarks_and_testbed §Q2][bt]).

## Decision drivers

- A coverage statement a reader can check, not a model-generated probability.
- Deterministic, replayable and cheap (milliseconds per case).
- Honest about misses in the first stage: coverage can never exceed retrieval.
- Usable with the small calibration sets we have.

## Considered options

1. **Split conformal on the verified score, per calibration family, with a separately calibrated `NO_FAULT` threshold** (chosen).
2. Top-1 only with fixed margin rules.
3. Fixed top-k (e.g. k = 3).
4. LLM self-reported confidence.
5. Mondrian conformal per (family × available-modality pattern).
6. Conformal risk control with an explicit "no root cause" pseudo-candidate.
7. Probability-based set methods (APS/RAPS) or transductive full-ranking conformal.

## Decision

**Scores.** For each candidate c in the decision pool, V(c) is the verified score from [02 §6.9](../02-architecture.md). Nonconformity s(c) = 1 − V(c) / max V over the decision pool. The top candidate has s = 0.

**Calibration (fitted in `bench`, task R-13).** On n calibration cases from one family, let s_i be the nonconformity of the true root in case i, or **+∞ if the true root is not in the decision pool** (so retrieval misses count against coverage). Set k = ⌈(n + 1)(1 − α)⌉ and q̂ = the k-th smallest s_i; if k > n, q̂ = +∞ (written as `q_hat: null`). Default **α = 0.10** (`config/causentra.yaml`, a priori per 02). Without a calibration file Causentra uses q̂ = 0 (set = top candidate only), writes `calibration.family = "uncalibrated"`, and such runs are never used for coverage results.

**Set.** C = {c in the decision pool : s(c) ≤ q̂}, sorted by V descending. If q̂ = +∞, C is the whole decision pool. C never contains services outside the decision pool, so coverage is bounded by retrieval; Retrieval@K and decision-pool retrieval are reported next to it, and coverage is measured only on held-out cases.

**Family and splits.** One calibration family per benchmark family by default (02 §12), leave-one-system-out reported. Splits are by cluster (system, root service, fault) so repetitions never straddle calibration and test; the split definitions live in [04](../04-evaluation-protocol.md) and are fixed in the pre-registration commit. Each family's file `config/calibration/<family>.json` ([03 §12.1](../03-contracts.md)), written by `bench`, holds n, α, q̂, m, β, τ_nf and the hash of the cases used (no labels or case IDs), and its SHA-256 goes into every run manifest. Engines receive the calibration through `ctx.config`, never by reading answer keys.

**`NO_FAULT`.** Statistic M = the maximum of the entry service's external `score_norm` and every internal `score_norm` from the `robust_z` detector (Anomara, [03 §4.1](../03-contracts.md)). On m no-fault calibration windows, τ_nf = the ⌈(m + 1)(1 − β)⌉-th smallest M, with **β = 0.10** (a priori); uncalibrated default τ_nf = log1p(3). `NO_FAULT` iff no service is silent (Anomara `silence` detector) and M ≤ τ_nf. Under exchangeability this returns `NO_FAULT` on at least 1 − β of normal windows; the rate of wrong `NO_FAULT` on fault cases is measured, not controlled. No-fault windows come from `synth-05`, VeylLab no-fault captures and pre-injection segments of RCAEval cases. RCAEval's pre-injection segment (about 12 min per the benchmark notes, [benchmarks_and_testbed §Q3][bt]) is shorter than the 28-minute window in [02 §5.1](../02-architecture.md), so those windows are clamped and their results are reported as exploratory.

**Status** (checked in this order; thresholds a priori from 02):

| Status | Rule | `confidence.level` | `root` |
|---|---|---|---|
| `NO_FAULT` | no service silent and M ≤ τ_nf | `none` | null; candidate set empty |
| `CONFIRMED` | set size 1, all mandatory trials (T1–T4, plus T10 for a proposal-origin candidate) pass, margin ≥ c_high = 0.30 | `high` | top candidate |
| `LIKELY` | top candidate passes all mandatory trials, set size ≤ 3, margin ≥ c_med = 0.15 | `medium` | top candidate |
| `INCONCLUSIVE` | anything else; `asks` lists the missing telemetry or trial that would settle it | `low` if a leader exists, else `none` | top candidate or null |

**Margin** = (V(top) − V(runner-up)) / V(top), which equals the runner-up's nonconformity; 1.0 if there is no runner-up. (Resolved in 02 §6.9, 2026-10-30: 02 now defines the margin the same way.)

**Display.** The card and console show the set and the trial tally (e.g. "verified 4/4 mandatory trials; candidate set {A, B}"), never a bare probability ([verified_agents §Q6][va]).

**Reporting (RQ3).** Empirical coverage, mean set size, abstention rate and AURC per family; LOSO coverage gap; `NO_FAULT` rate on no-fault windows and wrong-`NO_FAULT` rate on fault cases. Coverage is described as *marginal* and *under exchangeability*.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Top-1 with margin rules only | Simple | No coverage statement; violates P4 | — |
| Fixed top-k | Simple | No guarantee; same size for easy and hard cases | — |
| LLM self-confidence | No calibration data needed | Poorly calibrated without retrieval and learned transforms (LM-PACE); puts AI in the decision | Violates P1 |
| Mondrian per (family × modality pattern) | Coverage holds per stratum, sets grow honestly when data are missing ([novel_building_blocks §Q6][nb]) | Strata too small in month one | Ablation; candidate for v1.1 |
| Conformal risk control with a ∅ candidate ([novel_building_blocks §Q7][nb]) | Joint set + abstain in one rule | Not a ready-made method; needs adaptation | Future work |
| APS/RAPS, transductive full-ranking conformal | Tighter sets in theory | V is not a probability; heavier machinery | Plain split conformal first |

## Consequences

- **Positive:** A checkable coverage target and an honest "I don't know"; cost is milliseconds per case; fully deterministic given the calibration file.
- **Negative:** Calibration cases are taken from the test pool, which raises the minimum detectable difference for RQ1. If retrieval misses more than α of calibration cases, q̂ = +∞ and every verdict in that family becomes `INCONCLUSIVE` with the whole decision pool as its set; this is intended, but it can make the status distribution look poor. Network faults, where onset precedence flips, will produce wider sets. LOSO coverage will likely fall below nominal; this is reported, not fixed.
- **Follow-ups:** [04](../04-evaluation-protocol.md) defines families, split sizes and no-fault windows; R-13 fits and hashes calibration; this ADR refines 02 §6.9 without contradicting it; the margin definition, the `NO_FAULT` statistic and the status → `confidence.level` mapping are now in 02 §6.9 and 03 §10 (resolved 2026-10-30); full-text novelty check before any "first" claim ([11 §11](../11-research-paper-plan.md)).

## Confirmation

- R-12 acceptance ([07](../07-roadmap.md)): held-out coverage within 1 − α ± 0.05 on RE2 (calibration cases excluded) and a `NO_FAULT` false-alarm rate on held-out normal windows ≤ β + 0.05; per-family target held-out coverage ≥ 0.85 ([01 §9](../01-vision-and-requirements.md) SC-4).
- Unit tests: q̂ = +∞ when n < 9 at α = 0.10; a case whose root is outside the decision pool counts as a miss.

## Evidence

- [novel_building_blocks §Q6–Q7, §Q10][nb]; [verified_agents §Q6][va]; [sota_methods §Q6][sota]; [benchmarks_and_testbed §Q2–Q3][bt]; [report][rep], "Proposals are data; predicates are code".

[rep]: ../../reports/Veyltrace%20v2%20SOTA%20root%20cause%20analysis.md
[sota]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/sota_methods_2026.md
[bt]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/benchmarks_and_testbed.md
[va]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/verified_agents_local_llms.md
[nb]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/novel_building_blocks.md
