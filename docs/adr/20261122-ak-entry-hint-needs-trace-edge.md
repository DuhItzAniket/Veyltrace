# An entry hint counts only when the case's traces show it

- **Status:** Proposed (lead decision on #36, comment 7066702400; Accepted once the Observe owner approves the PR)
- **Date:** 2026-11-22
- **Author:** Aniket Kumar (AK), drafted by the lead's session from the #36 diagnosis
- **Deciders:** the lead
- **Consulted:** Observe (Annapurna) via #36
- **Issue / CCR:** #36 (O-11); blocks `results-code-v1` (#45). No contract change.
- **Supersedes:** none · **Superseded by:** none

## Context

The shared entry rule ([05 §3.3](../engines/05-causalith.md)) returns the configured system hint first (`entry.hints`, rule 1), whenever the hint names a known service. Anomara (`run()`, `detect_alert`) and Causalith call it, and Causalith's paths run from every node to these entries (05 §3.6). [05 §4](../engines/05-causalith.md) and §11 Q6 say the hint names "are checked on RE2 data at O-05 and change only by ADR".

That check fails on RE2-TT. The hint `tt: [ts-ui-dashboard]` is in `case_manifest.services` (from metrics and logs). It has **0 spans and appears in no `signal_cube.edges` pair** in `083d3e979f37` and `0899c071903d` (**measured**, #36 diagnosis). RCAEval does not trace the TT gateway. So no node can reach the entry, and `graph.paths` holds one row on `083d3e979f37`, the entry's own. Every RE2-TT cell would run without path evidence.

## Decision drivers

- The entry must be a node the case's call graph can reach, or the paths (02 §6.5) are empty.
- No tuning on RE2 test data ([04 §5.3](../04-evaluation-protocol.md)). The rule must rest on a priori architecture facts.
- OB and SS, where the hint works, must not change. SS has no traces at all.
- Anomara and Causalith must keep using one identical rule.

## Considered options

1. **(a) A hint counts only with a trace edge.** When the case has cross-service call pairs, keep the hinted services that appear in at least one pair (as caller or callee). If none remain, use rule 2 (call-pair roots).
2. **(b) Union the hint with the call-pair roots.**
3. **(c) Change the TT hint** to a traced service, by name.

## Decision

We choose **option (a)**, the lead's decision on #36. The rationale is a priori: a hint the traces never show is no entry a call path can reach.

Changes:

- `veyltrace_causalith.entry.entry_services` rule 1. With at least one call pair `a ≠ b`, a hinted service must occur in a pair.
- **Without any cross-service call pair** (a logs-only case such as RE2-SS, or a case whose only pairs are self pairs), rule 1 applies unchanged. The lead's wording, "only if it has at least one trace edge in the case", read literally, would drop the SS hint `front-end` and leave SS with no entry. That contradicts the rationale (an untraced gateway), so the check applies only to cases that have traces. *The drafting session made this reading; the Observe owner and the lead confirm it on the PR.*
- No config key, no contract change, and the 05 §3.3 hint table is unchanged.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| (b) union | keeps the hint everywhere | the untraced gateway stays an entry no path reaches; a hint and roots mixed in one set | does not fix the empty paths for the hinted node, and muddles the rule |
| (c) rename the TT hint | one-line config change | picks a service by looking at RE2 data, close to tuning on test data (04 §5.3); breaks if RCAEval traces change | not a priori |

## Consequences

**Positive:**

- `083d3e979f37` gets 6 entries: the trace roots `ts-admin-basic-info-service`, `ts-admin-travel-service`, `ts-consign-service`, `ts-inside-payment-service`, `ts-preserve-other-service` and `ts-preserve-service`.
- `graph.paths` on that case goes from 1 row to 56 rows, and 26 nodes now have a path (**measured**).
- RE2-OB and RE2-SS `graph.*` are byte-identical (**measured** on `011f3b9bc355` and `01781f30fe20`).
- No synth golden changes: every synth fixture uses system `other`, and no hint applies there.

**Negative / costs:**

- On TT, the entry set now comes from rule 2, so it depends on which services the traces show as roots in each case.
- `onsets.entry_services`, `graph.nodes.is_entry`, `graph.paths` and the verdict change on RE2-TT runs.
- `anomalies`, `alert`, `signal_cube.*`, `graph.edges` and the slate are unchanged on `083d3e979f37` (**measured**).

**Follow-ups:**

- The Observe owner reviews and accepts or changes the rule (#36).
- This lands before `results-code-v1` (#45).

## Confirmation

The tests are in `packages/causalith/tests/test_entry.py`:

- `test_a_hint_without_a_trace_edge_falls_back_to_call_pairs`: the TT shape, a hint with no spans.
- `test_a_traced_hint_still_wins_and_a_logs_only_case_keeps_its_hint`: a traced hint, no traces, and self pairs only.

The cross-engine test asserts `onsets.entry_services == is_entry` on every fixture (05 §3.3). The R-11 rerun shows non-empty TT paths.

## Evidence

- #36 diagnosis (lead's session, 2026-11-21): TT span services, `signal_cube.edges` pairs and the before/after `graph.paths` counts.
- [rcaeval_facts §Dataset layout](../../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/rcaeval_facts.md#dataset-layout) (the TT case folder names `ts-ui-dashboard_istio-latency-90`, a mesh-level, not a span-level, entry).
