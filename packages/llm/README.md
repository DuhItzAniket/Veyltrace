# veyltrace-llm

`veyltrace_llm`: LLM providers and the cassette used by Relentra and Causivra.

- Providers: Ollama, llama.cpp `llama-server`, any OpenAI-compatible endpoint, and a deterministic `FakeProvider` for tests.
- Calls are JSON-schema constrained and re-validated by the caller.
- Every call is recorded in the run's `cassette/`, keyed by SHA-256 of the canonical request. `--ai replay` serves recorded responses and fails on any unrecorded call, so verdicts replay on any machine.
- Talks to `localhost` only unless `VEYLTRACE_ALLOW_REMOTE_LLM=1` (split demo over LAN).
- Spec: [docs/engines/08-relentra.md §5](../../docs/engines/08-relentra.md); settings in `config/llm.yaml`.

**Status (X-00).** `veyltrace_llm.request` defines the canonical request (`LLMRequest.key` is the cassette key) and the provider outcome (`Completion`: content or a recorded error, usage, latency, runtime). `veyltrace_llm.fake.FakeProvider` serves scripted replies by cassette key, then by (purpose, occurrence), then a default; it can return connection errors and timeouts and reports fixed usage and latency, so other packages test without a model:

```python
from veyltrace_llm.fake import FakeProvider, FakeReply

fake = FakeProvider({"relentra.brief": [FakeReply.json({"proposals": [], "asks": []}), FakeReply.failure("timeout")]})
```

**Status (X-01).** Engines call the model through `LLMClient` in the run's AI mode:

```python
from veyltrace_llm.client import LLMClient
from veyltrace_llm.settings import settings_from

client = LLMClient(settings_from(ctx.config.section("llm")), ctx.ai_mode, ctx.cassette_dir)
reply = client.call_json("relentra.brief", messages, schema, params)  # reply.value, reply.completion
```

- `off` raises `AIDisabled`; `record` asks the provider and appends every outcome (errors included) to `cassette/<key>.json` and `cassette/index.json`; `replay` answers from the cassette, raises `CassetteMiss` on any unrecorded key or occurrence, and never builds a provider.
- Provider errors raise `ProviderError` (`ProviderUnavailable`, `ProviderTimeout`) with the recorded completion attached, so usage and latency still count; invalid JSON comes back in `reply.parse_error` for the caller's repair.
- Providers (`llm.provider`): `ollama` (`/api/chat`, schema as `format`), `llamacpp` (`/v1/chat/completions`, `json_schema` response format, `cache_prompt` from config), `openai_compat` (standard fields only; optional bearer key from `VEYLTRACE_LLM_API_KEY`), `fake`. `base_url` is the server root. HTTP is stdlib `http.client`, loaded only when a call is made; no retries.

Runtime settings for reproducible regeneration: llama.cpp `llama-server -np 1` with `cache_prompt: false` and a fixed seed, or Ollama with `OLLAMA_NUM_PARALLEL=1` and a fixed seed ([02 §8](../../docs/02-architecture.md)).

```sh
uv run python scripts/check.py --package llm
```
