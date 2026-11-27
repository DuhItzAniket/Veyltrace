# Observe cuts for v1.0: the Anomara TSFM plugin and the VeylLab adapter move to v1.1

- **Status:** Accepted (lead decision of 23 Nov 2026, relayed to the Observe lane; recorded here by the lane owner)
- **Date:** 2026-11-24
- **Author:** Annapurna S (AS)
- **Deciders:** the lead
- **Consulted:** Observe (Annapurna), Explain (Lakshanaa, for the VeylLab captures)
- **Issue / CCR:** #35 (O-10), #24 (O-07). No contract change.
- **Supersedes:** none · **Superseded by:** none

## Context

[07 §1.1](../07-roadmap.md) orders the cuts for a slipping milestone and asks for one ADR line per cut, so the paper reports it. Two Observe items are cut for v1.0:

- **O-10, the Anomara TSFM plugin** (#35), is cut item 1, "cut first". It was planned as an off-by-default detector for an ablation arm on RE2-OB. It is not built: `veyltrace_anomara.api` writes the detectors of 03 §4.1 and notes that `tsfm` is not built yet.
- **The `veyllab` adapter half of O-07** (#24). The two VeylLab experiments are already "not run" for R-16 ([ADR 20261121-ak-r16-cut-list](20261121-ak-r16-cut-list.md), addendum of 22 Nov): the lab has 8 kept captures against a target of at least 120, and X-14 moves to v1.1 (cut item 6).

The engine-freeze tag `results-code-v1` is cut, and compute for R-16 stops on Sat 28 Nov.

## Decision

1. **O-10 is cut from v1.0 and moves to v1.1.** #35 is closed as "not planned". No experiment YAML names a TSFM arm, so no cell of the 04 §6 matrix changes and `bench/results/not_run.yaml` needs no entry.
2. **The `veyllab` adapter moves to v1.1**, with X-14. The other half of O-07, the OTLP → canonical converter and the `otlp_live` adapter, stays in v1.0: the live demo on Online Boutique (X-10) depends on it and is on the never-cut list.

## Consequences

- **Positive:** the Observe lane's remaining v1.0 work is the converter for the live demo, the performance measurement (O-11), the docs (O-12) and the reproduction check (L-06).
- **Negative / costs:** v1.0 has no foundation-model detector to compare the statistical detectors against, so the paper makes no claim about one. The lab data is read by no adapter in v1.0, so no result uses real deploy, config or flag events; the change channel is evaluated on RCAEval-C's synthetic changes only (04 §11 already names this limit).
- **Follow-ups (v1.1):** O-10 as specified in [03-anomara](../engines/03-anomara.md); the `veyllab` adapter once X-11 has enough validated captures.

## Evidence

- [07 §1.1](../07-roadmap.md) cut list, items 1 and 6, and the never-cut line.
- [ADR 20261121-ak-r16-cut-list](20261121-ak-r16-cut-list.md), addendum of 22 Nov (the VeylLab experiments).
- #45 (R-16 plan): the Observe and Explain replies of 21 and 22 Nov on rows B10 and B11.
