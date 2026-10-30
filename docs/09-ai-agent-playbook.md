# 09 · AI agent playbook

> **Status:** v1.0 · **Owner:** lead · **Last updated:** 2026-10-30
> Goal: three people, each possibly on a different AI coding agent, work from the same rules and produce PRs that look the same. This doc says how to set up each tool so it loads [AGENTS.md](../AGENTS.md), how to run a session, what to paste into the agent, and how to recover when the agent goes wrong.
> The binding rules are in [AGENTS.md](../AGENTS.md); this doc explains and applies them. If the two disagree, AGENTS.md wins and the lead fixes this doc. Tool-behaviour claims come from [multi_agent_dev_and_sdlc][q1] (official vendor docs fetched 29–30 Oct 2026) unless marked **verify**.

## 1. Principles

### 1.1 One canonical rules file

The root `AGENTS.md` is the only rules file in the repo. Every tool we use reads it natively; Claude Code reads it through a one-line import.

| Tool | Root `AGENTS.md` | Nested `AGENTS.md` | How files combine |
|---|---|---|---|
| Claude Code | via `CLAUDE.md` containing `@AGENTS.md` (native reading from v2.1.277 only when **no** `CLAUDE.md` exists) | via a nested `CLAUDE.md` = `@AGENTS.md`, loaded when Claude reads or edits a file in that folder | concatenated, closest file read last |
| Codex (CLI, IDE, cloud) | yes | yes, from the Git root down to the current folder, one file per folder | concatenated, closer files later; capped at 32 KiB |
| OpenCode | yes | walks up from the current folder; "first matching file wins" | `instructions` globs in `opencode.json` add files |
| Cursor | yes | yes | combined with parents; the more specific file wins |
| Copilot cloud agent | yes | yes, nearest file wins | also reads a root-only `CLAUDE.md`/`GEMINI.md` |
| Copilot in VS Code | yes (`chat.useAgentsMdFile`, on by default) | only with `chat.useNestedAgentsMdFiles` (experimental, off by default) | additive, no precedence |
| Antigravity (IDE, CLI) | yes | yes, in any subfolder | cumulative; the more specific folder wins |
| Windsurf / Devin Desktop | yes, always on | subfolder file = auto-glob for that folder | rules engine; 12,000 characters per rule file |

Source: [multi_agent_dev_and_sdlc §Q1][q1].

### 1.2 Nested `AGENTS.md` per package, with a `CLAUDE.md` beside it

Each package may have `packages/<name>/AGENTS.md` with rules for that package only, written by the lane that owns the package. Next to it goes `packages/<name>/CLAUDE.md` whose whole content is `@AGENTS.md` and a newline. Reason: once a root `CLAUDE.md` exists, Claude Code's default mode reads `CLAUDE.md` files only, so without the nested import it would never see the package rules ([§Q1 inferences][q1]). `uv run --no-project python scripts/sync_agent_files.py` creates a missing nested `CLAUDE.md`; CI (`agent-files` job) fails if one is missing or has other content.

A nested `AGENTS.md` should look like this (≤ 3 KB):

```markdown
# packages/signalyth — rules for this package (adds to the root AGENTS.md)

Owner lane: Observe. Spec: docs/engines/02-signalyth.md. Contracts produced: signal_cube.* (docs/03-contracts.md §3).

- Inputs: telemetry.* via veyltrace_core.io loaders only. Outputs: signal_cube.* via the contract writers only.
- Drain3 template IDs must be stable across runs: sort log lines by (service, t_ns, body) before mining.
- Golden fixtures: fixtures/synth-01 … synth-05. Refresh with: uv run python scripts/check.py --package signalyth --update-golden
- Check: uv run python scripts/check.py --package signalyth
```

### 1.3 No copies, no tool-specific rule files

Do not create any of these. `scripts/sync_agent_files.py --check` fails in CI if one is committed.

| File or folder | Why not |
|---|---|
| `GEMINI.md` | Antigravity reads `AGENTS.md`, and its rules are cumulative, so a `GEMINI.md` would add a second copy of the rules ([§Q1][q1]). Gemini CLI itself stopped serving personal accounts on 18 Jun 2026. |
| `.cursor/rules/*.mdc` | Cursor reads `AGENTS.md` in the root and subfolders ([§Q1][q1]). A copy drifts. `.cursor/` is gitignored, and the CI check rejects `.cursor/rules/` if it is force-added. |
| `.github/copilot-instructions.md`, `.github/instructions/` | The Copilot cloud agent and VS Code read `AGENTS.md`. These files are only needed for Copilot **code review**; adding one needs an ADR and a change to the allow-list in the sync script. |
| `.windsurf/rules/`, `.devin/rules/`, `.agents/rules/` | Windsurf/Devin and Antigravity read `AGENTS.md`; `.agents/rules/` would load as Antigravity rules. `.agents/` is only for skills. |
| `AGENTS.override.md` | Codex uses it **instead of** `AGENTS.md` in that folder ([§Q1][q1]), so one person's agent would silently follow different rules. |
| symlinks (`CLAUDE.md -> AGENTS.md`) | Git for Windows disables symlinks by default; Claude Code refuses to create a worktree when `.claude` is a symlink ([§Q1][q1]). |

The same files are merged differently by each tool (concatenated, cumulative, nearest-wins, additive), and the Claude docs warn that contradictory instructions "may be resolved arbitrarily". One file, no copies, is the only setup where every agent sees the same rules.

### 1.4 Size budget

| Limit | Value | Source |
|---|---|---|
| Windsurf/Devin workspace rule file | 12,000 characters (probably applies to `AGENTS.md`; **verify**) | [§Q1][q1] |
| Antigravity file after includes | 24,000 bytes, then truncated | [§Q1][q1] |
| Codex combined instructions | 32 KiB (`project_doc_max_bytes`), then later files are dropped | [§Q1][q1] |
| Claude Code `CLAUDE.md` | keep under 200 lines | [§Q1][q1] |

Our budget: root `AGENTS.md` ≤ 10 KB (about 9 KB on 2026-10-30), each nested `AGENTS.md` ≤ 3 KB, root + nested ≤ 16 KB. The sync script fails CI above the hard limits (12,000 characters per file, 32 KiB root + nested). Long material goes in `docs/` and is linked, not imported.

### 1.5 Children add, never contradict

A nested `AGENTS.md` may add constraints for its package ("sort log lines before mining"). It may not relax or restate a root rule ("network calls are fine here", or a reworded copy of the Never list). Tools resolve conflicts differently (§1.1), so a contradiction means different agents follow different rules. If a root rule is wrong for your package, open a `type:question` issue; the lead changes the root file.

### 1.6 Personal configuration stays personal

MCP servers, model choice, permissions and editor settings are personal. MCP config is not portable between tools (different file, root key and format per tool, [§Q2][q2]) and MCP is never part of the build or the decision path. Keep each tool's MCP config at user level or in a gitignored file (§3). Never commit `.mcp.json`, `opencode.json`, `.vscode/mcp.json` or `.cursor/mcp.json`.

### 1.7 The human owns the PR

The agent proposes; the human reads every diff before committing, watches the checks run, and is the PR author. Agents never push to `main`, never merge, and never hold a token with admin rights.

## 2. Laptop toolchain (task L-01)

Do these in order on each Windows 11 laptop, then record the results in `docs/team/<initials>.md` ([template](team/README.md)). Run commands in **Git Bash** (installed with Git for Windows) unless the step says PowerShell. If a `winget` ID fails, find the right one with `winget search <name>` (**verify** IDs; they change).

### 2.1 Git and GitHub CLI

PowerShell (Git Bash does not exist yet):

```bash
winget install --id Git.Git -e
```

`.gitattributes` normalises line endings (`* text=auto eol=lf`). Turn off Git's own conversion so the attributes alone decide, and Windows checkouts hash the same bytes as Linux CI:

```bash
git config --global core.autocrlf false
```

```bash
git config --global user.name "Your Name"
```

```bash
git config --global user.email "you@example.com"
```

```bash
winget install --id GitHub.cli -e
```

```bash
gh auth login
```

Clone into a short path. Worktrees are created next to the clone (`../vt-<issue>`), so `C:\dev` keeps every path short:

```bash
gh repo clone DuhItzAniket/Veyltrace /c/dev/Veyltrace
```

The main clone `C:\dev\Veyltrace` stays on `main` and is used only to create worktrees. Agents never run in it.

### 2.2 uv and Python 3.12

```bash
winget install --id astral-sh.uv -e
```

```bash
uv python install 3.12
```

```bash
uv run --no-project --python 3.12 python --version
```

A system Python 3.11 can stay installed; uv uses its own 3.12. After M0 (`pyproject.toml` lands in R-02), install the workspace from inside a worktree with `uv sync --all-packages`.

Two ways to run a script, and they are not the same: `uv run scripts/check_lanes.py` reads the script's inline dependencies (PEP 723); `uv run python scripts/check_lanes.py` ignores them and fails with `ModuleNotFoundError` until the workspace provides them. Use the first form for `check_lanes.py` and `sync_labels.py`.

### 2.3 Node 24 LTS and pnpm

The console uses Node 24 LTS. The winget LTS package may already point to a newer major by late October 2026 (**verify**), so list the versions and install the highest `24.x.y`:

```bash
winget show --id OpenJS.NodeJS.LTS --versions
```

```bash
winget install --id OpenJS.NodeJS.LTS -e --version <highest 24.x.y>
```

```bash
node --version
```

pnpm comes through Corepack, which pins the version from `packageManager` in `console/package.json` (set by the Explain lane in X-00). If `corepack enable` fails with a permission error, run it once in an Administrator PowerShell (**verify**):

```bash
corepack enable
```

```bash
pnpm --version
```

### 2.4 WSL2, Docker Desktop and `.wslconfig`

Administrator PowerShell:

```bash
wsl --install
```

```bash
wsl --update
```

```bash
winget install --id Docker.DockerDesktop -e
```

Keep Docker Desktop on the WSL 2 engine (the default). The default WSL VM size is too small once the lab and telemetry run; raise it to 11–12 GB ([02 §8](02-architecture.md#8-technology-stack-pinned-at-m0-recorded-in-adrs), [benchmarks_and_testbed §Q3][lab]). Create `C:\Users\<you>\.wslconfig`:

```ini
[wsl2]
# 11GB leaves ~5 GB for Windows, the IDE and the agent. Use 12GB only while the lab runs with the browser closed.
memory=11GB
swap=4GB
# For tc netem delay/loss faults in the lab. Key name and section: verify with `wsl --version` and the WSL docs.
loadKernelModules=sch_netem

[experimental]
# Returns cached memory to Windows. Section depends on the WSL version: verify.
autoMemoryReclaim=gradual
```

Apply and check:

```bash
wsl --shutdown
```

```bash
docker run --rm hello-world
```

```bash
docker info --format "{{.MemTotal}}"
```

`MemTotal` should be about 11 GB. Whether Docker Desktop's WSL kernel loads `sch_netem` is unverified on our laptops ([§Q3 gaps][lab]); record the result in your team file.

### 2.5 kind, kubectl and Helm

```bash
winget install --id Kubernetes.kind -e
```

```bash
winget install --id Kubernetes.kubectl -e
```

```bash
winget install --id Helm.Helm -e
```

Smoke test (about 1–2 GB while running, *estimate*):

```bash
kind create cluster --name vt-smoke
```

```bash
kubectl get nodes
```

```bash
kind delete cluster --name vt-smoke
```

The lab itself (Online Boutique, Chaos Mesh via Helm with the containerd runtime, OTel Collector) is set up in X-02 and documented in `docs/05-fault-lab-and-dataset.md`.

### 2.6 Ollama and models

```bash
winget install --id Ollama.Ollama -e
```

Default model per [02 §12](02-architecture.md#12-open-decisions-tracked-as-adrs): Qwen3.5-9B Q4_K_M, else Qwen3.5-4B on weak CPUs. Ollama's default `qwen3.5` tag is reported to resolve to 9B (secondary source, [verified_agents_local_llms §Q4][llm4]); check exact tags on the Ollama library page (**verify**).

```bash
ollama pull qwen3.5:9b
```

```bash
ollama pull qwen3.5:4b
```

```bash
ollama run qwen3.5:9b "Reply with the single word ok."
```

```bash
ollama ps
```

`ollama ps` shows the loaded size and the CPU/GPU split; write both down. Do not use gpt-oss-20b as the main model on a 16 GB laptop: it takes about 13–14 GB loaded ([§Q4][llm4]).

### 2.7 llama.cpp and `llama-bench`

Published laptop speeds are too weak to quote, so each laptop measures its own: pp512 and tg128 with `llama-bench`, plus the GGUF SHA-256 and the llama.cpp build ([§Q4][llm4]).

Install llama.cpp (ships `llama-bench` and `llama-server`). If the winget ID does not exist (**verify**), download the release zip for your hardware (CPU AVX2, CUDA or Vulkan) from the llama.cpp GitHub releases page and add its folder to `PATH`:

```bash
winget install --id ggml.llamacpp -e
```

Find the GGUF file Ollama downloaded (the `FROM` line points at a blob under `.ollama\models\blobs`, **verify**). If `llama-bench` rejects the blob, download the official or Unsloth GGUF from Hugging Face into `C:\models` (never into the repo):

```bash
ollama show qwen3.5:9b --modelfile
```

Run the benchmark (add `-ngl 99` on a GPU build to offload all layers):

```bash
llama-bench -m <path-to-model.gguf> -p 512 -n 128 -r 3 -o md
```

Repeat with `-t <number of physical cores>` and keep the faster row. Then record the file hash and the build:

```bash
sha256sum <path-to-model.gguf>
```

```bash
llama-cli --version
```

Benchmark conditions: charger plugged in, Windows power mode "Best performance", other apps closed. Write them in the team file.

### 2.8 Record and open the PR

1. Copy the template from [docs/team/README.md](team/README.md) to `docs/team/<initials>.md` (`ak`, `as`, `cl`).
2. Paste the `llama-bench` markdown table as printed. Do not round or edit numbers.
3. Open a PR for your L-01 issue: branch `<lane>/<issue>-laptop-benchmark`, fragment `changes/<issue>.chore.md`, labels `lane:<lane>`, `type:chore`, `agent:<tool or none>`.

### 2.9 Checklist

| Tool | Check | Expected |
|---|---|---|
| Git | `git config --global core.autocrlf` | `false` |
| GitHub CLI | `gh auth status` | logged in to github.com |
| uv / Python | `uv run --no-project --python 3.12 python --version` | `Python 3.12.x` |
| Node / pnpm | `node --version` · `pnpm --version` | `v24.x` · a version |
| Docker / WSL | `docker info --format "{{.MemTotal}}"` | ≈ 11 GB |
| kind / kubectl / Helm | `kind version` · `kubectl version --client` · `helm version` | versions print |
| Ollama | `ollama list` | `qwen3.5:9b` (and `4b`) |
| llama.cpp | `llama-bench --help` | usage prints |

## 3. Per-tool setup

Rules for every tool:

- Start the agent in the issue's worktree (`../vt-<issue>`), never in the main clone. One agent per worktree.
- First message of every session is the **load check** below. If the agent cannot quote the rule, it has not loaded `AGENTS.md`: fix the setup before doing anything else.
- MCP servers, if any, are configured at user level or in a gitignored file, and are never needed to build, test or run Veyltrace.

Load check (paste as the first message):

```text
Before we start, answer three things and do not open any other file yet:
1. List every instruction file you have loaded for this folder, with paths.
2. Quote rule 2 of section 4 ("Never") of AGENTS.md word for word.
3. I work in the <reason|observe|explain> lane. List the paths you may edit in this session.
```

Expected: item 1 includes `AGENTS.md` (Claude also lists `CLAUDE.md`); item 2 starts "Never change a contract shape in code."; item 3 matches the lane's row in AGENTS.md §2.

### 3.1 Claude Code

| | |
|---|---|
| Reads | root `CLAUDE.md`, whose `@AGENTS.md` import pulls in `AGENTS.md` (read once, works in every mode). Nested `CLAUDE.md` files load when Claude reads or edits a file in that folder, and import the package `AGENTS.md`. |
| Why the import | Native `AGENTS.md` reading (v2.1.277+) is off whenever a `CLAUDE.md` exists, and is missing in older versions and some sessions. A `CLAUDE.md` that only *says* "read AGENTS.md" is weak: Claude sees the file only if it decides to open it ([§Q1][q1]). |
| Do not change | the "Project instructions" setting. It is honoured only in user-level settings, so a repo cannot enforce it; the import makes it irrelevant. |
| Verify | the load check; `/memory` also lists loaded memory files (**verify**). |
| Worktree | `claude --worktree <issue>-<slug>` creates `.claude/worktrees/<issue>-<slug>/` on branch `worktree-<issue>-<slug>`, from the remote default branch ([§Q3][q3]). Rename the branch to our convention as the first command: `git branch -m <lane>/<issue>-<slug>`. Alternative: create the worktree with plain `git worktree add` (§4 step 2) and start `claude` inside it. `.claude/worktrees/` is gitignored. |
| Skills | `.claude/skills/` (generated copy of `.agents/skills/`, §6). |
| MCP | Do not create a project `.mcp.json` (it is gitignored). Add servers at user scope (`claude mcp add --scope user …`, **verify** flag). Personal permissions go in `.claude/settings.local.json` (gitignored). The desktop app reads `.mcp.json` from the main checkout root for worktree sessions ([§Q2][q2]). |
| Limits | `CLAUDE.md` under 200 lines; imports nest at most four hops; `@path` inside code spans or fences is not expanded. |

### 3.2 OpenAI Codex (CLI, IDE extension, cloud)

| | |
|---|---|
| Reads | `AGENTS.md` in each folder from the Git root down to the current folder, one file per folder; `AGENTS.override.md` would take precedence (forbidden here). Global `~/.codex/AGENTS.md` first: keep it free of project rules. |
| Nested files | Loaded only for folders between the root and the folder Codex started in. Start Codex in the worktree root and let the session protocol (§4 step 4) make it read the package `AGENTS.md`. |
| Limits | Combined instructions capped at 32 KiB; files past the cap are dropped silently. The chain is built once per run or TUI session: restart Codex after `AGENTS.md` changes. Do not set `project_doc_fallback_filenames` to `CLAUDE.md` (it holds one import line). |
| Verify | the load check. |
| Worktree | plain `git worktree add` (§4 step 2), then start Codex in it. |
| Skills | scans `.agents/skills/` from the current folder up to the repo root; the initial skill list is capped at 2% of the context window (from a search summary of the official page, [§Q2][q2]). A user report says Codex **cloud** did not discover `.agents/skills/` (unconfirmed): in cloud tasks, name the skill file in the prompt ("follow `.agents/skills/open-pr/SKILL.md`"). |
| MCP | `~/.codex/config.toml`, `[mcp_servers.<id>]` (secondary source). `.codex/` is gitignored. |
| Cloud tasks | one issue, one branch, one PR still apply. Before marking the PR ready, check its changed files against your lane (§7). |

### 3.3 OpenCode

| | |
|---|---|
| Reads | walks up from the current folder for `AGENTS.md`, then `CLAUDE.md`; "the first matching file wins in each category"; then the global `~/.config/opencode/AGENTS.md`, then `~/.claude/CLAUDE.md` as a fallback ([§Q1][q1]). Started in the worktree root, it reads the root `AGENTS.md`. |
| Nested files | Not loaded automatically when started at the root (**verify**). Either rely on §4 step 4, or list your lane's package files under `instructions` (globs such as `packages/signalyth/AGENTS.md`) in a config that is **not** committed (**verify** how relative paths resolve in a global config). |
| Claude overlap | OpenCode also reads `~/.claude/CLAUDE.md` and `~/.claude/skills/`. If you use both tools, your personal Claude files leak into OpenCode; `OPENCODE_DISABLE_CLAUDE_CODE=1` turns that off. |
| Verify | the load check. |
| Worktree | plain `git worktree add`, then start OpenCode in it. |
| Skills | `.agents/skills/` support is reported by third parties only (**verify**); fall back to naming the file in the prompt. |
| MCP | global config only; never commit `opencode.json` (gitignored, like `.opencode/`). OpenCode's MCP schema was not verified. |

### 3.4 Google Antigravity (IDE and Antigravity CLI)

Gemini CLI and the Gemini Code Assist IDE extensions stopped serving Google AI Pro/Ultra and free personal accounts on 18 Jun 2026; Antigravity CLI replaces it ([§Q1][q1]). A teammate "on Gemini" uses Antigravity.

| | |
|---|---|
| Reads | `AGENTS.md`, `GEMINI.md` or `.agents/rules/*.md` in the root or any subfolder, plus `<dir>/.agents/AGENTS.md`. Rules are cumulative; walking up from the edited file, the more specific folder wins. Global rules: `~/.gemini/AGENTS.md`, `~/.gemini/GEMINI.md`, `~/.gemini/config/rules/*.md`, CLI-only `~/.gemini/antigravity-cli/rules/*.md` — keep project rules out of all of them. |
| Our `.agents/` folder | holds skills only. Never add `.agents/rules/` or `.agents/AGENTS.md`: Antigravity would load them as extra rules. |
| Limits | a file over 24,000 bytes after includes is truncated; global and always-on rules share a 20,000-token budget. `@[label](path)` inlines a file; a bare `@file` does not, so Antigravity ignores our `CLAUDE.md` import (fine: it reads `AGENTS.md` directly). |
| Verify | the load check. |
| CLI | command reported as `agy`, reusing `~/.gemini` (third-party sources; **verify**). |
| Worktree | plain `git worktree add`; open the worktree folder as the workspace. |
| Skills | Agent Skills carried over from Gemini CLI, which reads `.agents/skills/` ([§Q2][q2]); confirm in Antigravity (**verify**). |
| MCP | not researched; keep it in user-level config (**verify** location). `.antigravity/` and `.gemini/` are gitignored. |

### 3.5 Cursor

| | |
|---|---|
| Reads | `AGENTS.md` in the root and subfolders; nested files combine with parents and the more specific one wins. Project rules would be `.cursor/rules/*.mdc` (a plain `.md` there is ignored) — we do not use them. Precedence is Team, then Project, then User rules, and earlier sources win, so keep your User Rules free of project instructions. |
| Verify | the load check. Cursor's handling of `CLAUDE.md` is undocumented; it does not matter here. |
| Worktree | plain `git worktree add`; open the worktree folder in a new Cursor window. |
| Skills | `.agents/skills/` support is reported by third parties only (**verify**). |
| MCP | `.cursor/mcp.json` (secondary source) is covered by the `.cursor/` ignore rule; prefer the user-level file (**verify** path). |
| Note | an unverified search summary of an SBES 2026 study puts Cursor's merge-conflict rate at 47.8% vs 25.8% for Claude Code and 10.5% for Copilot ([§Q3][q3]). Keep Cursor PRs small and rebase often. |

### 3.6 GitHub Copilot (VS Code agent and cloud agent)

**VS Code agent mode.** Root `AGENTS.md` is read by default (`chat.useAgentsMdFile`). Nested files need the experimental `chat.useNestedAgentsMdFiles`, off by default ([§Q1][q1]). Set both in **User** settings (`.vscode/*` is gitignored):

```json
{
  "chat.useAgentsMdFile": true,
  "chat.useNestedAgentsMdFiles": true
}
```

Leave `chat.useClaudeMdFile` off: our `CLAUDE.md` holds only an import line (**verify** whether VS Code expands it). VS Code treats instruction sources as additive with no precedence, which is one more reason never to write contradicting rules.

| | |
|---|---|
| Verify | the load check in Copilot Chat (agent mode). |
| Worktree | plain `git worktree add`, then `code ../vt-<issue>` to open it in a new window. |
| MCP | `.vscode/mcp.json` with root key `servers` ([§Q2][q2]); it is gitignored by `.vscode/*`. Prefer user-level config. |

**Cloud agent (assigned from an issue).** Reads `AGENTS.md` anywhere in the repo (nearest wins) and a root-only `CLAUDE.md`/`GEMINI.md`. Rules for using it here:

- The human who assigns the issue owns the PR: check that every changed file is inside the lane before requesting review.
- The PR author is the Copilot bot, which is not in `.github/lanes.yml` `members`, so `check_lanes.py` treats it as an external contributor and **passes without checking paths**. Until that is fixed, the reviewer runs `uv run scripts/check_lanes.py --lane <lane>` on the branch and pastes the output.
- The branch name will not follow `<lane>/<issue>-<slug>`; that is accepted for cloud-agent PRs.
- Copilot **code review** reads only `copilot-instructions` files, which we do not have; its comments therefore do not know our rules.
- Student plan terms changed in 2026 and sources conflict ([§Q4][q4]); check your own plan's limits.

### 3.7 Windsurf / Devin Desktop

| | |
|---|---|
| Reads | `AGENTS.md` through the rules engine: root file always on; a subfolder file applies as an auto-glob for that folder. Rule folders `.devin/rules` (preferred) and `.windsurf/rules` (fallback) — we use neither. |
| Limits | 12,000 characters per workspace rule file (probably including `AGENTS.md`, **verify**); global rules file `~/.codeium/windsurf/memories/global_rules.md` limited to 6,000 characters — keep project rules out of it. |
| Memories | auto-generated memories are personal and can drift from `AGENTS.md`. If the agent cites a memory that contradicts `AGENTS.md`, delete that memory (**verify** UI). |
| Verify | the load check. |
| Worktree | plain `git worktree add`; open the worktree folder. |
| MCP | not researched; user-level config only (**verify** location). |

### 3.8 Summary

| Tool | Rules it loads here | Worktree | MCP (personal) | Watch out for |
|---|---|---|---|---|
| Claude Code | `CLAUDE.md` → `@AGENTS.md`; nested `CLAUDE.md` | `claude --worktree` + `git branch -m` | user scope | no project `.mcp.json` |
| Codex | `AGENTS.md` root → cwd | `git worktree add` | `~/.codex/config.toml` | 32 KiB cap; restart after rule changes |
| OpenCode | nearest `AGENTS.md` | `git worktree add` | global config | reads your `~/.claude` files too |
| Antigravity | `AGENTS.md` everywhere, cumulative | `git worktree add` | user level | never add `.agents/rules/` |
| Cursor | `AGENTS.md` root + subfolders | `git worktree add` | user level | no `.cursor/rules` |
| Copilot (VS Code / cloud) | `AGENTS.md`; nested needs a setting | `git worktree add` / cloud branch | user level | cloud PRs bypass the lane check |
| Windsurf / Devin | `AGENTS.md` via rules engine | `git worktree add` | user level | 12,000-character files; memories |

## 4. Session protocol

This is [AGENTS.md §3](../AGENTS.md#3-session-protocol-do-this-every-time) with the practical detail. Running example: Annapurna (Observe lane) works on issue #14, "O-03 Signalyth logs".

1. **Know the issue.** One session, one issue. Read it and its acceptance criteria:

   ```bash
   gh issue view 14 --comments
   ```

   Check the `lane:*` label is yours and the issue is on the current milestone. No issue yet: file one with the Task form first.

2. **Isolate.** From the main clone, create the worktree and branch from fresh `main`:

   ```bash
   git -C /c/dev/Veyltrace fetch origin
   ```

   ```bash
   git -C /c/dev/Veyltrace worktree add ../vt-14 -b observe/14-drain3-templates origin/main
   ```

   ```bash
   cd /c/dev/vt-14
   ```

   After M0, install the workspace in the new worktree: `uv sync --all-packages`. Claude Code users may instead run `claude --worktree 14-drain3-templates` and then `git branch -m observe/14-drain3-templates`.

3. **Start the agent and run the load check** (§3). Then paste the "Start an issue" template (§5.1) or invoke the `start-issue` skill.

4. **Read before writing.** The agent reads, in order: `AGENTS.md` → `packages/signalyth/AGENTS.md` → `docs/engines/02-signalyth.md` → only the sections of `docs/02-architecture.md` and `docs/03-contracts.md` that the engine spec links. Ask it for a ≤ 10-line summary of what applies. It must not open `_hackday-v1/` or any `answer_key` file.

5. **Agree the plan.** The agent lists the files it will touch, the tests it will write first and the checks it will run. You check every path is in your lane (`.github/lanes.yml`). A path outside the lane means a new issue for that lane, not an edit.

6. **Test first.** Tests against golden fixtures come before the implementation, for example a test that loads `veyltrace_core.testing.golden("signal_cube.templates", "synth-02")` and asserts the template IDs are identical across two runs. Every bug fix starts with a failing regression test.

7. **Implement in small commits.** Read each diff (`git diff`) before committing. Commit at every green step so you have a point to return to (§7):

   ```bash
   git commit -m "feat(signalyth): mine log templates with stable ordering (#14)"
   ```

8. **Check, and keep the output** for the PR:

   ```bash
   uv run python scripts/check.py --package signalyth
   ```

   ```bash
   uv run python scripts/check.py --determinism
   ```

   ```bash
   uv run scripts/check_lanes.py --lane observe
   ```

   Console work: `pnpm -C console check`. Changed `AGENTS.md`, `.agents/` or any Markdown: `uv run --no-project python scripts/sync_agent_files.py --check` and `uv run --no-project python scripts/check_links.py` (the same commands as the CI `agent-files` and `docs` jobs). Before M0 (3 Nov) `scripts/check.py` may not exist; the agent must say so, not invent a substitute.

9. **Record.** Add `changes/14.feat.md` with one sentence ([changes/README.md](../changes/README.md)).

10. **Rebase and open the PR** (or invoke the `open-pr` skill):

    ```bash
    git fetch origin && git rebase origin/main
    ```

    ```bash
    git push -u origin HEAD
    ```

    ```bash
    gh pr create --fill --label lane:observe --label type:feat --label agent:codex
    ```

    Then edit the PR body to the template: `Closes #14`, the Definition of Done ([10 §3](10-sdlc-and-quality.md#3-definition-of-ready-and-definition-of-done)), the **pasted** check output, and the handoff.

11. **Review loop.** Paste reviewer comments into the agent with the template in §5.5. Push fixes as new commits (the PR is squash-merged).

12. **Clean up after merge:**

    ```bash
    git -C /c/dev/Veyltrace worktree remove ../vt-14
    ```

    ```bash
    git -C /c/dev/Veyltrace branch -D observe/14-drain3-templates
    ```

    (`-D` because squash merges leave the branch "unmerged" from Git's point of view.)

13. **Stop** when the acceptance criteria are met. New ideas become new issues.

**Handoff note.** Every PR and every session that ends mid-issue leaves three lines (in the PR body or as an issue comment), so the next session or person can resume without the agent's chat history:

```text
Done: template mining sorted by (service, t_ns, body); golden for synth-01..05 refreshed.
Next: error-rate per template (acceptance criterion 2).
Risks: Drain3 similarity threshold 0.4 is a priori; needs a check on RE2-TT logs.
```

**Long sessions.** When the agent's context fills up or it starts repeating itself, end the session, write the handoff note, and start a fresh session with the "Start an issue" template plus the note.

## 5. Prompt templates

Paste these into the agent and replace `<…>`. Each one names the docs to read and the acceptance criteria to meet. They assume the load check (§3) already passed.

### 5.1 Start an issue

```text
We are working on issue #<N> (<ID> <title>) in the <lane> lane. Worktree: <path>, branch <lane>/<N>-<slug>.
1. Run `gh issue view <N> --comments` and restate the acceptance criteria as a numbered list.
2. Read, in order: AGENTS.md, packages/<package>/AGENTS.md (if it exists), docs/engines/<NN>-<engine>.md,
   then only the sections of docs/02-architecture.md and docs/03-contracts.md that the engine spec links.
   Do not open _hackday-v1/ or any answer_key file.
3. Reply with: (a) a summary of the spec sections that apply, at most 10 lines; (b) the files you plan to
   create or change, each marked "in lane" after checking .github/lanes.yml; (c) the tests you will write
   first; (d) the check commands you will run. Then wait for my go-ahead. Do not write code yet.
```

### 5.2 Implement an engine step from its spec

```text
Implement <step, e.g. "the silence detector"> in packages/<package>, as specified in
docs/engines/<NN>-<engine>.md §<section>, writing the outputs defined in docs/03-contracts.md §<section>.
Acceptance criteria (from issue #<N>):
- <criterion 1>
- <criterion 2>
Constraints (AGENTS.md §4–§5): read inputs only through veyltrace_core.io / veyltrace_contracts loaders and
write only through the contract writers; every threshold is a named key in config/<engine>.yaml with a
comment citing its source or "a priori"; no wall clock, no unseeded randomness (use veyltrace_core.rng),
no unsorted iteration; no network, LLM or HTTP imports; no new fields, columns or enum values — if one is
missing, stop and use the contract-change-request skill.
Work test-first: write the failing tests, show me them, then implement. After each green step, commit with
"feat(<package>): <summary> (#<N>)". Finish by running
`uv run python scripts/check.py --package <package>` and `uv run python scripts/check.py --determinism`
and paste the last 20 lines of each.
```

### 5.3 Write golden tests

```text
Write golden tests for <contract, e.g. anomalies> produced by packages/<package> on synth-01 … synth-05.
Read: docs/03-contracts.md §<section> (fields and sort key), docs/engines/<NN>-<engine>.md §<tests section>,
and docs/08-collaboration-and-git.md §8 (fixtures and stubs).
Use veyltrace_core.testing.golden("<contract>", "<case>") to load expected outputs from
packages/<package>/fixtures/<case>/. Assert: schema validity, the declared sort order, exact equality on
keys and IDs, and float equality as written by the contract writer. Add one hypothesis property test for
<numeric function> (e.g. invariance to input row order).
If fixtures must change, regenerate them only with
`uv run python scripts/check.py --package <package> --update-golden` and list every changed fixture file
with a one-line reason; I review fixture diffs like code. Do not edit fixtures by hand.
Acceptance: tests fail on the current stub where the spec says they should, pass after the change, and
`uv run python scripts/check.py --package <package>` is green (paste the output).
```

### 5.4 Fix a CI failure

```text
CI failed on PR #<P> (issue #<N>). Job: <lint|types|tests|isolation|determinism|contracts-in-sync|lanes|changelog|agent-files|docs|console>.
Log excerpt:
<paste the failing lines from `gh run view --log-failed` or the Actions page>
1. Reproduce locally with the same command CI runs (docs/10-sdlc-and-quality.md §5 lists them) and paste the output.
2. Explain the root cause in at most 5 lines.
3. Fix the cause inside the <lane> lane. Not allowed (AGENTS.md §4.7): skipping or weakening a test,
   adding "# type: ignore" or "noqa" without a reason comment, excluding files from a check, re-running
   until it passes. If the cause is in another lane's package or in a frozen contract, stop and tell me.
4. Re-run the failing check and the package check; paste both outputs. Commit as "fix(<package>): … (#<N>)".
```

### 5.5 Respond to review comments

```text
Review comments on PR #<P> (issue #<N>):
<paste each comment with its file and line, or run `gh pr view <P> --comments`>
For each comment: (a) say whether you agree, in one line, citing the spec section or AGENTS.md rule if relevant;
(b) if you agree, make the smallest change that addresses it; (c) if you disagree, draft a reply for me
instead of changing code. Do not change anything the comments do not ask for.
Then re-run `uv run python scripts/check.py --package <package>` (and --determinism for engine code),
paste the outputs, and give me a list "comment → commit SHA or drafted reply".
```

### 5.6 Draft a Contract Change Request

```text
While working on issue #<N> I need <information> that I cannot find in the contracts.
Use the contract-change-request skill (.agents/skills/contract-change-request/SKILL.md).
Read docs/03-contracts.md (the contract <name> and §1) and docs/08-collaboration-and-git.md §5.
Do not edit contracts/, contracts/generated/ or docs/03-contracts.md, and do not add any ad-hoc field,
column, file or JSON key. Give me the text for each field of the "Contract change" issue form:
contract and section, additive or breaking, producer lane, consumer lanes, proposed change (name, type,
unit, nullability, allowed values, sort-key impact), JSON Schema fragment, why existing fields cannot
carry it, fixture impact, and acceptance criteria. If we are past M1 (8 Nov), also draft the ADR.
Then tell me how we keep building against the current contract meanwhile.
```

### 5.7 Write an ADR

```text
Draft an ADR for the decision: <one line>. Context: issue #<N>, <links to CCR or discussion>.
File: docs/adr/<YYYYMMDD>-<initials>-<slug>.md, using the template docs/adr/_template.md.
Read first: docs/02-architecture.md §<relevant section> (it wins all disagreements) and §12 (open decisions),
and the research notes the decision depends on. Every factual claim cites a note in research_notes/ or
reports/ with its section, or is marked "estimate" or "verify". List at least two options with
consequences, including "do nothing". Keep it under 80 lines. Status: Proposed. Do not edit other
docs in this PR unless the decision changes them; if it does, list the exact sections to change.
```

### 5.8 Run an experiment

```text
Run the experiment in issue #<N>: <question>. Read docs/04-evaluation-protocol.md §<section>,
AGENTS.md §4.5 and §4.8.
1. Write or check the config bench/experiments/<name>.yaml (datasets, arms, alert protocol, seeds, metrics).
   Show it to me before running.
2. Run `uv run veyltrace bench run bench/experiments/<name>.yaml` and report the output folder
   bench/results/<experiment>/ (per_case.csv, summary.json, manifest).
3. Report numbers only from bench/results/<experiment>/summary.json and per_case.csv, copied exactly, with bootstrap CIs.
   Mark any cell not run as "not run: <reason>". Do not round differently, extrapolate, or describe a
   result you did not produce. Ground truth may be read only inside bench/.
Acceptance: the config is committed; re-running it reproduces the table; the PR includes the manifest
(git SHA, config hash, seeds) and a fragment changes/<N>.exp.md.
```

### 5.9 Write a paper section

```text
Draft the paper section "<section>" for issue #<N>. Read docs/11-research-paper-plan.md (outline and
claims for this section), the results under bench/results/<experiment>/, and the research notes you cite.
Rules: every number comes from bench/results/ produced by a committed config — give the file for each;
every citation links a source listed in research_notes/ or reports/ (no citations from memory);
estimates are marked "estimate"; limitations and threats are stated plainly; no marketing words.
Length: about <N> words. Write the section into the LaTeX file under paper/ agreed with the lead.
paper/ belongs to the Reason lane, except paper/sections/observe-* and paper/sections/explain-*, which
those lanes own (docs/08-collaboration-and-git.md §3): in the Observe or Explain lane, touch only your
lane's section file; anything else in paper/ needs the cross-lane label, agreed with the lead.
At the end, list each claim with its evidence (file path or note + section) so the lead can check them one by one.
```

## 6. Shared skills

**Format.** A skill is a folder `.agents/skills/<name>/` with a `SKILL.md` in the open Agent Skills format: YAML frontmatter with `name` and `description` only (Gemini/Antigravity keep only these two keys), then Markdown instructions. `name` equals the folder name. Optional subfolders `scripts/`, `references/`, `assets/` ([§Q2][q2]).

**Who reads `.agents/skills/`.**

| Tool | Project skills path | Status |
|---|---|---|
| Codex | `.agents/skills/` (cwd up to repo root) | official page, via search summary; cloud bug reported |
| Antigravity | `.agents/skills/` (inherited from Gemini CLI) | **verify** |
| Claude Code | `.claude/skills/` | official; we generate a copy |
| OpenCode | `~/.claude/skills/` (user level); `.agents/skills/` per third parties | **verify** |
| Cursor, Copilot, Windsurf/Devin | `.agents/skills/` per third parties | **verify** |

If your tool does not load skills, paste: `Follow .agents/skills/<name>/SKILL.md step by step.` Every skill is plain Markdown, so this always works.

**Generated copy for Claude Code.** `.claude/skills/` is a byte-for-byte copy made by `scripts/sync_agent_files.py` (not a symlink: Windows), with a `README.md` saying it is generated:

```bash
uv run --no-project python scripts/sync_agent_files.py
```

CI runs it with `--check` (`agent-files` job) and fails if the copy is stale. Never edit `.claude/skills/` by hand.

**Skills in this repo.**

| Skill | Use it when |
|---|---|
| `start-issue` | starting any session: confirm issue and lane, create the worktree, read the docs in order, propose a plan |
| `contract-change-request` | a field, column or enum value seems missing from a contract |
| `open-pr` | the acceptance criteria are met: checks, fragment, commit, PR with pasted output and handoff |
| `determinism-check` | after changing engines 1–7, 9 or deterministic parts of 10, or when the `determinism` job fails |

**Adding a skill.** `.agents/` belongs to the Reason lane: open an issue. Keep a skill under about 60 lines. A multi-step procedure that must behave identically everywhere belongs in a script under `scripts/` that the skill calls: slash commands and workflows are not portable between tools, shell commands are ([§Q2][q2]).

## 7. Guardrails and recovery

| Problem | How you notice | Recover | Prevent |
|---|---|---|---|
| Agent edited files outside the lane | `git diff --name-only origin/main...HEAD`; `uv run scripts/check_lanes.py --lane <lane>`; CI `lanes` | File exists on `main`: `git restore --source=origin/main --staged --worktree -- <path>`. File is new: `git rm -r -f -- <path>`. Commit "revert out-of-lane edits". Open an issue for the owning lane if the change is needed. | load check item 3; plan step (§4 step 5) |
| Agent invented a field, column, JSON key or enum value | review: compare writer calls and outputs with `docs/03-contracts.md`; schema validation in golden tests | revert the change; draft a CCR (§5.6); keep building against the current contract | AGENTS.md §4.2; `contract-change-request` skill |
| Agent loops (same error three times, rewrites the same file, undoes its own fix) | you see it | stop after two failed attempts at the same error. Discard uncommitted work with `git restore --staged --worktree .` (and delete new files listed by `git status`), or return to the last green commit with `git reset --hard <sha>` — local branch only, never a pushed shared branch. Start a fresh session with the handoff note and the exact error. | small commits at green steps; one issue per session |
| Agent says "tests pass" without running them | no command output in its reply or the PR | ask for the command and its output; re-run it yourself | PR template requires pasted output; reviewer re-runs at least one command; CI is the final word |
| Agent weakens checks (skips a test, `# type: ignore`, `noqa`, loosens a tolerance, edits a fixture by hand) | `git diff origin/main...HEAD -- '*tests*' '*fixtures*'`; grep the diff for `skip`, `ignore`, `noqa` | revert those hunks; fix the cause | AGENTS.md §4.7; review checklist in [10 §6](10-sdlc-and-quality.md#6-code-review-checklist) |
| Agent read forbidden material (`_hackday-v1/`, `answer_key`, injection times) | the transcript shows the file being opened | stop the session; discard its work; note it in the PR under Risks (it is a threat to validity for results) | §5.1 template says it; never paste ground truth into a prompt |
| Agent hand-edited `uv.lock`, `pnpm-lock.yaml` or `contracts/generated/` | file in the diff | `git checkout origin/main -- uv.lock && uv lock` ([08 §6](08-collaboration-and-git.md#6-lockfiles-and-dependencies)); regenerate contracts (Reason lane) | AGENTS.md §4.1 |
| Agent added a dependency inside a feature PR | `pyproject.toml` or `package.json` in the diff | move it to a separate `chore(deps)` PR | AGENTS.md §5 |
| Agent made a PR larger than 400 lines | `git diff --stat origin/main...HEAD` | split by acceptance criterion into stacked issues | plan step |
| Agent improvised a missing command (e.g. before M0) | a command not in AGENTS.md §6 | stop; use the documented command or wait for M0 | AGENTS.md §6 last line |
| Secrets near the agent | a token in a prompt, file or log | revoke the token at once; it is now in the tool's logs | use `gh auth login` (keyring); never paste tokens; `.env` stays gitignored |

### 7.1 Recording agent usage (for the paper)

The paper's methods and threats-to-validity sections report how the code was produced ([§Q5][q5]). Record it as we go; it costs a label per PR.

- Every PR has exactly one `agent:<tool>` label: the tool that wrote most of the diff (`agent:none` if none). The PR body's "Agent used" row names the tool and model.
- The Projects board has an **Agent** field ([10 §9](10-sdlc-and-quality.md#9-tracking)).
- Merge conflicts: when a rebase conflicts, add one line to the PR's Risks: `conflict: <files> (<structural|textual>)`.
- Weekly, the lead exports PR data for the scorecard and the paper:

  ```bash
  gh pr list --state merged --limit 500 --json number,title,labels,author,createdAt,mergedAt,additions,deletions > pr-usage.json
  ```

  and computes per agent: PRs merged, median cycle time, CI pass rate on first push, conflicts, review rounds. Raw exports are not committed; the derived table goes in `bench/results/process/` with the script that made it.
- What to say in the paper: which agents were used, the share of PRs per agent, and the controls (lanes, frozen contracts, CI gates, human review). Do not claim that an agent caused a quality difference: three people with different tools and tasks is not a controlled comparison.

[q1]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/multi_agent_dev_and_sdlc.md#q1-which-tools-read-agentsmd-natively-with-what-precedence-and-how-do-we-point-the-rest-at-it-without-duplicating-content
[q2]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/multi_agent_dev_and_sdlc.md#q2-are-agent-skills-commands-and-mcp-config-portable-across-tools
[q3]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/multi_agent_dev_and_sdlc.md#q3-how-do-we-avoid-merge-conflicts-and-drift-with-three-different-ai-agents-working-in-parallel
[q4]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/multi_agent_dev_and_sdlc.md#q4-how-should-a-tiny-team-track-the-sdlc-on-github-free
[q5]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/multi_agent_dev_and_sdlc.md#q5-what-does-research-paper-readiness-require-reproducibility-artifacts-citation-licences-venues-and-arxiv
[llm4]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/verified_agents_local_llms.md#q4-local-open-weight-models-for-a-16-gb-laptop-tool-use-json-speed-ram-licences
[lab]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/benchmarks_and_testbed.md#q3-live-testbed-on-a-16-gb-windows-laptop-which-demo-systems-fit-which-fault-injection-tools-work-locally-and-how-do-rcaevalaiopslab-style-faults-reproduce
