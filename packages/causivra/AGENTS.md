# AGENTS.md — packages/causivra

Adds to the root [AGENTS.md](../../AGENTS.md) and never overrides it.

- **Lane:** Explain. Edit only Explain paths (root AGENTS.md §2).
- **Purpose:** engine 10. Writes the incident card under a claim checker, assembles the in-toto receipt, implements `veyltrace replay`.
- **Spec:** [docs/engines/10-causivra.md](../../docs/engines/10-causivra.md) · master [02 §6.10](../../docs/02-architecture.md) · contracts [03 §10–12](../../docs/03-contracts.md).
- **Inputs:** `verdict`, `evidence`, `agent_trace`, `run_manifest`, `alert`, `case_manifest`, `onsets`, `changes`, `graph.*`, `config/causivra.yaml`, `config/llm.yaml`, playbooks, prompts.
- **Outputs:** `card.json`, `card.md`, `receipt.json` (optional `receipt.json.minisig`); replay report and exit codes 0–6.

## Package rules

1. Causivra never changes the verdict. Status, root, confidence and candidate set are copied verbatim.
2. May import `veyltrace_llm`, for summary prose only. Why-not, asks, next steps and titles are templates.
3. No LLM sentence reaches `card.json` unless it passes checker rules C1–C8 (spec §3.4). Two failed attempts → template prose.
4. The narrator sees placeholders, not values (`narration.show_values = false`). Numbers and entity names are filled by code.
5. Every template sentence must pass the checker; a test enforces it.
6. `NO_FAULT` and `INCONCLUSIVE` are written honestly: no certainty words, empty set shown as empty, no why-not for `NO_FAULT`.
7. `card.json` and `receipt.json` are written with `canonical_json`; `card.md` is rendered from artifacts only, with no render-time timestamps.
8. Replay exit codes and their precedence are fixed in the spec. Do not add codes.
9. Step 10 is split: 10a writes the card, core then writes `config.lock.json` and `run_manifest.json`, 10b writes the receipt (02 §6.10). Replay reads the run dir's `config.lock.json`, never the repo's `config/`.

## Commands

| Task | Command |
|---|---|
| Check this package | `uv run python scripts/check.py --package causivra` |
| Determinism gate | `uv run python scripts/check.py --determinism` |
| Replay a run | `uv run veyltrace replay runs/<…>/receipt.json` |

## Never

- Never write remediation that acts on a system; playbooks are read-only advice ("consider … after review").
- Never put a raw number, unplaceholdered entity name or uncited sentence into the summary.
- Never use an LLM as a judge of prose inside the pipeline.
- Never read signing keys from the repo or commit a secret key; the secret-key path comes from `VEYLTRACE_MINISIGN_SECRET_KEY`.
- Never read answer keys, `case_manifest.t_alert_hint_ns`, or anything under `bench/` or `lab/`.
