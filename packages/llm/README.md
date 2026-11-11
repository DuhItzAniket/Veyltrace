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

HTTP providers, the cassette and strict replay arrive in X-01.

Runtime settings for reproducible regeneration: llama.cpp `llama-server -np 1` with `cache_prompt: false` and a fixed seed, or Ollama with `OLLAMA_NUM_PARALLEL=1` and a fixed seed ([02 §8](../../docs/02-architecture.md)).

```sh
uv run python scripts/check.py --package llm
```
