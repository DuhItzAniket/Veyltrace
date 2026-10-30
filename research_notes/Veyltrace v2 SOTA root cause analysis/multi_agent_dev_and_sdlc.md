# Multi-agent parallel development, SDLC tracking and paper readiness for Veyltrace v2 (as of 30 Oct 2026)

Scope: a 3-person student team (Aniket = lead, Annapurna, Lakshanaa), each using a different AI coding agent, building one repo (github.com/DuhItzAniket/Veyltrace, personal-account-owned, currently empty) in about 1 month. Python core + TypeScript UI. Research-led, so the work has to be paper-ready.

Notes on sources: I fetched official vendor docs where possible (code.claude.com, learn.chatgpt.com/developers.openai.com, opencode.ai, cursor.com, docs.github.com, code.visualstudio.com, antigravity.google, geminicli.com, docs.devin.ai, conf.researchr.org, kdd2027.kdd.org, neurips.cc, blog.arxiv.org). Where a fact comes only from a search-engine summary or a third-party blog, I say so. Most vendor doc pages do not show a "last updated" date. The fetch date for all of them is 29–30 Oct 2026.

---

## Q1. Which tools read AGENTS.md natively, with what precedence, and how do we point the rest at it without duplicating content?

### Takeaway
By late 2026 AGENTS.md is the de facto shared file. Codex, OpenCode, Cursor, GitHub Copilot (coding agent + VS Code), Google Antigravity (IDE + CLI) and Windsurf/Devin Desktop all read it natively. Claude Code now does too (v2.1.277+), but **only when no CLAUDE.md exists**. The robust pattern is one canonical root `AGENTS.md`, optional nested `AGENTS.md` per owned directory, and at most a one-line `CLAUDE.md` containing `@AGENTS.md`. Don't create GEMINI.md, `.cursor/rules` or copilot-instructions copies. Gemini CLI was retired for personal/free accounts on 18 Jun 2026, so a teammate on "Gemini" should use Antigravity, which reads AGENTS.md natively.

### Cited Findings

**The standard itself**
- agents.md lists these supporting agents: Codex, Jules, Factory, Aider, goose, opencode, Zed, Warp, VS Code, Devin, UiPath, Junie, Amp, Cursor, RooCode, Gemini CLI, Kilo Code, Phoenix, Semgrep, GitHub Copilot coding agent, Ona, Windsurf, Augment Code. — [agents.md](https://agents.md/)
- The spec says "The closest AGENTS.md to the edited file wins", and explicit user chat prompts override all AGENTS.md instructions. — [agents.md](https://agents.md/)
- AGENTS.md "is now stewarded by the Agentic AI Foundation under the Linux Foundation". The page gives no date. — [agents.md](https://agents.md/)
- agents.md gives these config tips:
  - Aider: add `read: AGENTS.md` to `.aider.conf.yml`.
  - Gemini CLI: set the context file name to `AGENTS.md` in `.gemini/settings.json`.
  - Migration: rename the old file to AGENTS.md and symlink the old name to it. — [agents.md](https://agents.md/)

**Claude Code** (official docs, code.claude.com/docs/en/memory)
- Claude Code reads AGENTS.md natively starting at **v2.1.277**, but by default only when there is **no** `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` in the working directory or any directory above it. If both exist, it reads "Your CLAUDE.md files only". — [Claude Code memory docs](https://code.claude.com/docs/en/memory)
- A `CLAUDE.md` that imports AGENTS.md (`@AGENTS.md`) works in all modes, and "Keeping the import never makes Claude read AGENTS.md twice". — [Claude Code memory docs](https://code.claude.com/docs/en/memory)
- A `CLAUDE.md` that only tells Claude in words to read AGENTS.md is weak: "Claude sees AGENTS.md only if it decides to open the file". The docs say to replace the sentence with an `@AGENTS.md` import. — [Claude Code memory docs](https://code.claude.com/docs/en/memory)
- A `CLAUDE.md` that is a symlink to AGENTS.md also works, and the content is read once. — [Claude Code memory docs](https://code.claude.com/docs/en/memory)
- The **Project instructions** setting has four values: `claude-md-or-agents-md` (default), `claude-md-and-agents-md`, `claude-md` and `managed-only`. In a settings file it goes under `pluginConfigs."cc-plugin-agents-md@builtin".options.instructionFiles`. Claude Code reads that entry from `~/.claude/settings.json`, a `--settings` file or managed settings, and **ignores it in project and local settings files**. A repo therefore cannot force it for the team. — [Claude Code memory docs](https://code.claude.com/docs/en/memory)
- In some sessions native AGENTS.md reading is unavailable:
  - versions before 2.1.277
  - the built-in plugin is disabled
  - sometimes the first session after an upgrade
  - before v2.1.281, Bedrock sessions and sessions with telemetry off

  The docs recommend importing AGENTS.md from a CLAUDE.md in those cases. — [Claude Code memory docs](https://code.claude.com/docs/en/memory)
- **Imports**: `@path/to/file` syntax. Relative paths resolve against the importing file, and imports nest to a maximum depth of four hops. Imports outside the working directory trigger a one-time approval dialog. Imports are not expanded inside code spans or fenced blocks. — [Claude Code memory docs](https://code.claude.com/docs/en/memory)
- **Load order**: CLAUDE.md files from the filesystem root down to the working directory are concatenated, not overridden. Files closer to the launch directory are read last. Subdirectory CLAUDE.md files load on demand once Claude reads, writes or edits a file in that subdirectory. — [Claude Code memory docs](https://code.claude.com/docs/en/memory)
- **`.claude/rules/*.md`**: rules can carry YAML frontmatter `paths:` (globs), and then load only when Claude touches a matching file. Rules without `paths` load at launch. The directory supports symlinks, but a symlink pointing outside the repo is treated as an external import. — [Claude Code memory docs](https://code.claude.com/docs/en/memory)
- The docs recommend keeping each CLAUDE.md under 200 lines. Contradictory instructions may be resolved arbitrarily. — [Claude Code memory docs](https://code.claude.com/docs/en/memory)

**OpenAI Codex (CLI / IDE / cloud)**
- Global scope (`~/.codex` or `CODEX_HOME`): Codex checks `AGENTS.override.md`, then `AGENTS.md`, and uses only the first non-empty file. — [Codex AGENTS.md guide](https://learn.chatgpt.com/docs/agent-configuration/agents-md) (redirected from developers.openai.com/codex/guides/agents-md)
- Project scope: Codex walks from the project root (usually the Git root) down to the cwd. In each directory it checks `AGENTS.override.md`, then `AGENTS.md`, then the names in `project_doc_fallback_filenames`. It includes "at most one file per directory". Files closer to the cwd appear later and therefore override earlier guidance. — [Codex AGENTS.md guide](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- The combined instructions are capped by `project_doc_max_bytes`, **default 32 KiB**. Codex stops adding files at the cap. The instruction chain is built once per run or TUI session. — [Codex AGENTS.md guide](https://learn.chatgpt.com/docs/agent-configuration/agents-md)

**OpenCode**
- OpenCode walks up from the cwd looking for `AGENTS.md`, then `CLAUDE.md`, and "The first matching file wins in each category". It then checks the global `~/.config/opencode/AGENTS.md`, then `~/.claude/CLAUDE.md` as a fallback. — [OpenCode rules docs](https://opencode.ai/docs/rules/)
- The `instructions` field in `opencode.json` accepts globs (e.g. `packages/*/AGENTS.md`, `.cursor/rules/*.md`) and remote URLs. These files are combined with AGENTS.md. OpenCode also supports `~/.claude/skills/`. Claude compatibility can be turned off with `OPENCODE_DISABLE_CLAUDE_CODE=1`. — [OpenCode rules docs](https://opencode.ai/docs/rules/)

**Cursor**
- "Cursor supports AGENTS.md in the project root and subdirectories". Nested files are combined with parent files, and the more specific file wins. — [Cursor rules docs](https://cursor.com/docs/context/rules)
- Project rules live in `.cursor/rules` as **`.mdc`** files, and "A plain .md file in .cursor/rules is ignored by the rules system". Frontmatter fields are `description`, `globs` and `alwaysApply`. — [Cursor rules docs](https://cursor.com/docs/context/rules)
- Precedence is Team Rules, then Project Rules, then User Rules, and "earlier sources take precedence when guidance conflicts". The page does not mention CLAUDE.md. — [Cursor rules docs](https://cursor.com/docs/context/rules)

**GitHub Copilot**
- The Copilot coding agent ("cloud agent") supports:
  - `.github/copilot-instructions.md`
  - path-specific `.github/instructions/*.instructions.md` with `applyTo`
  - `AGENTS.md` anywhere in the repo ("the nearest AGENTS.md file in the directory tree will take precedence")
  - a single **root-only** `CLAUDE.md` or `GEMINI.md`

  — [GitHub Docs: repository custom instructions](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions)
- Copilot **code review** uses repo-wide and path-specific copilot instruction files. The `excludeAgent` frontmatter (`"code-review"` / `"cloud-agent"`) scopes a file to one surface. Code review reads instructions from the PR's head branch. — [GitHub Docs: repository custom instructions](https://docs.github.com/en/copilot/how-tos/configure-custom-instructions/add-repository-instructions)
- In VS Code, `chat.useAgentsMdFile` (root AGENTS.md) is enabled by default. Nested AGENTS.md (`chat.useNestedAgentsMdFiles`) is **experimental and disabled by default**. CLAUDE.md (root, `.claude/CLAUDE.md`, `CLAUDE.local.md`) is read when `chat.useClaudeMdFile` is on, and `.claude/rules` use `paths`. "Applicable instruction sources are additive", so you should not rely on precedence between files. — [VS Code custom instructions](https://code.visualstudio.com/docs/copilot/customization/custom-instructions)

**Google Antigravity (IDE + Antigravity CLI)**
- **Workspace and directory rules**: `AGENTS.md`, `GEMINI.md` or `.agents/rules/*.md` in the root or any subdirectory. Antigravity also checks `<dir>/.agents/AGENTS.md` and `<dir>/.agents/GEMINI.md`. The legacy `<dir>/.agent/rules/*.md` is still read. — [Antigravity Rules docs](https://antigravity.google/docs/rules/)
- **Global rules**: `~/.gemini/AGENTS.md`, `~/.gemini/GEMINI.md`, `~/.gemini/config/rules/*.md`, plus the CLI-only `~/.gemini/antigravity-cli/rules/*.md`. — [Antigravity Rules docs](https://antigravity.google/docs/rules/)
- **Precedence**: rules are cumulative. For a file being read or edited, Antigravity walks up from that file's folder to the workspace root, and the more specific directory rule wins a conflict. — [Antigravity Rules docs](https://antigravity.google/docs/rules/)
- **Frontmatter**: files in `rules/` need a `trigger` (`always_on` / `model_decision` / `glob` / `manual`) or they are "silently discarded". AGENTS.md and GEMINI.md take no frontmatter and are always on for their directory. — [Antigravity Rules docs](https://antigravity.google/docs/rules/)
- **Includes**: `@[label](path)` inlines another file. A bare `@filename` only rewrites the reference to an absolute path. — [Antigravity Rules docs](https://antigravity.google/docs/rules/)
- **Limits**: a file over **24,000 bytes** after includes is truncated. Global and always-on rules share a **20,000-token** budget, and when it is exceeded the largest files become on-demand pointers. — [Antigravity Rules docs](https://antigravity.google/docs/rules/)
- Only immediate `.md` files in `.agents/rules/` are scanned. Files in nested subfolders need registering in `.agents/rules.json`. — [Antigravity Rules docs](https://antigravity.google/docs/rules/)

**Gemini CLI → Antigravity CLI (important change)**
- Google announced on **19 May 2026** that Antigravity CLI is the successor. On **18 Jun 2026**, Gemini CLI and the Gemini Code Assist IDE extensions stopped serving requests for Google AI Pro/Ultra and free "Gemini Code Assist for individuals" accounts. Enterprise Code Assist licences and paid API keys are unaffected. Agent Skills, Hooks, Subagents and Extensions (renamed "Antigravity plugins") carry over. — [Google Developers Blog](https://developers.googleblog.com/en/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)
- The Gemini CLI skills docs page (last updated 30 Apr 2026) also says Gemini CLI "was replaced by Antigravity CLI on June 18th, 2026". — [Gemini CLI skills docs](https://geminicli.com/docs/cli/skills/)
- Third-party sources say the CLI command is `agy`, that it reuses `~/.gemini`, and that it is closed-source. The official post does not name the command. — [The New Stack](https://thenewstack.io/gemini-cli-antigravity-replacement/); [Lets Data Science](https://letsdatascience.com/news/google-replaces-gemini-cli-with-antigravity-cli-574b2056)
- Legacy Gemini CLI (for anyone still on an API key) defaults to `GEMINI.md`. `context.fileName` in `settings.json` accepts a list, e.g. `["AGENTS.md","CONTEXT.md","GEMINI.md"]`, and AGENTS.md is **not** read by default. It supports `@file.md` imports, just-in-time subdirectory loading and `/memory show|reload`. — [Gemini CLI GEMINI.md docs](https://geminicli.com/docs/cli/gemini-md/)

**Windsurf (docs now branded "Devin Desktop")**
- `docs.windsurf.com/.../memories` now redirects to docs.devin.ai/desktop. `.devin/rules` is preferred, with `.windsurf/rules` kept as a fallback. Global rules live in `~/.codeium/windsurf/memories/global_rules.md`. — [Devin Desktop / Cascade memories & rules](https://docs.devin.ai/desktop/cascade/memories)
- AGENTS.md is "Processed by the same Rules engine — root-level = always-on, subdirectory = auto-glob for that directory". — [Devin Desktop / Cascade memories & rules](https://docs.devin.ai/desktop/cascade/memories)
- Rule triggers are `always_on`, `model_decision`, `glob` and `manual`. Workspace rule files are limited to **12,000 characters** each, and the global file to 6,000. — [Devin Desktop / Cascade memories & rules](https://docs.devin.ai/desktop/cascade/memories)

**Symlinks on Windows**
- Git for Windows "disables support for symbolic links by default". Enabling them requires Developer Mode or the `SeCreateSymbolicLinkPrivilege` right, plus `core.symlinks=true` (e.g. `git clone -c core.symlinks=true <URL>`). — [Git for Windows: Symbolic Links](https://gitforwindows.org/symbolic-links)
- Claude Code also refuses to create a worktree when `.claude` or `.claude/worktrees` is a symlink. — [Claude Code worktrees docs](https://code.claude.com/docs/en/worktrees)

### Inferences
- **Recommended instruction layout for Veyltrace**:
  ```
  AGENTS.md                      # canonical, tool-agnostic. Keep it under ~10 KB / ~150 lines (see size limits below)
  CLAUDE.md                      # exactly one line: @AGENTS.md  (+ optional Claude-only notes)
  core/AGENTS.md                 # lane rules for the Python core (owner: X)
  ui/AGENTS.md                   # lane rules for the TS UI (owner: Y)
  contracts/AGENTS.md            # "FROZEN – do not edit without an ADR + lead approval"
  .github/copilot-instructions.md  # only if someone uses Copilot *code review*; 3–5 lines plus a link to AGENTS.md
  ```
- **No GEMINI.md and no `.cursor/rules` copies.** Antigravity and Cursor both read AGENTS.md natively, and Antigravity would *add* a GEMINI.md on top of AGENTS.md (rules are cumulative), so a copy just duplicates content.
- **Size budget.** The tightest limits found are Windsurf/Devin's 12,000 characters per rule file (which probably applies to AGENTS.md, since it goes through the same engine), Antigravity's 24,000 bytes per file and Codex's 32 KiB combined. Keep the root AGENTS.md around 8–10 KB. Put lane detail in nested AGENTS.md files and long references in `docs/`, linked rather than imported.
- **Claude Code and nested AGENTS.md.** Once a root CLAUDE.md exists, Claude's default mode reads CLAUDE.md files only, so it probably ignores nested `core/AGENTS.md` etc. (my reading of the docs; worth testing). Three ways to fix it:
  - (a) Put a one-line `CLAUDE.md` with `@AGENTS.md` next to each nested AGENTS.md.
  - (b) Delete the root CLAUDE.md and rely on native reading (v2.1.277+).
  - (c) The Claude user sets `claude-md-and-agents-md` in `~/.claude/settings.json`.

  Option (a) is deterministic and works for every Claude version.
- **The existing Veyltrace `CLAUDE.md` is weak.** It currently says in prose "Read AGENTS.md first", which is the pattern the Claude docs call weak because Claude only sees the file if it decides to open it. Replace it with an `@AGENTS.md` import line. Also, as of this session no `AGENTS.md` exists at the repo root (the directory listing shows only `.gitattributes`, `.gitignore`, `LICENSE`, `_hackday-v1/`, `reports/`, `research_notes/`).
- **Avoid symlinks** (`CLAUDE.md -> AGENTS.md`). Git for Windows disables them by default, so a teammate cloning on Windows without Developer Mode will likely get a small text file containing the link target instead. That is an inference: the Git for Windows page doesn't describe the on-disk result. Imports (`@AGENTS.md`) are portable and need no OS privileges.
- **Copilot nested AGENTS.md.** For a Copilot user in VS Code, nested AGENTS.md needs the experimental `chat.useNestedAgentsMdFiles` setting. The cloud coding agent already honours nearest-wins.
- **Same files, different merge rules.** Precedence is consistent ("more specific/closer wins"), but the mechanics differ:
  - Codex: one file per directory, concatenated.
  - Claude: concatenated, closest last.
  - Cursor and Antigravity: cumulative, specific wins.
  - VS Code: additive with no precedence.

  So never write contradictory rules in parent and child files. Child files should only *add* lane-specific constraints.

### Gaps
- I couldn't find an official doc page confirming Antigravity CLI's command name (`agy`) or whether it is open source. Only third-party sources cover those.
- Whether Windsurf/Devin's 12,000-character limit applies to AGENTS.md specifically (the docs only say "workspace rule files").
- Cursor's handling of CLAUDE.md is not documented on the rules page.
- Most vendor pages show no "last updated" date, so the version-specific claims are "as fetched 29–30 Oct 2026".

---

## Q2. Are agent skills, commands and MCP config portable across tools?

### Takeaway
Skills are now mostly portable through the open Agent Skills format (`SKILL.md` with `name`/`description` frontmatter). `.agents/skills/` is emerging as the shared project path: Codex and Gemini/Antigravity confirm it officially, Cursor/Copilot only via third parties. Claude Code still documents `.claude/skills/`. MCP config is **not** portable: each tool has its own file and root key, and Codex uses TOML.

### Cited Findings
- Agent Skills is "a lightweight, open format". A skill is a folder containing `SKILL.md` with `name` and `description` at minimum, plus optional `scripts/`, `references/` and `assets/`. It loads by progressive disclosure: names and descriptions at startup, the full body on activation. Anthropic originally developed it and released it as an open standard. — [agentskills.io](https://agentskills.io/)
- **Codex**:
  - It scans `.agents/skills` in every directory from the cwd up to the repo root. User skills live in `$HOME/.agents/skills` and admin skills in `/etc/codex/skills`.
  - It follows symlinked skill folders and does not merge same-name skills.
  - The initial skill list is capped at 2% of the context window (8,000 characters if the window is unknown).

  This comes from a search summary of the official page. — [Codex: Build skills](https://developers.openai.com/codex/skills)
- A user-reported (unconfirmed) bug says Codex **Cloud** did not discover repo skills under `.agents/skills/`. — [openai/codex issue #52266](https://github.com/openai/codex/issues/52266)
- **Gemini CLI** discovers workspace skills in `.gemini/skills/` or the `.agents/skills/` alias, and the alias takes precedence over `.gemini/skills/`. Precedence across tiers is built-in < extension < user < workspace. The page says skills are "Based on the Agent Skills open standard". — [Gemini CLI skills docs](https://geminicli.com/docs/cli/skills/)
- **Antigravity** keeps Agent Skills from Gemini CLI. — [Google Developers Blog](https://developers.googleblog.com/en/an-important-update-transitioning-gemini-cli-to-antigravity-cli/)
- **OpenCode** supports `~/.claude/skills/` for Claude compatibility. — [OpenCode rules docs](https://opencode.ai/docs/rules/)
- **Claude Code** loads project skills from `.claude/skills`. In a worktree with no `.claude/skills` directory, it reads through to the main checkout's skills, and the same applies to `.claude/agents` and `.claude/commands`. — [Claude Code worktrees docs](https://code.claude.com/docs/en/worktrees)
- Third-party (not vendor) sources say Codex, Cursor, GitHub Copilot, Gemini CLI and OpenCode read `.agents/skills/`, and that Claude Code's docs don't list that path (it reads `.claude/skills/`). They also say Gemini CLI keeps only `name` and `description` from frontmatter, and that Codex uses a separate `agents/openai.yaml` for manual-only invocation. — [cubic.dev](https://www.cubic.dev/blog/agent-skills); [AgentsCamp](https://agentscamp.com/guides/skills/agent-skills-open-standard)
- **MCP config** differs by tool:

  | Tool | File | Root key | Source |
  |---|---|---|---|
  | Claude Code | `.mcp.json` | `mcpServers` | [Glama guide](https://glama.ai/mcp/servers/@okets/folder-mcp/blob/d01bb52143b8721e59eae8d588a80c2dd8391cc9/docs/guides/MCP-AUTO-CONFIGURATION-GUIDE.md) (secondary) |
  | Cursor | `.cursor/mcp.json` | `mcpServers` | [morphllm](https://www.morphllm.com/cursor-mcp-server) (secondary) |
  | VS Code | `.vscode/mcp.json` | `servers` | [VS Code MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration) |
  | Codex | `~/.codex/config.toml` (project `.codex/config.toml` disputed) | TOML `[mcp_servers.<id>]` | [mehmetbaykar.com](https://mehmetbaykar.com/posts/how-to-migrate-mcp-servers-from-cursor-to-codex/) (secondary) |

- Claude Code reads `.mcp.json` from the main checkout root for worktree sessions started in the desktop app. — [Claude Code worktrees docs](https://code.claude.com/docs/en/worktrees)

### Inferences
- **Put canonical team skills in `.agents/skills/<name>/SKILL.md`.** Good candidates: "add a new RCA algorithm adapter", "run the determinism check", "write a towncrier fragment", "open a PR with the template".
  - For Claude Code, add `.claude/skills/` as a **copy** generated by a small `scripts/sync_agent_files.py`, not a symlink (Windows). A CI step should check that the two match.
  - Keep frontmatter to `name` and `description` only, since Gemini/Antigravity drop other keys.
- **Keep MCP out of the build and decision path.** The project rules already say "no AI or network in the decision path", so MCP servers are personal dev tooling. Each person keeps their own tool's MCP file **gitignored**, so there is no cross-tool config to sync and no merge conflicts on `.mcp.json`, `.cursor/mcp.json` or `.vscode/mcp.json`.
- **Slash commands and workflows are not portable** (Claude `.claude/commands`, Antigravity workflows, Cursor commands). Write any multi-step procedure once as a script under `scripts/` (or a `Makefile`/`justfile` target) and mention it in AGENTS.md. Every agent can run a shell command, so this is the only truly portable "command".

### Gaps
- I could not render agentskills.io's client showcase (JS page), so I don't have an authoritative per-tool support list.
- No official Cursor or Copilot doc page confirming `.agents/skills/` was fetched.
- No official Claude Code statement on `.agents/skills/` was found.
- Antigravity's skills and workflows directory paths are documented on separate pages (`/docs/skills`, `/docs/ide/workflows/`) that I did not fetch. A third-party claim that legacy `.agents/workflows/` stop working on 19 Oct 2026 is unverified. — [search summary of iceberglakehouse/agentpedia blogs](https://iceberglakehouse.com/posts/2026-03-context-google-antigravity/)
- OpenCode's MCP config schema (`opencode.json`) was not verified.

---

## Q3. How do we avoid merge conflicts and drift with three different AI agents working in parallel?

### Takeaway
2026 data shows parallel AI-agent PRs conflict often: about 28% of agentic PRs overall, and cross-agent pairs about twice as often as same-agent pairs (42% vs 20%). Most conflicts are in source code and many are structural (add/add, modify/delete). Humans resolve over 96% of them. With three different agents, Veyltrace is in the highest-risk regime. The fix is structural rather than social:
- strict directory ownership enforced by CODEOWNERS and CI
- contract-first with frozen schemas and generated code
- no shared "registry" files: use auto-discovery, fragments and per-owner ID ranges
- one worktree and one short-lived branch per agent task
- lockfile changes owned by one person and regenerated, never hand-merged

GitHub merge queue is **not available** on a personal-account repo, so use "require branches up to date" plus required checks instead.

### Cited Findings

**Evidence on parallel AI-agent conflicts**
- **AgenticFlict (AIware '26)**: 142K+ agentic PRs from 59K+ repos, 107K+ processed by deterministic merge simulation. 29K+ of them had merge conflicts, a **27.67%** conflict rate, with noticeable variation across agents. — [arXiv 2604.03551](https://arxiv.org/abs/2604.03551)
- **Xu, Subramanian & Karthik (arXiv 2607.04697, Jul 2026)**, on 33,596 agent PRs in 2,807 repos:
  - Overlap: 40.2% of repos have co-active agent PR pairs, covering 79.4% of agent PRs (95.0% within a 1-week window).
  - Cross-agent pairs are rare (0.5%) but conflict at **41.7%**, vs **19.8%** for same-agent pairs (non-overlapping 95% CIs).
  - **84.4%** of conflicted files are source code, not dependency manifests.
  - About **42%** of conflicts are structural (modify/delete or add/add).

  — [arXiv 2607.04697](https://arxiv.org/abs/2607.04697)
- **SBES 2026 empirical study**: of 14,960 conflicting merges, 96.1% were resolved by a human and 3.1% by the agent. Per-agent conflict rates ranged from 10.5% (Copilot) to 47.8% (Cursor), with Claude Code at 25.8%. These numbers come from a search summary and were not verified against the PDF. — [SBES 2026 paper](https://cbsoft.sbc.org.br/2026/data/papers/sbes/How%20AI%20Coding%20Agents%20Resolve%20Merge%20Conflicts%20An%20Empirical%20Study.pdf)

**Worktrees per agent**
- `claude --worktree <name>` creates `.claude/worktrees/<name>/` on branch `worktree-<name>`, branched from the remote default branch by default (`worktree.baseRef: "fresh"`; `"head"` is optional).
  - Add `.claude/worktrees/` to `.gitignore`.
  - `.worktreeinclude` copies gitignored files such as `.env` into each new worktree.
  - Subagents can use `isolation: worktree`.
  - Claude Code blocks edits and git commands that target the main checkout from an isolated session.

  — [Claude Code worktrees docs](https://code.claude.com/docs/en/worktrees)
- Plain `git worktree add ../project-feature-a -b feature-a` works for any tool. — [Claude Code worktrees docs](https://code.claude.com/docs/en/worktrees)

**GitHub enforcement on our plan**
- Merge queue is available only "in any public repository owned by an organization, or in private repositories owned by organizations using GitHub Enterprise Cloud". If used, CI must trigger on `merge_group`. — [GitHub Docs search result for merge queue](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue)
- Branch protection options include required reviews, **Require review from Code Owners**, required status checks, "Require branches to be up to date before merging", linear history, conversation resolution and merge queue. — [GitHub Docs: About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- Older GitHub docs say protected branches are available on public repos with GitHub Free, and on public and private repos with Pro/Team/Enterprise. The current page's snippet only confirms the Free/public case. — [GitHub Enterprise 2.13 docs](https://docs.github.com/en/enterprise/2.13/user/articles/about-protected-branches)
- **CODEOWNERS**:
  - It can live in `.github/`, the root or `docs/`, and the first one found is used.
  - It must be on the PR's base branch.
  - "the last matching pattern takes the most precedence".
  - Owners need explicit write access.
  - Approval from any one listed owner satisfies "Require review from Code Owners".

  — [GitHub Docs: About code owners](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)
- Verified students can get GitHub Pro free through the Student Developer Pack (third-party sources). — [GitHub Education pack](https://education.github.com/pack); [capitalandcompute](https://capitalandcompute.net/blog/github-student-developer-pack-2026/)

**Lockfiles**
- uv: the consensus is to regenerate rather than hand-merge: `git checkout --ours uv.lock && uv lock && git add uv.lock`. A conflicted `uv.lock` can be invalid TOML, in which case delete it and re-run `uv lock`. — [quax PR #272](https://github.com/nstarman/quax/pull/272); [astral-sh/uv issue #16348](https://github.com/astral-sh/uv/issues/16348)
- pnpm: "pnpm can automatically resolve merge conflicts in pnpm-lock.yaml". If you have conflicts, "run pnpm install and commit the changes". Always commit the lockfile. pnpm recommends Git branch lockfiles to avoid conflicts. — [pnpm.io/git](https://pnpm.io/git)

**Shared-file hot spots**
- **Changelog**: towncrier news fragments are one file per change, named `<issue>.<type>` (e.g. `1234.bugfix`, `3456.doc.rst`), or `+anything.bugfix` for orphan changes. The `directory` is set in `pyproject.toml`/`towncrier.toml`. `towncrier build` concatenates the fragments into the changelog and `git rm`s them, and `--draft` previews. — [towncrier tutorial](https://towncrier.readthedocs.io/en/stable/tutorial.html)
- **ADR numbering**:
  - Log4brains identifies ADRs by slug and uses a `YYYYMMDD-slug` date prefix specifically to reduce Git merge conflicts. — [log4brains summary](https://awesome.ecosyste.ms/projects/github.com%2Fthomvaill%2Flog4brains)
  - Sequential ADR numbers collide in practice on parallel branches. — [clan.lol ADR numbering](https://docs.clan.lol/decisions/03-adr-numbering-process)
  - Date indexes avoid conflicts but lose short numeric references. — [Cloud Posse proposal](https://docs.cloudposse.com/resources/adrs/proposed/proposed-use-iso-8601-date-index-for-adrs/)

### Inferences (concrete conflict-free workflow for Veyltrace)
1. **Ownership map, written in three places.** The same map goes in the root `AGENTS.md` (an "Ownership" table), in `.github/CODEOWNERS`, and in a CI check: a `scripts/check_ownership.py` that fails a PR touching paths outside the author's lane unless it has a `cross-lane` label. Example lanes (adapt to `docs/02-architecture.md`):
   - Aniket: `contracts/`, `core/engine/`, CI, `pyproject.toml`/`uv.lock`, `docs/adr/`
   - Annapurna: `core/detectors/` or `core/ingest/`, plus experiments/benchmarks
   - Lakshanaa: `ui/` (TypeScript, `package.json`/`pnpm-lock.yaml`), plus UI-facing API adapters

   Because each agent edits only its own tree, the 42%-structural add/add and modify/delete class largely disappears.
2. **Contract-first, frozen in week 1.**
   - `contracts/` holds JSON Schema or OpenAPI and protobuf/pydantic models. Python and TS types are **generated** from it (e.g. datamodel-codegen / openapi-typescript) and committed under `generated/` dirs that nobody edits by hand.
   - Mark the generated dirs `linguist-generated=true` in `.gitattributes`, and add a CI check that regenerates them and fails on diff.
   - Contract changes need an ADR plus the lead's approval (CODEOWNERS on `contracts/` = lead plus one other).
   - Each lane starts against **interface stubs or fakes** from the contract, so nobody waits on anybody.
3. **No shared registries.** Hot spots are `__init__.py` re-exports, a central algorithm registry dict, router tables, `CHANGELOG.md` and ADR numbers. Replace them with:
   - entry-points or directory auto-discovery (e.g. each detector module registers via a decorator, or the registry scans `core/detectors/*/`)
   - towncrier fragments: `changes/<issue>.<type>.md`
   - ADR names `docs/adr/YYYYMMDD-<initials>-<slug>.md`, or per-person number ranges (A001–A099 Aniket, N100–N199 Annapurna, L200–L299 Lakshanaa)
4. **Lockfiles have one owner.**
   - Only the lane owner changes `uv.lock` / `pnpm-lock.yaml`, in a dedicated `chore(deps)` PR.
   - In `.gitattributes`, set `uv.lock -merge` (or `merge=binary`) so Git never produces a half-merged TOML file. On conflict, regenerate with `uv lock` / `pnpm install`. AGENTS.md should tell agents never to hand-edit lockfiles.
   - The existing repo already has a `.gitattributes` to extend.
5. **Branching.**
   - Trunk-based: `main` plus short-lived `<owner>/<issue>-<slug>` branches that live under 1–2 days, each in its own worktree (`claude --worktree`, or `git worktree add` for the other tools).
   - Squash-merge only, with linear history.
   - Rebase onto `main` at least daily, and before opening a PR.
6. **Substitute for merge queue.** The repo is owned by a personal account, so there is no merge queue. Instead:
   - Turn on "Require branches to be up to date before merging" plus required checks (lint, type, test, determinism).
   - Turn on auto-merge.
   - Optionally move the repo into a free GitHub organization. If the repo is public, that unlocks merge queue (per the docs' availability sentence). If it stays private, branch protection probably needs GitHub Pro, which students can get through the Student Pack.
7. **CODEOWNERS caveat.** An author cannot approve their own PR (general GitHub behaviour, not re-verified this session). If a lane's only code owner is its author, "Require review from Code Owners" cannot be satisfied. List two owners per path (owner plus lead, and the lead's paths owned by lead plus one other).
8. **Pre-commit and commit conventions.**
   - Add a `pre-commit` config: ruff, ruff-format, mypy/pyright, eslint/prettier, a check for hand-edited generated files, and a towncrier-fragment-present check.
   - Use Conventional Commits (`feat(core): …`) so release notes and SemVer bumps can be automated (release-please or python-semantic-release).
   - These tool recommendations come from general knowledge; I did not fetch their docs this session.
9. **Agent-specific guardrails in AGENTS.md.**
   - "Never edit files outside your lane."
   - "Never edit `contracts/` or `generated/`."
   - "Never touch lockfiles."
   - "One issue = one branch = one PR, ≤400 changed lines."
   - "Run `make check` before committing."

   Agents follow concise, specific rules more reliably (Claude docs: under 200 lines, no contradictions).
10. **Drift control.** Add a weekly "integration Friday" where the lead rebases everything, re-runs the end-to-end determinism test and updates AGENTS.md. This matters because most conflicts are resolved by humans anyway (96.1% in the SBES data).

### Gaps
- I did not verify changesets, Conventional Commits, release-please or pre-commit docs in this session. They are standard tools, but the specifics above come from general knowledge.
- Whether "require code owner review" is satisfiable when the author is the sole owner was not verified against current GitHub docs.
- Current GitHub docs on protected branches for **private** repos under Free vs Pro are ambiguous in the fetched text (the plan header didn't render).
- There is no controlled study on whether directory ownership or contract-first measurably reduces *AI-agent* conflict rates. The recommendation is inferred from the conflict taxonomy (structural vs textual, source-code-dominated).

---

## Q4. How should a tiny team track the SDLC on GitHub Free?

### Takeaway
GitHub Free is enough:
- issue forms plus labels plus milestones (one per week)
- a Projects board (Backlog → In progress → In review → Done)
- a PR template carrying the Definition of Done
- required CI checks
- SemVer tags with towncrier-built release notes

CI minutes only matter if the repo is private. Public repos get free standard runners, while a private repo on the Free plan gets $12 of compute a month (about 2,000 Linux minutes). Keep CI on Linux and avoid Windows and macOS runners.

### Cited Findings
- **Issue forms**: YAML files in `.github/ISSUE_TEMPLATE/`.
  - Required keys: `name`, `description`, `body`.
  - Optional keys: `title`, `labels`, `assignees`, `type`, `projects` (format `OWNER/NUMBER`; the opener needs write access to the project).
  - Body element types: `markdown`, `input`, `textarea`, `dropdown`, `checkboxes`, `upload`.
  - Issue forms are still marked "public preview".

  — [GitHub Docs: issue form syntax](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms)
- **Actions billing**: included compute is GitHub Free $12/month (500 MB artifacts, 10 GB cache per repo), Pro $18, Team $18. "Standard GitHub-hosted runners in public repositories" are free, and self-hosted runners are free. Per-minute rates are Linux 2-core $0.006, Windows 2-core $0.010 and macOS $0.062. — [GitHub Docs: Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- **Required checks**: required status checks and "Require branches to be up to date before merging" are branch-protection options. — [GitHub Docs: About protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
- **Copilot for students**: on 13 Mar 2026 students were moved to a new "Copilot Student" plan. One source says new student sign-ups were paused in April 2026 and the plan is about 200 AI credits a month; another (updated 1 Oct 2026) says Copilot remains free for verified students. These conflict. — [layer3labs](https://www.layer3labs.io/guides/github-copilot-student); [buildmvpfast](https://www.buildmvpfast.com/blog/student-developer-perks-free-ai-tools-copilot-cursor-2026)

### Inferences (proposed setup, mostly from general GitHub practice)
- **Milestones**: one per week (W1 contracts and skeleton → W2 lanes → W3 integration and experiments → W4 paper and freeze), plus a `v0.x` release tag at the end of each week (SemVer pre-1.0: `0.1.0`, `0.2.0`, …; `1.0.0` = paper artifact).
- **Labels**:
  - `lane:core|detect|ui|contracts|infra`
  - `type:feat|bug|chore|exp|paper|adr`
  - `agent:claude|codex|cursor|antigravity|copilot|opencode`, to track which agent produced the PR. This is useful later as a methods detail or threat-to-validity note in the paper.
  - `cross-lane`, `blocked`, `frozen-contract`
- **Projects board**: one board with fields Status, Lane, Week/Iteration, Size (S/M/L) and Agent, using the built-in auto-add and auto-close workflows. I did not verify current Projects free-tier limits this session.
- **Definition of Done** (checkboxes in `.github/pull_request_template.md`):
  - tests added and passing
  - `make check` green (ruff, mypy/pyright, eslint, tsc, pytest, vitest)
  - **determinism check** green: run the RCA pipeline twice on the fixed seed and fixture and diff the output JSON byte-for-byte
  - towncrier fragment added
  - no edits outside the lane or to `contracts/` or `generated/`
  - ADR linked if there is an architectural change
  - docs updated
  - the agent used is recorded
- **CI gates** (`.github/workflows/ci.yml`):
  - Jobs: `lint` → `type` → `test` → `determinism` → `contracts-in-sync` → `ownership`. Add `towncrier check --compare-with origin/main`.
  - Use `concurrency` with cancel-in-progress to save minutes.
  - Run on `ubuntu-latest` only.
  - If the repo is private, budget: the Free plan covers about 2,000 Linux minutes a month. A 5-minute pipeline × ~15 PR pushes a day × 30 days is about 2,250 minutes, which is over budget. Either make the repo public, cache aggressively, or use path filters so UI-only PRs skip the Python jobs and vice versa.
- **Release**: tag `vX.Y.Z` on `main` → `towncrier build` → GitHub Release. Each release also triggers a Zenodo DOI (see Q5).

### Gaps
- I did not fetch current GitHub Projects (v2) limits or features, PR template docs or the SemVer/Conventional Commits specs this session.
- The visibility of the Veyltrace repo (public vs private) is unknown. It changes CI cost, merge-queue eligibility and branch-protection availability.

---

## Q5. What does research-paper readiness require: reproducibility, artifacts, citation, licences, venues and arXiv?

### Takeaway
- **Make the repo artifact-ready from day 1.** Add a CITATION.cff, an archived Zenodo DOI per release, and a one-command reproduction script with fixed seeds and committed result JSON. This is what ACM "Available/Functional/Reusable" badges and the NeurIPS checklist reward.
- **Deadlines.** Given the 1-month build (to about end of Nov 2026), the main 2027 research deadlines for ICSE, FSE and KDD cycle 1 have **passed**. Realistic near-term targets:
  - ICSE 2027 workshops and Student Research Competition: **13 Nov 2026**
  - WWW 2027 Demos: **16 Nov 2026**
  - FSE 2027 Industry track: **23 Jan 2027**
  - KDD 2027 cycle 2: Feb 2027, exact date unconfirmed
  - ISSRE 2027 and NeurIPS 2027 E&D: spring 2027, inferred and unannounced
- **arXiv.** First-time student submitters now need a personal endorsement from an established author, typically their faculty advisor.

### Cited Findings

**Citation and archiving**
- **CITATION.cff**: put it at the repo root on the default branch. GitHub then shows a "Cite this repository" link in the sidebar with APA and BibTeX output. Minimal fields: `cff-version: 1.2.0`, `message`, `authors`, `title`, `version`, `date-released`. — [GitHub Docs: CITATION files](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-citation-files)
- **Zenodo DOI**: log in to Zenodo with GitHub, toggle the repo **On**, and every new GitHub release then gets a new DOI. The repo must be **public**. An organization-owned repo may need owner approval for the Zenodo app. Include a licence. — [GitHub Docs: Referencing and citing content](https://docs.github.com/en/repositories/archiving-a-github-repository/referencing-and-citing-content)

**Artifact badges**
- **ACM Artifacts Available** requires permanent public archival with a DOI or similar identifier. Under v1.1, "personal web pages, GitHub, GitLab, or a similar software-development site is not adequate". — [UPenn AE guidelines quoting ACM](https://li.seas.upenn.edu/artifact-evaluation); [ACM v1.0 (not current)](https://www.acm.org/publications/policies/artifact-review-badging/)
- ICPE 2024 required a permanent URL or DOI such as Zenodo. — [ICPE 2024 AE track](https://icpe2024.spec.org/tracks-and-submissions/artifact-evaluation-track)
- **Functional** means documented, consistent, complete, exercisable, and with evidence of verification and validation. **Reusable** means Functional plus careful documentation and structure that enable reuse. *Evaluated* badges don't require public availability, only availability to reviewers. — [UPenn AE guidelines](https://li.seas.upenn.edu/artifact-evaluation)

**NeurIPS**
- The Datasets & Benchmarks track was renamed **Evaluations & Datasets (E&D)** for NeurIPS 2026. It follows the main-track CFP for formatting and ethics, and therefore the main-track checklist.
  - Datasets must be documented in **Croissant** format, including Responsible-AI metadata.
  - Code and datasets must be public by camera-ready.
  - The 2026 deadlines were abstract 4 May 2026 and full paper 6 May 2026.

  — [NeurIPS blog, 23 Mar 2026](https://blog.neurips.cc/2026/03/23/introducing-the-evaluations-datasets-track-at-neurips-2026/); [NeurIPS 2026 E&D CFP](https://neurips.cc/Conferences/2026/CallForEvaluationsDatasets); [NeurIPS newsletter May 2026](https://blog.neurips.cc/2026/05/29/neurips-newsletter-may-2026/)

**ICSE 2027** (Dublin, 25 Apr–1 May 2027)
- The research track deadline was 30 Jun 2026 (abstract 23 Jun). Starting with ICSE 2027 there is a single summer cycle. — [ICSE 2027 dates](https://conf.researchr.org/dates/icse-2027); [PaperPilot](https://www.getpaperpilot.com/deadlines/icse-2027.html); [ICSE news](https://icse-conferences.org/news.html)
- The SEIP deadline was 23 Oct 2026 (passed). — [PaperPilot](https://www.getpaperpilot.com/deadlines/icse-2027.html)
- Still open per the official dates page:
  - **Workshop papers due Fri 13 Nov 2026** (workshops listed include AGENT, AIPerf, ReCode, GREENS and others; notification 11 Dec)
  - **ACM SRC due 13 Nov 2026**
  - **Doctoral Symposium due 14 Nov 2026**
  - **Industry Challenge solutions due 13 Nov 2026**
  - **Competitions due 4 Dec 2026**
  - CAIN Posters & Demos due 6 Nov 2026
  - Artifact Evaluation for accepted papers: registration 22 Jan 2027, submission 29 Jan 2027

  — [ICSE 2027 dates](https://conf.researchr.org/dates/icse-2027)

**FSE 2027** (Shenzhen, 12–16 Jul 2027)
- The research papers deadline was 2 Oct 2026 (third-party). — [PaperPilot](https://www.getpaperpilot.com/deadlines/fse-2027.html)
- **Industry papers due 23 Jan 2027 (AoE)**, notification 20 Mar 2027. Long papers are 10+2 pages and short papers 5+1. The track welcomes work "applied in an industrial context or their relevance to such context is clearly identified". — [FSE 2027 Industry track](https://conf.researchr.org/track/fse-2027/fse-2027-industry-papers)

**WWW 2027** (Dublin, 10–14 May 2027, OpenReview)
- The research-track paper deadline is listed as about 18–19 Oct 2026 by aggregators only (passed). Camera-ready is 31 Jan 2027. — [WWW 2027 research CFP](https://www2027.thewebconf.org/?p=296); [MyHuiban](https://www.myhuiban.com/conference/137?lang=en-us)
- **Demos due 16 Nov 2026**, notification 4 Jan 2027, published in Companion Proceedings. — [WWW 2027 Demos CFP](https://www2027.thewebconf.org/demos/)

**KDD 2027**
- The cycle-1 research deadline was 26 Jul 2026 (abstract 19 Jul), with notification 14 Nov 2026. — [KDD 2027 research CFP](https://kdd2027.kdd.org/research-track-call-for-papers/)
- A February 2027 second cycle exists (FAQ), but the exact date was not captured. August-cycle research acceptance was 19%. — [KDD 2027 FAQ](https://kdd2027.kdd.org/frequently-asked-questions/)
- Tracks are Research, Applied Data Science (for deployed systems), Datasets & Benchmarks, and AI for Sciences. — [KDD 2027 ADS CFP](https://kdd2027.kdd.org/applied-data-science-ads-track-call-for-papers/)

**ISSRE, ASE and AIOps workshops**
- **ISSRE 2027**: 19–22 Oct 2027, Macau. The CFP is not yet published. — [BERI listing](https://www.beri.net/events/issre-2027)
- ISSRE 2026's research deadline was about 17 Apr 2026, for reference. — [ISSRE 2026 dates](https://cyprusconferences.org/issre2026/?p=244382)
- **ASE 2027**: no CFP found.
- **AIOps workshops**: no 2027 CFP found. The closest, AnServApp 2026 (RCA and fault diagnosis topics, 6 pages), closed 14 Aug 2026. — [AnServApp 2026](https://sites.google.com/view/anservapp2026)

**arXiv**
- Since **21 Jan 2026** (Mathematics since 10 Dec 2025), automatic endorsement needs both an institutional email **and** prior authorship of an accepted paper in that endorsement domain. Otherwise you need a personal endorsement from an established author in the domain. — [arXiv blog: Math endorsement policy](https://blog.arxiv.org/arxiv/2025/12/10/updated-endorsement-policy-for-arxiv-mathematics); [arXiv blog 2026 index](https://blog.arxiv.org/2026); [CASRAI summary](https://casrai.org/news/arxiv-2026-endorsement-english-ai-policy-changes)
- arXiv also added a monthly per-author submission cap on top of the limit of 3 active submissions. I didn't confirm the cap's exact value. — [404 Media](https://404media.co/arxiv-is-rate-limiting-submissions-because-it-cant-keep-up-with-ai-slop)

### Inferences
- **Paper-ready repo checklist** (build in week 1 so it is not a scramble):
  - `CITATION.cff` listing all three authors and the advisor, if any.
  - `LICENSE`: the existing 11 KB file is probably Apache-2.0, judging by its size; verify. Apache-2.0 gives an explicit patent grant, and MIT is shorter. Either is accepted by Zenodo and ACM.
  - Datasets and result tables under CC-BY-4.0, in a `data/LICENSE` file.
  - `REPRODUCE.md` with a single `make reproduce` command that runs the benchmarks with fixed seeds and pinned `uv.lock` / `pnpm-lock.yaml`.
  - `results/<run_id>/` holding a plain JSON `manifest.json` (git SHA, config hash, seed, dataset hash, wall-clock, machine) plus `metrics.json`. Commit small results directly to git. Use DVC (local remote) only for datasets too large for git, and skip cloud MLflow, in line with the project's no-network principle. These tool choices come from general knowledge; DVC and MLflow docs were not fetched this session.
- **Make the repo public before the first tagged release.** Zenodo requires public repos, ACM "Available" requires an archival DOI, and public repos also get free Actions minutes.
- **Venue strategy for a 1-month build** (dates verified above unless marked):
  1. **13 Nov 2026**: ICSE 2027 SRC (ACM Student Research Competition, made for students) or a relevant ICSE workshop (AGENT, AIPerf). Check each workshop's own CFP for AIOps/RCA fit.
  2. **16 Nov 2026**: WWW 2027 Demos, a demo of the RCA UI and system.
  3. **23 Jan 2027**: FSE 2027 Industry track, if framed around industrial relevance or industrial data.
  4. **Feb 2027**: KDD 2027 cycle 2 (Research or ADS/D&B). Confirm the date.
  5. **About Apr 2027 (inferred)**: ISSRE 2027 research track, a natural home for RCA and reliability work.
  6. **About May 2027 (inferred from 2026)**: NeurIPS 2027 E&D, if the contribution is an RCA *benchmark or evaluation*. Needs Croissant + RAI metadata.
  7. ASE 2027: watch for a CFP; ASE deadlines are historically around late spring (unverified).
- **arXiv**: each student should identify an endorser now (advisor or co-author with cs.SE / cs.DC / cs.LG arXiv history) and post the preprint after, or alongside, submission, subject to the venue's anonymity rules.
- **Record the multi-agent process.** Log which agent wrote which PR (the `agent:` label) and the conflict counts. This is cheap to collect and could become a methods or threat-to-validity paragraph, or even a side contribution given the 2026 literature on agentic-PR conflicts.

### Gaps
- I could not fetch the current ACM Artifact Review and Badging v1.1 page (HTTP 403), so badge text is from secondary quotes.
- The NeurIPS 2026 main checklist text was not fetched, and NeurIPS 2027 dates are not announced.
- ISSRE 2027, ASE 2027 and the KDD 2027 cycle-2 exact deadlines were not found. Neither was the WWW 2027 research deadline on the official site (aggregators only).
- I did not individually check which ICSE 2027 workshops explicitly solicit AIOps/RCA papers.
- No source found for 2027 AIOps-specific workshops (e.g. at ICSE/ASPLOS/ICSOC).
- ICSE-SEIP 2027 already closed (23 Oct 2026). The ICSE Demonstrations track deadline is not shown as upcoming; only its 11 Dec notification is listed.
- DVC/MLflow local-mode docs, the Apache-2.0 vs MIT comparison and CC-BY guidance were not researched this session. The recommendations above are general knowledge.
- The exact value of the arXiv monthly submission cap was not found.
