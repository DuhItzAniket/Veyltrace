# NO_FAULT · no fault detected in the incident window

**NO_FAULT** · confidence: none · candidate set size: 0 · margin: 0.07

## Summary

- No anomaly above threshold was found at the entry service or inside any service.
- The candidate set is empty and no root cause is named.

## Candidate set

- empty

## Evidence

| Atom | Evidence | Value | Unit |
|---|---|---|---|
| Ec3ee13da9f | checkout self_time anomaly (incident) | 1.03 | z |
| E0c9b9b1ec7 | checkout anomaly not explained by parents (incident) | 0.74 | z |
| E69dec80d43 | checkout silence (incident) | 0 |  |
| E58335ef082 | frontend mem anomaly (incident) | 0.707 | z |
| E2a9591ce1a | frontend silence (incident) | 0 |  |
| E89d6468c5f | payment mem anomaly (incident) | 1.09 | z |
| Ee3995a0e55 | payment anomaly not explained by parents (incident) | 1.09 | z |
| E23c811e2ae | payment silence (incident) | 0 |  |

## Timeline

- 00:22:00 UTC — alert (oracle)
- 00:22:00 UTC — incident onset

## Path

none

## Why not

- none

## Asks

- none

## Next steps

- Confirm with the alert source whether the alert was spurious. (PB-NOFAULT-01)
- Check the service level thresholds of the entry services. (PB-NOFAULT-01)
- Check for silent services or gaps in the telemetry. (PB-NOFAULT-01)

prose: template

---

verdict_hash: `37c10d1b80af0da7bf34bbf560bdc1cbdec358ae980c59320206c750ff813687`  
card_hash: `7d31b11ec0d1de5e4331483a768e0c36b7389d3e786bda066bab6f10f4c6225e`  
replay: `uv run veyltrace replay <run dir>/receipt.json`
