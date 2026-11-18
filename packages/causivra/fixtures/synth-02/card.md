# INCONCLUSIVE · leading candidate recommend

**INCONCLUSIVE** · confidence: low · candidate set size: 1 · margin: 0.02

## Summary

- No single root cause could be established; the candidate set has 1 service. (cites: E106e938451, E064e599e66, Ec8c7dbc9ee, E0ac060be5f, Eb6f68006b9, Efd34e2ffcd)
- The leading candidate is recommend. (cites: E106e938451, E064e599e66, Ec8c7dbc9ee, E0ac060be5f, Eb6f68006b9, Efd34e2ffcd)
- The asks below list what would settle it: trials to check and context to inspect. (cites: E106e938451, E064e599e66, Ec8c7dbc9ee, E0ac060be5f, Eb6f68006b9, Efd34e2ffcd)

## Candidate set

- recommend

## Evidence

| Atom | Evidence | Value | Unit |
|---|---|---|---|
| Ea219385f6e | catalog mem anomaly (incident) | 0.445 | z |
| E7b0771b7a9 | catalog silence (incident) | 0 |  |
| Ec3ee13da9f | checkout self_time anomaly (incident) | 1.31 | z |
| E69dec80d43 | checkout silence (incident) | 0 |  |
| E58335ef082 | frontend mem anomaly (incident) | 0.534 | z |
| E2a9591ce1a | frontend silence (incident) | 0 |  |
| E106e938451 | recommend self_time anomaly (incident) | 0.811 | z |
| E064e599e66 | recommend onset precedence over dependents (onset) | 1 |  |
| Ec8c7dbc9ee | recommend onset precedence over self (onset) | 0 | ms |
| E0ac060be5f | recommend propagation to entry (incident) | 1 |  |
| Eb6f68006b9 | recommend propagation to path (incident) | 1 |  |
| Efd34e2ffcd | recommend silence (incident) | 0 |  |

## Timeline

- 00:22:00 UTC — alert (oracle)
- 00:22:00 UTC — incident onset
- 00:22:00 UTC — recommend external onset (cites: Ec8c7dbc9ee)

## Path

recommend → frontend

## Why not

- **frontend**: frontend showed no internal anomaly that its callees do not explain (failed T1, origin). (cites: E2a9591ce1a, E58335ef082)
- **checkout**: checkout showed no internal anomaly that its callees do not explain (failed T1, origin). (cites: E69dec80d43, Ec3ee13da9f)
- **catalog**: catalog showed no internal anomaly that its callees do not explain (failed T1, origin). (cites: E7b0771b7a9, Ea219385f6e)

## Asks

- trial: T1:recommend — mandatory trial T1 failed: no_internal_anomaly
- context: frontend — runner-up within margin 0.02

## Next steps

- Check the trials named in the asks (failed or untestable). (PB-INCONC-01)
- Inspect the named service, or the ranked slate, around the incident onset. (PB-INCONC-01)
- Inspect each member of the candidate set. (PB-INCONC-01)
- Run the diagnosis again once the asks are answered. (PB-INCONC-01)

prose: template

---

verdict_hash: `1a3a258dcf72ee41945fbd4456d4f103f84df74b573c748e1ce5b22a7cccded1`  
card_hash: `2307404fa576dc4578b34dd89b276986df693d34fd6c2a5ff13e00bb88c7dc10`  
replay: `uv run veyltrace replay <run dir>/receipt.json`
