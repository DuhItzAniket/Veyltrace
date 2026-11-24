# Annapurna S (`as`)

> Lane: Observe · GitHub: `@anu-082006` · Last updated: 2026-11-24

This laptop is the **Observe development machine**. It is the only macOS arm64 machine on the team, which matters for golden fixtures (see "macOS arm64 notes"). It runs no R-16 experiment and no local LLM.

## Laptop

| Item | Value |
|---|---|
| Model | Apple MacBook Air (`Mac16,12`) |
| CPU | Apple M4, 10 cores (4 performance and 6 efficiency) |
| RAM | 16 GB |
| GPU / VRAM | integrated (Apple M4, unified memory); no discrete GPU |
| Free disk | 8.5 GB of 228 GB (2026-11-24, with RE2 dev cases 3 of 270 and all of Nezha fetched) |
| macOS | `sw_vers`: macOS 15.5, build 24F74 (the template's Windows, WSL and `.wslconfig` rows do not apply) |
| Docker Desktop | `docker --version`: Docker version 29.3.1, build c2be9cc; `docker info` memory not captured |
| `sch_netem` loads in WSL | not applicable (no lab collection on this laptop) |

Disk is the limit on this machine: 8.5 GB free. A full RE2 fetch (3.44 GB on Hugging Face, plus the conversion cache) fits only just, so this laptop works on the three RE2 development cases and Nezha, and full-RE2 measurements come from the other laptops.

## Toolchain versions

Captured 2026-11-24.

| Tool | Command | Output |
|---|---|---|
| Git | `git --version` | git version 2.39.5 (Apple Git-154) (`core.autocrlf` is `input`) |
| GitHub CLI | `gh --version` | gh version 2.103.2 (2026-10-23) |
| uv | `uv --version` | uv 0.13.8 (Homebrew 2026-11-12 aarch64-apple-darwin) |
| Python | `uv run --no-project --python 3.12 python --version` | Python 3.12.16 |
| Node | `node --version` | v26.5.0 |
| pnpm | `pnpm --version` | not installed (no console work on this laptop) |
| kind | `kind version` | not installed (no lab on this laptop) |
| kubectl | `kubectl version --client` | Client Version: v1.35.3 |
| Helm | `helm version --short` | not installed |
| Ollama | `ollama --version` | not installed |
| llama.cpp | `llama-cli --version` | not installed |

## macOS arm64 notes

- **Golden fixtures are not regenerated here (#256).** Anomara's `bocpd` and `robust_z` scores differ in the last digits between this machine and the one that produced the committed goldens (on `synth-01`, 62 of 284 `anomalies` rows). The golden comparison is tolerant, so every gate passes here; but `--update-golden` on this laptop would write those differences into the fixtures. PRs from this lane that need new goldens ask the lead to regenerate them (as #450 did).
- **Python differs in the patch version** from the recording host (3.12.16 here, 3.12.13 there). No test has depended on it.
- **Gates run with `VEYLTRACE_DATA` unset**, so `real_data` tests skip; real-data checks use a scratch data root.
- **Pipeline speed and memory on this machine** (AI off, one case per RE2 system, warm conversion cache; from #36, 23 Nov, `main` at `9e553e1c`, measured with `scripts/observe/perf_check.py`): RE2-OB 9.2 s and 1,001 MiB peak RSS, RE2-SS 5.4 s and 395 MiB, RE2-TT 18.0 s and 1,740 MiB. One case per system is not a p95.

## Local LLM benchmark

**Not run: no local LLM on this laptop.** Ollama and llama.cpp are not installed, and the Observe lane's engines never call a model (AGENTS.md §4, Never 3). The AI arms are recorded on the recording host ([ak.md](ak.md)).

**Proposed default model for this laptop:** none.

## AI coding agent

| Item | Value |
|---|---|
| Tool | Claude Code (Claude desktop app, Code tab) |
| Version and model | *to fill* |
| Plan and limits | *to fill* |
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
| Laptop free for overnight runs | no: 8.5 GB free disk and 3 of 270 RE2 cases; not used for R-16 |
