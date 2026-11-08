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

## Stub (R-00)

Until R-10 lands, `api.run` calls the package's own stub, `veyltrace_causentra.stub` (it replaces core's R-02 placeholder). The stub proves the wiring and makes no claim about the root cause.

**Reads**, all through `ctx` and the contract loaders:
- `case_manifest`;
- `slate`;
- `evidence`, all columns;
- `proposals`, only when present (AI on), schema-validated;
- `graph.nodes`, `graph.edges` and `graph.paths`, with the 09 §2.1 columns;
- `onsets` and `alignment`;
- the config keys `alpha`, `calibration.uncalibrated_q_hat`, `proposals.max`, `status.likely_max_set` and `asks.max`;
- the calibration, through `ctx.config.calibration`, `calibration_family` and `calibration_sha256`.

**Missing or bad inputs:**
- A missing `slate` or `evidence` gives `status = "failed"` and no verdict (09 §6).
- A missing `graph.edges`, `graph.paths` or `alignment` counts as zero rows (no tolerance), with a note. The step still writes a verdict, so a run that FaultLoom keeps alive (06 §6) is not failed here. With no graph edges, T3 and T4 are written `untestable: no_graph_edges` (09 §6).
- `case_manifest`, `graph.nodes` and `onsets` are required by FaultLoom's main pass (06 §6), so the pipeline never reaches Causentra without them. A missing one raises `ArtifactMissing`.
- A schema-invalid `proposals.json` counts as no proposals (06 §6: "Causentra treats the case as having no valid proposals"). Both proposal lists stay empty, a note is added and the step is `degraded`.
- A calibration fitted at another α than `causentra.alpha` gives `status = "failed"` and no verdict. Its q̂ is the ⌈(n+1)(1−α)⌉-th score at the file's α (09 §3.7; 03 §12.1), so `confidence.alpha` would otherwise contradict `q_hat`. This mirrors the 09 §3.15 arm/protocol rule; 09 §3.15 does not list α yet.
- A `case_id` that differs from the run's raises `ContractValidationError`.

**Writes** `verdict.json` through `ctx.write`, so it is schema-checked, order-checked and self-hashed:
- **Status.** `status = INCONCLUSIVE`, `root = null`, `confidence.level = none` and `margin = 0.0`.
- **`ranked`.** Every slate candidate appears, in slate rank order, with `origin = slate`. `indicator`, `fault_class` and `component` are copied from the slate, and `fused_score` comes from `slate.all_scores` (the candidate's own value if U lacks it). Each candidate has `v = 0.0` and `nonconformity = 1.0`. This is the 09 §3.15 "all V = 0" case: no trial is evaluated, so nothing has verified support and there is no leader. The slate order is the Causatrix stub's tie-break (see the Causatrix README): name-only with no atoms (synth today), internal-anomaly-first, then earliest onset, then name with R-06's anomaly atoms. Either way `ranked` and `ranks_rcaeval` are not a ranking.
- **`trials`.** A trial is written only when it applies and an existence fact of the inputs already makes it `untestable`. It gets the 09 §3.4 reason and `atoms = []`:

  | Trial | Written as `untestable` when | Reason |
  |---|---|---|
  | T1 | the candidate has no `internal_anomaly` robust_z atom and no `silence` atom | `no_internal_series` |
  | T2 | the candidate has no `onset_precedence{self}` atom | `no_onset` |
  | T3 | `graph.edges` has no row | `no_graph_edges` |
  | T4 | the candidate has no `silence` atom; otherwise, `graph.edges` has no row | `no_silence_status`; `no_graph_edges` |
  | T5 | `sources.traces` and the candidate has no `self_time_share` atom | `no_latency_increase` |
  | T6 | `sources.events` is false | `no_events` |
  | T8 | the candidate has no `intervention` atom | `intervention_unavailable` |

  Every other trial is **omitted**: T1–T6 and T8 when their precondition does not hold, and always T9. Under 03 §10 an omitted trial reads as "not applicable", but in an R-00 verdict it means "not evaluated". Only T7 without a `peer_contrast` atom and T10 for slate candidates are truly not applicable. Consumers (Causivra's card, X-03) must not render R-00 trials as trial results; an R-00 verdict is recognisable by `v = 0` everywhere and an upstream slate with `rankers_active = []`. On the synth fixtures (no atoms, no edges), every candidate has T1–T5 and T8 untestable.
- **`asks`.** Only the 09 §3.11 asks that follow from the verdict itself, sorted by (priority, kind, target), de-duplicated and truncated to `asks.max`:
  - Priority 4, `{trial, set:<first three of C>, "candidate set has <n> members"}`, when |C| > `status.likely_max_set`. This happens only with a calibration whose q̂ ≥ 1 or null.
  - Priority 6, `{telemetry, all, "no anomaly evidence in any source"}`, for "no leader". It is written only while the evidence has no `internal_anomaly`, `external_anomaly` or `silence` engine atom, so its text stays true. Once R-06 adds atoms, the missing leader is the stub's, not the case's, and the ask is dropped.
  - Priorities 1–3 and 5 are about the leader and its runner-up, so they never fire without a leader.
- **`candidate_set`.** The 09 §3.7 rule `s ≤ q̂`, using the run's q̂. Uncalibrated, `q̂ = calibration.uncalibrated_q_hat = 0.0`, so the set is empty. A calibration file with `q_hat = null` (+∞) puts the whole pool in the set. `confidence.q_hat` records the q̂ used (it was `null` in R-02).
- **`ranks_rcaeval`.** The pool in ranked order, then the rest of `slate.all_scores` in its contract order.
- **`calibration`.** The family id and file hash, or the uncalibrated sentinel.
- **`params_sha256`.** `sha256_json` of the effective causentra section (equals `section_sha256(resolved, "causentra")`).
- **`verdict_hash`.** The contract's self hash, which excludes `run_id`.
- **`EngineResult`.** `status = "ok"` (`degraded` for a schema-invalid `proposals.json`), with `stub.STUB_NOTE` ("stub: R-00 …", which makes `diagnose` print its "placeholder outputs" warning) and counters in `metrics`.

**What the stub does not do, and why:**
- **No trial is evaluated.** No pass or fail is written, and no factor or S0 is computed. Only the `untestable` results in the table above are written, because each is fixed by the 09 §3.4 precondition alone. No reason was invented.
- **No decision function.** There is no S0, no claim sum, no 09 §3.6 tie-break, no NO_FAULT test and no CONFIRMED/LIKELY. `ranked` keeps slate order because the tie-break needs I(c) and onsets.
- **No admissions.** No proposal enters the decision pool, so proposals never add a candidate.
- **Few proposal outcomes.** Outcomes are given only where they are facts of the input files: `budget` (status `failed`/`skipped`, or beyond the first `proposals.max` by `proposal_id`) and `unknown_entity` (`hypothesis.service ∉ graph.nodes`). Every other proposal is left **undecided**: it appears in neither `proposals_accepted` nor `proposals_rejected`, and it is counted in `metrics.proposals_undecided`. Accepting one, or rejecting it as `claim_false`/`bad_args`, would state a verification result the stub has not computed. This departs from 09 §3.10 "exactly one outcome" until R-10.
- **Unclassified services.** Services of U outside the slate get the indicator `unknown` in `ranks_rcaeval`. Causatrix's `classify()` is not imported in the stub; `unknown` is the indicator vocabulary's value for "not classified".
- **No trial plugins.** The stub registers nothing under `veyltrace.trials`.

**Replaced by:**
- R-10: T1–T4, decision steps 1–3 and 5–6, the uncalibrated set and `verdict_hash` on real scores.
- R-12: T5–T10, the conformal set, the NO_FAULT threshold, statuses and asks.

Every 09 §4 key is already declared in `config/causentra.yaml`, with `trials.disabled` from 09 §9, so ablation overrides can name them.
