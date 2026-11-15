# Bench's summary.json and manifest.json get contracts before the first released result

- **Status:** Accepted (lead, on #69, 2026-11-14)
- **Date:** 2026-11-14
- **Author:** Aniket Kumar (AK)
- **Deciders:** the lead
- **Consulted:** Observe (O-14 reads `summary.json`), Explain (none)
- **Issue / CCR:** #69
- **Supersedes:** none · **Superseded by:** none

## Context

Bench writes 3 files per experiment (04 §9). Only `per_case.csv` has a contract (`bench_result`, 03 §13.2). `summary.json` and `manifest.json` are canonical JSON described in prose (03 §13.2, 04 §9), so a mistyped or missing key is never caught. Every paper number follows table → `summary.json` → `manifest.json` → experiment YAML + commit (04 §10.2), so these 2 files are part of the evidence chain. The M2 table (R-11) is the first result that will be released. Contracts are still 0.x because the R-07 freeze (#17) is open, so new contracts are additive and cheap now.

The `n_outside_universe` count names the wrong set. It counts roots outside `case_manifest.services` (04 §7's n_i), while 04 §7 separates n_i from the candidate universe U of 06 §2.1.

## Decision drivers

- Every reported number must be traceable and validated on write (04 §10.2).
- No released result should need a breaking rename later.
- Keep bench's writers on the shared contract path (AGENTS.md §5: outputs go through the matching writers).

## Considered options

1. **Two new contracts, `bench_summary` and `bench_manifest`,** validated on write, with the rename done in the same change.
2. **Pydantic models inside bench only:** validated on write, but no JSON Schema, so no generated types for O-14 and R-17 and no entry in 03.
3. **Keep prose only:** no work now, and errors surface at paper time.

## Decision

We choose **option 1**. It is the only option that puts both files on the same contract path as every other artefact, with generated Python and TS types for O-14 and R-17. It is additive at 0.1.0.

What changes:
- `contracts/schemas/bench_summary.schema.json` and `bench_manifest.schema.json` are added, and `scripts/gen_contracts.py` is rerun.
- Bench writes both through the core io writers.
- `schema_version` replaces the ad-hoc `schema` key. `producer` stays; `statistics` stays a string until O-14; `experiment` is a plain object validated by bench's strict model (lead answers on #69).
- Each group's metrics sit under `metrics`, one entry per 04 §9 metric name, null when the experiment does not list it. CONVENTIONS §3.1 requires every property to be present, and the generator does not support `propertyNames`, so the CCR's flat optional keys are not expressible. Nesting keeps every key typed and keeps "not requested" (null entry) apart from "undefined" (null inside an entry).
- `outcomes` always holds all five `run_outcome` values, 0 when none, so its keys are typed too.
- `n_outside_universe` becomes `n_outside_services`. The internal `CaseScore.in_universe` keeps its name for now: the open causatrix stack (#200) carries `bench/.../metrics.py`, and renaming it there is not worth a conflict.
- 03 gains §13.3 and §13.4; 04 §9 and `bench/README.md` link them.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Bench-only pydantic | small; no contract regeneration | no schema or TS types; 03 still prose | consumers outside bench can't rely on it |
| Prose only | no work | typos ship; a breaking rename later | fails 04 §10.2 traceability |

## Consequences

- **Positive:** every summary and manifest is validated on write, and O-14 and R-17 get typed inputs.
- **Negative / costs:** about 0.5 person-days (*estimate*). The schemas must be extended when `statistics` becomes an object (O-14), which is a minor bump.
- **Follow-ups:** O-14 extends `statistics`; R-17 reads only `bench_summary`.

## Confirmation

The synth-smoke bench test validates both files through the io readers, and `contracts-in-sync` stays green.

## Evidence

- 03 §13.2 and 04 §7, §9, §10.2 (in-repo).
- `bench/src/veyltrace_bench/summary.py` and `runner.py` at `f0a2ed3`: the current keys.
