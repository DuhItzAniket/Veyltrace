# INCONCLUSIVE · leading candidate frontend

**INCONCLUSIVE** · confidence: low · candidate set size: 1 · margin: 0.09

## Summary

- No single root cause could be established; the candidate set has 1 service. (cites: E58335ef082, Eb7975b24ea, E6a49a9c872, Edf0b80e253, E2a9591ce1a)
- The leading candidate is frontend. (cites: E58335ef082, Eb7975b24ea, E6a49a9c872, Edf0b80e253, E2a9591ce1a)
- The asks below list what would settle it: trials to check and context to inspect. (cites: E58335ef082, Eb7975b24ea, E6a49a9c872, Edf0b80e253, E2a9591ce1a)

## Candidate set

- frontend

## Evidence

| Atom | Evidence | Value | Unit |
|---|---|---|---|
| Ea219385f6e | catalog mem anomaly (incident) | 0.445 | z |
| E7b0771b7a9 | catalog silence (incident) | 0 |  |
| Ec3ee13da9f | checkout self_time anomaly (incident) | 1.31 | z |
| E69dec80d43 | checkout silence (incident) | 0 |  |
| E58335ef082 | frontend mem anomaly (incident) | 0.534 | z |
| Eb7975b24ea | frontend onset precedence over self (onset) | 0 | ms |
| E6a49a9c872 | frontend propagation to entry (incident) | 1 |  |
| Edf0b80e253 | frontend propagation to path (incident) | 1 |  |
| E2a9591ce1a | frontend silence (incident) | 0 |  |
| E106e938451 | recommend self_time anomaly (incident) | 0.811 | z |
| Efd34e2ffcd | recommend silence (incident) | 0 |  |

## Timeline

- 00:22:00 UTC — alert (oracle)
- 00:22:00 UTC — frontend external onset (cites: Eb7975b24ea)
- 00:22:00 UTC — incident onset

## Path

frontend

## Why not

- **recommend**: recommend showed no internal anomaly that its callees do not explain (failed T1, origin). (cites: E106e938451, Efd34e2ffcd)
- **checkout**: checkout showed no internal anomaly that its callees do not explain (failed T1, origin). (cites: E69dec80d43, Ec3ee13da9f)
- **catalog**: catalog showed no internal anomaly that its callees do not explain (failed T1, origin). (cites: E7b0771b7a9, Ea219385f6e)

## Asks

- trial: T1:frontend — mandatory trial T1 failed: no_internal_anomaly
- context: recommend — runner-up within margin 0.09

## Next steps

- Check the trials named in the asks (failed or untestable). (PB-INCONC-01)
- Inspect the named service, or the ranked slate, around the incident onset. (PB-INCONC-01)
- Inspect each member of the candidate set. (PB-INCONC-01)
- Run the diagnosis again once the asks are answered. (PB-INCONC-01)

prose: template

---

verdict_hash: `67fb6c8a444258019f07cd79274554aa4e76db5f5205b531772696b36943f889`  
card_hash: `03cc920d90493b2cbfb0b3ff5df27dbf36aaafbd4008580510474ea17bba227e`  
replay: `uv run veyltrace replay <run dir>/receipt.json`
