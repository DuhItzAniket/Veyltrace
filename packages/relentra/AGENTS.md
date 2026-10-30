# AGENTS.md — packages/relentra

Adds to the root [AGENTS.md](../../AGENTS.md) and never overrides it.

- **Lane:** Explain. Edit only Explain paths (root AGENTS.md §2).
- **Purpose:** engine 8, the LLM investigator. It **proposes** hypotheses and predicate checks; code decides.
- **Spec:** [docs/engines/08-relentra.md](../../docs/engines/08-relentra.md) · master [02 §6.8](../../docs/02-architecture.md) · contracts [03 §7–9](../../docs/03-contracts.md).
- **Inputs:** `slate`, `evidence` (via FaultLoom `evidence_cards`), `graph.*`, `signal_cube.*`, `anomalies`, `onsets`, `changes` (read-only tools), `alert`, `case_manifest`, system briefs, `config/relentra.yaml`, `config/llm.yaml`, cassette (replay).
- **Outputs:** `proposals.json`, `agent_trace.jsonl`; cassette entries through `veyltrace_llm`.

## Package rules

1. Talk to models only through `veyltrace_llm` (allowed for this package). No HTTP client, `torch` or `transformers` imports.
2. Every model output passes the per-case JSON schema, then Pydantic, then FaultLoom `validate()` before it is written. Invalid parts are dropped with a trace line, never silently.
3. `args` holds only the arguments after the subject; a `subject` key is `bad_args` (03 §9.1, 06 §3.5). Argument ranges come from the predicate registry, not from this package.
4. No clock reads. Budgets use `latency_ms` recorded in the cassette. Seeds and permutations come from `veyltrace_core.rng`.
5. Prompts live in `prompts/*.md`, system briefs in `briefs/*.md`. Any edit changes `prompt_sha256` and invalidates cassettes: re-record on purpose, never edit a cassette by hand.
6. Briefs describe architecture only: no fault names, flag names or injection hints.
7. `baseline.py` (agent-only baseline) is called by bench only. `api.run` must never import it.
8. Tests use `FakeProvider`. CI never needs a running model.

## Commands

| Task | Command |
|---|---|
| Check this package | `uv run python scripts/check.py --package relentra` |
| Determinism gate | `uv run python scripts/check.py --determinism` |
| Lane check | `uv run scripts/check_lanes.py --lane explain` |

## Never

- Never import `veyltrace_causentra`, read `verdict.json`, `case_manifest.t_alert_hint_ns`, answer keys, or any path under `bench/` or `lab/`.
- Never add a tool that returns raw telemetry rows or reads files outside the run directory.
- Never relax a schema enum into free text (entities, predicates, fault classes, trials).
- Never let the model's numbers reach code as facts; thresholds in `args` are the only numbers it supplies.
- Never commit cassettes recorded on non-synthetic data.
