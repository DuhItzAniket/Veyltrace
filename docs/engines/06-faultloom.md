# 06 · FaultLoom — weave observations into per-candidate evidence atoms

> Status: v0.1-draft · Lane: Reason · Master: [docs/02-architecture.md §6.6](../02-architecture.md) · Contracts: [docs/03-contracts.md §7](../03-contracts.md) (output), §2.1, §2.6, §3–§6, §8, §9.1 (inputs) · Last updated: 2026-10-30

## 1. Purpose and scope

FaultLoom is the only place where evidence for the decision is created ([02 §3.1](../02-architecture.md)). It turns the Observe tables into **evidence atoms**: one row per (candidate service, kind, defining arguments), each with a number, a unit, a window and references to the rows it came from.

It runs twice per case ([02 §4](../02-architecture.md)):

| Pass | Pipeline step | Input it adds | What it writes |
|---|---|---|---|
| Engine pass | 5 | Observe outputs | every engine atom (`origin = "engine"`) for every service in the universe |
| Claim pass | 8 | `slate`, `proposals` | one `claim_check` atom per (library predicate, canonical args, claim-pass pool candidate), plus `intervention` atoms for decision-pool candidates (§3.6), appended to `evidence` |

It also owns two public code surfaces used by other engines:

- the **predicate library** (entry point group `veyltrace.predicates`), read by Causentra for polarity and by Relentra's schema builder for the closed predicate enum;
- `evidence_cards(slate, k, *, ctx)`, the deterministic compact view that Relentra `brief` mode puts in its prompt (§3.7).

Out of scope: ranking (Causatrix), deciding (Causentra), reading `telemetry.*` directly, reading answer keys, any model call. FaultLoom never chooses which candidate is right; every atom is computed the same way for every service.

## 2. Inputs and outputs (exact fields)

### 2.1 Inputs

| Contract ([03](../03-contracts.md)) | Fields read | Pass |
|---|---|---|
| `case_manifest` §2.1 | `case_id`, `sources.{metrics,logs,traces,events}`, `services` | both |
| `alert` §2.6 | `t_alert_ns`, `windows.baseline`, `windows.incident` (already clamped to available data) | both |
| `signal_cube.series` §3.1 | `series_id`, `service`, `component`, `signal`, `family`, `klass`, `source`, `unit`, `t_ns`, `value` | both |
| `signal_cube.edges` §3.2 | `caller`, `callee`, `window`, `calls`, `error_rate`, `p50_gap_ms`, `p99_gap_ms` | both |
| `signal_cube.templates` §3.3 | `service`, `template_id`, `count_baseline`, `count_incident`, `error_level` | both |
| `signal_cube.critical_path` §3.4 | `window`, `service`, `traces`, `cp_self_ms_p50`, `cp_self_ms_p99`, `cp_share_mean`, `traces_total`, `traces_slow`, `cp_share_sum_slow` | both |
| `anomalies` §4.1 | `series_id`, `service`, `component`, `family`, `klass`, `source`, `detector`, `score`, `above_threshold` | both |
| `onsets` §4.2 | `t_onset_ns`, `entry_services`, `per_service[].{service, external_onset_ns, external_onset_source, internal_onset_ns, internal_onset_source, silent}` | both |
| `alignment` §5.1 | `offsets[].{source, service, offset_ns}`, `tolerance_ns` | both |
| `changes` §5.2 | `change_id`, `entity`, `kind`, `scope`, `delta_to_onset_ms`, `proximity`, `peer_contrast` | both |
| `graph.nodes` / `.edges` / `.paths` §6 | `node`, `kind`, `is_entry`; `src`, `dst`, `provenance`, `weight`, `anomalous`; `candidate`, `path_rank`, `nodes`, `anomalous_fraction` | both |
| `slate` §8 | `candidates[].service` | claim |
| `proposals` §9.1 | `status`, `proposals[].{proposal_id, hypothesis.service, claims[].{claim_id, predicate, args}}` | claim |

Shared values used below:

- `k_anom` = `thresholds.anomaly_z` from `config/core.yaml` (default 3.0; PRISM's ε = 3 for z-scores, SimpleRCA's 3-sigma alert rule [rcaeval_facts §Anomaly scoring methods][rf-methods], [§Published baselines][rf-baselines]).
- `tol_ns` = `alignment.tolerance_ns` (coarsest source step).
- **Universe U** = `case_manifest.services` ∪ {`graph.nodes.node` with `kind ≠ external`} (external nodes join only if `universe.include_external` in `config/core.yaml` is true; default false). Sorted A→Z. Causatrix and Causentra use the same rule.
- **Component map**: the set of (`service`, `component`) pairs in `signal_cube.series`. A `changes.entity` maps to service *s* if it equals *s* or is a component of *s*. Entities that map to nothing, and rows with `scope = cluster`, produce no per-service atom (§11 Q6).
- **Windows**: `W_base` = `alert.windows.baseline`; `W_inc` = `alert.windows.incident`; `W_score` = [`t_onset_ns`, min(`t_onset_ns` + `window.score_ms`, end of `W_inc`)]. Pre-aggregated tables (`edges`, `templates`, `critical_path`) already carry `baseline`/`incident` labels from Signalyth and are used as given.
- **Onset of a service**: `onset(s)` = the smaller non-null of the **aligned** `internal_onset_ns`, `external_onset_ns` in `onsets.per_service`; null if both are null or *s* is absent. Aligned = onset + `offset_ns` of the `alignment.offsets` row for (`*_onset_source`, *s*), else (`*_onset_source`, null), else + 0 ([03 §4.2, §5.1](../03-contracts.md)).

### 2.2 Output: `evidence` (key `candidate, kind, atom_id`)

| Column | How FaultLoom fills it |
|---|---|
| `atom_id` | §3.2 |
| `candidate` | service in U (engine pass) or claim-pass pool candidate (claim pass) |
| `component` | component of the row that set the value when it differs from `candidate`; else null |
| `kind` | one of the 15 kinds in [03 §7](../03-contracts.md) |
| `predicate` | null for engine atoms; library name for `claim_check` |
| `args_json` | canonical JSON of the defining arguments (§3.4); for `claim_check`, the predicate arguments after the subject |
| `value` | float64, never NaN or ±inf; when there is no measurable value it is 0.0 and the meaning is carried by `holds`/absence (rules per kind) |
| `unit` | per kind (§3.4); null for unitless scores and fractions |
| `window` | `baseline`, `incident` or `onset` |
| `refs` | sorted, de-duplicated reference strings (§3.3) |
| `origin` | `engine` (engine pass and `intervention` atoms) or `claim_check` |
| `holds` | null for engine atoms; `true`, `false` or null (predicate not evaluable) for `claim_check` |
| `producer` | `faultloom@<package version>` |

The writer (`veyltrace_core.io`) sorts by key, stamps `veyltrace.schema = evidence/<version>` and returns the file SHA-256. The claim pass rewrites `evidence.parquet` as engine atoms ∪ claim atoms; engine atoms are read back, never recomputed, so they are byte-identical before and after.

## 3. Algorithm

### 3.1 Engine pass, step by step

1. Load inputs through `veyltrace_core.io` loaders; build U, the component map, windows and `onset(s)`.
2. For each service in U (A→Z) and each atom kind in the order of the table in §3.4, compute the atoms whose emission condition holds.
3. Compute `atom_id` and `refs` for each atom; assert `atom_id` uniqueness (a collision is a hard error, never silently dropped).
4. Validate every row against the `evidence` schema (no NaN/inf, fractions in [0, 1], `window` in the enum).
5. Write `evidence.parquet`; return `EngineResult` with row counts per kind in `metrics`.

### 3.2 `atom_id`

`atom_id = "E" + sha256_hex(canonical_json([kind, candidate, A]))[:10]`, via `veyltrace_core.ids.atom_id(kind, candidate, A)`:

- engine atoms: `A` = the defining-arguments object of §3.4 (always contains `window`, so atoms of one kind in two windows never collide);
- `claim_check`: `A = {"args": <canonical predicate args>, "predicate": <name>}`.

`canonical_json` is the core function ([03 §1](../03-contracts.md)): sorted keys, `(",", ":")` separators, UTF-8, floats rounded to 9 decimals. Float-typed arguments are converted to `float` before hashing so `3` and `3.0` give one ID (Python renders `3.0`). Same inputs give the same IDs on every machine, which lets Causivra cite atoms and replay match them.

### 3.3 `refs` grammar

| Source row | Reference string |
|---|---|
| a series | its `series_id` as-is (`{service}\|{component}\|{signal}\|{source}`) |
| a change | its `change_id` (`C…`) |
| a template | its `template_id` (`T…`) |
| any other row (edges, critical path, graph rows, onsets entries) | `<table>#<first 12 hex of sha256(canonical_json(row))>`, e.g. `graph.edges#3f9a0c41d2e7`; `<table>` is the contract name |

`atom_sources(atom)` (public helper, used by Causentra T9) = the `source` field of every series reference ∪ the fixed tag of the kind (§3.4 column "Sources").

### 3.4 Atom catalogue

All z-type values are the detector's raw `score` (PRISM ranks on raw deviation scores [rcaeval_facts §Anomaly scoring methods][rf-methods]). `score_norm` is not stored on atoms: for `robust_z` Anomara defines it as `log1p(score)`, so Causentra's `NO_FAULT` statistic, which 02 states in `score_norm` units, is recovered exactly as `log1p(value)` ([09 §3.8](09-causentra.md)).

| Kind | Defining args `A` | Value (unit) | Window | Sources | Emitted when |
|---|---|---|---|---|---|
| `internal_anomaly` | `{detector, family, source, window}` | max `score` over `anomalies` rows with `klass = internal` (z, sigma or score) | incident | from refs | ≥ 1 row for that (service, family, detector, source) |
| `external_anomaly` | same | same with `klass = external` | incident | from refs | same |
| `onset_precedence` | `{scope: self, window}` | (`onset(c)` − `t_onset_ns`) / 1e6 (ms) | onset | — | `onset(c)` not null |
| `onset_precedence` | `{scope: dependents, window}` | fraction of anomalous dependents that *c* precedes or ties (fraction) | onset | — | `onset(c)` not null and dependents set non-empty |
| `onset_precedence` | `{scope: internal_vs_external, window}` | (`external_onset_ns` − `internal_onset_ns`) / 1e6 (ms; positive = internal first) | onset | — | both onsets present |
| `propagation` | `{scope: entry, window}` | fraction of anomalous entry services reachable from *c* (fraction) | incident | — | graph has ≥ 1 edge and ≥ 1 anomalous entry |
| `propagation` | `{scope: anomalous, window}` | fraction of other anomalous services reachable from *c* (fraction) | incident | — | graph has ≥ 1 edge and ≥ 1 other anomalous service |
| `propagation` | `{scope: path, window}` | `anomalous_fraction` of the `path_rank = 1` row for *c* (fraction) | incident | — | `graph.paths` has a row for *c* |
| `change_proximity` | `{change_id, event_kind, window}` | `changes.proximity` (unitless, 0–1) | onset | events | change maps to *c*, `scope ≠ cluster`, `proximity > 0` |
| `peer_contrast` | `{source: anomalies, window}` | top component's max internal z minus median of the other components' max (z) | incident | from refs | *c* has ≥ `peer.min_components` components with internal `robust_z` rows |
| `peer_contrast` | `{source: changes, window}` | max non-null `changes.peer_contrast` over changes mapped to *c* (unit as Causync, §11 Q7) | onset | events | ≥ 1 such row |
| `spectrum` | `{formula, weighting, window}` | weighted Ochiai over slow incident traces (unitless, 0–1) | incident | traces | `sources.traces` and incident `critical_path` non-empty |
| `critical_path_share` | `{window}` | `cp_share_mean` for (window, *c*); 0 if *c* is absent from that window (fraction) | baseline / incident | traces | `sources.traces` and `critical_path` non-empty in that window |
| `self_time_share` | `{quantile, window}` | share of the positive critical-path self-time increase owned by *c* (fraction) | incident | traces | denominator ≥ `self_time.min_total_increase_ms` |
| `log_new_template` | `{error_level_only, min_count, window}` | number of templates with `count_baseline = 0` and `count_incident ≥ min_count` (count) | incident | logs | `sources.logs` and *c* has ≥ 1 template row |
| `log_error_rate` | `{window}` | error-level lines per second, incident minus baseline (lines/s) | incident | logs | same |
| `silence` | `{window}` | 1.0 if silent, else 0.0 | incident | from refs | *c* appears in `onsets.per_service` or in any `anomalies` row |
| `edge_gap` | `{direction, quantile, window}` | median over qualifying edges of Δgap (ms) | incident | traces | ≥ 1 qualifying edge |
| `intervention` | `{parents_hash, series_id, window}` | `stat_resid` of Causalith's `intervention_test`: persistent robust z of the target series' residual after regressing it on its parents (z) | incident | from refs | claim pass only, decision-pool candidates, test testable (§3.6) |
| `claim_check` | `{args, predicate}` | predicate value (§3.5) | per predicate | per predicate | claim pass only |

Detailed formulas:

**Internal / external anomaly.** For detector *d* ∈ `atoms.detectors` (default `robust_z`, `nsigma`, `silence`), family *f*, source *s*: `value = max score` over the matching `anomalies` rows of *c* (all components). `component` = the component of the maximising row (ties: component A→Z). `refs` = the `series_id`s that attain the maximum. Units: `z` for `robust_z`, `sigma` for `nsigma`, `score` for `silence`. Every series has one row per detector even below threshold ([03 §4.1](../03-contracts.md)), so atoms exist for healthy services too; that is what lets rankers order them. Direction (`up`/`down`) is not stored; it is recoverable from `refs` (§11 Q12).

**Onset precedence (dependents).** `D(c)` = services *d* ≠ *c* with a path *d* → … → *c* in `graph.edges` (transitive callers), `onset(d)` not null, and max external `robust_z` of *d* ≥ `k_anom`. Value = |{d ∈ D(c) : onset(c) ≤ onset(d) + tol_ns}| / |D(c)|. The tolerance absorbs scrape-step quantisation (metrics are often 15 s scrapes [rcaeval_facts §Metric step and windows][rf-step]).

**Propagation.** Reachability is computed on the reversed call graph (edges `dst → src`, the direction anomalies propagate), with *c* reaching itself. "Anomalous entry" = service in `onsets.entry_services` ∪ {`is_entry`} with max external `robust_z` ≥ `k_anom`. "Anomalous" = max of internal or external `robust_z` ≥ `k_anom`, or `silence` = 1. This is the "explanatory coverage" check from the earlier design notes.

**Spectrum (critical-path-weighted Ochiai).** The per-trace spectrum is `e_f(s) = Σ_{failing traces} w_s(t)`, `e_p(s) = Σ_{passing traces} w_s(t)`, where `w_s(t)` is the share of trace *t*'s critical-path time spent in *s*'s self time, and `Ochiai = e_f / √((e_f + n_f)(e_f + e_p))` [novel_building_blocks §Q3][nbb]. Failing = **slow** incident traces (root duration above the baseline p95 of its entry operation, [03 §3.4](../03-contracts.md)); passing = the other incident traces, so the comparison is concurrent:

- `e_f(c) = cp_share_sum_slow[inc, c]`;
- `cov(c) = traces_total[inc] · cp_share_mean[inc, c]` (= `e_f + e_p`; Signalyth averages `cp_share_mean` over all eligible traces of the window);
- `F = max_s traces_slow[inc, s]` (slow traces in the window; exact when every slow trace's root service has critical-path self time, as it normally does; F is the same for every service, so it scales the values but never reorders them);
- `value = e_f / √(F · cov(c))`, and 0 when `e_f = 0` or `F = 0`. Since `e_f ≤ min(F, cov(c))`, the value lies in [0, 1].

`weighting = none` (ablation) uses `traces_slow[inc, c]` for `e_f` and `traces[inc, c]` for `cov(c)`.

**Self-time share.** `Δ(s) = cp_self_ms_<q>[inc, s] − cp_self_ms_<q>[base, s]` (missing row = 0), *q* = `self_time.quantile`. `value = max(0, Δ(c)) / Σ_{s∈U} max(0, Δ(s))`. This is the "latency accounting" quantity of trial T5: the share of the critical-path latency increase owned by *c*'s own work. The entry service's end-to-end increase is approximated by the sum of positive self-time increases (§11 Q2).

**Log atoms.** `E_w(c) = Σ count_w` over *c*'s templates with `error_level = true`; `dur_w` = window length in seconds from `alert.windows`. `log_error_rate = E_inc/dur_inc − E_base/dur_base`. `log_new_template` is emitted twice per service, with `error_level_only` false and true, `min_count = templates.min_count`. SimpleRCA's log error-keyword count reached 0.83 Top-1 on RE3-SS and RE3-TT, where metric-only PRISM had 0.20 on RE3-SS [rcaeval_facts §Published baselines][rf-baselines]; these atoms carry that signal.

**Silence.** `value = 1.0` if `onsets.per_service[c].silent` or any `anomalies` row of *c* has `detector = silence` and `above_threshold = true`. A service that stops reporting is never treated as healthy [verified_agents §Q2][va].

**Edge gap.** Qualifying edges for direction `in` are rows with `callee = c`, for `out` rows with `caller = c`, with incident `calls ≥ edge_gap.min_calls` and non-null `p<q>_gap_ms` in both windows. `Δgap = p<q>_gap_ms[inc] − p<q>_gap_ms[base]`; value = median (even count: mean of the two middle values after sorting). Emitted for `quantile` ∈ {p50, p99}. A network fault on *X* widens the caller−callee gap on every edge touching *X* while *X*'s own processing time stays flat (earlier design notes, untested on RCAEval).

**Intervention** (trial T8, claim pass only, §3.6). `series_id` = the target series passed to Causalith's `intervention_test` (the `refs` series of *c*'s top `internal_anomaly{robust_z}` atom; null lets Causalith pick its default target); `parents_hash` = first 12 hex of `sha256_json(CIResult.parents)`; value = `CIResult.stat_resid`; `refs` = target and parent `series_id`s. A result with `reason` set (untestable) produces no atom ([05 §3.7](05-causalith.md)).

### 3.5 Predicate library

Each predicate is a frozen object registered under entry point group `veyltrace.predicates`:

```python
class Predicate(Protocol):
    name: str                      # library name, e.g. "zscore_above"
    params: tuple[Param, ...]      # arguments after the subject, in order
    polarity: Literal[1, -1]       # +1 supports, -1 refutes the subject being the root
    window: Literal["baseline", "incident", "onset"]
    unit: str | None
    def evaluate(self, view: EvidenceInputs, subject: str, args: Mapping[str, ArgValue]) -> PredicateResult: ...

@dataclass(frozen=True)
class Param:
    name: str
    type: Literal["float", "int", "service", "signal"]
    min: float | None = None       # inclusive
    max: float | None = None       # inclusive

@dataclass(frozen=True)
class PredicateResult:
    value: float                   # 0.0 when not measurable
    holds: bool | None             # None = not evaluable on this case/subject
    refs: tuple[str, ...]          # sorted
```

Polarity is code and must equal the [03 §7](../03-contracts.md) table; a unit test compares them. Weights are **not** in FaultLoom: Causentra reads `predicates.<name>.weight` from `config/causentra.yaml` (defaults from 03).

| Predicate | Params after subject (range) | Value (unit) | `holds` | `holds = null` when | Polarity |
|---|---|---|---|---|---|
| `zscore_above` | `signal: signal`, `k: float [1, 100]` | max `robust_z` `score` over the subject's series with that `signal` (z) | value ≥ k | subject has no series with that signal | supports |
| `onset_before` | `other_service: service` | (`onset(other)` − `onset(subject)`)/1e6 (ms) | `onset(subject) ≤ onset(other) − tol_ns` | either onset missing, or subject = other | supports |
| `edge_anomalous` | `callee: service` | 1.0 if edge subject→callee exists and `anomalous`, else 0.0 | edge exists and `anomalous = true` | subject = callee, or the edge's `anomalous` is null (no trace data) | refutes |
| `self_time_share_above` | `x: float [0, 1]` | `self_time_share` of subject (fraction) | value ≥ x | no `self_time_share` atom for subject | supports |
| `change_before_onset` | `max_ms: float [0, 86400000]` | smallest \|`delta_to_onset_ms`\| among changes on subject with `delta_to_onset_ms ≤ 0` (ms; 0.0 if none) | such a change exists with \|Δ\| ≤ max_ms | `sources.events` false | supports |
| `template_new_in_incident` | `min_count: int [1, 1000000]` | number of subject templates with `count_baseline = 0` and `count_incident ≥ min_count` (count) | value ≥ 1 | `sources.logs` false or subject has no templates | supports |
| `error_rate_above` | `x: float [0, 1]` | incident error ratio of calls into subject: Σ calls·error_rate / Σ calls over incident `edges` with `callee = subject` (fraction) | value ≥ x | no incident edge into subject | supports |
| `silent` | — | `silence` atom value | value = 1.0 | subject has no `silence` atom | supports |
| `on_critical_path` | `min_share: float [0, 1]` | incident `critical_path_share` of subject (fraction) | value ≥ min_share | `sources.traces` false | supports |
| `peer_gap_above` | `x: float [0, 100]` | max `peer_contrast` value of subject over both sources | value ≥ x | subject has no `peer_contrast` atom | supports |

Predicates reuse the atom functions of §3.4, so a claim is valid only if FaultLoom's own evidence code can recompute it ([02 §3.1](../02-architecture.md)).

**Argument validation** (`validate(predicate_name, args, case) -> Ok | Rejection`), applied before evaluation:

1. `predicate_name` not in the library → `unknown_predicate`.
2. `args` is not a JSON object, has a missing or extra key, or contains `subject` → `bad_args`. The subject is never in `args`; it is implied (§3.6; [03 §9.1](../03-contracts.md)).
3. Type checks: `float` accepts JSON numbers (not booleans), finite, within [min, max]; `int` accepts integral numbers within range; `signal` must be a `signal` value present in this case's `signal_cube.series`; `service` must be a `graph.nodes.node`. Failures → `bad_args`, except an unknown service → `unknown_entity`.
4. Canonicalise: floats to `float`, ints to `int`; the canonical object is what is hashed and stored in `args_json`.

### 3.6 Claim pass (pipeline step 8): symmetric evaluation

1. If `proposals.json` is absent (`ai.mode = off`) or has no claims, there are no claim atoms: skip to step 6 (intervention atoms for the slate). Engine atoms stay byte-identical.
2. **Claim-pass pool** `P` = `slate.candidates[].service` ∪ {`hypothesis.service` of every proposal}, sorted A→Z ([02 §4](../02-architecture.md): slate ∪ every proposed candidate; not to be confused with Causentra's *decision pool*). A proposed service that is not a `graph.nodes.node` has no data in the case and is rejected `unknown_entity` by Causentra, so it is left out of `P`; its proposal's valid claims are still evaluated on `P`, because running a check on every pool member cannot favour anyone.
3. Collect claims from all proposals (sorted by `proposal_id`, then `claim_id`); validate each (§3.5). Keep the distinct valid pairs (predicate, canonical args), sorted by predicate name then `canonical_json(args)`. Duplicate claims are evaluated once.
4. For every pair and every *c* ∈ P, call `evaluate(view, subject=c, args)` and write one atom: `kind = claim_check`, `candidate = c`, `predicate`, `args_json`, `value`, `unit`, `window`, `refs`, `holds`, `origin = claim_check`. The subject substitution is the whole symmetry mechanism: the model chooses *which* check runs, code runs it for every candidate, and the result is the same no matter which proposal asked ([02 §2 P2](../02-architecture.md)).
5. Rejected claims (`unknown_predicate`, `unknown_entity`, `bad_args`) produce no atom. Causentra re-derives the reasons with the same `validate()` function (it is pure), so no extra artefact is needed; `bad_args` is a valid `proposals_rejected.reason` ([03 §10](../03-contracts.md)).
6. **Intervention atoms.** Decision pool `D` = slate ∪ {proposed services in `graph.nodes` with at least one valid claim whose predicate has polarity *supports* and holds for that service} (the rule of [02 §6.9](../02-architecture.md) step 1, computed from this pass's own atoms). For the first `intervention.max_candidates` members of `D` in `slate.all_scores` order, call Causalith's `intervention_test` (its `ci.*` config from `config/causalith.yaml`) and write one `intervention` atom per testable result (§3.4). Members beyond the limit or untestable get no atom, so Causentra marks T8 `untestable` for them.
7. Rewrite `evidence.parquet` = engine atoms ∪ claim atoms ∪ intervention atoms, sorted by key.

The claim count is bounded by Relentra's budget (≤ 5 hypotheses, ≤ 12 turns [02 §6.8](../02-architecture.md)) and the claim-pass pool by K + 5.

### 3.7 Evidence cards for Relentra `brief` mode

```python
def evidence_cards(slate: Slate, k: int = 6, *, ctx: RunContext, order: Sequence[str] | None = None) -> CardDeck
```

Pure and read-only: it loads `evidence`, `graph.*`, `onsets`, `alert` and `case_manifest` through `ctx`, never writes. `order` (optional) is a permutation of the slate services that sets the card order; Relentra's permutation ablation uses it ([08-relentra OQ-2](08-relentra.md)). Default: slate rank order. EviRCA's evidence-card design matched or beat tool-heavy agents at 15–26× fewer tokens, and the evidence shown mattered more than prompt wording (+0.30 vs +0.05) [sota_methods §Q3][sm]; [benchmarks_and_testbed §Q2][bt].

`CardDeck` fields:

| Field | Content |
|---|---|
| `case` | t_onset relative to `alert.t_alert_ns` (s); entry services with their max external z; sources present; up to 5 earliest onsets as (service, ms after t_onset), A→Z on ties |
| `candidates[]` | one card per slate candidate, in `order` (default slate order): `rank`, `service`, `mode`, `fault_class`, `indicator`, `fused_score`, `atoms[]` (≤ k), `path` (rank-1 path, ≤ 6 nodes), `change` (latest `change_proximity`: event kind, ms before onset) or null, `against[]` (≤ 2 refuting facts, below) |
| `library[]` | each predicate: name, params with types and ranges, polarity (so the model knows which checks it may request) |
| `text` | the deterministic rendering sent to the model |
| `approx_tokens` | `ceil(len(text.encode("utf-8")) / cards.bytes_per_token)` (an *estimate*; FaultLoom may not import a tokenizer) |
| `truncated` | true if the budget forced removal of whole candidate cards |
| `deck_sha256` | sha256 of `canonical_json` of the deck without this field |

**Atom selection per candidate.** Walk this kind priority list and take the best atom of each kind until *k* are chosen: `internal_anomaly` (robust_z), `external_anomaly` (robust_z), `onset_precedence` (self), `change_proximity`, `self_time_share`, `spectrum`, `log_new_template` (error_level_only = true), `log_error_rate`, `silence` (only if 1.0), `edge_gap` (in, p50), `peer_contrast`, `propagation` (entry). "Best" = highest value, ties by `atom_id`.

**Against facts.** (a) a direct callee whose max internal z is ≥ the candidate's (name and z); (b) `onset_precedence` (dependents) < 1.0 (the fraction). These are the facts a careful reviewer would raise; showing them counters anchoring.

**Rendering.** One line per atom: `<atom_id> <kind> <key args> <value><unit>`, numbers with 3 significant digits (`format(x, ".3g")`), no raw series, no timestamps beyond the relative ones. Example line: `Eff7aaef775 internal_anomaly cpu/metrics z=9.1`.

**Budget.** If `approx_tokens > cards.max_tokens` (default 1,500), reduce *k* by 1 for all cards (minimum 2), then drop the case-card onset list, then drop candidate cards from the bottom and set `truncated = true`. The header lines of the remaining cards are never cut. Relentra's context limit is 16 K ([02 §6.8](../02-architecture.md)), so the deck leaves room for the system brief and the schema.

### 3.8 Worked micro-example (numbers computed for this doc)

A 3-service trace case: `frontend` (entry) → `checkoutservice` → `paymentservice` (tables below shorten the names to frontend / checkout / payment).

*Atom ID.* `checkoutservice` has `robust_z` scores 9.1 (series `checkoutservice|checkoutservice|cpu|metrics`) and 2.0 (mem). The cpu atom has `A = {"detector":"robust_z","family":"cpu","source":"metrics","window":"incident"}`; the hashed string is `["internal_anomaly","checkoutservice",{"detector":"robust_z","family":"cpu","source":"metrics","window":"incident"}]` and `atom_id = Eff7aaef775`. A claim `zscore_above(·, signal="cpu", k=4)` evaluated for `checkoutservice` hashes `["claim_check","checkoutservice",{"args":{"k":4.0,"signal":"cpu"},"predicate":"zscore_above"}]` → `E7d69a580cc`.

*Spectrum.* Incident critical-path rows (frontend / checkout / payment): `traces_total` = 800, `cp_share_mean` = 0.20 / 0.70 / 0.10, `traces_slow` = 500 / 500 / 300, `cp_share_sum_slow` = 60 / 400 / 40. `F = 500`.

| Service | e_f | cov = 800 × cp_share_mean | Ochiai |
|---|---|---|---|
| checkout | 400 | 560 | 400 / √(500 × 560) = 0.7559 |
| frontend | 60 | 160 | 0.2121 |
| payment | 40 | 80 | 0.2000 |

*Self-time share* (p50, ms, baseline → incident): frontend 12 → 13, checkout 20 → 95, payment 8 → 9.5. Positive increases 1 + 75 + 1.5 = 77.5 ms; `checkout` share = 75 / 77.5 = 0.9677, so T5 (≥ 0.30) would pass for `checkout` and fail for the others.

*Dependents precedence.* `onset(checkout)` = t_onset + 0 s, `onset(frontend)` = t_onset + 15 s, `tol_ns` = 15 s: 0 ≤ 15 + 15 → `checkout` precedes its only anomalous dependent; value 1.0.

### 3.9 Edge cases

| Case | Behaviour |
|---|---|
| `t_onset_ns` outside `W_inc` | `W_score` clamped to `W_inc`; atoms still emitted |
| `traces_total = 0` in a window | no `critical_path_share` for that window; no `spectrum` if it is the incident window |
| no slow incident traces (`F = 0`) | every `spectrum` value is 0 (Causatrix's `cp_sbfl` then abstains on constant scores) |
| Service with traces but absent from incident critical path | `critical_path_share` = 0, `spectrum` = 0 (it was not on any slow path) |
| Same change row maps to two services (entity is a shared component) | one atom per service |
| Graph with cycles | reachability by BFS over sorted adjacency; cycles are harmless |
| Service named in proposals but not in `graph.nodes` | not in the claim-pass pool; its valid claims are still evaluated on the pool |
| Predicate evaluation raises | hard error (bug), never a silent `holds = null` |

## 4. Configuration — `config/faultloom.yaml`

| Key | Default | Unit | Rationale / source |
|---|---|---|---|
| `atoms.detectors` | `[robust_z, nsigma, silence]` | — | detectors the rankers need (`prism_m`, `baro_rs` → robust_z; `nsigma` → nsigma); `bocpd` gives onsets only; `tsfm` is an Anomara ablation |
| `window.score_ms` | 300000 | ms | a priori; PRISM's early-window result (81% vs 68% Top-1 with the first 10% of post-fault data) argues for short windows [rcaeval_facts §Anomaly scoring methods][rf-methods]; ablation 60000 / 600000 |
| `self_time.quantile` | `p50` | — | a priori (median is robust to trace sampling); ablation `p99` |
| `self_time.min_total_increase_ms` | 5.0 | ms | a priori; below this there is no latency increase to account for |
| `spectrum.formula` | `ochiai` | — | Ochiai outperformed other coefficients in an industrial SBFL study [rcaeval_facts §Traces][rf-traces]; ablation `dstar2` |
| `spectrum.weighting` | `critical_path` | — | CP-SBFL card [novel_building_blocks §Q3][nbb]; ablation `none` |
| `templates.min_count` | 3 | lines | a priori; filters one-off lines |
| `peer.min_components` | 2 | components | a peer needs at least one other replica |
| `edge_gap.min_calls` | 10 | calls | a priori; medians over fewer calls are noise |
| `cards.max_tokens` | 1500 | tokens (*estimate*) | a priori; fits Relentra's 16 K context with room for brief and schema |
| `cards.bytes_per_token` | 4 | bytes | *estimate* for English/JSON-like text |
| `cards.k_default` | 6 | atoms | a priori |
| `intervention.max_candidates` | 5 | candidates | Causalith's `ci.max_candidates` limit ([05 §3.7](05-causalith.md)) |
| `predicates.<name>.<param>.min/max` | as §3.5 | — | ranges in §3.5; widening is a code review item |

`thresholds.anomaly_z` and `universe.include_external` live in `config/core.yaml` because Causatrix and Causentra use the same values.

## 5. Determinism and isolation rules

- Pure function of declared inputs + config. No wall clock, no `random`, no environment reads; iteration over services, series, edges and templates is always over sorted keys.
- Sums use `math.fsum` over sorted inputs; no BLAS calls (`@`, `np.dot`) on float arrays that feed outputs, so results do not depend on SIMD or thread count across the three Windows laptops and Ubuntu CI.
- Medians and maxima are order-independent; ties resolved by name A→Z.
- Imports allowed: `veyltrace_core`, `veyltrace_contracts`, `numpy`, `pyarrow`, `duckdb`, `networkx`, stdlib. Banned: `veyltrace_llm`, any LLM or HTTP client, `socket`, `torch`, `transformers`, `pandas` (package rule). `tests/test_isolation.py` enforces the root list.
- FaultLoom never reads `telemetry.*`, `answer_key`, `inject_time` or folder names.

## 6. Missing data and failure behaviour

| Missing | Effect |
|---|---|
| traces (`sources.traces` false; RE2-SS and RE3-SS have no traces [rcaeval_facts §Datasets and telemetry][rf-data]) | no `spectrum`, `critical_path_share`, `self_time_share`, `edge_gap`; `error_rate_above` and `on_critical_path` evaluate to null |
| logs | no log atoms; `template_new_in_incident` null |
| events | no `change_proximity`, no `peer_contrast{changes}`; `change_before_onset` null |
| metrics | anomaly atoms come only from traces/logs series |
| onsets for a service | no `onset_precedence` atoms for it; `onset_before` null |
| graph with no edges | no `propagation` atoms; reachability-based values not emitted |
| `alignment` absent | `tol_ns` = 15,000,000,000 (15 s, the common Prometheus scrape step) and a warning in `EngineResult.notes` |
| a required contract file absent (`case_manifest`, `alert`, `anomalies`, `onsets`, `graph.nodes`) | `EngineResult.status = failed`; pipeline stops (later engines cannot run without evidence) |
| malformed `proposals.json` (schema-invalid) | claim pass skipped, `status = degraded`; Causentra treats the case as having no valid proposals |

Absence is always "no atom" or `holds = null`, never a zero that looks like a healthy measurement.

## 7. Tests

**Unit** (`packages/faultloom/tests/`)

- each atom kind on hand-built tables, including every emission condition in §3.4 and every edge case in §3.9;
- `atom_id` matches the two IDs in §3.8 exactly;
- `log1p(value)` of every `robust_z` anomaly atom equals the max `score_norm` of its referenced `anomalies` rows (Anomara defines `score_norm = log1p(score)` for robust z, [03-anomara](03-anomara.md)); Causentra's `NO_FAULT` statistic relies on this ([09 §3.8](09-causentra.md));
- predicate table: polarity equals 03 §7; every validation branch (`unknown_predicate`, `unknown_entity`, `bad_args` for missing, extra, `subject` key, wrong type, out of range, NaN);
- `evidence_cards`: byte-identical text for the same inputs; budget enforcement; `truncated` set only when cards are dropped.

**Golden** (`veyltrace_core.testing.golden("evidence", case)`), fixtures in `packages/faultloom/fixtures/synth-0N/`. Package tests compare bytes only; behavioural expectations below are checked by the bench smoke experiment (which may read the synth answer keys) and by the human reviewing a fixture update.

| Case | What the fixture must show (review checklist) |
|---|---|
| synth-01 CPU hog | injected service: `internal_anomaly{cpu, robust_z}` ≥ `k_anom`; its callers: external anomalies only; `self_time_share` highest |
| synth-02 network delay | injected service: no internal atom ≥ `k_anom`; `edge_gap{in,p50}` and `{out,p50}` > 0 on its edges |
| synth-03 error injection | `log_new_template{error_level_only: true}` ≥ 1 and `log_error_rate` > 0 on the injected service |
| synth-04 change-induced regression | one `change_proximity` atom on the injected service with value > 0.5 (Causync acceptance O-06) |
| synth-05 no-fault | no internal or external `robust_z` atom ≥ `k_anom` anywhere; all `silence` = 0 |

**Property tests** (hypothesis):

- permutation invariance: shuffling input row order gives identical `evidence` bytes;
- monotonicity: raising one series' score never lowers its atom value;
- bounds: fractions in [0, 1]; no NaN/inf; Ochiai in [0, 1];
- symmetry: for random proposals, the set of `claim_check` atoms depends only on the set of distinct (predicate, args) and the claim-pass pool, not on which proposal named which service or in what order;
- rename invariance: consistently renaming services renames atoms' candidates, and IDs change only through the candidate string.

**Real-case smoke**: one RE2-OB, one RE2-SS (no traces), one RE2-TT case; checks schema validity, runtime and the determinism gate (two runs, equal hashes).

## 8. Performance budget

| Item | Budget | Basis |
|---|---|---|
| Engine pass, one RE2-TT case (~340–376 metrics, ~778k spans aggregated upstream [rcaeval_facts §Datasets and telemetry][rf-data], [§Metric step and windows][rf-step]) | ≤ 3 s, ≤ 1 GB peak RSS | *estimate*; FaultLoom reads aggregates, not spans |
| Claim pass (≤ 12 distinct claims × ≤ 10 claim-pass pool candidates) | ≤ 1 s | *estimate* |
| `evidence_cards` | ≤ 200 ms | *estimate* |
| Atom count | ≤ ~5,000 rows per case | *estimate*: ≤ 70 services × ~60 atoms |

These sit inside the deterministic path budget of ≤ 30 s and ≤ 3 GB per RE2 case ([02 §9](../02-architecture.md)).

## 9. Evaluation hooks and ablations

All arms are config overrides in an experiment YAML ([04 §9](../04-evaluation-protocol.md)); none is tuned on test splits.

| Ablation | Config | Question |
|---|---|---|
| Atom-kind drop | `atoms.disabled: [<kind>]` | which evidence channel carries accuracy |
| Detector set | `atoms.detectors` | robust_z vs nsigma as the base scorer |
| Score window | `window.score_ms` ∈ {60000, 300000, 600000} | early-window effect |
| Spectrum weighting | `spectrum.weighting: none`, `formula: dstar2` | does CP weighting add to plain SBFL |
| Self-time quantile | `self_time.quantile: p99` | T5 sensitivity |
| Card size | `cards.k_default` ∈ {3, 6, 9}; `cards.max_tokens` | proposer lift vs tokens (RQ2, RQ5) |

FaultLoom also reports per-case counters (atoms per kind, claims evaluated, claims rejected by reason) in `EngineResult.metrics` for the bench cost and proposer tables.

## 10. Tasks and milestones ([07](../07-roadmap.md))

| ID | Scope in this engine | Milestone |
|---|---|---|
| R-00 | stub: schema-valid `evidence` on synth | M0 (3 Nov) |
| R-06 | v0: `internal_anomaly`, `external_anomaly`, stable `atom_id`, golden tests | M1 (8 Nov) |
| R-07 | contracts 1.0 freeze; CCRs from §11 decided here | M1 |
| R-08 | v1: all kinds, predicate library with polarity, symmetric claim pass, `evidence_cards` | M2 (15 Nov) |
| X-07 (Explain) | consumes `evidence_cards` from R-08 fixtures | M2 |
| R-12 | T8 `intervention` atoms in the claim pass (§3.6) | M3 (22 Nov) |

## 11. Open questions (each with a default)

1. ~~Does `claims[].args` include the subject?~~ *Resolved in 03 §9.1 (2026-10-30):* `args` excludes the subject; a `subject` key is `bad_args`.
2. **Latency accounting.** *Resolved in 03 §3.4 (2026-10-30) for the spectrum:* `traces_total`, `traces_slow` and `cp_share_sum_slow` exist (slow = above the baseline p95 of the entry operation; error status does not count), used in §3.4. Still open: T5's entry-latency increase is approximated by the sum of positive self-time increases (§3.4). *Default:* keep; a slow-trace total per window (instead of `max_s traces_slow`) would need a CCR only if the two ever differ on real data.
3. ~~Onset alignment.~~ *Resolved in 03 §4.2 (2026-10-30):* `per_service[].*_onset_source` exists; offsets are applied as in §2.1.
4. **Context-klass series** (traffic) have no atom kind. *Default:* not atomised; traffic drops reach the rankers through two-sided robust z on internal/external series and through `silence`. CCR (`context_anomaly`) only if the telemetry ablation shows a loss.
5. ~~T8 intervention evidence.~~ *Resolved in 03 §7 (2026-10-30):* kind `intervention`, computed in the claim pass for decision-pool candidates (§3.4, §3.6).
6. **Cluster-scope changes.** *Default:* excluded from per-service atoms.
7. **Units of `changes.peer_contrast`.** *Default:* assumed comparable to robust z; confirm with Causync (O-06).
8. **`error_rate` series units** are not fixed in 03. *Default:* `error_rate_above` uses trace edges only.
9. ~~`graph.paths` coverage.~~ *Resolved in 02 §6.5 (2026-10-30):* Causalith computes paths for every anomalous service; `propagation{scope: path}` is absent only for services without an anomaly.
10. ~~`bad_args` has no home in the verdict.~~ *Resolved in 03 §10 (2026-10-30):* `bad_args` is a `proposals_rejected.reason`.
11. **Score window.** *Default* 5 min; whether onset-anchored windows should also be used for Signalyth's aggregates is an Observe question (it runs before `t_onset` exists).
12. **Anomaly direction** is not stored on atoms. *Default:* recover from `refs`; CCR only if the mode rules need it.

## 12. References

- Master spec: [02-architecture §3, §4, §6.6, §9](../02-architecture.md); contracts: [03 §1, §7](../03-contracts.md); roadmap: [07](../07-roadmap.md).
- [novel_building_blocks §Q3 (CP-SBFL), §Q5 (changes), §Q6 (telemetry ablation)][nbb]
- [sota_methods_2026 §Q3 (EviRCA evidence cards, DecompRCA)][sm]
- [verified_agents_local_llms §Q2 (failure modes: silence-as-health, untested edges)][va]
- [benchmarks_and_testbed §Q2 (evidence vs prompt effect, decoy sentence)][bt]
- PRISM, SimpleRCA, RE3 and RCAEval data facts: [rcaeval_facts §Anomaly scoring methods][rf-methods], [§Published baselines][rf-baselines], [§Datasets and telemetry][rf-data], [§Metric step and windows][rf-step]
- [v2 research report][report]

[nbb]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/novel_building_blocks.md
[sm]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/sota_methods_2026.md
[va]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/verified_agents_local_llms.md
[bt]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/benchmarks_and_testbed.md
[rf-data]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#datasets-and-telemetry-per-system
[rf-step]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#metric-step-and-windows
[rf-baselines]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#published-baseline-numbers
[rf-methods]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#anomaly-scoring-methods
[rf-traces]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#traces-spectrum-and-timing

[report]: ../../reports/Veyltrace%20v2%20SOTA%20root%20cause%20analysis.md
