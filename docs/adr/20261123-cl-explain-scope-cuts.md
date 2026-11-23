# The MCP server (X-12) and lab collection beyond the live demo (X-11) move to v1.1

- **Status:** Accepted (lead scope note to Explain, 2026-11-23)
- **Date:** 2026-11-23
- **Author:** C Lakshanaa (CL)
- **Deciders:** the lead
- **Consulted:** Explain; Observe gets the same note for O-07 (#24)
- **Issue / CCR:** #49 (X-12), #44 (X-11)
- **Supersedes:** none · **Superseded by:** none

## Context

The engine freeze tag `results-code-v1` is cut, and R-16 compute stops on Sat 28 Nov, 18:00. Five working days are left before M4. Explain has the most open tasks. [07 §1.1](../07-roadmap.md) says to cut in order and to give each cut an ADR line, so the paper reports it honestly. Items 3 (Relentra `investigate`) and 6 (VeylLab release, X-14) were cut on 21–22 Nov in [20261121-ak-r16-cut-list](20261121-ak-r16-cut-list.md). The VeylLab experiments are "not run" in `bench/results/not_run.yaml`.

## Decision drivers

- The never-cut list of 07 §1.1 comes first: the console verdict view (X-05) and the live demo on Online Boutique (X-10).
- No paper number depends on either task.

## Considered options

1. **Cut both as below.**
2. **Keep X-12:** about 1 person-day (*estimate*, 07), taken from the never-cut items.
3. **Keep collecting toward 120 captures:** no v1.0 experiment would read them.

## Decision

We choose **option 1**.

| Task | Decision | Basis |
|---|---|---|
| X-12 MCP server (#49) | not built in v1.0; moves to v1.1; #49 is closed as "not planned" | 07 §1.1 cut item 4 |
| X-11 lab collection (#44) | only the captures the X-10 live demo needs; the ≥ 120 target moves to v1.1 with X-14 | the VeylLab experiments are "not run" ([addendum of 22 Nov](20261121-ak-r16-cut-list.md#addendum-22-nov-2026-the-two-veyllab-experiments)) |

No code, config or contract changes.

## Consequences

- **Positive:** the remaining Explain days go to X-09, X-05 and X-10.
- **Negative / costs:** no agent tool interface in v1.0. Agents use the CLI and the gateway API (06). There is no VeylLab dataset beyond the demo captures.
- **Follow-ups:** in v1.1, reopen X-12 and finish X-11 toward X-14.

## Confirmation

#49 is closed as "not planned" with a link to this ADR, and #44's remaining scope names only the demo captures.

## Evidence

- [07 §1.1](../07-roadmap.md) cut list and never-cut list; the X-11, X-12 and X-14 rows of 07.
- [20261121-ak-r16-cut-list](20261121-ak-r16-cut-list.md) and its 22 Nov addendum.
