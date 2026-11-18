# CONFIRMED · checkout · unknown

**CONFIRMED** · confidence: high · candidate set size: 1 · margin: 0.76

## Summary

- checkout is the only member of the candidate set and passed every mandatory trial. (cites: Ec3ee13da9f, E39040cc71a, E8aa8de679c, E586a046788, Ee33689c27e, E69dec80d43)
- Its strongest internal signal was checkout self_time anomaly (incident) at 16.5 z. (cites: Ec3ee13da9f)
- Confidence is high; its verified score leads frontend by a relative margin of 0.76. (cites: Ec3ee13da9f, E39040cc71a, E8aa8de679c, E586a046788, Ee33689c27e, E69dec80d43)

## Candidate set

- checkout

## Evidence

| Atom | Evidence | Value | Unit |
|---|---|---|---|
| E005b71362a | cart self_time anomaly (incident) | 0.409 | z |
| Ec3ee13da9f | checkout self_time anomaly (incident) | 16.5 | z |
| E39040cc71a | checkout onset precedence over self (onset) | 0 | ms |
| E8aa8de679c | checkout onset precedence over dependents (onset) | 1.00 |  |
| E586a046788 | checkout propagation to entry (incident) | 1.00 |  |
| Ee33689c27e | checkout propagation to path (incident) | 1.00 |  |
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

verdict_hash: `df310d9a6e65e5965a6862c9df6c2644127fd9c3d272d3fece49c4759f2cc164`  
card_hash: `a8c186cdc7fd03650fc5550d6108575487c29575c927e47922c6f38583777b76`  
replay: `uv run veyltrace replay <run dir>/receipt.json`
