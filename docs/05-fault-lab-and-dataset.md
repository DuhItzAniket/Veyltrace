# 05 · Fault lab and the VeylLab dataset

> Status: v0.1-draft · Lane: Explain · Master: [02 §8](02-architecture.md#8-technology-stack-pinned-at-m0-recorded-in-adrs) (Lab row), [§10](02-architecture.md#10-deployment-shapes), [§6.1](02-architecture.md#61-infralume--ingest), [P7](02-architecture.md#2-design-principles-binding) · Contracts: [03 §2](03-contracts.md#2-infralume-outputs), [§13.1](03-contracts.md#131-answer_key--key-case_id) · Roadmap: X-02, X-06, X-11, X-14 · Last updated: 2026-11-24

---

## 1. Purpose and scope

The lab (`lab/`) is a fault-injection testbed that runs on one 16 GB Windows laptop. It has two jobs:

1. **Live demo**: a real system with real faults, feeding the gateway's live mode ([06](06-gateway-and-console.md)).
2. **VeylLab dataset**: labelled incident captures with published injection parameters, validated user impact, no-fault controls and decoy changes, fixing the flaws reviewers now cite in RCAEval-style data: unpublished `tc`/`stress-ng` parameters, non-independent repetitions, missing telemetry and answers encoded in folder names ([benchmarks_and_testbed §Q5][bt-q5]).

| System | Profile | Status | Why |
|---|---|---|---|
| Online Boutique v0.10.7 on kind + Chaos Mesh 2.8.7 | `ob` | primary; the live demo on it is never cut ([07 §1.1](07-roadmap.md#11-cut-list-if-a-milestone-slips-by--1-day)) | same system as RCAEval-OB and Nezha-OB (transfer experiments); requests only 1.57 CPU / 1,368 MiB |
| OpenTelemetry Demo 3.1.0 on Docker Compose | `otel` | alternate; **cut for v1.0** (07 §1.1 cut item 5): not built, `lab/up.py --profile otel` exits with "not implemented" | built-in flag faults; polyglot; Kafka |

The two profiles are **never run at the same time** ([02 §10](02-architecture.md#10-deployment-shapes)). Train Ticket does not fit: its guide asks for at least 24 GB of memory ([benchmarks_and_testbed §Q3][bt-q3]).

**v1.0 scope.** Lab collection (X-11) covers only the captures the live demo (X-10) needs; the ≥ 120 target moves to v1.1 with the dataset release X-14 ([ADR 20261123-cl-explain-scope-cuts](adr/20261123-cl-explain-scope-cuts.md), [ADR 20261121-ak-r16-cut-list](adr/20261121-ak-r16-cut-list.md) and its 22 Nov addendum). The experiments `veyllab-oracle-rq1-v1` and `veyllab-oracle-rq2-v1` are "not run". Sections on cut work keep the design and say so.

Out of scope here: the OTLP → canonical converter (Infralume, Observe lane, task O-07: `veyltrace_infralume.otlp` is on `main`, the `veyllab` adapter is not yet; the lab's release build would call the converter), scoring (bench, Reason lane).

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

Recorded in [ADR 20261109-cl-lab-ob-profile](adr/20261109-cl-lab-ob-profile.md); the values live in `lab/ob/pins.yaml`.


| Component | Version | Source / note |
|---|---|---|
| Online Boutique | v0.10.7 (2026-09-18), Apache-2.0 | [bt §Q3][bt-q3] |
| OpenTelemetry Demo | 3.1.0 (2026-09-18) | [bt §Q3][bt-q3] |
| Chaos Mesh | 2.8.7 (2026-10-28), Apache-2.0, Helm install | [bt §Q3][bt-q3] |
| OTel Collector | contrib v0.164.0 (2026-10-26) | [stack_and_market §A1][sm-a1] |
| Locust | as bundled by each demo (Locust 2.47.0 is current, MIT) | [bt §Q4][bt-q4] |
| kind, `kindest/node` | kind v0.33.0; `kindest/node:v1.37.0` pinned by digest in `pins.yaml` and `kind.yaml` | first live run, 2026-11-09 |
| Images | Collector and all 12 OB images pinned by digest (`pins.yaml`, overlay `images:`) | first live run, 2026-11-09 |
| kubectl, Helm, Docker | not pinned; versions recorded in every capture's `orchestrator.json` | not covered by the notes |

## 3. Profile `ob`: Online Boutique on kind

### 3.1 Cluster

```yaml
# lab/ob/kind.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
name: veyllab
nodes:
  - role: control-plane
    image: kindest/node:v1.37.0@sha256:a1ed56cf…      # kind v0.33.0's default; full digest in the file
    extraPortMappings:
      - containerPort: 30080          # frontend NodePort
        hostPort: 8080
        listenAddress: "127.0.0.1"    # local only
```

One node keeps memory down; k3d is an equivalent fallback if kind misbehaves ([bt §Q3][bt-q3]). The Collector spool (`/veyllab/spool`) stays inside the node container and is copied out with `docker cp` at export, so no `extraMounts` host path is needed; image digests are recorded in every capture's `orchestrator.json`; those of the first live run (2026-11-09) are pinned in `lab/ob/pins.yaml`, `kind.yaml` and the overlay ([ADR 20261109-cl-lab-ob-profile](adr/20261109-cl-lab-ob-profile.md)).

### 3.2 Application

- The v0.10.7 release manifest is vendored in `lab/ob/upstream/kubernetes-manifests.yaml` (`uv run python lab/up.py --vendor`) with its SHA-256 in `SHA256SUMS` and its Apache-2.0 notice; `lab/up.py --profile ob` refuses to start on a hash mismatch. A kustomize overlay `lab/ob/overlay/` changes only: namespace `veyllab-app`, `frontend-external` → NodePort 30080, load-generator settings, tracing settings, image digests.
- Resources from the manifest: 12 Deployments (10 services, `loadgenerator`, `redis-cart`); requests 1.57 CPU / 1,368 MiB; limits 2.7 CPU / 2,286 MiB ([bt §Q3][bt-q3]).
- **Load generator**: the bundled Locust `loadgenerator`, defaults `USERS=10`, `RATE=1` ([bt §Q4][bt-q4]); lab profiles use 10 (default) and 30 users (plan entry `users`; reset sets `USERS` on the Deployment). Keep ≥ 20% host CPU idle, because a saturated load generator inflates response times ([bt §Q4][bt-q4]).
- **Tracing**: the overlay sets `ENABLE_TRACING=1`, `COLLECTOR_SERVICE_ADDR` (the lab Collector, port 4317) and `OTEL_SERVICE_NAME` on the `server` container of the 10 services (OB's tracing component). On the first live run spans arrived from frontend, checkoutservice, currencyservice, emailservice, productcatalogservice and paymentservice. Services that do not emit spans still produce container metrics and logs.

### 3.3 Telemetry pipeline

One `otelcol-contrib` v0.164.0 Deployment `veyllab-collector` in namespace `veyllab-obs` with a single replica (the `k8s_objects` receiver must run once to avoid duplicates, [stack_and_market §A4][sm-a4]). 0.164.0 renames the components, and the lab uses the new names ([ADR 20261109-cl-lab-ob-profile](adr/20261109-cl-lab-ob-profile.md)):

```yaml
# lab/ob/collector.yaml, ConfigMap config.yaml (abridged)
receivers:
  otlp: {protocols: {grpc: {endpoint: "0.0.0.0:4317"}, http: {endpoint: "0.0.0.0:4318"}}}
  kubelet_stats: {collection_interval: 15s, auth_type: serviceAccount, metric_groups: [container, pod, node]}   # RBAC on nodes/stats
  file_log: {include: [/var/log/pods/*/*/*.log], exclude: [veyllab-obs and chaos-mesh pod logs], start_at: end}
  k8s_objects:
    objects:
      - {name: events, mode: watch}
      - {name: deployments, group: apps, mode: watch}
processors:
  memory_limiter: {check_interval: 1s, limit_mib: 448, spike_limit_mib: 96}   # a priori, under a 512Mi limit
  k8s_attributes: {}      # runs first, so OTLP data carries its namespace for the scrub
  filter/scrub: {}        # drop chaos-mesh namespace and flagd telemetry, chaos k8s events (§11)
  transform/scrub: {}     # delete feature_flag.* and chaos-mesh.org/* attributes (§11)
  batch: {}
exporters:
  file/traces:  {path: /veyllab/spool/traces.jsonl,  format: json, rotation: {max_megabytes: 100, max_backups: 100}}
  file/metrics: {path: /veyllab/spool/metrics.jsonl, format: json, rotation: {max_megabytes: 100, max_backups: 100}}
  file/logs:    {path: /veyllab/spool/logs.jsonl,    format: json, rotation: {max_megabytes: 100, max_backups: 100}}
service:
  pipelines:   # processors in every pipeline: [memory_limiter, k8s_attributes, filter/scrub, transform/scrub, batch]
    traces:  {receivers: [otlp], exporters: [file/traces]}
    metrics: {receivers: [otlp, kubelet_stats], exporters: [file/metrics]}
    logs:    {receivers: [otlp, file_log, k8s_objects], exporters: [file/logs]}
```

Container limit 512 MiB, `GOMEMLIMIT=400MiB` (75–80% of the limit; `memory_limiter` refuses data above its threshold) ([stack_and_market §A1][sm-a1]). The capture path deliberately uses the file exporter instead of Prometheus, Jaeger or Loki: no extra databases, and every capture is a set of hashable files ([bt §Q4][bt-q4]).

**Live mode** (the demo only, [06 §3.3](06-gateway-and-console.md#33-live-otlphttp-receiver)): `uv run python lab/up.py --profile ob --live-export [URL]` applies the same manifest with one more exporter, `otlp_http/gateway` (`encoding: json`, `compression: gzip`), added to all three pipelines next to the file exporters. The default URL is `gateway_otlp_endpoint` in `pins.yaml` (`http://host.docker.internal:4319`); the URL must be `http(s)://host:port` with no path. A pod-template annotation carries the endpoint, so switching restarts the Collector. Without the flag the committed `collector.yaml` is applied unchanged, as every capture campaign needs, and running `up` again without it switches export off.

### 3.4 Chaos Mesh 2.8.7

```sh
# as run by lab/up.py (every helm and kubectl call names the context kind-veyllab)
helm repo add chaos-mesh https://charts.chaos-mesh.org --force-update
helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh --namespace chaos-mesh --create-namespace \
  --version 2.8.7 --values lab/ob/chaos-mesh-values.yaml --wait --timeout 900s
```

Helm is the recommended install (the `install.sh` script is deprecated); the chart defaults to the Docker runtime, so `chaos-mesh-values.yaml` sets `chaosDaemon.runtime=containerd` and `socketPath=/run/containerd/containerd.sock` for kind; the chart sets no resource requests, so its footprint is unmeasured ([bt §Q3][bt-q3]). The values file also turns the dashboard off and runs one controller instead of three, to save memory. StressChaos and NetworkChaos work inside kind on Docker Desktop for Windows: X-02 captured F01 and F04 on 2026-11-09 ([ADR 20261109-cl-lab-ob-profile](adr/20261109-cl-lab-ob-profile.md)). The Helm wait is 15 min because the first image pull took more than 5.

## 4. Profile `otel`: OpenTelemetry Demo 3.1.0 on Compose

**Cut for v1.0** (07 §1.1 cut item 5, "keep Online Boutique"): this profile is not built; no ADR line records the cut yet. The design below stays for v1.1. Today only the mutual exclusion exists: `lab/up.py --profile otel` refuses while the kind cluster exists, then exits 2 ("not implemented yet"), and plan files accept only `profile: ob`.

- `lab/up.py --profile otel` refuses to start while the kind cluster `veyllab` exists, and `--profile ob` refuses while the demo's Compose project (`opentelemetry-demo`, name to confirm) is up.
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
| F14 | No fault | — (`is_no_fault = true`) | none | — | none (control) | implemented (X-11): no target, same phases; key with null times and `injection_json` (03 §13.1, as synth-05), reference time in `orchestrator.json` |
| F15 | Multi-fault | per root | two of F01, F04, F05 on two different services, overlapping | L1 each | both patterns | — |
| F16 | Benign noise | — (added to another case) | 2-minute load spike (30 users) on the load generator | — | transient traffic change, no SLI breach expected | — |

**Implemented** (X-06, `lab/vlab/faults.py`; [ADR 20261109-cl-lab-catalog-packager](adr/20261109-cl-lab-catalog-packager.md)): F01, F02, F04–F08, F11, F13. The indicator column above uses `family` names; answer keys use the 03 §1 `indicator` vocabulary (`errors` → `error`; F05's `net` → `latency`, the pre-registered mapping of 04 §7). Keys also carry `mode` by mechanism (F01, F02 `resource`; F04, F05 `network`; F11 `change`; F13 `dependency`; F06–F08 null). As built: F02 uses 1 worker; L2 kills (F06, F07) apply one PodChaos at `t_inject` and repeat it through a Chaos Mesh `Schedule` (`@every 120s`); F08's duration is capped by the fault window; F11 is only the CPU limit cut (the request is cut with it when needed, and both are restored from the vendored manifest), not the `targetPort` variant; F13 is only the NetworkChaos delay (F04's levels), not the StressChaos variant. F14 is a plan entry with no target or severity. F09 is deferred: HTTPChaos has no request percentage, so 10% / 50% abort cannot be expressed. Not built: F03, F09, F12, F15, F16; F10 and every flag variant need the `otel` profile (cut, §4).

**Live demo fault.** `lab/demo/f04-currencyservice-l1.yaml` is the NetworkChaos `vl-demo-f04`: F04 L1 (200 ms, 20 ms jitter) on `currencyservice` for 600 s, exactly what `injection()` builds for that entry; `lab/tests/test_demo_manifest.py` keeps the two equal ([06-live-demo](06-live-demo.md)).

**Targets.** OB: the 10 application services (all faults but F13) plus `redis-cart` (F13 only; F03 later); `loadgenerator` is never a target. Default grid (`lab/vlab/plan_gen.py`, a priori; [ADR 20261110-cl-lab-validation](adr/20261110-cl-lab-validation.md)): 5 target services (`cartservice`, `checkoutservice`, `currencyservice`, `frontend`, `productcatalogservice`) × 8 fault types (F01, F02, F04–F08, F11), plus F13 on `redis-cart`, × 3 repetitions at L1, L2, L1 (F02 and F07 always L2; the third repetition at 30 users), plus ⌈10%⌉ F14 controls: 136 cases. The notes' ≈ 10% noisy cases and up to 20 multi-fault cases ([bt §Q5][bt-q5]) are not in the grid (F15, F16 not built). The seed shuffles the grid once; `lab/make_plan.py` deals it round-robin to laptops and cuts it into nights of 24. Collection beyond the demo captures moves to v1.1 ([ADR 20261123-cl-explain-scope-cuts](adr/20261123-cl-explain-scope-cuts.md)).

## 7. Change events

**Real changes.** Every lab change is made through the platform so it shows up the way it would in production: `kubectl set image`, `set env`, `set resources`, `rollout restart`, `patch` (OB) and Compose image or limit updates (OTel). On `ob`, the Collector's `k8s_objects` receiver turns Deployment updates and Kubernetes events into log records ([stack_and_market §A4][sm-a4]). The packager (§10) moves these records out of the logs and into the capture's `events.jsonl` in `telemetry.events` shape ([03 §2.5](03-contracts.md#25-telemetryevents--key-t_ns-entity-kind)): `kind` ∈ `deploy | config | restart | k8s_event`, `source_system = k8s`. Only the app namespace counts. A Deployment record is a change when `generation > observedGeneration`, the first per (deployment, generation); its kind comes from the latest `managedFields` update (`f:image` → `deploy`, `restartedAt` → `restart`, else `config`). Events from the capture window become `k8s_event`, or `restart` for reasons `Killing`, `BackOff`, `OOMKilling` ([ADR 20261109-cl-lab-catalog-packager](adr/20261109-cl-lab-catalog-packager.md)).

**Flag flips and Compose changes** (`otel` profile only; not built, §4) have no Kubernetes object. The orchestrator emits one OTLP log record per change to the Collector, with resource attribute `service.name = veyllab-orchestrator` and attributes `veyllab.change.kind`, `veyllab.change.entity`, `veyllab.change.detail` (canonical JSON). Flag keys are replaced by `sha256(flag_key)[:8]` so the change channel works but the name does not reveal the fault (`paymentFailure` would). The packager writes them to `events.jsonl` as `kind = flag | config | deploy`, `source_system = manual` (OQ-3).

**Decoy changes** (*not built*: `lab/vlab/plan.py` rejects `decoy: true`, and every key has `decoy_changes_json = null`). With probability `p_decoy` = 0.5 (a priori) per case, the orchestrator makes one benign change on a random non-root service at a time drawn uniformly in [`t_inject` − 10 min, `t_inject` + 2 min]: `kubectl set env deploy/<svc> APP_REVISION=<n>` (a real rolling restart) or an image re-tag to the same digest. Names are neutral on purpose (no "decoy" token). Each decoy is listed in `answer_key.decoy_changes_json`. Real lab decoys complement bench's synthetic RCAEval-C decoys ([02 §6.4](02-architecture.md#64-causync--time-and-change)).

**Never a change event:** Chaos Mesh CRDs, chaos-daemon actions and their Kubernetes events. They are filtered in the Collector and again at packaging (§11).

## 8. Per-case protocol

### 8.1 Phases

The orchestrator `lab/campaign.py` executes a plan file `lab/plans/<plan>.yaml` (`profile`, `dataset`, `seed`, optional `durations_s` overrides, ordered `entries` of `fault`, `target`, `severity` (default L1), `users` (10 or 30) and `decoy`) and runs these phases for each entry; `--dry-run` prints every command without touching a cluster, and `--cleanup` only removes leftover faults and re-applies the overlay. Committed plans: `x02-smoke.yaml`, `x06-catalog.yaml`; `lab/make_plan.py` writes night plans to `lab/captures/`. Each attempt ends `captured`, `reset_failed`, `baseline_unrecovered`, `inject_failed`, `host_suspended` (the host slept mid-phase; no key) or `case_failed`.

| Phase | Duration | Action |
|---|---|---|
| Reset | ≤ 5 min | delete leftover chaos CRDs; restore config, flags and images (re-apply the overlay; set the entry's `USERS`); `kubectl rollout restart` every app Deployment (every 10th case: delete and recreate the namespace, *not built yet*); wait for every rollout (300 s each), else mark `reset_failed` and skip |
| Warm-up | 3 min | traffic on; not part of the capture's baseline |
| Baseline check | ≈ 0.5 min | entry-service p95 latency ≤ 1.5 × the reference p95 measured at setup, and error rate ≤ 1% (a priori; *not built yet*: the campaign checks only that the entry service answers HTTP 200); on failure wait 2 min and retry once, else `baseline_unrecovered` |
| Baseline | 10 min | capture on (Collector scaled to 0, spool emptied, scaled to 1); decoy change if scheduled (not built) |
| Fault | 10 min | record host clock ns and kind node clock ns (`docker exec veyllab-control-plane date +%s%N`) for skew; inject at `t_inject` |
| Recovery | 2 min | remove the fault; keep capturing |
| Export | ≈ 1 min | scale the Collector to 0 (flushes the spool) and `docker cp` it out; write `orchestrator.json` and the answer key; run validation |

Total ≈ 25–30 min per case, matching the ≈ 25 min the notes assume ([bt §Q5][bt-q5]). The capture holds 10 minutes before the fault, while [02 §5.1](02-architecture.md#51-alert-time-and-windows) defines an 18-minute baseline window; core's alert step clamps the window to the available data and records `clamped = true` in `alert.json`, as it does for RCAEval cases with ~10–12 min before injection (OQ-4).

### 8.2 Validation rule

Keep a fault case only if user-facing impact is measurable, as the FSE'26 benchmark did (1,430 of 9,152 injections kept) ([bt §Q5][bt-q5]):

1. SLI series: entry-service (`frontend`) server-span p95 latency and error rate in 30 s buckets, computed by lab code from the capture's spans.
2. Baseline: median and MAD of each SLI over the baseline buckets, MAD floored at 1% of the median and at an absolute 1 ms (p95) or 0.5 percentage points (error rate), because an error-free baseline has median and MAD 0; at least 6 baseline buckets (3 min), else the case is not validated (`insufficient_baseline`) (all a priori; [ADR 20261110-cl-lab-validation](adr/20261110-cl-lab-validation.md)).
3. Buckets are aligned to `t_inject` (for an F14 control: the reference time where a fault would start, recorded in the capture's `orchestrator.json`). Every bucket of the window is kept (silent baseline buckets do not count toward the baseline); a bucket after `t_inject` with no entry-service span is an outage and breaches both SLIs, and a run needs adjacent buckets. Keep if, within 5 minutes after `t_inject`, at least 2 consecutive buckets exceed `median + 5 × MAD` for either SLI (k = 5, N = 5 min: a priori).
4. No-fault cases are kept only if **no** such breach occurs (a clean control).
5. Every attempt, kept or not, is logged with its reason; acceptance rate is reported per fault type and system.

The campaign runs the rule at export and writes `validated` and `sli_impact_json` into the key and the attempt into `lab/captures/attempts.jsonl`; `uv run python lab/validate.py [--captures DIR] [ID …]` re-validates older captures.

### 8.3 Throughput

At ≈ 25 min per case, one laptop makes ≈ 57 attempts per 24 h, or ≈ 24 per 10-hour night; three laptops for six nights give ≈ 430 attempts (computed in [bt §Q5][bt-q5]). Bench runs compete for the same machines, so collection may get only alternate nights (≈ 215 attempts). The acceptance rate on laptops is unknown (FSE'26's 15.6% came from a harder cluster setup and may not transfer). Reaching 120 validated cases needs ≈ 28% acceptance with six full nights, or ≈ 56% with alternate nights (*estimates*). That target moves to v1.1 ([ADR 20261123-cl-explain-scope-cuts](adr/20261123-cl-explain-scope-cuts.md)); on 22 Nov 8 captures were kept. Daily counts go into the standup (X-11): `uv run python lab/report.py` (today), `--date YYYY-MM-DD` or `--all`.

## 9. Capture format

Rule: **no engine reads anything under `lab/`** ([02 §9](02-architecture.md#9-cross-cutting-rules), rule 3). Raw captures and answer keys therefore live under `lab/captures/` (git-ignored); only the packaged capture, which carries no answer, goes where Infralume can read it.

```
lab/captures/<capture_id>/                           raw capture (lab code only)
  otlp/{traces,metrics,logs}.jsonl  otlp/<signal>-<timestamp>.jsonl   Collector file exporters (active + rotated), OTLP JSON
  orchestrator.json                                  versions, digests, host spec, clock skew, file hashes
lab/captures/answer_keys/<capture_id>.json           answer key (lab and bench only)
lab/captures/attempts.jsonl                          every attempt with its validation result

${VEYLTRACE_DATA}/veyllab/<dataset>/<capture_id>/    packaged capture, read by Infralume's `veyllab` adapter
  otlp/traces.jsonl  otlp/metrics.jsonl  otlp/logs.jsonl          scrubbed, protobuf-JSON mapping
  events.jsonl                                       change records in telemetry.events shape
  oracle_alert.json                                  {"t_alert_ns": <published injection time>}
  capture.json                                       {"capture_id", "system"}
```

This is the layout [engines/01 §`veyllab`](engines/01-infralume.md) expects, to be confirmed with the Observe lane at O-07; the `veyllab` adapter is not on `main` yet, so nothing reads packaged captures today. `capture_id` = 32 random hex chars (lab is not analysis code; randomness is fine) and carries no meaning; Infralume derives `case_id` = first 12 hex of SHA-256(`capture_id`) ([03 §1](03-contracts.md#1-how-contracts-work)). `oracle_alert.json` is the oracle-protocol hint ([02 §5.1](02-architecture.md#51-alert-time-and-windows)): Infralume passes it to core as `case_manifest.t_alert_hint_ns` with `hint_source = oracle`, exactly as RCAEval publishes its injection times; under the detected protocol Infralume leaves `t_alert_hint_ns` null with `hint_source = none` ([03 §2.1](03-contracts.md#21-case_manifestjson)), so the injection time never reaches engines. No other packaged file mentions a fault, target, flag or injection.

## 10. Packaging

`uv run python lab/package.py --dataset veyllab-ob --captures lab/captures/<id>…`:

1. Read the raw capture; drop records matched by the scrub rules (§11).
2. Move `k8s_objects` records from the logs into `events.jsonl` (§7). Orchestrator change records and flag-key hashing belong to the `otel` profile (not built, §4).
3. Write the scrubbed OTLP files, `oracle_alert.json` (the key's `t_inject_ns`; for F14 the reference time in `orchestrator.json`) and `capture.json`; host identity is replaced (§11).
4. Post-scan every packaged file and path for deny-listed tokens; a hit removes that capture's package, withholds its key and makes the run exit 1.
5. Merge the answer key into `${VEYLTRACE_DATA}/answer_keys/<dataset>.parquet`, the registry path of [03 §13.1](03-contracts.md#131-answer_key--key-case_id), keyed by `case_id`, through bench's `write_answer_keys` (core io: schema, unique `case_id`, refuses a git work tree; `--data-root` overrides `$VEYLTRACE_DATA`); bench loads it from there. Every key carries all 03 §13.1 columns, null where unknown.

**Release build** (`lab/release.py`, X-14; *not built*, moves to v1.1 with X-14, [ADR 20261121-ak-r16-cut-list](adr/20261121-ak-r16-cut-list.md)): for each validated case, convert the packaged capture to canonical `telemetry.{metrics,logs,spans,events}` Parquet with Infralume's converter library `veyltrace_infralume.otlp` (Observe lane, O-07; the lab does not parse OTLP itself); assemble `cases/<case_id>/telemetry/*.parquet`, `answer_keys/answer_key.parquet` (including `validated` and `sli_impact_json`), `metadata/lab_metadata.parquet` (host spec, versions, skew) and `MANIFEST.json` (every file with SHA-256) in a staging folder under `lab/captures/release/`.

## 11. Answer keys and leakage

**Answer keys** follow [03 §13.1](03-contracts.md#131-answer_key--key-case_id): `case_id`, `dataset`, `system` (`ob`), `is_no_fault`, `root_service`, `root_component` (container), `fault_class`, `fault_label` (the F-id), `indicator`, `mode`, `t_inject_ns`, `t_end_ns`, `injection_json` (`{fault_id, tool, tool_version, params, severity, seed}`; `params` also holds the applied Chaos Mesh specs or kubectl arguments), `extra_roots_json` (F15), `decoy_changes_json`, `validated` (the §8.2 rule passed) and `sli_impact_json` (measured entry-service SLI change). An F14 key has null root columns, times and `injection_json`. Keys are written by the orchestrator under `lab/captures/answer_keys/`, never into a capture folder, and read only by lab and bench code ([AGENTS.md §4.5](../AGENTS.md)).

**Leakage scrubbing (P7)**, applied in the Collector (`filter/scrub`, `transform/scrub`), again at packaging, and a third time by Infralume at ingest:

| Source of leakage | Rule |
|---|---|
| OpenFeature evaluation attributes | drop `feature_flag.*` ([bt §Q3][bt-q3]; inference to verify on real telemetry) |
| flagd | drop all telemetry with `service.name` = flagd |
| Chaos Mesh | drop telemetry from the `chaos-mesh` namespace, events whose source is a chaos controller, labels and annotations `chaos-mesh.org/*`; at packaging also every log record whose body hits the deny-list (kube-apiserver naming a chaos CRD) and the pod-failure placeholder image `google-containers/pause` |
| Change records | flag keys hashed; neutral image tags (`veyllab/<svc>:r-<hash8>`) and env names |
| Tokens | deny-list post-scan (`lab/vlab/package.py`): `chaos` and `feature_flag` anywhere (so every `*Chaos` CRD kind), `google-containers/pause`, and at word starts `stress-ng`, `netem`, `inject`, `fault`, `decoy` and the 8 flag keys named in §6; the full OTel Demo flag list comes with the `otel` profile |
| Host identity | replace the Windows user name, host name and LAN IPs with `veyllab-user`, `veyllab-host`, `192.0.2.1` |
| Folder names | opaque `capture_id`; `case_id` derived from it |

## 12. Dataset release plan

**Moves to v1.1** with X-14 (07 §1.1 cut item 6; [ADR 20261121-ak-r16-cut-list](adr/20261121-ak-r16-cut-list.md), [ADR 20261123-cl-explain-scope-cuts](adr/20261123-cl-explain-scope-cuts.md)). Nothing below is built: no release files, Croissant metadata or datasheet yet.

| Item | Plan |
|---|---|
| Name and ids | VeylLab; datasets `veyllab-ob`, `veyllab-otel` (`otel` cut, §4) ([03 §2.1](03-contracts.md#21-case_manifestjson)) |
| Content | canonical Parquet (zstd) per case; answer keys and lab metadata in separate files; injector scripts, plan files, kind/Helm/Compose files and image digests; per-case outputs of every baseline (none of 23 audited RCA papers released per-case outputs, [bt §Q2][bt-q2]) |
| Licence | data CC BY 4.0; code Apache-2.0 (the repo licence) |
| Metadata | Croissant JSON-LD with the mandatory Responsible-AI fields (NeurIPS 2026 E&D flags submissions without them) and a datasheet that states laptop threats: host contention, Docker Desktop VM, single-node kind, clock skew ([bt §Q2][bt-q2]) |
| Hosting | Zenodo DOI (artifact) plus a Hugging Face mirror |
| Size | ≈ 10–20 MB per case, so ≈ 1.2–2.4 GB for 120 cases (*estimate* from RCAEval RE2 per-case sizes, [bt §Q5][bt-q5]) |
| Targets | ≥ 120 validated cases (02 §12 default), mainly `ob`; not reached (8 kept on 22 Nov), so the release is v1.1 (X-14, [07 §1.1](07-roadmap.md#11-cut-list-if-a-milestone-slips-by--1-day)). Later: ≈ 300 cases, the threshold for a separate dataset submission ([07 §8](07-roadmap.md#8-after-the-month)) |
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

- Plan generator: same seed → identical plan; grid balance per (service, fault); disjoint laptop shares; every night is a valid plan.
- `lab/campaign.py --dry-run` and `lab/up.py --dry-run`: print every command, touch no cluster; `--live-export` adds only the exporter.
- Packager on a tiny synthetic OTLP capture that `lab/tests/test_package.py` writes to a temporary folder (no committed fixtures).
- Leak scan: `feature_flag.*` attributes and a kube-apiserver line naming a chaos CRD are scrubbed; planted tokens that survive scrubbing (a flag name, `stress-ng`, the pause image) must fail packaging.
- Answer keys: test that no answer-key file is ever written under a capture or case folder.
- Validation rule: unit tests with synthetic SLI series (breach, no breach, no-fault control).

## 14. Tasks and milestones

| ID | Scope | Milestone |
|---|---|---|
| L-01 | `.wslconfig`, netem check, `docs/team/<initials>.md` | M0, 3 Nov |
| X-02 | `ob` profile: kind, OB, Collector, Chaos Mesh; one CPU (F01) and one delay (F04) fault captured with answer keys | M1, 8 Nov |
| X-06 | catalog automation (≥ 8 fault types), load profiles, packager, answer keys; `otel` profile cut (07 §1.1 item 5) | M2, 15 Nov |
| X-11 | overnight collection on all laptops, validation rule, daily counts; v1.0: only the live-demo captures, the ≥ 120 target moves to v1.1 ([ADR 20261123-cl-explain-scope-cuts](adr/20261123-cl-explain-scope-cuts.md)) | M3–M4 |
| X-14 | packaging, Croissant draft, release files | v1.1 ([ADR 20261121-ak-r16-cut-list](adr/20261121-ak-r16-cut-list.md)) |

## 15. Open questions

| # | Question | Default |
|---|---|---|
| OQ-1 | CCR: `fault_class` has no class for crashes or unavailability (F06–F08) | *Resolved in 03 (2026-10-30):* `availability` added; F06–F08 use it |
| OQ-2 | CCR: `answer_key` has no fields for validation result or SLI impact | *Resolved in 03 (2026-10-30):* optional `validated` and `sli_impact_json` added ([03 §13.1](03-contracts.md#131-answer_key--key-case_id)) |
| OQ-3 | Packaged-capture layout and the `events.jsonl` mapping are agreed between two lanes but are not a 03 contract | §9 layout as in engines/01; confirm at O-07 (adapter not on `main` yet); propose a `veyllab_capture` contract only if the layout changes after M1 |
| OQ-4 | Lab baseline (10 min) is shorter than the 02 §5.1 baseline window (18 min) | keep 10 min (comparable to RCAEval's ~10–12 min); `alert.json` records `clamped = true`; move to 20 min if Anomara's onset error on lab cases is worse than on RE2 (costs ≈ 10 min per case) |
| OQ-5 | Does the demo laptop fit the lab, the gateway and the 9B model? | *Resolved in 02 §10 (2026-10-30):* lab + gateway ≈ 5–8.5 GB in WSL2 (*estimate*); the single-laptop demo runs with `--ai off` or the 4B model; the 9B model only on the split or cassette demo. Still measure at X-02 |
| OQ-6 | OB tracing variables, `k8sobjects` on kind, `kubeletstats` RBAC, HTTPChaos on gRPC, IOChaos targets, `extraMounts` path form on Docker Desktop | *Partly resolved at X-02* ([ADR 20261109-cl-lab-ob-profile](adr/20261109-cl-lab-ob-profile.md)): no `extraMounts` (spool copied with `docker cp`); spans from 6 OB services; `k8s_objects` change records work on kind. Open: HTTPChaos on gRPC (F09 deferred), IOChaos targets (F03 not built) |
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
