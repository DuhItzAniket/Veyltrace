# Aniket Kumar (`ak`)

> Lane: Reason · GitHub: `@DuhItzAniket` · Last updated: 2026-11-23

This laptop is the **recording host**: every R-16 AI-arm run is recorded here, so its model file is the pinned GGUF of `config/llm.yaml` (#449) and RQ6 Tier 1 replays start from runs made here.

## Laptop

| Item | Value |
|---|---|
| Model | LENOVO 83DG |
| CPU | Intel(R) Core(TM) i7-14650HX, 16 cores / 24 threads |
| RAM | 16 GB (one module, 5600 MT/s); 15.7 GB visible to Windows |
| GPU / VRAM | NVIDIA GeForce RTX 4050 Laptop GPU, 6141 MiB (`nvidia-smi`, driver 616.56); Intel UHD Graphics (integrated) |
| Free disk | 185 GB of 953 GB on C: (2026-11-23, after fetching RE3 and Nezha) |
| Windows | Windows 11 Home Single Language 26H2, build 26300.9974 |
| WSL | `wsl --version`: WSL version 3.0.5.0, kernel 6.18.58.1-1 |
| `.wslconfig` | none (WSL defaults) |
| Docker Desktop | `docker --version`: Docker version 29.8.2, build 7fc2dff; `docker info` memory not captured |
| `sch_netem` loads in WSL | not tried (no lab collection on this laptop) |

RAM is the limit on this machine: with the Claude desktop app open, free RAM was 3.0 GB at 06:45 IST on 23 Nov. R-16 therefore runs at most 1–2 heavy jobs in the day and 3 overnight (#45 plan).

## Toolchain versions

Captured 2026-11-23.

| Tool | Command | Output |
|---|---|---|
| Git | `git --version` | git version 2.55.0.windows.3 (`core.autocrlf` is `false`) |
| GitHub CLI | `gh --version` | gh version 2.102.0 (2026-09-30) |
| uv | `uv --version` | uv 0.13.0 (4ecd0eff2 2026-10-09 x86_64-pc-windows-msvc) |
| Python | `uv run --no-project --python 3.12 python --version` | Python 3.12.13 |
| Node | `node --version` | v25.9.0 |
| pnpm | `pnpm --version` | 12.11.2 |
| kind | `kind version` | not installed (no lab on this laptop) |
| kubectl | `kubectl version --client` | Client Version: v1.36.1, Kustomize Version: v5.8.1 |
| Helm | `helm version --short` | not installed |
| Ollama | `ollama --version` | client version is 0.40.16 |
| llama.cpp | `llama-cli --version` | not installed (see below) |

## Local LLM

### Pinned model file

| Model | Ollama tag | Quant | GGUF SHA-256 | Size |
|---|---|---|---|---|
| Qwen3.5-9B | `qwen3.5:9b` | Q4_K_M (GGUF header `general.file_type = 15`) | `02d45dc1cf451ba2475ac33b301c2dd8f985abe4c182ce04a1f2f5bf0260278d` | 5,629,109,120 bytes |

The SHA-256 is the model layer of the Ollama manifest (`~/.ollama/models/manifests/registry.ollama.ai/library/qwen3.5/9b`). The blob was re-hashed and gives the same value, and its GGUF header was read directly (2026-11-22). It is the value pinned in `config/llm.yaml` (#449).

### Benchmark

**No `llama-bench` run (lead decision, 2026-11-23).** `llama-bench` exists to choose a model per laptop (02 §12), and the model is already chosen and pinned. RQ5's cost numbers come from the pipeline's own per-case records (04 §2), not from `llama-bench`. Installing llama.cpp on the recording host just before R-16 was not worth the download and machine time.

The speed that matters here is a brief-sized call through Ollama. It is measured with `llm_bench` (a prompt of about 7,300 characters through the Ollama API) just before the first R-16 AI run, when Ollama has to be started anyway. The raw output is pasted below unchanged, with its conditions. A run at 06:45 on 23 Nov was skipped because free RAM was 3.0 GB, and the 9B needs about 5 GB; a number taken under memory pressure would mislead.

Conditions: *to fill at measurement time* (charger, power mode, other apps, date).

```text
<raw llm_bench output and `ollama ps` here, before the first R-16 AI run>
```

**Default model for this laptop:** Qwen3.5-9B Q4_K_M, pinned for all AI arms (04 §4, §10.7).

## AI coding agent

| Item | Value |
|---|---|
| Tool | Claude Code (Claude desktop app, Code tab) |
| Version and model | Claude Opus 5.5 |
| Plan and limits | *to fill*; the 5-hour usage limit was reached several times during M3 |
| Load check passed ([09 §3](../09-ai-agent-playbook.md#3-per-tool-setup)) | yes (`CLAUDE.md` → `AGENTS.md` loaded in every session) |
| Skills load from `.agents/skills` or `.claude/skills` | yes (`.claude/skills`: start-issue, open-pr, contract-change-request, determinism-check) |
| Personal MCP servers | *to fill* |

## Availability

| Item | Value |
|---|---|
| Time zone | IST (UTC+5:30) |
| Usual working hours | *to fill* |
| Focused hours per week (*estimate*) | *to fill* |
| Unavailable dates (31 Oct – 1 Dec) | *to fill* |
| Laptop free for overnight runs | every night from 23 to 27 Nov (R-16) |
