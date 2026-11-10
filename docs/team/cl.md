# C Lakshanaa (`cl`)

> Lane: Explain · GitHub: `@C-LAKSHANAA` · Last updated: 2026-11-10

This file covers two machines. **Laptop 1** is the lab machine (kind, Online Boutique, Chaos Mesh; X-02, X-06, X-11 captures). **Laptop 2** runs the local LLM (the split demo of [02 §10](../02-architecture.md#10-deployment-shapes)) and is measured separately; its section is filled in on that machine.

## Laptop 1 (lab)

| Item | Value |
|---|---|
| Model | Lenovo 82KA |
| CPU | 11th Gen Intel Core i5-1135G7 @ 2.40GHz, 4 cores / 8 threads |
| RAM | 40 GB (32 GB + 8 GB), 3200 MT/s |
| GPU / VRAM | Intel Iris Xe Graphics (integrated, shared memory); no discrete GPU |
| Free disk | 83 GB of 337 GB on C: (2026-11-10) |
| Windows | Windows 11 Pro 25H2, build 26200.9711 |
| WSL | `wsl --version`: WSL 3.0.3.0, kernel 6.18.54.1-1, WSLg 1.0.79 |
| `.wslconfig` | none (WSL defaults: half of RAM, about 20 GB) |
| Docker Desktop | 4.95.0.242831, engine 29.8.2; memory available to Docker 19.44 GiB (`docker stats`, 2026-11-09; `docker info` not captured) |
| `sch_netem` loads in WSL | yes: `modprobe sch_netem` and a 1 ms `tc netem` qdisc inside the kind node succeeded on 2026-11-09, so F04, F05 and F13 run here |

### Toolchain versions

| Tool | Command | Output |
|---|---|---|
| Git | `git --version` | git version 2.50.1.windows.1 (`core.autocrlf` is `true`; 09 §2.1 asks for `false`, not changed yet) |
| GitHub CLI | `gh --version` | gh version 2.103.3 (2026-10-26) |
| uv | `uv --version` | uv 0.13.1 (62faed335 2026-10-13 x86_64-pc-windows-msvc) |
| Python | `uv run --no-project --python 3.12 python --version` | Python 3.12.15 |
| Node | `node --version` | v24.21.0 |
| pnpm | `pnpm --version` | not installed |
| kind | `kind version` | kind v0.33.0 go1.26.10 windows/amd64 (built from source on 2026-11-09: GitHub release downloads returned 504) |
| kubectl | `kubectl version --client` | Client Version: v1.36.1 |
| Helm | `helm version --short` | v4.3.1+gc0d08d0 |
| Ollama | `ollama --version` | not installed on this laptop (LLM runs on Laptop 2) |
| llama.cpp | `llama-cli --version` | not installed on this laptop (LLM runs on Laptop 2) |

### Lab measurements (2026-11-09/10)

- The `ob` profile ran with 1.71 GiB in the kind node container (`docker stats`), CPU about 36% while idle traffic ran.
- First start pulled every image: Chaos Mesh alone took more than 5 minutes from ghcr.io, the app more than 15 minutes.
- On battery the laptop entered Modern Standby repeatedly and the battery fell from 83% to 28% in about an hour under lab load; seven cases were lost (`host_suspended`). **Run campaigns on mains power only.**
- Lab results: 9 fault types captured, 7 validated by the 05 §8.2 rule (ADRs `20261109-cl-lab-catalog-packager`, `20261110-cl-lab-validation`).

## Laptop 2 (LLM host)

To be measured on that machine, following [09 §2.6–2.7](../09-ai-agent-playbook.md#26-ollama-and-models).

| Item | Value |
|---|---|
| Model | TODO |
| CPU | TODO |
| RAM | TODO |
| GPU / VRAM | TODO |
| Free disk | TODO |
| Ollama | `ollama --version`: TODO |
| llama.cpp | `llama-cli --version`: TODO |

### Local LLM benchmark

Conditions: charger TODO, power mode TODO, other apps TODO, date TODO.

| Model | Quant | GGUF SHA-256 | Backend (CPU / CUDA / Vulkan) | Threads | `-ngl` | pp512 (t/s) | tg128 (t/s) | Loaded size (`ollama ps`) |
|---|---|---|---|---|---|---|---|---|
| Qwen3.5-9B | Q4_K_M | | | | | | | |
| Qwen3.5-4B | | | | | | | | |

Raw `llama-bench` output (`-p 512 -n 128 -r 3 -o md`), pasted unchanged:

```text
TODO: paste here
```

**Proposed default model:** TODO, from the tg128 value and RAM headroom on Laptop 2.

## AI coding agent

| Item | Value |
|---|---|
| Tool | Claude Code (desktop app, Code tab) |
| Version and model | Claude Opus 5.5 (`claude-opus-5-5`) |
| Plan and limits | TODO |
| Load check passed ([09 §3](../09-ai-agent-playbook.md#3-per-tool-setup)) | yes, on 2026-11-09: the repo skills (`start-issue`, `open-pr`, `determinism-check`, `contract-change-request`) were listed in the session |
| Skills load from `.agents/skills` or `.claude/skills` | yes (`.claude/skills`) |
| Personal MCP servers | Desktop Commander, Claude in Chrome, Claude Docs; design and engineering plugin connectors present but not signed in |

## Availability

| Item | Value |
|---|---|
| Time zone | IST (UTC+5:30) |
| Usual working hours | TODO |
| Focused hours per week (*estimate*) | TODO |
| Unavailable dates (31 Oct – 1 Dec) | TODO |
| Laptop free for overnight runs | TODO (Laptop 1, on mains power only) |
