# NO_FAULT · no fault detected in the incident window

**NO_FAULT** · confidence: none · candidate set size: 0 · margin: 0.02

## Summary

- No anomaly above threshold was found at the entry service or inside any service.
- The candidate set is empty and no root cause is named.

## Candidate set

- empty

## Evidence

| Atom | Evidence | Value | Unit |
|---|---|---|---|
| Ec7616db24a | catalog logs anomaly (incident) | 0 | z |
| E7b0771b7a9 | catalog silence (incident) | 0 |  |
| E11349da276 | checkout logs anomaly (incident) | 0 | z |
| E69dec80d43 | checkout silence (incident) | 0 |  |
| E652ceb691c | frontend logs anomaly (incident) | 0 | z |
| E2a9591ce1a | frontend silence (incident) | 0 |  |

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

verdict_hash: `dc640b8724e59f0b0b43146cbb82fa19d7724961429c0edf68ac2c00a2b14843`  
card_hash: `17449708a01ebcbca25b3bbd720a9f5c05e65eedc3b0860d1a650168e1a31a21`  
replay: `uv run veyltrace replay <run dir>/receipt.json`
