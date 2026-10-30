# veyltrace-causivra

Engine 10 of Veyltrace: turns a sealed verdict into an incident card and a receipt that anyone can re-check.

- Spec: [docs/engines/10-causivra.md](../../docs/engines/10-causivra.md)
- Card: title, status, root, candidate set, timeline, path, evidence table, why-not, asks, deterministic playbooks. Prose is LLM-written with placeholders and a claim checker, or template prose when AI is off or the checker rejects it twice.
- Receipt: in-toto Statement v1 with the run manifest, `verdict_hash`, `card_hash` and the agent-trace head; optional minisign signature.
- Replay: `veyltrace replay <receipt.json>` re-hashes the stored outputs of steps 0–4, `config.lock.json`, calibration and cassette, re-runs pipeline steps 5–10 (`--full`: 0–10) and exits 0 (ok), 1 (error), 2 (verdict mismatch), 3 (inputs changed), 4 (config), 5 (environment drift), 6 (narrative only).

```sh
uv run veyltrace diagnose --dataset synth --case synth-01 --ai off
uv run veyltrace replay runs/synth/<case_id>/<run_id>/receipt.json
uv run python scripts/check.py --package causivra
```
