# CONFIRMED · catalog · mem

**CONFIRMED** · confidence: high · candidate set size: 1 · margin: 0.76

## Summary

- catalog is the only member of the candidate set and passed every mandatory trial. (cites: Ea219385f6e, E09d7fef8c9, Ec7e15656c4, E9d37c91c2d, Eb7b0de766f, E7b0771b7a9)
- Its strongest internal signal was catalog mem anomaly (incident) at 82.1 z. (cites: Ea219385f6e)
- Confidence is high; its verified score leads frontend by a relative margin of 0.76. (cites: Ea219385f6e, E09d7fef8c9, Ec7e15656c4, E9d37c91c2d, Eb7b0de766f, E7b0771b7a9)

## Candidate set

- catalog

## Evidence

| Atom | Evidence | Value | Unit |
|---|---|---|---|
| Ea219385f6e | catalog mem anomaly (incident) | 82.1 | z |
| E09d7fef8c9 | catalog onset precedence over self (onset) | 0 | ms |
| Ec7e15656c4 | catalog onset precedence over dependents (onset) | 1 |  |
| E9d37c91c2d | catalog propagation to entry (incident) | 1 |  |
| Eb7b0de766f | catalog propagation to path (incident) | 1 |  |
| E7b0771b7a9 | catalog silence (incident) | 0 |  |
| E035e845d05 | checkout mem anomaly (incident) | 0.826 | z |
| E69dec80d43 | checkout silence (incident) | 0 |  |
| E58335ef082 | frontend mem anomaly (incident) | 0.56 | z |
| E2a9591ce1a | frontend silence (incident) | 0 |  |
| E3fa4c27025 | recommend mem anomaly (incident) | 0.528 | z |
| Efd34e2ffcd | recommend silence (incident) | 0 |  |

## Timeline

- 00:21:00 UTC — catalog deploy change (cites: E1a3227d1c7)
- 00:22:00 UTC — alert (oracle)
- 00:22:00 UTC — catalog external onset (cites: E09d7fef8c9, Ec60a81fd6f)
- 00:22:00 UTC — catalog internal onset (cites: E09d7fef8c9, Ec60a81fd6f)
- 00:22:00 UTC — incident onset

## Path

catalog → frontend

## Why not

- **frontend**: frontend showed no internal anomaly that its callees do not explain (failed T1, origin). (cites: E2a9591ce1a, E58335ef082)
- **recommend**: recommend showed no internal anomaly that its callees do not explain (failed T1, origin). (cites: E3fa4c27025, Efd34e2ffcd)
- **checkout**: checkout showed no internal anomaly that its callees do not explain (failed T1, origin). (cites: E035e845d05, E69dec80d43)

## Asks

- none

## Next steps

- Compare memory use with the limit on catalog. (PB-MEM-01)
- Check restarts and memory kill events of catalog. (PB-MEM-01)
- Look for steady memory growth on catalog, a sign of a leak. (PB-MEM-01)
- Consider a restart or a rollback after review. (PB-MEM-01)
- Identify the change that preceded the onset on the timeline. (PB-CHANGE-01)
- Compare catalog with its peers or with the previous version. (PB-CHANGE-01)
- Consider a rollback after review. (PB-CHANGE-01)

prose: template

---

verdict_hash: `5dbf5d34518e779749df34b0a963f268751466ebf8511ebd8c394ba17a86e1f8`  
card_hash: `7729e9463a184e4bf27b6341f9166870b58adfccc04975e7f3ab3b8c8412dc46`  
replay: `uv run veyltrace replay <run dir>/receipt.json`
