# CONFIRMED · checkout · unknown

**CONFIRMED** · confidence: high · candidate set size: 1 · margin: 0.78

## Summary

- checkout is the only member of the candidate set and passed every mandatory trial. (cites: Ec3ee13da9f, E39040cc71a, E8aa8de679c, E586a046788, Ee33689c27e, Ec64c7d2ef8, E69dec80d43)
- Its strongest internal signal was checkout self_time anomaly (incident) at 16.5 z. (cites: Ec3ee13da9f)
- Confidence is high; its verified score leads frontend by a relative margin of 0.78. (cites: Ec3ee13da9f, E39040cc71a, E8aa8de679c, E586a046788, Ee33689c27e, Ec64c7d2ef8, E69dec80d43)

## Candidate set

- checkout

## Evidence

| Atom | Evidence | Value | Unit |
|---|---|---|---|
| E005b71362a | cart self_time anomaly (incident) | 0.409 | z |
| Ec3ee13da9f | checkout self_time anomaly (incident) | 16.5 | z |
| E39040cc71a | checkout onset precedence over self (onset) | 0 | ms |
| E8aa8de679c | checkout onset precedence over dependents (onset) | 1 |  |
| E586a046788 | checkout propagation to entry (incident) | 1 |  |
| Ee33689c27e | checkout propagation to path (incident) | 1 |  |
| Ec64c7d2ef8 | checkout self-time share at p50 (incident) | 0.991 |  |
| E69dec80d43 | checkout silence (incident) | 0 |  |
| E128139729e | frontend self_time anomaly (incident) | 0.485 | z |
| E2a9591ce1a | frontend silence (incident) | 0 |  |
| E87fe04b0bc | payment self_time anomaly (incident) | 0.485 | z |
| E23c811e2ae | payment silence (incident) | 0 |  |
| E106e938451 | recommend self_time anomaly (incident) | 0.744 | z |
| Efd34e2ffcd | recommend silence (incident) | 0 |  |

## Timeline

- 00:22:00 UTC — alert (oracle)
- 00:22:00 UTC — checkout external onset (cites: E39040cc71a, E58f665f302)
- 00:22:00 UTC — checkout internal onset (cites: E39040cc71a, E58f665f302)
- 00:22:00 UTC — incident onset

## Path

checkout → frontend

## Why not

- **frontend**: frontend showed no internal anomaly that its callees do not explain (failed T1, origin). (cites: E128139729e, E2a9591ce1a)
- **recommend**: recommend showed no internal anomaly that its callees do not explain (failed T1, origin). (cites: E106e938451, Efd34e2ffcd)
- **payment**: payment showed no internal anomaly that its callees do not explain (failed T1, origin). (cites: E23c811e2ae, E87fe04b0bc)

## Asks

- none

## Next steps

- Review the evidence table. (PB-UNK-01)
- Collect the telemetry listed under asks. (PB-UNK-01)

prose: template

---

verdict_hash: `16fa25393f5a6e8b7ed9c6085b0926192d065699780da8fc1bf4976c32edcb79`  
card_hash: `272b1758555eb1825c540203d8bc4112961729d11c7353e025b079b7777b7aeb`  
replay: `uv run veyltrace replay <run dir>/receipt.json`
