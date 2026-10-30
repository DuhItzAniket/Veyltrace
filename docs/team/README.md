# docs/team — one file per person

Each person keeps `docs/team/<initials>.md`: what their laptop can do, which AI agent they use, and when they are available. The files are written in task L-01 ([07 §2](../07-roadmap.md#2-phase-0--ground-sat-31-oct--tue-3-nov)), following the setup in [09 §2](../09-ai-agent-playbook.md#2-laptop-toolchain-task-l-01). They are needed for three things:

- **Planning:** the lead splits overnight experiment runs (R-16) and lab collection (X-11) by laptop, and picks the demo laptop.
- **Model choice:** the default local model per laptop is decided from the `llama-bench` results ([02 §12](../02-architecture.md#12-open-decisions-tracked-as-adrs)).
- **The paper:** hardware, model hashes and measured speeds are reported as measured, not quoted from vendors ([verified_agents_local_llms §Q4][llm4]); the agent tool per person feeds the methods section ([09 §7.1](../09-ai-agent-playbook.md#71-recording-agent-usage-for-the-paper)).

| File | Person | Lane |
|---|---|---|
| `ak.md` | Aniket Kumar | Reason |
| `as.md` | Annapurna S | Observe |
| `cl.md` | C Lakshanaa | Explain |

Rules:

- Only you edit your file (`docs/team/*.md` is an author-owned shared path in `.github/lanes.yml`).
- Paste tool output as printed. Do not round, convert or "clean up" benchmark numbers. Anything not measured is marked *estimate*.
- Update the file when something material changes (new model pinned, RAM upgrade, agent tool switched, availability change) in a small `docs(team): …` PR.
- No secrets, serial numbers, IP addresses or personal contact details.

## Template

Copy everything inside the block into `docs/team/<initials>.md`.

````markdown
# <Full name> (`<initials>`)

> Lane: <Reason | Observe | Explain> · GitHub: `@<login>` · Last updated: YYYY-MM-DD

## Laptop

| Item | Value |
|---|---|
| Model | <vendor and model> |
| CPU | <model>, <physical cores> cores / <threads> threads |
| RAM | <GB>, <speed if known> |
| GPU / VRAM | <model, GB> or none |
| Free disk | <GB> on the drive holding the repo and models |
| Windows | `winver` build: <...> |
| WSL | `wsl --version`: <...> |
| `.wslconfig` | memory=<...>, swap=<...>, other keys: <...> |
| Docker Desktop | <version>; `docker info --format "{{.MemTotal}}"`: <...> |
| `sch_netem` loads in WSL | yes / no / not tried |

## Toolchain versions

| Tool | Command | Output |
|---|---|---|
| Git | `git --version` | |
| GitHub CLI | `gh --version` | |
| uv | `uv --version` | |
| Python | `uv run --no-project --python 3.12 python --version` | |
| Node | `node --version` | |
| pnpm | `pnpm --version` | |
| kind | `kind version` | |
| kubectl | `kubectl version --client` | |
| Helm | `helm version --short` | |
| Ollama | `ollama --version` | |
| llama.cpp | `llama-cli --version` | |

## Local LLM benchmark

Conditions: charger <plugged in / battery>, power mode <...>, other apps <closed / list>, date <YYYY-MM-DD>.

| Model | Quant | GGUF SHA-256 | Backend (CPU / CUDA / Vulkan) | Threads | `-ngl` | pp512 (t/s) | tg128 (t/s) | Loaded size (`ollama ps`) |
|---|---|---|---|---|---|---|---|---|
| Qwen3.5-9B | Q4_K_M | | | | | | | |
| Qwen3.5-4B | | | | | | | | |

Raw `llama-bench` output (`-p 512 -n 128 -r 3 -o md`), pasted unchanged:

```text
<paste here>
```

**Proposed default model for this laptop:** <Qwen3.5-9B Q4_K_M | Qwen3.5-4B ...>, because <tg128 value and RAM headroom>.

## AI coding agent

| Item | Value |
|---|---|
| Tool | <Claude Code | Codex | OpenCode | Antigravity | Cursor | Copilot | Windsurf/Devin | none> |
| Version and model | <e.g. CLI version, model name> |
| Plan and limits | <free / student / paid; known usage caps> |
| Load check passed ([09 §3](../09-ai-agent-playbook.md#3-per-tool-setup)) | yes, on YYYY-MM-DD |
| Skills load from `.agents/skills` or `.claude/skills` | yes / no (paste the file path into prompts instead) |
| Personal MCP servers | names only, or none |

## Availability

| Item | Value |
|---|---|
| Time zone | IST (UTC+5:30) |
| Usual working hours | <e.g. weekdays 18:00–23:00, weekends 10:00–18:00> |
| Focused hours per week (*estimate*) | <...> |
| Unavailable dates (31 Oct – 1 Dec) | <dates and reason, e.g. exams> |
| Laptop free for overnight runs | <which nights> |
````

[llm4]: ../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/verified_agents_local_llms.md#q4-local-open-weight-models-for-a-16-gb-laptop-tool-use-json-speed-ram-licences
