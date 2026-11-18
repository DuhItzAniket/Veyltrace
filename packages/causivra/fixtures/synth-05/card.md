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
| E847fffbec6 | catalog self_time anomaly (incident) | 1.05 | z |
| E7b0771b7a9 | catalog silence (incident) | 0 |  |
| Ec3ee13da9f | checkout self_time anomaly (incident) | 1.03 | z |
| E69dec80d43 | checkout silence (incident) | 0 |  |
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

verdict_hash: `fbf9ef9f1a434a8c8ea851bbbb65527517ca1b4924537f144c8545cb650c4953`  
card_hash: `1ab50aa0ef93dd87eb70e1b4fb3e7271868b7ccb50fa363d9ed19d5e0da05550`  
replay: `uv run veyltrace replay <run dir>/receipt.json`
