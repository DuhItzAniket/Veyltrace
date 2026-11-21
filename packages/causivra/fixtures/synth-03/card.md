# CONFIRMED · payment · exception

**CONFIRMED** · confidence: high · candidate set size: 1 · margin: 0.75

## Summary

- payment is the only member of the candidate set and passed every mandatory trial. (cites: Ed5c1d9ce83, E30ea86ddc2, Eac14b6a0ea, Ee4ddfcab63, Ee881a7d380, E23c811e2ae)
- Its strongest internal signal was payment logs anomaly (incident) at 8 z. (cites: Ed5c1d9ce83)
- Confidence is high; its verified score leads checkout by a relative margin of 0.75. (cites: Ed5c1d9ce83, E30ea86ddc2, Eac14b6a0ea, Ee4ddfcab63, Ee881a7d380, E23c811e2ae)

## Candidate set

- payment

## Evidence

| Atom | Evidence | Value | Unit |
|---|---|---|---|
| Eb2a1231709 | cart mem anomaly (incident) | 0.794 | z |
| E9609f44d49 | cart silence (incident) | 0 |  |
| E11349da276 | checkout logs anomaly (incident) | 5 | z |
| E69dec80d43 | checkout silence (incident) | 0 |  |
| E58335ef082 | frontend mem anomaly (incident) | 0.653 | z |
| E2a9591ce1a | frontend silence (incident) | 0 |  |
| Ed5c1d9ce83 | payment logs anomaly (incident) | 8 | z |
| E30ea86ddc2 | payment onset precedence over self (onset) | 0 | ms |
| Eac14b6a0ea | payment onset precedence over dependents (onset) | 1 |  |
| Ee4ddfcab63 | payment propagation to entry (incident) | 1 |  |
| Ee881a7d380 | payment propagation to path (incident) | 1 |  |
| E23c811e2ae | payment silence (incident) | 0 |  |

## Timeline

- 00:18:00 UTC — cart-1 deploy change (cites: Ea59a066a7a)
- 00:22:00 UTC — alert (oracle)
- 00:22:00 UTC — incident onset
- 00:22:00 UTC — payment external onset (cites: E30ea86ddc2, Ecd2417b504)
- 00:22:00 UTC — payment internal onset (cites: E30ea86ddc2, Ecd2417b504)

## Path

payment → checkout → frontend

## Why not

- **checkout**: checkout showed no internal anomaly that its callees do not explain (failed T1, origin). (cites: E11349da276, E69dec80d43, Ed5c1d9ce83)
- **frontend**: frontend showed no internal anomaly that its callees do not explain (failed T1, origin). (cites: E2a9591ce1a, E58335ef082)
- **cart**: cart showed no internal anomaly that its callees do not explain (failed T1, origin). (cites: E9609f44d49, Eb2a1231709)

## Asks

- none

## Next steps

- Inspect exception records and stack traces on payment. (PB-EXC-01)
- Map the exceptions to the code path in payment. (PB-EXC-01)
- Check the latest code deploy of payment. (PB-EXC-01)

prose: template

---

verdict_hash: `b0b03436fcbd70dec5060e0c3c8e0eb716f3f2a9abe020d55f4e11f3098beee4`  
card_hash: `bda36fbcd93b3e8d8c54e949c2cb0047c3003e01a4160dcb24ae1a71f3b92e0a`  
replay: `uv run veyltrace replay <run dir>/receipt.json`
