# The lab catalog maps 05's fault table onto contract vocabularies, and the packager scrubs by content

- **Status:** Proposed
- **Date:** 2026-11-09
- **Author:** C Lakshanaa (cl)
- **Deciders:** the lead
- **Consulted:** Explain lane; Observe lane for the `events.jsonl` mapping (05 OQ-3)
- **Issue / CCR:** #31
- **Supersedes:** none · **Superseded by:** none

## Context

X-06 automates the 05 §6 fault catalog and adds the 05 §10 packager. Building them against the contracts and real captures from X-02 ([ADR 20261109-cl-lab-ob-profile](20261109-cl-lab-ob-profile.md)) surfaced five points that 05 leaves open or states differently from 03:

1. 05 §6 labels indicators with `family` names (`errors`, `net`); `answer_key.indicator` uses the 03 §1 `indicator` vocabulary, which has neither.
2. `AnswerKeyRow` requires every column, including `mode`, which 05 §11 does not list.
3. 05 §10 writes answer keys to `lab/captures/answer_keys/<dataset>.parquet`; the 03 registry and bench's loader use `${VEYLTRACE_DATA}/answer_keys/<dataset>.parquet`.
4. On the F04 capture, kube-apiserver and etcd logged `networkchaos.chaos-mesh.org` at injection time: the Collector's namespace and attribute rules do not catch it.
5. The k8sobjects watch replays nothing at start, so a Deployment's first record in a capture can already be the change; there is no earlier object to diff against.

## Decision drivers

- No invented fields or values (AGENTS §4.2); answer keys must validate against `AnswerKeyRow`.
- Bench must find the keys without any lab-specific path.
- Nothing packaged may reveal a fault (P7, 05 §11).

## Decision

- **Indicators:** `errors` → `error`; F05 loss → `error` (its expected signals are retries and errors). **Mode** by mechanism, the pairs the synth cases use: F01, F02 `resource`; F04, F05 `network`; F11 `change`; F13 `dependency`; F06–F08 null, because no `mode` value fits pod and container availability (open question below).
- **Answer keys** carry all 17 columns (null where unknown) and are merged into `${VEYLTRACE_DATA}/answer_keys/<dataset>.parquet` through bench's `write_answer_keys`; 05 §10 is updated to match.
- **Content scrub:** besides the namespace, `service.name` and attribute rules, the packager drops every log record whose body matches the deny-list, then post-scans every packaged file; any hit removes the package and withholds its key. Tool artefacts are deny-listed too: Chaos Mesh pod-failure swaps the container image for `gcr.io/google-containers/pause`, and kubelet logs pulling it, which no real outage does (seen on the live F08 run); such events and log records are dropped like the apiserver lines. A container kill (F07) shows as the container being re-created (`Created`, `Pulled`, `Started`), not as `Killing`, because Chaos Mesh signals the container directly; that is kept as is. Deny-list tokens match at word starts (`\bfault` matches `faultTolerance`, not `default`); no false positive appeared on two real captures.
- **Change records:** a Deployment record is a change when `metadata.generation > status.observedGeneration`. Its kind comes from the fields of the latest `Update` entry in `managedFields`: `f:image` → `deploy`, `restartedAt` → `restart`, otherwise `config`. k8s Events in the app namespace from the capture window become `k8s_event` (`restart` for `Killing`, `BackOff`, `OOMKilling`; a failed probe, `Unhealthy`, stays `k8s_event`). Records from `veyllab-obs` (the Collector's own capture restarts) are lab machinery and are dropped.
- **Catalog:** F01, F02, F04–F08, F11, F13. L2 kills apply one PodChaos at `t_inject` and repeat it through a Chaos Mesh `Schedule` (`@every 120s`), because a Schedule fires first one period after creation (measured on the live run: exactly 120 s). F11 cuts the CPU limit read from the vendored manifest and restores exactly that value. F09 is deferred: HTTPChaos has no request percentage. Reset re-applies the overlay, which restores config, images and the load profile (10 or 30 users per plan entry).

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Add `net` / `errors` to `indicator` | literal 05 table | contract change after M1 freeze; rankers never emit them | mapping is lossless for scoring |
| Keep keys under `lab/captures/` | follows 05 text | bench would need a lab-only path | the registry path already exists |
| Drop kube-system logs entirely | simplest | loses real control-plane signal | content scrub keeps all but leaking records |
| Diff Deployment objects | exact field diff | no prior object in a watch | generation + managedFields needs no history |

## Consequences

- **Positive:** keys load with bench's loader unchanged; packaged captures passed the deny-list on real data.
- **Negative / costs:** F06–F08 keys have `mode = null`; a scorer that compares `mode` must treat null as "any".
- **Follow-ups:** CCR or lead decision on a `mode` for availability faults; confirm the `events.jsonl` mapping with Observe at O-07; F09 via flags on the `otel` profile; F03, F12, F14–F16, decoys and the `otel` profile.

## Confirmation

`uv run python scripts/check.py --package lab` (planted-leak, change-record and contract-model tests) and the X-06 live run: each new fault type captured once, packaged, and its key loaded by `veyltrace_bench.answer_keys.load_answer_keys`.

## Evidence

- [05 §6, §7, §10, §11](../05-fault-lab-and-dataset.md#6-fault-catalog); [03 §1, §2.5, §13.1](../03-contracts.md#131-answer_key--key-case_id); X-02 captures (kube-apiserver line `quota admission added evaluator for: networkchaos.chaos-mesh.org`).
