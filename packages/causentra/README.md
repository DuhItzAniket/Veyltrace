# veyltrace-causentra (`veyltrace_causentra`)

Engine 9 of Veyltrace v2 (Reason lane): the deterministic verifier. Statistical rankers and the LLM investigator only propose; Causentra decides.

For every candidate in the decision pool (slate ∪ proposed candidates in `graph.nodes` with at least one supporting claim that code found true) it runs ten fixed trials (origin, precedence, propagation, silence, latency accounting, change alignment, peer contrast, intervention, leave-one-source-out, claim checks), computes the verified score

`V(c) = S0(c) × Π trial_factor(c) × (1 + clip(Σ_p w_p · polarity_p · holds_p(c), −0.3, +0.3))`,

builds a split-conformal candidate set (α = 0.10), and returns `CONFIRMED`, `LIKELY`, `INCONCLUSIVE` (with asks) or `NO_FAULT`, sealed by `verdict_hash` so replay can check it.

Spec: [docs/engines/09-causentra.md](../../docs/engines/09-causentra.md). Rules for agents: [AGENTS.md](AGENTS.md).

| | |
|---|---|
| Reads | `slate`, `evidence`, `proposals` (AI on), `graph.*`, `onsets`, `alignment`, `case_manifest`; calibration through `ctx.config.calibration` (from `config/calibration/<family>.json`) |
| Writes | `verdict.json` |
| Config | `config/causentra.yaml` (trial factors, margins, predicate weights, α, β) |

```bash
uv run python scripts/check.py --package causentra
uv run veyltrace diagnose --dataset synth --case synth-05 --ai off   # expect NO_FAULT
```

## v1 (R-10)

- **Modules:** `config` (`CausentraConfig`, the 09 §4 keys R-10 reads), `inputs` (`load_inputs`: U, G and the 07 §2.1 quantities from Causatrix's views, claim_check atoms kept apart, q̂ and τ_nf), `trials` (T1–T4, declared under `veyltrace.trials`), `decision` (steps 1–3 and 6, nonconformity, the set at the run's q̂), `outcome` (step 5, asks, proposal outcomes, `ranks_rcaeval`), `verdict` (assembly, `verdict_hash`) and `api`.
- **Trials.** T1–T4 are evaluated on every decision-pool candidate. T10 (claim checks) runs on proposal-origin candidates only and is mandatory for them, so one without a T10 pass is never confirmed (09 §3.4, #226).
- **Set.** Uncalibrated, q̂ = `calibration.uncalibrated_q_hat` = 0.0: the leader plus exact ties. A calibration file's q̂ is read at 9 decimals, the precision the decision compares s at (09 §5); null is +∞, the whole pool.
- **NO_FAULT** needs at least one robust_z anomaly atom: M is a maximum over them, so a case with none (missing telemetry, or the synth fixtures while Anomara is a stub) is never NO_FAULT.
- **Ask 6** ("no anomaly evidence in any source") fires only when there is no leader and no service is anomalous by value (I, E or NS ≥ k_anom, or Sil = 1); healthy 0.0 atoms no longer suppress it.
- **Proposals.** Every proposal gets one outcome in the 09 §3.10 order. Claims are matched on FaultLoom's `validate()` output, the canonical args the claim pass stored (`"k": 4` finds the atom of `4.0`); a claim `validate()` rejects never holds, and a proposal not admitted with such a claim is rejected `bad_args` (#216).
- **Hand-made goldens** (`fixtures/handmade/`): a CPU hog (CONFIRMED, root checkout resource/cpu) and a healthy case (NO_FAULT), each run through Causatrix first.

## v2 (R-12)

- **Supporting trials T5–T8** (09 §3.4), each compared at 9 decimals against its `trials.*` key: T5 latency accounting (`self_time_share` ≥ `trials.T5.min_share`; applies only with traces), T6 change alignment (`change_proximity` ≥ `trials.T6.min_proximity`, e⁻¹; untestable without events, failed `no_recent_change` when events exist but no change maps to the candidate), T7 peer contrast (`peer_contrast` ≥ `trials.T7.min_gap`; applies only with a `peer_contrast` atom), T8 intervention (`intervention` ≥ `k_anom`; untestable without an atom). A failed supporting trial costs 0.9, an untestable one nothing. A non-applicable trial is omitted from `trials[]`.
- **T9 leave-one-source-out** (module `loso`): for each present source, Causatrix's pure `rank()` runs once more on the engine atoms whose `atom_sources` exclude it (claim-pass `intervention` atoms left out, as at step 6) and on the edges whose provenance is not only that source, with the source switched off in `sources`; the candidate passes when it stays within `slate.k` every time, else fails `drops_out_without:<first source, sorted>`. At most 4 `rank()` calls per case; not applicable below 2 sources.
- **T6 is not gated** on the candidate being anomalous: 09 §3.4 has no such precondition and `config/causentra.yaml` no key for it (09 §7 synth-03 note).
