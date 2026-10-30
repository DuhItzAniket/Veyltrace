# 05 · Fault lab and the VeylLab dataset

> Status: v0.1-draft · Lane: Explain · Master: [02 §8](02-architecture.md#8-technology-stack-pinned-at-m0-recorded-in-adrs) (Lab row), [§10](02-architecture.md#10-deployment-shapes), [§6.1](02-architecture.md#61-infralume--ingest), [P7](02-architecture.md#2-design-principles-binding) · Contracts: [03 §2](03-contracts.md#2-infralume-outputs), [§13.1](03-contracts.md#131-answer_key--key-case_id) · Roadmap: X-02, X-06, X-11, X-14 · Last updated: 2026-10-30

---

## 1. Purpose and scope

The lab (`lab/`) is a fault-injection testbed that runs on one 16 GB Windows laptop. It has two jobs:

1. **Live demo**: a real system with real faults, feeding the gateway's live mode ([06](06-gateway-and-console.md)).
2. **VeylLab dataset**: labelled incident captures with published injection parameters, validated user impact, no-fault controls and decoy changes, fixing the flaws reviewers now cite in RCAEval-style data: unpublished `tc`/`stress-ng` parameters, non-independent repetitions, missing telemetry and answers encoded in folder names ([benchmarks_and_testbed §Q5][bt-q5]).

| System | Profile | Status | Why |
|---|---|---|---|
| Online Boutique v0.10.7 on kind + Chaos Mesh 2.8.7 | `ob` | primary; the live demo on it is never cut ([07 §1.1](07-roadmap.md#11-cut-list-if-a-milestone-slips-by--1-day)) | same system as RCAEval-OB and Nezha-OB (transfer experiments); requests only 1.57 CPU / 1,368 MiB |
| OpenTelemetry Demo 3.1.0 on Docker Compose | `otel` | alternate; cut 5th | built-in flag faults; polyglot; Kafka |

The two profiles are **never run at the same time** ([02 §10](02-architecture.md#10-deployment-shapes)). Train Ticket does not fit: its guide asks for at least 24 GB of memory ([benchmarks_and_testbed §Q3][bt-q3]).

Out of scope here: the OTLP → canonical converter (Infralume, Observe lane, task O-07; the lab calls it), scoring (bench, Reason lane).

## 2. Laptop setup

### 2.1 Assumptions

16 GB RAM, Windows 11, Docker Desktop with the WSL2 backend, no GPU assumed, no cloud. Lab code is Python 3.12 scripts in `lab/` that drive `kind`, `kubectl`, `helm` and `docker` as subprocesses (no Kubernetes client library). `lab/` is not a uv workspace member ([08 §3.1](08-collaboration-and-git.md#31-hot-spots-removed-by-design)); scripts that need workspace packages (the packager) run from the repo root with `uv run python lab/<script>.py` after `uv sync --all-packages`.

### 2.2 WSL2 (`%UserProfile%\.wslconfig`)

WSL2 defaults to 50% of Windows RAM (8 GB here), swap 25% of RAM and all logical CPUs ([benchmarks_and_testbed §Q3][bt-q3]). The default is too tight once telemetry is on.

```ini
[wsl2]
memory=12GB                 # 11–12 GB (estimate from the notes); 11GB on laptops that also run Ollama on Windows
swap=4GB
processors=<logical CPUs minus 2>   # a priori: keep 2 for Windows
# load sch_netem at boot: key name and section per MS Learn wsl-config (notes: loadKernelModules); verify at L-01

[experimental]
autoMemoryReclaim=gradual
```

Apply with `wsl --shutdown`, then restart Docker Desktop. **Netem check (L-01, required before any network fault):** current WSL kernels build `CONFIG_NET_SCH_NETEM=m` ([benchmarks_and_testbed §Q3][bt-q3]), but loading it under Docker Desktop is unverified on these laptops. Inside the kind node: `docker exec veyllab-control-plane sh -c "modprobe sch_netem; tc qdisc add dev lo root netem delay 1ms && tc qdisc del dev lo root"`. Record the result in `docs/team/<initials>.md`. If it fails, network faults (F04, F05, F13-delay) are disabled on that laptop.

### 2.3 Pinned versions (recorded in an ADR at X-02)

| Component | Version | Source / note |
|---|---|---|
| Online Boutique | v0.10.7 (2026-09-18), Apache-2.0 | [bt §Q3][bt-q3] |
| OpenTelemetry Demo | 3.1.0 (2026-09-18) | [bt §Q3][bt-q3] |
| Chaos Mesh | 2.8.7 (2026-10-28), Apache-2.0, Helm install | [bt §Q3][bt-q3] |
| OTel Collector | contrib v0.164.0 (2026-10-26) | [stack_and_market §A1][sm-a1] |
| Locust | as bundled by each demo (Locust 2.47.0 is current, MIT) | [bt §Q4][bt-q4] |
| kind, `kindest/node`, kubectl, Helm | pinned by digest at X-02 | not covered by the notes |

## 3. Profile `ob`: Online Boutique on kind

### 3.1 Cluster

```yaml
# lab/ob/kind.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: veyllab
nodes:
  - role: control-plane
    image: kindest/node:<version>@sha256:<digest>      # pinned at X-02
    extraMounts:
      - hostPath: <spool dir visible to Docker Desktop>  # verify path form at X-02
        containerPath: /veyllab/spool
    extraPortMappings:
      - containerPort: 30080          # frontend NodePort
        hostPort: 8080
        listenAddress: "127.0.0.1"    # local only
```

One node keeps memory down; k3d is an equivalent fallback if kind misbehaves ([bt §Q3][bt-q3]).

### 3.2 Application

- The v0.10.7 release manifest is vendored in `lab/ob/upstream/kubernetes-manifests.yaml` with its SHA-256 and Apache-2.0 notice; a kustomize overlay `lab/ob/overlay/` changes only: `frontend-external` → NodePort 30080, load-generator settings, tracing settings, image digests.
- Resources from the manifest: 12 Deployments (10 services, `loadgenerator`, `redis-cart`); requests 1.57 CPU / 1,368 MiB; limits 2.7 CPU / 2,286 MiB ([bt §Q3][bt-q3]).
- **Load generator**: the bundled Locust `loadgenerator`, defaults `USERS=10`, `RATE=1` ([bt §Q4][bt-q4]); lab profiles use 10 (default) and 30 users. Keep ≥ 20% host CPU idle, because a saturated load generator inflates response times ([bt §Q4][bt-q4]).
- **Tracing**: OB services export OpenTelemetry traces when tracing is enabled through environment variables; the exact variables per service are not in the research notes and are verified against the v0.10.7 source at X-02. Services that do not emit spans still produce container metrics and logs.

### 3.3 Telemetry pipeline

One `otelcol-contrib` v0.164.0 Deployment with a single replica (the `k8sobjects` receiver must run once to avoid duplicates, [stack_and_market §A4][sm-a4]):

```yaml
# lab/ob/collector.yaml (sketch; component names verified at X-02)
receivers:
  otlp: {protocols: {grpc: {}, http: {}}}
  kubeletstats: {collection_interval: 15s}          # container cpu/mem/net/fs; RBAC on nodes/stats
  filelog: {include: [/var/log/pods/*/*/*.log]}     # pod logs via hostPath (single node)
  k8sobjects:
    objects:
      - {name: events, mode: watch}
      - {name: deployments, mode: watch}
processors:
  memory_limiter: {check_interval: 1s, limit_mib: 448, spike_limit_mib: 96}   # a priori, under a 512Mi limit
  filter/scrub: {}        # drop chaos-mesh namespace telemetry and chaos-mesh.org/* attributes (§11)
  k8sattributes: {}
  batch: {}
exporters:
  file/spool: {path: /veyllab/spool/otlp.jsonl, format: json, rotation: {}}
  otlphttp/gateway: {endpoint: "<gateway OTLP endpoint>"}   # live mode only
service:
  pipelines:
    traces:  {receivers: [otlp], processors: [memory_limiter, filter/scrub, k8sattributes, batch], exporters: [file/spool]}
    metrics: {receivers: [otlp, kubeletstats], processors: [memory_limiter, filter/scrub, k8sattributes, batch], exporters: [file/spool]}
    logs:    {receivers: [otlp, filelog, k8sobjects], processors: [memory_limiter, filter/scrub, k8sattributes, batch], exporters: [file/spool]}
```

Container limit 512 MiB, `GOMEMLIMIT=400MiB` (75–80% of the limit; `memory_limiter` refuses data above its threshold) ([stack_and_market §A1][sm-a1]). The capture path deliberately uses the file exporter instead of Prometheus, Jaeger or Loki: no extra databases, and every capture is a set of hashable files ([bt §Q4][bt-q4]). In live mode the same Collector also exports OTLP/HTTP to the gateway.

### 3.4 Chaos Mesh 2.8.7

```sh
helm repo add chaos-mesh https://charts.chaos-mesh.org
helm install chaos-mesh chaos-mesh/chaos-mesh -n chaos-mesh --create-namespace --version 2.8.7 \
  --set chaosDaemon.runtime=containerd \
  --set chaosDaemon.socketPath=/run/containerd/containerd.sock
```

Helm is the recommended install (the `install.sh` script is deprecated); the chart defaults to the Docker runtime, so kind needs the containerd values above; the chart sets no resource requests, so its footprint is unmeasured ([bt §Q3][bt-q3]). Disabling the dashboard to save memory is checked at X-02. Whether NetworkChaos and StressChaos work inside kind nested in Docker Desktop on Windows is unverified; X-02's acceptance (one CPU and one delay fault captured) is that check.

## 4. Profile `otel`: OpenTelemetry Demo 3.1.0 on Compose

- `lab/up.py --profile otel` refuses to start while the kind cluster `veyllab` exists, and `--profile ob` refuses while the demo's Compose project is up.
- Start with `make start-minimal` (drops Kafka, accounting and fraud detection; ≈ 3 GB) ([bt §Q3][bt-q3]). Disable Locust browser traffic (`LOCUST_BROWSER_TRAFFIC_ENABLED=false`); browser users are why the load generator has a 1.5 GB limit ([bt §Q4][bt-q4]).
- Capture: add the same `file/spool` exporter to the demo's Collector configuration (mechanism for extra Collector config verified at X-06).
- Faults: flagd flags (UI at `http://localhost:8080/feature`) for application faults; network faults through a helper container that joins the target's network namespace and runs `tc netem` (the Pumba `--tc-image` pattern; Pumba itself states it does not support Windows, [bt §Q3][bt-q3]); config regressions through `docker update` of CPU or memory limits. CPU hogs are not offered on this profile in v0.1.
- Note: 3.1.0's load generator is Locust while the live flag docs mention k6, a version discrepancy recorded in the notes ([bt §Q3][bt-q3]); pin to the 3.1.0 tag.

## 5. Memory budget

Values are sourced where a source is given; everything else is an *estimate* to be replaced by `docker stats` and `kubectl top` measurements at X-02.

| Component | `ob` profile | `otel` profile | Source |
|---|---|---|---|
| Windows + Docker Desktop VM overhead | 4–6 GB | 4–6 GB | *estimate* (unsourced in the notes) |
| kind node (control plane) | 1–2 GB | — | *estimate*, inferred from the K3s 2 GB server minimum |
| Application | 1,368 MiB requests / 2,286 MiB limits | ≈ 3 GB minimal mode; core limits 4,155 MB | [bt §Q3][bt-q3] |
| Load generator | inside the OB figures | 1,500 MB limit with browser traffic; less without (unmeasured) | [bt §Q4][bt-q4] |
| Collector | 512 MiB limit | 400 MB demo limit | [sm §A1][sm-a1], [bt §Q4][bt-q4] |
| Demo observability (Jaeger 1.2 GB, OpenSearch 1 GB, Prometheus 200 MB, Grafana 175 MB) | not run | 2,664 MB limits | [bt §Q3][bt-q3] |
| Chaos Mesh | unmeasured; *estimate* 0.3–0.6 GB | — | chart sets no resources |
| Gateway + DuckDB | 2–3 GB | 2–3 GB | *estimate* ([sm §A2][sm-a2]) |
| Qwen3.5-9B Q4 + KV cache | 6–7 GB | 6–7 GB | *estimate* ([report][rep-16gb]) |

Inside WSL2, the `ob` lab plus the gateway comes to roughly 5–8.5 GB (*estimate*), which fits a 12 GB VM. Adding the 9B model on the same laptop likely exceeds 16 GB, so the single-laptop demo runs with `--ai off` or the 4B model; an AI-on demo with the 9B model uses the split demo (model on a second laptop) or the cassette demo ([02 §10](02-architecture.md#10-deployment-shapes)). Collection campaigns run without any LLM.

## 6. Fault catalog

Parameters are a priori defaults with two severity levels; every value used is written into `injection_json` and published (the gap RCAEval left open, [bt §Q3][bt-q3]). Duration is the 10-minute fault window unless stated. `fault_class` uses 03's closed vocabulary; `indicator` uses 03's `family` vocabulary.

| ID | Fault | `fault_class` / `indicator` | Tool (`ob` / `otel`) | Parameters (L1 / L2) | Expected signals | To verify |
|---|---|---|---|---|---|---|
| F01 | CPU hog | `cpu` / `cpu` | StressChaos cpu / — | 2 workers at 80% / 100% load | target CPU and self-time up; caller latency up | — |
| F02 | Memory pressure / leak | `mem` / `mem` | StressChaos memory / flags `emailMemoryLeak`, `recommendationCacheFailure` | 256 MB / 512 MB (may hit the limit and OOM-kill) | memory up; restarts; latency up | — |
| F03 | Disk I/O latency | `disk` / `disk` | IOChaos latency on a mounted volume / — | 100 ms / 500 ms, all operations | I/O latency on `redis-cart`; cart latency up | OB volume targets other than `redis-cart` |
| F04 | Network delay | `delay` / `latency` | NetworkChaos delay / netns `tc netem delay` | 200 ms / 1,000 ms, jitter 10% | edge latency into the target; caller latency; edge gap | netem on WSL2 (§2.2) |
| F05 | Packet loss | `loss` / `net` | NetworkChaos loss / netem loss | 10% / 50% (AIOpsLab used 99%) | retries, errors, latency tails | netem |
| F06 | Pod kill | `availability` / `errors` | PodChaos pod-kill / `docker kill` with restart policy | one kill / kill every 120 s | brief silence, restart events, caller errors | — |
| F07 | Container restart | `availability` / `errors` | PodChaos container-kill / `docker restart` | one / every 120 s | restart events, brief silence | — |
| F08 | Pod failure | `availability` / `errors` | PodChaos pod-failure / `docker pause` | 200 s (AIOpsLab default) / 600 s | target silent; caller errors | — |
| F09 | HTTP / gRPC error injection | `error` / `errors` | HTTPChaos abort on the frontend HTTP server / flags `paymentFailure`, `cartFailure`, `adFailure`, `productCatalogFailure` | 10% / 50% abort; flag variants | error rate and error log templates at target and callers | HTTPChaos on OB's gRPC services is not expected to work |
| F10 | Exception via feature flag | `exception` / `errors` | — / flags whose effect is a thrown exception | flag on | exception records in logs or span events | per-flag mapping at X-06 (`error` if no exception record appears) |
| F11 | Config change regression | `config` / `cpu` or `errors` | `kubectl set resources` (CPU limit cut) or Service `targetPort` misconfiguration (AIOpsLab) / `docker update` limits | limit ÷ 4 / ÷ 10; wrong port | rollout event, then throttling and latency, or connection errors | — |
| F12 | Bad deploy (image change) | `error` or `delay` (by patch) / `errors` or `latency` | `kubectl set image` to a locally built OB variant (`kind load docker-image`) / Compose image swap | one-line patch adding errors / delay | deploy event, onset after rollout | stretch: image build effort |
| F13 | Dependency (DB/cache) slowdown | `dependency` / `latency` | NetworkChaos delay or StressChaos on `redis-cart` / flags `productCatalogLockContention`, `kafkaQueueProblems` | as F04 / F01 | callers of the datastore slow; datastore signals | — |
| F14 | No fault | — (`is_no_fault = true`) | none | — | none (control) | — |
| F15 | Multi-fault | per root | two of F01, F04, F05 on two different services, overlapping | L1 each | both patterns | — |
| F16 | Benign noise | — (added to another case) | 2-minute load spike (30 users) on the load generator | — | transient traffic change, no SLI breach expected | — |

**Targets.** OB: the 10 application services plus `redis-cart` (F03, F13); `loadgenerator` is never a target. Default grid (a priori, following the notes): 5 target services × 9 fault types (F01, F02, F04–F09, F11) × 3 repetitions per severity schedule, plus ≈ 10% no-fault cases, ≈ 10% noisy cases and up to 20 multi-fault cases ([bt §Q5][bt-q5]). The plan file fixes the order from a recorded seed.

## 7. Change events

**Real changes.** Every lab change is made through the platform so it shows up the way it would in production: `kubectl set image`, `set env`, `set resources`, `rollout restart`, `patch` (OB) and Compose image or limit updates (OTel). On `ob`, the Collector's `k8sobjects` receiver turns Deployment updates and Kubernetes events (OOMKilled, BackOff, Killing) into log records ([stack_and_market §A4][sm-a4]). The packager (§10) moves these records out of the logs and into the capture's `events.jsonl` in `telemetry.events` shape ([03 §2.5](03-contracts.md#25-telemetryevents--key-t_ns-entity-kind)): `kind` ∈ `deploy | config | restart | k8s_event`, `source_system = k8s`.

**Flag flips and Compose changes** have no Kubernetes object. The orchestrator emits one OTLP log record per change to the Collector, with resource attribute `service.name = veyllab-orchestrator` and attributes `veyllab.change.kind`, `veyllab.change.entity`, `veyllab.change.detail` (canonical JSON). Flag keys are replaced by `sha256(flag_key)[:8]` so the change channel works but the name does not reveal the fault (`paymentFailure` would). The packager writes them to `events.jsonl` as `kind = flag | config | deploy`, `source_system = manual` (OQ-3).

**Decoy changes.** With probability `p_decoy` = 0.5 (a priori) per case, the orchestrator makes one benign change on a random non-root service at a time drawn uniformly in [`t_inject` − 10 min, `t_inject` + 2 min]: `kubectl set env deploy/<svc> APP_REVISION=<n>` (a real rolling restart) or an image re-tag to the same digest. Names are neutral on purpose (no "decoy" token). Each decoy is listed in `answer_key.decoy_changes_json`. Real lab decoys complement bench's synthetic RCAEval-C decoys ([02 §6.4](02-architecture.md#64-causync--time-and-change)).

**Never a change event:** Chaos Mesh CRDs, chaos-daemon actions and their Kubernetes events. They are filtered in the Collector and again at packaging (§11).

## 8. Per-case protocol

### 8.1 Phases

The orchestrator `lab/campaign.py` executes a plan file `lab/plans/<plan>.yaml` (profile, seed, ordered entries of fault id, target, severity and decoy flag) and runs these phases for each entry; `--dry-run` prints every command without touching a cluster.

| Phase | Duration | Action |
|---|---|---|
| Reset | ≤ 5 min | delete leftover chaos CRDs; restore config, flags and images; `kubectl rollout restart` every app Deployment (every 10th case: delete and recreate the namespace); wait until all are ready, else mark `reset_failed` and skip |
| Warm-up | 3 min | traffic on; not part of the capture's baseline |
| Baseline check | ≈ 0.5 min | entry-service p95 latency ≤ 1.5 × the reference p95 measured at setup, and error rate ≤ 1% (a priori); on failure wait 2 min and retry once, else `baseline_unrecovered` |
| Baseline | 10 min | capture on; decoy change if scheduled |
| Fault | 10 min | inject at `t_inject`; record host clock ns and kind node clock ns (`docker exec veyllab-control-plane date +%s%N`) for skew |
| Recovery | 2 min | remove the fault; keep capturing |
| Export | ≈ 1 min | close spool files; write capture folder, manifest and answer key; run validation |

Total ≈ 25–30 min per case, matching the ≈ 25 min the notes assume ([bt §Q5][bt-q5]). The capture holds 10 minutes before the fault, while [02 §5.1](02-architecture.md#51-alert-time-and-windows) defines an 18-minute baseline window; core's alert step clamps the window to the available data and records `clamped = true` in `alert.json`, as it does for RCAEval cases with ~10–12 min before injection (OQ-4).

### 8.2 Validation rule

Keep a fault case only if user-facing impact is measurable, as the FSE'26 benchmark did (1,430 of 9,152 injections kept) ([bt §Q5][bt-q5]):

1. SLI series: entry-service (`frontend`) server-span p95 latency and error rate in 30 s buckets, computed by lab code from the capture's spans.
2. Baseline: median and MAD of each SLI over the baseline buckets, MAD floored at 1% of the median (a priori).
3. Keep if, within 5 minutes after `t_inject`, at least 2 consecutive buckets exceed `median + 5 × MAD` for either SLI (k = 5, N = 5 min: a priori).
4. No-fault cases are kept only if **no** such breach occurs (a clean control).
5. Every attempt, kept or not, is logged with its reason; acceptance rate is reported per fault type and system.

### 8.3 Throughput

At ≈ 25 min per case, one laptop makes ≈ 57 attempts per 24 h, or ≈ 24 per 10-hour night; three laptops for six nights give ≈ 430 attempts (computed in [bt §Q5][bt-q5]). Bench runs compete for the same machines, so collection may get only alternate nights (≈ 215 attempts). The acceptance rate on laptops is unknown (FSE'26's 15.6% came from a harder cluster setup and may not transfer). Reaching 120 validated cases needs ≈ 28% acceptance with six full nights, or ≈ 56% with alternate nights (*estimates*). Daily counts go into the standup (X-11).

## 9. Capture format

Rule: **no engine reads anything under `lab/`** ([02 §9](02-architecture.md#9-cross-cutting-rules), rule 3). Raw captures and answer keys therefore live under `lab/captures/` (git-ignored); only the packaged capture, which carries no answer, goes where Infralume can read it.

```
lab/captures/<capture_id>/                           raw capture (lab code only)
  otlp/traces-*.jsonl  otlp/metrics-*.jsonl  otlp/logs-*.jsonl   Collector file exporter, OTLP JSON
  orchestrator.json                                  versions, digests, host spec, clock skew, file hashes
lab/captures/answer_keys/<capture_id>.json           answer key (lab and bench only)
lab/captures/attempts.jsonl                          every attempt with its validation result

${VEYLTRACE_DATA}/veyllab/<dataset>/<capture_id>/    packaged capture, read by Infralume's `veyllab` adapter
  otlp/traces.jsonl  otlp/metrics.jsonl  otlp/logs.jsonl          scrubbed, protobuf-JSON mapping
  events.jsonl                                       change records in telemetry.events shape
  oracle_alert.json                                  {"t_alert_ns": <published injection time>}
  capture.json                                       {"capture_id", "system"}
```

This is the layout [engines/01 §`veyllab`](engines/01-infralume.md) expects, to be confirmed with the Observe lane at O-07. `capture_id` = 32 random hex chars (lab is not analysis code; randomness is fine) and carries no meaning; Infralume derives `case_id` = first 12 hex of SHA-256(`capture_id`) ([03 §1](03-contracts.md#1-how-contracts-work)). `oracle_alert.json` is the oracle-protocol hint ([02 §5.1](02-architecture.md#51-alert-time-and-windows)): Infralume passes it to core as `case_manifest.t_alert_hint_ns` with `hint_source = oracle`, exactly as RCAEval publishes its injection times; under the detected protocol Infralume leaves `t_alert_hint_ns` null with `hint_source = none` ([03 §2.1](03-contracts.md#21-case_manifestjson)), so the injection time never reaches engines. No other packaged file mentions a fault, target, flag or injection.

## 10. Packaging

`uv run python lab/package.py --dataset veyllab-ob --captures lab/captures/<id>…`:

1. Read the raw capture; drop records matched by the scrub rules (§11).
2. Move `k8sobjects` records and orchestrator change records from the logs into `events.jsonl` (§7); hash flag keys.
3. Write the scrubbed OTLP files, `oracle_alert.json` (from the orchestrator's `t_inject`) and `capture.json`.
4. Post-scan every packaged file for deny-listed tokens; any hit fails the run.
5. Append the answer key to `lab/captures/answer_keys/<dataset>.parquet` ([03 §13.1](03-contracts.md#131-answer_key--key-case_id)), keyed by `case_id`; bench loads it from there.

**Release build** (`lab/release.py`, X-14): for each validated case, convert the packaged capture to canonical `telemetry.{metrics,logs,spans,events}` Parquet with Infralume's converter library `veyltrace_infralume.otlp` (Observe lane, O-07; the lab does not parse OTLP itself); assemble `cases/<case_id>/telemetry/*.parquet`, `answer_keys/answer_key.parquet` (including `validated` and `sli_impact_json`), `metadata/lab_metadata.parquet` (host spec, versions, skew) and `MANIFEST.json` (every file with SHA-256) in a staging folder under `lab/captures/release/`.

## 11. Answer keys and leakage

**Answer keys** follow [03 §13.1](03-contracts.md#131-answer_key--key-case_id): `case_id`, `dataset`, `is_no_fault`, `root_service`, `root_component` (container), `fault_class`, `indicator`, `t_inject_ns`, `t_end_ns`, `injection_json` (`{fault_id, tool, tool_version, params, severity, seed}`), `extra_roots_json` (F15), `decoy_changes_json`, `validated` (the §8.2 rule passed) and `sli_impact_json` (measured entry-service SLI change). They are written by the orchestrator under `lab/captures/answer_keys/`, never into a capture folder, and read only by lab and bench code ([AGENTS.md §4.5](../AGENTS.md)).

**Leakage scrubbing (P7)**, applied in the Collector (`filter/scrub`), again at packaging, and a third time by Infralume at ingest:

| Source of leakage | Rule |
|---|---|
| OpenFeature evaluation attributes | drop `feature_flag.*` ([bt §Q3][bt-q3]; inference to verify on real telemetry) |
| flagd | drop all telemetry with `service.name` = flagd |
| Chaos Mesh | drop telemetry from the `chaos-mesh` namespace, events whose source is a chaos controller, labels and annotations `chaos-mesh.org/*` |
| Change records | flag keys hashed; neutral image tags (`veyllab/<svc>:r-<hash8>`) and env names |
| Tokens | deny-list post-scan: `chaos`, `stress-ng`, `netem`, `StressChaos`, `NetworkChaos`, `PodChaos`, `IOChaos`, `HTTPChaos`, `inject`, `fault`, `decoy`, every flag key in the OTel Demo flag list |
| Host identity | replace Windows user names, host names and LAN IPs with fixed placeholders |
| Folder names | opaque `capture_id`; `case_id` derived from it |

## 12. Dataset release plan

| Item | Plan |
|---|---|
| Name and ids | VeylLab; datasets `veyllab-ob`, `veyllab-otel` ([03 §2.1](03-contracts.md#21-case_manifestjson)) |
| Content | canonical Parquet (zstd) per case; answer keys and lab metadata in separate files; injector scripts, plan files, kind/Helm/Compose files and image digests; per-case outputs of every baseline (none of 23 audited RCA papers released per-case outputs, [bt §Q2][bt-q2]) |
| Licence | data CC BY 4.0; code Apache-2.0 (the repo licence) |
| Metadata | Croissant JSON-LD with the mandatory Responsible-AI fields (NeurIPS 2026 E&D flags submissions without them) and a datasheet that states laptop threats: host contention, Docker Desktop VM, single-node kind, clock skew ([bt §Q2][bt-q2]) |
| Hosting | Zenodo DOI (artifact) plus a Hugging Face mirror |
| Size | ≈ 10–20 MB per case, so ≈ 1.2–2.4 GB for 120 cases (*estimate* from RCAEval RE2 per-case sizes, [bt §Q5][bt-q5]) |
| Targets | v1.0: ≥ 120 validated cases (02 §12 default), mainly `ob`; ships in v1.0 only if reached, else v1.1 (X-14, [07 §1.1](07-roadmap.md#11-cut-list-if-a-milestone-slips-by--1-day)). Later: ≈ 300 cases, the threshold for a separate dataset submission ([07 §8](07-roadmap.md#8-after-the-month)) |
| Statistics note | with ≈ 30% discordant pairs, ≈ 90 cases detect ≈ 14-point differences and ≈ 270 detect ≈ 7 points ([bt §Q5][bt-q5]) |

**Licences of third-party software** (verify each LICENSE file at the pinned tag before release):

| Software | Licence | Status |
|---|---|---|
| Online Boutique v0.10.7 | Apache-2.0 | stated in the notes (GitHub API) |
| OpenTelemetry Demo 3.1.0 | not stated in the notes | **unverified**; check before release |
| Chaos Mesh 2.8.7 | Apache-2.0 | stated in the notes |
| Locust | MIT | stated in the notes |
| OTel Collector contrib | not stated in the notes | **unverified** |
| k6 | AGPL-3.0 | not used by the lab |

**Ethics.** Traffic is synthetic; no real users are involved. Telemetry contains demo product names and generated orders only. The release redistributes recordings and our own scripts; vendored manifests keep their licence headers and a NOTICE names Online Boutique and the OpenTelemetry Demo as the systems under test.

## 13. Lab tests

- Plan generator: same seed → identical plan; grid balance per (service, fault).
- `lab/campaign.py --dry-run`: prints every command, touches no cluster.
- Packager on a tiny synthetic OTLP capture committed under `lab/tests/fixtures/` (synthetic data only).
- Leak scan: planted tokens (`feature_flag.key`, a flag name, `chaos-mesh.org/` annotation) must fail packaging.
- Answer keys: test that no answer-key file is ever written under a capture or case folder.
- Validation rule: unit tests with synthetic SLI series (breach, no breach, no-fault control).

## 14. Tasks and milestones

| ID | Scope | Milestone |
|---|---|---|
| L-01 | `.wslconfig`, netem check, `docs/team/<initials>.md` | M0, 3 Nov |
| X-02 | `ob` profile: kind, OB, Collector, Chaos Mesh; one CPU (F01) and one delay (F04) fault captured with answer keys | M1, 8 Nov |
| X-06 | catalog automation (≥ 8 fault types), load profiles, packager, answer keys, `otel` profile | M2, 15 Nov |
| X-11 | overnight collection on all laptops, validation rule, daily counts; target ≥ 120 validated by M4 | M3–M4 |
| X-14 | packaging, Croissant draft, release files | M4, 29 Nov |

## 15. Open questions

| # | Question | Default |
|---|---|---|
| OQ-1 | CCR: `fault_class` has no class for crashes or unavailability (F06–F08) | *Resolved in 03 (2026-10-30):* `availability` added; F06–F08 use it |
| OQ-2 | CCR: `answer_key` has no fields for validation result or SLI impact | *Resolved in 03 (2026-10-30):* optional `validated` and `sli_impact_json` added ([03 §13.1](03-contracts.md#131-answer_key--key-case_id)) |
| OQ-3 | Packaged-capture layout and the `events.jsonl` mapping are agreed between two lanes but are not a 03 contract | §9 layout as in engines/01; confirm at O-07; propose a `veyllab_capture` contract only if the layout changes after M1 |
| OQ-4 | Lab baseline (10 min) is shorter than the 02 §5.1 baseline window (18 min) | keep 10 min (comparable to RCAEval's ~10–12 min); `alert.json` records `clamped = true`; move to 20 min if Anomara's onset error on lab cases is worse than on RE2 (costs ≈ 10 min per case) |
| OQ-5 | Does the demo laptop fit the lab, the gateway and the 9B model? | *Resolved in 02 §10 (2026-10-30):* lab + gateway ≈ 5–8.5 GB in WSL2 (*estimate*); the single-laptop demo runs with `--ai off` or the 4B model; the 9B model only on the split or cassette demo. Still measure at X-02 |
| OQ-6 | OB tracing variables, `k8sobjects` on kind, `kubeletstats` RBAC, HTTPChaos on gRPC, IOChaos targets, `extraMounts` path form on Docker Desktop | verify at X-02; drop what fails and record it in the ADR |
| OQ-7 | Does `scripts/check.py --package lab` support a non-workspace folder? | *Resolved in 08 §3 (2026-10-30):* yes, it lints and tests `lab/` by path |
| OQ-8 | OTel Demo and Collector licences | verify before release; block X-14 publication until done |

[bt-q2]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/benchmarks_and_testbed.md#q2-evaluation-methodology-best-practice-metrics-statistics-cross-system-generalization-ablations-costlatency-llm-pitfalls-and-what-reviewers-expect
[bt-q3]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/benchmarks_and_testbed.md#q3-live-testbed-on-a-16-gb-windows-laptop-which-demo-systems-fit-which-fault-injection-tools-work-locally-and-how-do-rcaevalaiopslab-style-faults-reproduce
[bt-q4]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/benchmarks_and_testbed.md#q4-load-generation-and-telemetry-pipeline-on-a-laptop-locust-k6-otel-collector-prometheus-jaegertempo-loki-with-memory-footprints
[bt-q5]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/benchmarks_and_testbed.md#q5-how-can-a-3-person-team-produce-a-new-credible-labelled-dataset-as-a-paper-contribution-fault-catalog-case-count-ground-truth-release-format
[sm-a1]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/stack_and_market.md#a1-opentelemetry-in-2026-collector-distributions-otlp-ingestion-in-python-semantic-convention-stability-profiles-ebpf-obibeyla-minimal-footprint
[sm-a2]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/stack_and_market.md#a2-storage-and-query-for-a-single-node-analytical-rca-engine-16-gb-laptop
[sm-a4]: ../research_notes/Veyltrace%20v2%20SOTA%20root%20cause%20analysis/stack_and_market.md#a4-capturing-change-events-kubernetes-events-deployments-config-and-feature-flag-changes-git-commits
[rep-16gb]: ../reports/Veyltrace%20v2%20SOTA%20root%20cause%20analysis.md#online-boutique-and-the-opentelemetry-demo-fit-train-ticket-does-not
