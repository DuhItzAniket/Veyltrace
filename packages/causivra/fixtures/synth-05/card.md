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

verdict_hash: `b18b910875260a0eb54cf0593ce35743ab32273491408cf3ccc93b819743f591`  
card_hash: `3988352b4de9b3307d056a54d7d3566cfaa74ce5c926a5c081647a176cae7e13`  
replay: `uv run veyltrace replay <run dir>/receipt.json`
