# Parquet as the durable format, DuckDB as the in-process query engine

- **Status:** Accepted (version pin confirmed by the M0 smoke test, per [02 §12](../02-architecture.md))
- **Date:** 2026-10-30
- **Author:** Aniket Kumar (ak)
- **Deciders:** lead
- **Consulted:** Observe lane (main producer), Explain lane (gateway live buffer)
- **Issue / CCR:** kickoff; M0 smoke test
- **Supersedes:** none · **Superseded by:** none

## Context

- Veyltrace needs one analytical store that serves offline benchmark cases and live snapshots with the same code path, runs in-process on a 16 GB laptop, and gives byte-stable inputs for hashing and replay.
- **DuckDB 2.0.0 LTS shipped on 21 Oct 2026** with a new default storage format that versions below 2.0 cannot read; LTS support runs until at least Oct 2027 and **1.5 is supported until Mar 2027**. On Windows, most core extensions are still built with MSVC. 2.0's new PEG parser and async I/O were nine days old at decision time ([stack_and_market §A2][sm]).
- DuckDB's ASOF JOIN answers "latest change before each service's onset" in one query ([stack_and_market §A2][sm]).
- A local Tempo deployment alone is sized at 4–8 GB RAM, 16 GB or more when it shares a host; running Tempo, Loki and Prometheus (plus ClickHouse) separately will not fit comfortably ([stack_and_market §A2][sm]).
- RCAEval ships its 735 cases as ~3.4 GB of Parquet on Hugging Face ([sota_methods §Q5][sota]).

## Decision drivers

- One code path for offline and live analysis.
- Deterministic, hashable inputs and outputs.
- Fits in ≤ 3 GB per case alongside everything else ([02 §9](../02-architecture.md)).
- A storage-format change in a dependency must not break stored artifacts.

## Considered options

1. **Parquet (zstd) durable + DuckDB in-process, 2.0.x LTS default, 1.5.x fallback** (chosen).
2. DuckDB native `.duckdb` files as the store.
3. Self-hosted Tempo + Loki + Prometheus as Veyltrace's store.
4. ClickHouse / ClickStack locally.
5. Polars or pandas only, no SQL engine.

## Decision

1. **Every telemetry table and engine artifact is Parquet (zstd)** in long format with fixed column names, sorted by its declared key, with the schema name and version in file metadata (`veyltrace.schema`), or canonical JSON ([03 §1](../03-contracts.md)).
2. **DuckDB is a query engine only.** No `.duckdb` file is an input or output of any run. Engines open in-memory connections over Parquet.
3. **Version pin:** DuckDB **2.0.x LTS** by default, pinned in `uv.lock`. If the M0 smoke test fails on any team laptop (Windows extension, parser or I/O issue), fall back to **1.5.x** (supported to Mar 2027) through a one-line `chore(deps)` PR plus a superseding ADR. Because only Parquet is persisted, switching versions does not change any artifact.
4. **Determinism settings:** `threads=1` for final aggregates, exact quantiles, explicit `ORDER BY` on every result written ([report][rep], "Replay re-verifies recorded proposals"); `memory_limit` set from config.
5. **Change alignment** uses ASOF JOIN on aligned times (Causync).
6. **No self-hosted Tempo, Loki or Prometheus as Veyltrace storage.** Live mode keeps an in-memory window in the gateway and freezes it to Parquet with hashes when a diagnosis starts ([02 §5](../02-architecture.md)). The lab's capture stack (one OTel Collector with `memory_limiter`, plus whatever minimal backends [05-fault-lab-and-dataset](../05-fault-lab-and-dataset.md) specifies) exists only to produce captures. `grafana/otel-lgtm` is an optional, memory-capped side panel for the demo, never a dependency.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Native `.duckdb` files | Faster repeated queries | 2.0 files unreadable by < 2.0; binary files are hard to hash stably and cannot be committed | Format break and hashing |
| Tempo + Loki + Prometheus | "Production-shaped" | Several GB of RAM; Tempo search is non-deterministic, so every pull would need snapshotting anyway ([benchmarks_and_testbed §Q4][bt]) | RAM and determinism |
| ClickHouse / ClickStack | Scales well | No official local RAM minimum; extra service | Cloud-later option |
| Polars/pandas only | No SQL engine | No ASOF JOIN equivalent as simple; two query styles across lanes | DuckDB SQL is shared offline and live |

## Consequences

- **Positive:** Same SQL over benchmark folders, lab captures and live snapshots; any live diagnosis becomes a replayable offline case. Parquet is readable by every analysis tool reviewers use.
- **Negative:** Parquet file bytes include a writer string, so file hashes depend on the pinned `pyarrow`; a different version shows up as replay exit 5 (environment drift) rather than silent change. Parquet files are git-ignored ([AGENTS.md §4.6](../../AGENTS.md)), so only small synthetic fixtures are committed; per-case benchmark results are written as CSV (`bench/results/<experiment>/per_case.csv`, committed, [03 §13.2](../03-contracts.md)), which resolves [12-risks](../12-risks.md) RK-23.
- **Follow-ups:** M0 smoke test on all three laptops (DuckDB version, Parquet round trip, ASOF JOIN); record the result in this ADR's PR.

## Confirmation

- Determinism gate: identical output hashes across two runs on `synth-01` and one real case.
- O-11: ≤ 30 s and ≤ 3 GB per RE2 case on the slowest laptop.

## Evidence

- [stack_and_market §A2–A3][sm]; [sota_methods §Q5][sota]; [benchmarks_and_testbed §Q4][bt]; [report][rep], "One Collector, Parquet and DuckDB replace a five-database stack".

[rep]: ../../reports/Veyltrace%20v2%20SOTA%20root%20cause%20analysis.md
[sota]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/sota_methods_2026.md
[bt]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/benchmarks_and_testbed.md
[sm]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/stack_and_market.md
