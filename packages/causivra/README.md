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

**Status (X-03).** Both steps are this package's.

- Card (10a, `card.py`): title by status; status, root, confidence and candidate set copied from the verdict; evidence table from the leaders' trial atoms and holding claim checks with `labels.<kind>`; timeline; rank-1 path; why-not per runner-up; asks; deterministic playbooks (`playbooks.yaml`); template summary prose (10 §3.5); `card_hash`; `card.md` rendered from `card.json` only. Every sentence goes through the placeholder filler (`placeholders.py`) and one number formatter (`fmt.py`). LLM narration and the claim checker C4–C8 arrive in X-09.
- Receipt (10b, `receipt.py`): checks that `run_manifest.json` lists `verdict.json`, `card.json` and `card.md` with their current hashes and that the card belongs to the verdict, verifies the agent-trace chain (head `null` when the trace is absent or empty) and writes the in-toto Statement as canonical JSON. Signing and replay arrive in X-09.
- Config: `config/causivra.yaml` (`card.evidence_max`, `why_not.max`, `format.sig_digits`, `labels.<kind>`, `asks.<kind>`); the mandatory trial set comes from `causentra.mandatory`.
