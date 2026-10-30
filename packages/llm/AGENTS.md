# AGENTS.md — packages/llm

Adds to the root [AGENTS.md](../../AGENTS.md) and never overrides it.

- **Lane:** Explain. Edit only Explain paths (root AGENTS.md §2).
- **Purpose:** `veyltrace_llm`, the only code that talks to an LLM: providers (`ollama`, `llamacpp`, `openai_compat`, `fake`), JSON-schema-constrained calls, cassette record/replay.
- **Spec:** [docs/engines/08-relentra.md §3.8, §5](../../docs/engines/08-relentra.md) · master [02 §5.2, §8, §9](../../docs/02-architecture.md).
- **Inputs:** canonical requests from Relentra, Causivra and the gateway health probe; `config/llm.yaml`; `ai.mode`.
- **Outputs:** parsed responses with usage and recorded latency; `cassette/<key>.json` and `cassette/index.json` in the run directory.

## Package rules

1. Only `relentra`, `causivra` and `gateway` may import this package (CI isolation test).
2. **Localhost only:** accept `base_url` hosts `localhost`, `127.0.0.1`, `::1`. Any other host is rejected before a connection or DNS lookup unless `VEYLTRACE_ALLOW_REMOTE_LLM=1`.
3. **Cassette key** = SHA-256 of `canonical_json` of the canonical request (purpose, model, messages with LF line endings, schema, sampler params). Headers, URLs, timeouts and thread counts are not part of the key.
4. **Strict replay:** in `replay` mode a missing key or occurrence raises `CassetteMiss` and no socket is opened. `off` mode refuses every call.
5. Record mode refuses to write into a non-empty cassette directory unless `--force-record` is given. Files are written atomically and contain no timestamps.
6. Provider errors and timeouts are recorded as outcomes, so replay reproduces them.
7. Within the pipeline, this package is the only code that reads a clock (monotonic, to measure latency); the value is written to the cassette before it is returned.
8. `FakeProvider` must stay deterministic and cover errors and timeouts; other packages' tests depend on it.

## Commands

| Task | Command |
|---|---|
| Check this package | `uv run python scripts/check.py --package llm` |
| Lane check | `uv run scripts/check_lanes.py --lane explain` |

## Never

- Never add a default `base_url` that is not loopback, or bypass the remote-host check.
- Never read API keys from config files or write them (or any header) into a cassette; `openai_compat` keys come from the environment only.
- Never retry inside a provider without recording each attempt.
- Never cache responses anywhere except the cassette.
- Never download model weights; models are installed manually (task L-01).
