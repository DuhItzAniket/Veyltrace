# NO_FAULT · no fault detected in the incident window

**NO_FAULT** · confidence: none · candidate set size: 0 · margin: 0.00

## Summary

- No anomaly above threshold was found at the entry service or inside any service.
- The candidate set is empty and no root cause is named.

## Candidate set

- empty

## Evidence

| Atom | Evidence | Value | Unit |
|---|---|---|---|
| Ec3ee13da9f | checkout self_time anomaly (incident) | 1.03 | z |
| E69dec80d43 | checkout silence (incident) | 0 |  |
| E58335ef082 | frontend mem anomaly (incident) | 0.707 | z |
| E2a9591ce1a | frontend silence (incident) | 0 |  |
| E89d6468c5f | payment mem anomaly (incident) | 1.09 | z |
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

verdict_hash: `4b44fc6afa1181c2f3e0015a299f8390ab91a723feb1580a73be8d0dd7517fa2`  
card_hash: `9594e5865069a33290211cb8806d10436cf8ff9b58ee73f832f0bdbf71f4c2a0`  
replay: `uv run veyltrace replay <run dir>/receipt.json`
