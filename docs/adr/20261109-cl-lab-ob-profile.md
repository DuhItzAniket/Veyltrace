# The `ob` lab profile records image digests per capture and copies the spool out with `docker cp`

- **Status:** Proposed
- **Date:** 2026-11-09
- **Author:** C Lakshanaa (cl)
- **Deciders:** the lead
- **Consulted:** Explain lane
- **Issue / CCR:** #19
- **Supersedes:** none · **Superseded by:** none

## Context

X-02 builds the `ob` profile of the laptop fault lab ([05 §3](../05-fault-lab-and-dataset.md#3-profile-ob-online-boutique-on-kind)): Online Boutique v0.10.7 on kind, OTel Collector contrib v0.164.0 and Chaos Mesh 2.8.7, with one CPU (F01) and one delay (F04) fault captured as raw OTLP files plus answer keys. 05 §2.3 asks for an ADR that pins versions. Two points of the spec sketch could not be settled from the research notes:

1. **Digests.** 05 §2.3 says kind, `kindest/node`, kubectl, Helm and images are "pinned by digest at X-02", but no digest appears in the notes, and this machine had no cluster running when the profile was written. Writing digests from memory would be inventing values (AGENTS §4.8).
2. **Spool path.** 05 §3.1 mounts a host folder into the kind node with `extraMounts` and flags its path form on Docker Desktop for Windows as unverified (05 OQ-6).

## Decision drivers

- Every capture must say exactly which versions produced it (05 §11 `injection_json`, 05 §12 release).
- No invented values.
- Captures must work on all three Windows laptops without per-laptop path tweaks.

## Considered options

1. **Record digests per capture; pin by copying them into `lab/ob/pins.yaml` after the first live run.**
2. **Block X-02 until someone looks up every digest by hand.**
3. **Spool on a host folder via `extraMounts`** (the 05 §3.1 sketch).
4. **Spool inside the kind node and `docker cp` it out at export.**

## Decision

We choose **1 and 4**.

- `lab/ob/pins.yaml` holds the sourced versions of 05 §2.3 (OB v0.10.7, Chaos Mesh chart 2.8.7, `otel/opentelemetry-collector-contrib:0.164.0`) with `digest: null`. Each capture's `orchestrator.json` records `kind version`, `kubectl version`, `helm version`, the Docker server version and the image plus `imageID` (digest) of every running container. After the first live run those digests are copied into `pins.yaml`, and the kind node image into `lab/ob/kind.yaml`.
- The OB release manifest is vendored with `uv run python lab/up.py --vendor` into `lab/ob/upstream/` together with `SHA256SUMS`; `lab/up.py --profile ob` refuses to start when the hash does not match.
- The Collector writes to `hostPath /veyllab/spool` inside the kind node container. `lab/vlab/capture.py` turns capture on by scaling the Collector to zero, emptying the spool and scaling back to one; it turns capture off by scaling to zero again (the file exporters flush on shutdown), then runs `docker cp veyllab-control-plane:/veyllab/spool/. lab/captures/<capture_id>/otlp/`. No `extraMounts`, so the path-form question of OQ-6 does not arise.
- Every `kubectl` and `helm` call names `--context kind-veyllab`, so the lab cannot act on another cluster.
- The Collector runs `k8sattributes` before `filter/scrub` (05 §3.3 lists them the other way round), so OTLP data already carries its namespace when the chaos-mesh rule runs.

### Verified on the first live run (2026-11-09, Windows 11, Docker Desktop 4.95, WSL kernel 6.18, 40 GB RAM)

- kind v0.33.0 single node; netem loads inside the node (05 §2.2 check passes), so F04 runs on this laptop.
- Chaos Mesh 2.8.7 StressChaos injects inside kind (`AllInjected=True`); the stressed `productcatalogservice` sat at its 200m CPU limit. One controller replica instead of the chart's three (laptop budget); first-start image pulls from ghcr.io took > 5 min, so the Helm wait is 15 min.
- The OB manifest is a kustomize base (`lab/ob/upstream/kustomization.yaml`): kustomize refuses a single file outside the overlay.
- otelcol-contrib 0.164.0 deprecates `k8sattributes`, `filelog`, `kubeletstats` and `k8sobjects` in favour of `k8s_attributes`, `file_log`, `kubelet_stats` and `k8s_objects`; the lab uses the new names. `filter/scrub` uses `error_mode: silent`, because its `body["object"]` rules cannot evaluate on plain-text pod logs and `ignore` logs a warning per record.
- Spans arrived from frontend, checkoutservice, currencyservice, emailservice, productcatalogservice and paymentservice within minutes; no spooled record mentioned chaos after the Collector scrub (packaging re-checks, X-06).
- Digests from that run are now pinned: `kindest/node:v1.37.0@sha256:a1ed56cf…` (identical to kind v0.33.0's published default), the Collector image, and all 12 OB images through the overlay's `images:` list.
- Windows Modern Standby froze the first attempt for ~20 min mid-fault. `Runner.sleep` now waits in 5 s wall-clock steps and raises `HostSuspended` on a jump above 30 s (a priori); the case is logged `host_suspended`, its fault is removed and no answer key is written. Campaigns should run on mains power with the screen-off timeout disabled.

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| 2: look up digests by hand first | pinned from day one | blocks the M1 task; a hand-copied digest is not verified against what actually ran | per-capture recording is verifiable |
| 3: `extraMounts` host folder | no copy step | path form on Docker Desktop for Windows unverified (OQ-6); differs per laptop | `docker cp` works on every Docker host |

## Consequences

- **Positive:** every capture carries the exact versions and digests that produced it; capture boundaries are explicit Collector restarts, so warm-up data never leaks into a capture.
- **Negative / costs:** about 30 s of Collector restart per case (*estimate*); data in flight during the restart is lost, which only affects the first seconds of the baseline.
- **Follow-ups:** first live run of `lab/plans/x02-smoke.yaml`; copy digests into `pins.yaml` and `kind.yaml`; check the OB tracing variables, `kubeletstats` RBAC, `k8sobjects` on kind and the chaos-event filter expressions on real telemetry (05 OQ-6); the 05 §8.1 p95/error baseline check and the §8.2 validation rule (X-11); decoys, packager and `otel` profile (X-06).

## Confirmation

`uv run python scripts/check.py --package lab` passes (dry-run tests prove no command or file is touched), and the first live run produces `lab/captures/<id>/orchestrator.json` with a digest for every image and two answer keys under `lab/captures/answer_keys/`.

## Evidence

- Versions and components: [05 §2.3, §3](../05-fault-lab-and-dataset.md#23-pinned-versions-recorded-in-an-adr-at-x-02), sourced there to `research_notes/` (benchmarks_and_testbed §Q3, stack_and_market §A1, §A4).
