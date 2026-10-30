# Veyltrace v2: Laptop-Friendly Telemetry Stack and the 2026 AI-RCA Competitive Landscape

Research date: 30 Oct 2026. These notes build on the earlier notes in `research_notes/Veyltrace outage diagnosis research/`, specifically `engineering_feasibility.md` and `industry_market.md`. They do not repeat what is there. Already covered there:
- DuckDB 1.5.x CSV/Parquet/memory knobs, Polars 2.0, Drain3, FastAPI native SSE (0.135+) and FastAPI 0.159
- uv-in-Docker recipe, Prometheus/Loki/Tempo/Jaeger query APIs, AWS deployment
- Datadog/Dynatrace/New Relic/PagerDuty/Honeycomb/incident.io pricing, the DevOps Guru sunset, and early funding for Resolve, Traversal, Cleric and Causely

Constraints: 3 students, a 1-month build, Windows laptops with 16 GB RAM and Docker, Python core, and a live demo.

Release dates on GitHub release pages often show day and month only. Where I inferred the year from context, I say so.

---

## A1. OpenTelemetry in 2026: Collector distributions, OTLP ingestion in Python, semantic-convention stability, Profiles, eBPF (OBI/Beyla), minimal footprint

### Takeaway
OTel is production-shaped but still versioned 0.x for the Collector (v0.164.0, 26 Oct 2026). Use **otelcol-contrib**, or an OCB-built slim distribution, as the single ingest point:
- set `memory_limiter` and `GOMEMLIMIT` to roughly 400–512 MiB
- have it forward OTLP/HTTP to a Python ingest service.

Treat **Profiles (public alpha since Mar 2026)** and **OBI eBPF (beta, pre-1.0, Linux-kernel-only)** as stretch goals, not core dependencies. **HTTP and DB** are the safest stable semantic conventions to key RCA features on. **K8s resource attributes** are also stable. **RPC, CI/CD/VCS and process** are release candidates. **Feature flags and GenAI** are still in development.

### Cited Findings
**Collector versions and distributions**
- The latest collector-releases tag is **v0.164.0 (26 Oct)**, preceded by v0.163.2 (21 Oct) and v0.163.0/.1 (16 Oct). The year 2026 is inferred from asset timestamps. All releases are still 0.x. The v0.164.0 notes add the `file_log` receiver, `resource_detection` processor and `transform` processor to the **core** distribution as "priorities for stabilization". It builds with Go 1.26.10 — [GitHub opentelemetry-collector-releases](https://github.com/open-telemetry/opentelemetry-collector-releases/releases)
- The Collector already ships a split version scheme: stable modules use 1.x and the rest 0.x. For example, the January 2026 release was **v1.49.0/v0.143.0** — [FusionReactor, Jan 2026](https://fusion-reactor.com/blog/opentelemetry-collector-v1-49-0-v0-143-0-whats-new-in-january-2026/)
- The GA plan is "a distribution of the Collector that contains a minimum set of components which have been stabilized". I found no Collector 1.0 GA announcement as of Oct 2026 — [Collector GA roadmap](https://github.com/open-telemetry/opentelemetry-collector/blob/main/docs/ga-roadmap.md); [Datadog OTel news](https://opensource.datadoghq.com/category/otel-news/)
- The project ships five official distributions, each released roughly every two weeks: **core (otelcol), contrib, k8s, otlp, and eBPF profiler** — [Datadog blog on Collector distributions, Jul 2025](https://www.datadoghq.com/blog/otel-collector-distributions.md); [OneUptime, Feb 2026](https://oneuptime.com/blog/post/2026-02-06-core-vs-contrib-opentelemetry-collector/markdown)
- Custom slim builds use the OpenTelemetry Collector Builder (OCB, `cmd/builder`), which is released alongside each version — [GitHub collector-releases](https://github.com/open-telemetry/opentelemetry-collector-releases/releases); [OneUptime OCB guide, Feb 2026](https://oneuptime.com/blog/post/2026-02-06-build-custom-opentelemetry-collector-distribution-ocb/markdown)

**Minimal footprint**
- Splunk's distribution is configured by default to use **512 MB** — [Splunk sizing docs](https://help.splunk.com/ja-jp/splunk-observability-cloud/manage-data/splunk-distribution-of-the-opentelemetry-collector/splunk-distribution-of-the-opentelemetry-collector-の利用開始/collector-要件/サイジングとスケーリング)
- A third-party guide suggests **0.25–0.5 cores and 256–512 MB** for low-resource instances, and **GOMEMLIMIT at 75–80%** of the container limit (about 400 MiB for 512 MB). These are illustrative, not benchmarked — [OneUptime right-sizing](https://oneuptime.com/blog/post/2026-02-06-right-size-cpu-memory-opentelemetry-collector/markdown); [OneUptime GOMEMLIMIT](https://oneuptime.com/blog/post/2026-02-06-gomemlimit-memory-limiter-stable-collectors/markdown)
- `memory_limiter` monitors Go heap use and refuses data above its thresholds — [Ubuntu observability docs](https://documentation.ubuntu.com/observability/latest/how-to/configure-and-tune/configure-memory-limits-otelcol/)

**OTLP ingestion in Python**
- OTLP over gRPC is always protobuf. OTLP/HTTP accepts protobuf or JSON on `POST /v1/traces` (and `/v1/metrics`, `/v1/logs`). Payloads nest ResourceSpans → ScopeSpans → Spans — [OneUptime OTLP explainer, Feb 2026](https://oneuptime.com/blog/post/2026-02-06-otlp-opentelemetry-protocol-explained/markdown)
- The Collector's OTLP/HTTP JSON must use the **protobuf JSON mapping**. Proto-version skew between sender and receiver is a common cause of "invalid protobuf" errors — [Collector OTLP receiver README](https://github.com/open-telemetry/opentelemetry-collector/blob/7d7ae2eb34b5d387627875c498d7f43619f37ee3/receiver/otlpreceiver/README.md); [OneUptime protobuf errors](https://oneuptime.com/blog/post/2026-02-06-fix-invalid-protobuf-errors-otlp-export/view)
- The generated `ExportTraceServiceRequest` type is in `opentelemetry.proto.collector.trace.v1.trace_service_pb2`, shipped via the `opentelemetry-proto` dependency of the OTLP exporters — [tessl registry: opentelemetry-exporter-otlp-proto-common](https://tessl.io/registry/tessl/pypi-opentelemetry-exporter-otlp-proto-common)
- **OTel Python SDK 1.44.0 was released 16 Jul 2026** (third-party tracker) — [versio.io](https://www.versio.io/en/product-release-end-of-life-eol-opentelemetry-opentelemetry-python-sdk.html)
- Python **logs** are still "Development" status (underscore-prefixed modules), while traces and metrics are stable. This comes from third-party pages, not opentelemetry.io — [OpenObserve Python guide](https://openobserve.ai/opentelemetry/python/); [dev.co](https://dev.co/observability/open-source/opentelemetry-python). By contrast, Go Logs API/SDK reached release candidate (v1.47.0-rc.1) — [OTel blog](https://opentelemetry.io/blog/2026/go-logs-api-sdk-rc/)

**Semantic-convention stability**

Years below are inferred: v1.38 is 2025 and v1.39 onward is 2026 — [GitHub semantic-conventions releases](https://github.com/open-telemetry/semantic-conventions/releases)
- **HTTP** has been stable since v1.23.0 (Nov 2023) and **database** since v1.33.0 (2025) — [ClickHouse semconv explainer](https://clickhouse.com/resources/engineering/opentelemetry-semantic-conventions); [OneUptime migration guide](https://oneuptime.com/blog/post/2026-02-06-migrate-old-semantic-conventions-stable/view)
- **v1.40.0 (19 Feb)**:
  - core RPC, gRPC and Dubbo marked **release candidate**
  - `service.instance.id` **stable**
  - recording exceptions as span events **deprecated**, with an opt-in env var `OTEL_SEMCONV_EXCEPTION_SIGNAL_OPT_IN` to move them to logs
  - feature flags: `error.message` deprecated in favour of `feature_flag.error.message`
- **v1.41.0 (28 Apr)**: `deployment.environment.name` **stable**.
- **v1.42.0 (12 Jun)**: "a core selection of Kubernetes and container registry resource attributes have officially graduated to `stable`". All `gen_ai.*` conventions were deprecated and moved to a dedicated repository.
- **v1.43.0 (3 Jul)**: CI/CD span, metric, log, attribute and entity conventions moved to **release candidate**, as did VCS, process metrics/entity, and Oracle DB connection attributes.
- **v1.44.0 (4 Aug)**: container and K8s memory metrics moved to **release candidate**, along with the process namespace and `network.interface.name`.
- The official OTel blog says messaging and RPC are "in progress", not stable — [OTel blog: instrumentation ecosystem 2026](https://opentelemetry.io/blog/2026/exploring-instrumentation-ecosystem); [Grafana 2026 outlook](https://grafana.com/blog/opentelemetry-and-grafana-labs-whats-new-and-whats-next-in-2026)

**Profiles signal**
- The Profiling SIG declared **public Alpha in March 2026**. The docs status was updated on 23 Mar 2026 — [OTel blog: Profiles enters public alpha](https://opentelemetry.io/blog/2026/profiles-alpha/); [Polar Signals, 26 Mar 2026](https://blog.polarsignals.com/blog/posts/2026/03/26/opentelemetry-profiling-goes-alpha)
- What Alpha contains:
  - OTLP Profiles in proto **v1.10.0**, pprof-compatible with lossless round-trip, carrying `trace_id`/`span_id` association.
  - The eBPF profiler is now a Collector receiver with its own official distribution, and needs **Collector ≥ v0.148.0**.
  - The SIG says it "should not be used for critical production workloads", and "production-ready backends have not yet emerged".
  - Elastic's `devfiler` is for local exploration only.

  — [OTel blog](https://opentelemetry.io/blog/2026/profiles-alpha/)
- Spec v1.59.0 added a formal data model for Profiles (Jul 2026) — [Datadog OTel news, Jul 2026](https://opensource.datadoghq.com/otel-news/2026/07/)
- No Beta announcement was found as of late Oct 2026. A ClickHouse page (updated 29 Jul 2026) lists Beta and GA as next steps — [ClickHouse otel news](https://clickhouse.com/resources/engineering/otel-news-profiles-signal)

**OpenTelemetry eBPF Instrumentation (OBI) and Grafana Beyla**
- Grafana donated Beyla to OTel as **OBI** in 2025. Beyla now imports OBI as a library, and "every feature that is available in OBI is also available in Beyla", while Beyla releases faster. Beyla-only extras include process metrics, survey mode and Alloy integration. Environment-variable prefixes are `OTEL_EBPF_*` for OBI and `BEYLA_*` for Beyla — [Grafana docs: OBI instead of Beyla](https://grafana.com/docs/beyla/latest/obi/). Beyla release notes show v3.31.0 bumping the OBI submodule — [newreleases: Beyla v3.31.0](https://newreleases.io/project/github/grafana/beyla/release/v3.31.0)
- 2026 SIG goals — [OTel blog: OBI 2026 goals](https://opentelemetry.io/blog/2026/obi-goals/):
  - a **stable 1.0** as the "flagship goal"
  - current protocol coverage of **HTTP, gRPC, SQL**, with MQTT/AMQP/NATS/Redis pub/sub/MongoDB/cloud SDKs planned
  - .NET in progress
  - a Collector distribution with OBI as a receiver
  - integration with the eBPF profiler
- OBI docs were updated for **v0.10.0 (20 Jul 2026)** — [OBI docs](https://opentelemetry.io/docs/zero-code/obi/). Splunk listed OBI as **Beta** at KubeCon EU 2026 — [Splunk KubeCon EU 2026](https://www.splunk.com/en_us/blog/observability/splunk-kubecon-eu-2026-observability-innovations.html). One DevToolLab post cites "1.26.0/1.36.0" OBI versions that conflict with the official 0.x line, so treat it as unreliable — [DevToolLab](https://devtoollab.com/blog/ebpf-observability-tools)
- Beyla/OBI needs **Linux kernel 5.8+ with BTF** and does not run on Windows or macOS — [dev.co Beyla](https://dev.co/observability/open-source/beyla); [Grafana community](https://community.grafana.com/t/how-can-we-use-beyla-for-windows-servers/160144). eBPF on WSL2 may require recompiling the WSL2 kernel with eBPF flags (community guides) — [DEV: eBPF on WSL2](https://dev.to/wiresurfer/unleash-the-forbidden-enabling-ebpfxdp-for-kernel-tinkering-on-wsl2-43fj)

### Inferences
- **Recommended pipeline.** Demo services use the Python/Go/Node OTel SDKs and export OTLP to one otelcol-contrib container:
  - processors: `memory_limiter`, `batch`, `transform`, `k8sattributes` if on k8s
  - exporters: (a) OTLP/HTTP-protobuf to Veyltrace's FastAPI `/v1/{traces,metrics,logs}`, and optionally (b) otel-lgtm for a "real Grafana" side view.

  With the Collector in front, Veyltrace's Python receiver only has to parse one well-formed protobuf shape. Batching, retries and receiver diversity come for free.
- **Pin the proto version.** Use the same `opentelemetry-proto` version as the SDKs in the lockfile to avoid the "invalid protobuf" skew failure.
- **Key RCA joins on stable semconv attributes.** Use `service.name`, `service.instance.id`, `deployment.environment.name`, HTTP `http.response.status_code`/`http.route`, DB `db.*`, and K8s resource attributes. Treat RPC, CI/CD and VCS attributes as RC: they are usable, but expect renames.
- **eBPF and Profiles are poor core bets for a 1-month Windows-laptop build.**
  - OBI needs a BTF-enabled Linux kernel, which Docker Desktop's WSL2 kernel may not provide (unverified) and is pre-1.0.
  - Profiles is alpha with no production backend.

  Both work well as roadmap or future-work slides: "zero-code coverage via OBI", "profile-level evidence via OTLP Profiles once Beta".
- **Logs.** Because the Python logs SDK is still Development, prefer emitting logs via stdout plus the Collector's `filelog` receiver, or accept API churn by pinning versions.

### Gaps
- No measured idle RSS for otelcol-contrib vs core vs an OCB slim build was found. Measure locally with `docker stats`.
- Could not confirm whether Docker Desktop's stock WSL2 kernel exposes `/sys/kernel/btf/vmlinux` (needed by OBI). Test on the team laptops.
- I did not verify the official per-language Python logs status page or the exact OBI release number as of Oct 2026.
- No Python OTLP receiver reference implementation was found. The FastAPI + `ParseFromString` approach is an inference.

---

## A2. Storage and query for a single-node analytical RCA engine (16 GB laptop)

### Takeaway
Keep **Parquet (zstd) + DuckDB in-process** as the analytical core.

DuckDB **2.0.0 LTS shipped 21 Oct 2026** with a new storage format. Version 1.5 is supported to March 2027, so use Parquet as the durable interchange and either engine version works. **ASOF JOIN** is the key primitive for aligning change events, metrics and spans on time.

Avoid running a full Tempo + Loki + Prometheus + ClickHouse stack. Tempo alone is sized at 4–8 GB, and 16 GB+ is recommended when it shares a host. Use **grafana/otel-lgtm** (single image, explicitly dev/demo only) for a "production-shaped" side panel if wanted. ClickHouse/ClickStack, VictoriaMetrics and Jaeger v2 are cloud-later options.

### Cited Findings
**DuckDB**
- **DuckDB 2.0.0 LTS "Cinnamon Teal" was released 21 Oct 2026**. It is "our biggest feature release so far".
  - LTS support runs "until at least October 2027", and **1.5 support was extended to March 2027**. 1.4 is supported until 17 Nov 2026.
  - Features:
    - the Quack client-server protocol polished, with `CONNECT` and CLI `-serve`/`-connect`
    - **asynchronous I/O** for Parquet, CSV and native storage
    - first-class **VARIANT**
    - triggers
    - a default PEG parser
    - "agent mode" CLI output, which cuts output tokens 59% on TPC-H
    - C API v2 and DuckLake 1.1
  - **Files written in the new 2.0 default format cannot be read by <2.0.**
  - On Windows the CLI is built with Clang, but "most core extensions are still built with MSVC".

  — [DuckDB announcement](https://duckdb.org/2026/10/21/announcing-duckdb-200)

  (The GitHub tag name "Cyanoptera" in the earlier notes is consistent with this: cinnamon teal is *Spatula cyanoptera*.)
- Dev-build benchmarks reported Parquet-on-S3 about **2.9× faster** than 1.5.5 and one CSV test about **19.4× faster**. These are pre-release figures reported secondhand — [InfoWorld](https://infoworld.com/article/4210635/duckdb-2-0-coming-this-fall-with-client-server-mode); [AlternativeTo](https://alternativeto.net/news/2026/10/duckdb-s-major-2-0-release-turns-the-database-management-system-into-a-full-fledged-server/)
- **ASOF JOIN** matches each left row to the nearest right row satisfying an inequality (e.g. `h.when >= p.when`) plus equality keys.
  - The `USING (key, ts)` form treats the last column as the inequality.
  - `ASOF LEFT JOIN` keeps unmatched rows with NULLs.
  - Each left row matches at most one right row.

  — [DuckDB ASOF join guide (2.0 docs)](https://duckdb.org/docs/2.0/guides/sql_features/asof_join.html)

**Jaeger v2**
- Jaeger v2.18.0 added **native ClickHouse storage in alpha** behind a feature gate. It targets ClickHouse 25.x and the schema may break — [Jaeger ClickHouse docs v2.18](https://www.jaegertracing.io/docs/2.18/storage/clickhouse/); [stack-archive write-up](https://stack-archive.com/blog/jaeger-clickhouse-storage-8x-compression-2026/) (third-party)
- Badger (embedded KV) works only "in the all-in-one configuration or with the remote storage component". The latest docs are 2.20 (Jul 2026) — [Jaeger Badger docs 2.20](https://www.jaegertracing.io/docs/2.20/storage/badger/)
- The Jaeger v2 Storage API natively supports the OTLP data model — [Jaeger roadmap](https://www.jaegertracing.io/roadmap)

**Grafana Tempo and Grafana**
- Tempo monolithic (`-target=all`, no Kafka needed) is documented at version 3.0.x. The local Linux starting point is **4 CPUs and 4–8 GB RAM**, with **16 GB or more** when Grafana, an object store or Prometheus share the machine. The docs say these are not hard minimums — [Tempo deploy locally (Linux)](https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/deploy/locally/linux/); [Tempo deployment modes v3.0](https://grafana.com/docs/tempo/v3.0.x/reference-tempo-architecture/deployment-modes/)
- Grafana itself needs a minimum of 512 MB RAM and 1 core — [Grafana install docs](https://grafana.com/docs/grafana/next/setup-grafana/installation.md)

**grafana/otel-lgtm**
- The image bundles an OTel Collector, Prometheus, Loki, Tempo and Grafana. It is "intended for development, demo, and testing environments". Run it with `docker run -p 3000:3000 -p 4317:4317 -p 4318:4318 grafana/otel-lgtm`, persist via a `/data` volume, and tune retention via `PROMETHEUS_EXTRA_ARGS` — [Grafana docs: docker-otel-lgtm](https://grafana.com/docs/opentelemetry/docker-lgtm/); [Go pkg docker-otel-lgtm](https://pkg.go.dev/github.com/grafana/docker-otel-lgtm)
- A third-party report says the lgtm pod OOM-crashed on small clusters and Loki's disk filled up. Fixes were GOMEMLIMIT, shorter retention and collector limits — [silogen/cluster-forge PR #790](https://github.com/silogen/cluster-forge/pull/790)

**ClickHouse / ClickStack**
- A single-image local distribution bundles the HyperDX UI, an OTel collector and ClickHouse. ClickHouse gives no official local RAM minimum, and its managed sizing figures are "estimates only" — [ClickStack overview](https://clickhouse.com/docs/use-cases/observability/clickstack/overview); [ClickStack managed sizing](https://clickhouse.com/docs/clickstack/getting-started/managed)
- ClickStack has an open issue to support OTel Profiles end-to-end — [ClickStack issue #9](https://upd.dev/ClickHouse/ClickStack/issues/9)

**VictoriaMetrics family**
- Vendor claims "up to 7x less RAM than Prometheus" for millions of series, and says single-node suffices for most workloads up to millions of active series — [VictoriaMetrics README mirror](https://forge.k3s.fr/github-mirrors/VictoriaMetrics/src/commit/f5dfe1cacd8106c83edd1c43e433558ce409b656)
- The v1.132.0 (Dec 2025) changelog warned of **memory leaks when ingesting OTLP**. Feb 2026 updates stream large OTLP requests with lower peak memory — [VictoriaMetrics changelog 2025](https://docs.victoriametrics.com/victoriametrics/changelog/changelog_2025/); [VictoriaMetrics Feb 2026 updates](https://victoriametrics.com/blog/victoriametrics-february-2026-ecosystem-updates/)
- VictoriaTraces is a single binary with no external dependencies — [VictoriaTraces](https://victoriametrics.com/products/victoriatraces/)

### Inferences
- **Recommended laptop storage design: "hot window in memory, cold in Parquet".**
  - Hot: the Python ingest service keeps the last N minutes per signal in Arrow record batches or a DuckDB in-memory table.
  - Every 5–10 s it flushes partitioned Parquet: `signal=/date=/hour=/part-*.parquet`, zstd.
  - The RCA engine queries `read_parquet('…/**/*.parquet', hive_partitioning=true)` plus the hot table.
  - Offline benchmark cases (RCAEval etc.) land in the same schema, so batch and live share one code path.
- **DuckDB version choice.** For a 1-month build starting now:
  - **1.5.x** (supported to Mar 2027) is lowest-risk.
  - **2.0** is fine if Parquet, not `.duckdb` files, is the persistence format, so the storage-format break doesn't matter.
  - Pin in `uv.lock` either way. 2.0's new PEG parser and async I/O are 9 days old.
- **ASOF JOIN uses for RCA:**
  - "Which deployment/flag change was the latest before each anomaly onset per service" (`ASOF LEFT JOIN changes USING (service, ts)`).
  - Aligning irregular span aggregates to metric scrape timestamps.
- **Rough memory budget on 16 GB.** I summed vendor guidance here; I did not measure it.

  | Component | Memory |
  |---|---|
  | Windows + Docker Desktop VM overhead | ~4–6 GB |
  | OTel demo microservices | ~2–4 GB (unmeasured) |
  | Collector | ~0.5 GB |
  | Veyltrace API + DuckDB `memory_limit` | 2–3 GB |
  | Optional otel-lgtm, capped with `--memory` | 2–3 GB |

  Self-hosting Tempo, Loki and Prometheus separately, or adding ClickHouse, will not fit comfortably.
- **"Production-shaped" story.** Use an adapter architecture (Prometheus/Loki/Tempo HTTP APIs, already documented in the earlier notes) plus OTLP ingest. That shows the engine can sit on real backends without running them all locally. ClickHouse/ClickStack or Jaeger v2 + ClickHouse are the natural "cloud later" backends.

### Gaps
- No measured RAM for otel-lgtm at idle or under demo load, and no official Loki monolithic minimum.
- No current independent benchmark comparing DuckDB 2.0 vs 1.5 on time-windowed observability queries.
- ClickHouse local idle footprint and VictoriaLogs/VictoriaTraces footprints are unquantified by official sources.

---

## A3. Streaming vs batch: one engine for offline benchmark cases and a live sliding window; queue options at small scale

### Takeaway
At 3-person, single-laptop scale, the best "queue" is **none**: Collector → OTLP/HTTP → FastAPI ingest → in-process ring buffer plus periodic Parquet flush. Run RCA as a **micro-batch over a sliding window** using the same DuckDB SQL used offline.

Add **Redis Streams** only if a separate worker process must consume asynchronously. **NATS JetStream** is the cleaner choice if you want durable replay and acks as a first-class feature. Either adds an extra container and failure mode.

### Cited Findings
- NATS JetStream bundles durable streams, replay, acknowledged consumers and KV buckets "all from one small binary". Redis has richer native data structures: lists, sets, sorted sets, hashes, streams and Lua — [DEV/scour: NATS as unified backbone](https://scour.ing/@hello/p/https://dev.to/thedonmon/beyond-kafka-and-redis-a-practical-guide-to-nats-as-your-unified-cloud-native-backbone-4g86); [Synadia blog](https://www.synadia.com/blog/replace-redis-with-nats-atomic-counters-and-microsecond-key-value) (Synadia sells NATS)
- The official `nats.py` client split into a core client and a separate `nats-jetstream` layer. The JetStream API is no longer attached via `nc.jetstream()`, so older examples break — [tessl: nats-py JetStream management](https://tessl.io/registry/tessl/pypi-nats-py/files/docs/jetstream-management.md)
- A common pattern pairs NATS JetStream for event transport with Redis for state — [hoop.dev](https://hoop.dev/blog/what-nats-redis-actually-does-and-when-to-use-it) (low-authority blog)
- The Collector's own `batch` processor and exporter queues already provide buffering and retry upstream of the Python service — [Datadog: Collector batch/memory](https://docs.datadoghq.com/opentelemetry/config/collector_batch_memory/)

### Inferences
- **Proposed design.**
  - `IngestBuffer`: per-signal Arrow batches with a time index, flushed to Parquet partitions.
  - `WindowAnalyzer.run(window_start, window_end)`: pure function from (Parquet glob + hot buffer) to evidence JSON.
  - Live mode: a scheduler calls it every k seconds over `[now − W, now]`, or on an anomaly trigger.
  - Offline mode: the same function over a frozen case directory.
  - Determinism: snapshot the window (Parquet + sha256) before analysis, so every live diagnosis is replayable as an offline case. Reproducibility becomes a feature, not a limitation.
- **Trigger and engine choice.** Use cheap streaming detectors on the hot buffer (EWMA/robust-z per service RED metric) to *trigger* the heavier window RCA. Don't stream the whole RCA. A dedicated streaming engine (Flink, Bytewax, Arroyo) is overkill for a 1-month demo; I did not research them.
- **If a queue is needed.** Redis Streams with `XADD`/`XREADGROUP` is likely the fastest for Python students. NATS JetStream gives better replay semantics. Both are optional; document the interface so it can be swapped.

### Gaps
- No 2026 head-to-head benchmark of Redis Streams vs NATS JetStream at small scale in Python was found.
- No source quantifies OTLP ingest throughput for a FastAPI/Python protobuf receiver. Measure it, and consider Granian/uvicorn workers if needed.

---

## A4. Capturing change events: Kubernetes events, deployments, config and feature-flag changes, Git commits

### Takeaway
Change events can be captured through OTel-native paths:
- The Collector **`k8sobjects` receiver** watches `events` and `deployments` and emits them as logs.
- The **CI/CD and VCS semantic conventions** (release candidate since v1.43.0) give a schema for deploy and commit events.
- **OpenFeature** maps flag *evaluations* to OTel log records. Flag *changes* surface as the provider event `PROVIDER_CONFIGURATION_CHANGED`, which may carry the changed flag keys.

OTel has **no finalized convention for flag-change events**. Veyltrace should define its own `change_event` table, `(ts, service, kind ∈ {deploy, config, flag, k8s_event, commit}, ref, attributes)`, and populate it from these sources.

### Cited Findings
- **`k8sobjects` receiver**:
  - configure `events` with `mode: watch`, and use pull mode for objects like pods — [OpenShift docs](https://docs.openshift.com/container-platform/4.13/observability/otel/otel-collector/otel-collector-receivers.html); [Splunk k8sobjects receiver](https://help.splunk.com/en/splunk-observability-cloud/manage-data/available-data-sources/supported-integrations-in-splunk-observability-cloud/opentelemetry-receivers/kubernetes-objects-receiver)
  - supported object types include **deployments, events, pods, services** — [Splunk: collect events](https://help-preview.splunk.com/en/splunk-observability-cloud/manage-data/splunk-distribution-of-the-opentelemetry-collector/get-started-with-the-splunk-distribution-of-the-opentelemetry-collector/collector-for-kubernetes/configure-events)
  - needs get/list/watch RBAC on `events` in both the core and `events.k8s.io` API groups — [OneUptime k8s metrics](https://oneuptime.com/blog/post/2026-02-06-collect-kubernetes-cluster-metrics-opentelemetry/markdown)
  - run as a single-replica Deployment to avoid duplicates — [KodeKloud OTCA notes](https://notes.kodekloud.com/docs/Prep-Course-OpenTelemetry-Certified-Associate-OTCA-Certification/OTel-Collector-Core-Components/OpenTelemetry-Collector-Receivers/page.md)
  - a separate `k8s_events` receiver also exists — [Splunk configure events](https://help.splunk.com/en/splunk-observability-cloud/manage-data/splunk-distribution-of-the-opentelemetry-collector/get-started-with-the-splunk-distribution-of-the-opentelemetry-collector/collector-for-kubernetes/configure-events)
- **Semantic conventions for changes** — [GitHub semconv releases](https://github.com/open-telemetry/semantic-conventions/releases):
  - v1.43.0 (Jul 2026) promoted "CI/CD span, metric, log, attribute, and entity conventions" and VCS to **release candidate**
  - `deployment.environment.name` became **stable** in v1.41.0
- **Feature-flag semantic conventions** are "in development". The current form is *Feature Flags in Events*, with attributes such as `feature_flag.key` and `feature_flag.result.variant` — [OTel semconv: feature flags](https://opentelemetry.io/docs/specs/semconv/feature-flags/); [feature-flags events](https://opentelemetry.io/docs/specs/semconv/feature-flags/feature-flags-events/)
- A community proposal for **feature-flag change events** notes they "may not be generated by SDKs or instrumentations, but by the feature flag management tools". It is not finalized — [open-telemetry/community #2042](https://github.com/open-telemetry/community/pull/2042)
- OpenFeature spec Appendix D maps OpenFeature fields to OTel feature-flag log records — [OpenFeature Appendix D](https://openfeature.dev/specification/appendix-d); [OpenFeature blog](https://openfeature.dev/blog/feature-observability-semantic-conventions)
- **OpenFeature provider events**:
  - `PROVIDER_CONFIGURATION_CHANGED` signals "a change was made to the backend flag configuration"
  - payloads may include the **list of changed flag keys**
  - support depends on the provider (e.g. Unleash maps its config-changed state to it)

  — [OpenFeature events spec](https://openfeature.dev/specification/sections/events); [OpenFeature events concept](https://openfeature.dev/docs/reference/concepts/events); [Unleash OpenFeature Node](https://docs.getunleash.io/sdks/openfeature/node)

  The flagd Elixir provider exposes `:configuration_changed` events — [hex: flagd provider](https://readme.hex.pm/open_feature_provider_flagd/0.1.0)

### Inferences
- **Demo change sources**, in a kind/k3d cluster or plain Docker Compose:
  1. **Deploys**: emit a CI/CD-semconv log record from a `make deploy` script (image tag, `vcs.ref.head.revision`, service), or watch `deployments` via `k8sobjects`.
  2. **Config/flags**: run flagd with a flag file. A small watcher subscribes to `PROVIDER_CONFIGURATION_CHANGED` from the Python OpenFeature SDK, or diffs the flag file in Git, and emits `change_event(kind=flag, keys=[…])`.
  3. **K8s events**: `k8sobjects` watch on `events` (OOMKilled, BackOff, FailedScheduling).
  4. **Git**: `git log --since` on the demo repo, or GitHub webhooks if cloud. Attach `vcs.*` attributes.
- **Evaluations carry ground truth.** Flag *evaluation* events on spans/logs (`feature_flag.key`/`variant`) are valuable RCA evidence. They show which requests took the new code path, which supports a "flag X variant B → 5xx" verifier check.
- **Kubernetes on laptops is optional.** Docker Compose plus synthetic change events from scripts is enough for the core demo. Adding kind for `k8sobjects` costs RAM (unmeasured).

### Gaps
- I could not confirm whether the **Python flagd provider** emits `PROVIDER_CONFIGURATION_CHANGED` with changed flag keys. Test it.
- No documented `k8sobjects` config example for watching **Deployment rollouts** specifically. It is inferred from the supported object types.
- I did not research Argo CD/Flux notification hooks as change sources.

---

## A5. Backend/API and UI choices for a small team (2026)

### Takeaway
Use **FastAPI + Pydantic v2** for the backend. It has the largest ecosystem and the most AI-coding-agent familiarity, and native SSE is already covered in the earlier notes. Litestar's advantages (msgspec, class controllers) don't justify the switch for 3 students.

Frontend: **React + TypeScript + Vite 8** (Rolldown, stable since Mar 2026), **ECharts 6.x** for time series, and **Cytoscape.js** for the analysis-oriented service/causal graph. Use React Flow (`@xyflow/react` 12.x) only if users edit graphs.

Generate TS types from FastAPI's OpenAPI with **openapi-typescript + openapi-fetch** (thin), or **@hey-api/openapi-ts** (full client). Use **uv workspaces** for Python and pnpm for the web app.

### Cited Findings
**FastAPI vs Litestar**
- FastAPI has the larger community and more examples for developers *and AI coding tools* — [Encore, 23 Oct 2026](https://encore.dev/articles/litestar-vs-fastapi). Litestar has fewer ready-made add-ons — [Better Stack](https://betterstack.com/community/guides/scaling-python/litestar-vs-fastapi/)
- Performance claims conflict:
  - One post finds Litestar slower in synthetic tests — [danilchenko.dev](https://www.danilchenko.dev/posts/fastapi-vs-litestar/).
  - Another claims about 2× lower latency — [Markaicode](https://markaicode.com/benchmarks/litestar-production-benchmark-latency/).
  - A Korean deep-dive attributes most of Litestar+Granian's TechEmpower advantage to **Granian**, with FastAPI on Granian roughly equal — [youngju.dev, May 2026](https://www.youngju.dev/blog/culture/2026-05-16-python-backend-frameworks-2026-fastapi-litestar-starlette-sanic-quart-robyn-django-ninja-blacksheep-deep-dive)

**Build tooling and charts**
- **Vite 8 stable was announced 12 Mar 2026.** Rolldown replaces esbuild + Rollup. `@vitejs/plugin-react` v6 uses Oxc for React Refresh, so Babel is no longer a dependency — [Vite 8 announcement](https://vite.dev/blog/announcing-vite8). **Rolldown 1.0 stable shipped May 2026** — [InfoQ, May 2026](https://infoq.com/news/2026/05/vite-v8-rust/); [VoidZero Rolldown RC](https://voidzero.dev/posts/announcing-rolldown-rc)
- **Apache ECharts 6** added beeswarm charts, scatter jitter, broken axis and custom-series charts, with breaking changes from v5 — [ECharts 6 features](https://echarts.apache.org/handbook/en/basics/release-note/v6-feature); [v5→v6 migration](https://www.mintlify.com/apache/echarts/migration/v5-to-v6). **ECharts 6.1.0 was released 19 May 2026** — [ASF release catalog](https://release-catalog.apache.org/echarts/6.1.0/index.html)
- **Graph libraries.** `@xyflow/react` is at **12.10.2 (27 Mar 2026)**; the legacy `reactflow` package is 11.x — [depscope @xyflow/react](https://mcp.depscope.dev/pkg/npm/@xyflow/react). A 2026 comparison frames React Flow for *authoring* and Cytoscape.js for *analysis*, and notes Cytoscape's breadthfirst and cose/fcose layouts suit dependency maps — [First AI Movers: React Flow vs Cytoscape](https://radar.firstaimovers.com/react-flow-vs-cytoscape-graph-engine-choice) (opinion piece)

**Typed contracts**
- FastAPI documents generating clients from its OpenAPI schema — [FastAPI: generate clients](https://fastapi.tiangolo.com/em/advanced/generate-clients)
- **openapi-typescript** is types-only and is usually paired with **openapi-fetch**, the smallest runtime. **Orval** generates TanStack Query hooks. **@hey-api/openapi-ts** generates full SDKs and has FastAPI walkthroughs; check nullable/optional field output — [PkgPulse 2026 comparison](https://www.pkgpulse.com/guides/orval-vs-openapi-typescript-vs-kubb-openapi-client-2026); [Classmethod: FastAPI × hey-api](https://dev.classmethod.jp/articles/fastapi-hey-api-openapi-ts/)
- The old `openapi-typescript-codegen` was discontinued, and its maintainers point to @hey-api/openapi-ts — [npm @hey-api/openapi-ts](https://npmjs.com/package/@hey-api/openapi-ts)

**Monorepo**
- **uv workspaces** give a single lockfile, a shared venv and cross-package resolution. Apache Airflow runs **120+ Python distributions** from one repo on uv workspaces (FOSDEM 2026) — [pydevtools FOSDEM talk](https://pydevtools.com/blog/fosdem-talk-modern-python-monorepo/); [pydevtools uv workspace how-to](https://pydevtools.com/handbook/how-to/how-to-set-up-a-python-monorepo-with-uv-workspaces/)

### Inferences
- **Repo layout:**
  - `packages/veyltrace-core` (pure RCA, no I/O)
  - `packages/veyltrace-ingest` (OTLP receiver, buffer)
  - `apps/api` (FastAPI)
  - `apps/web` (Vite/React, pnpm)
  - `contracts/` (Pydantic models → `openapi.json` → generated `web/src/api/types.ts`)

  Root `pyproject.toml` declares the uv workspace, and `pnpm-workspace.yaml` covers web only.
- **Contract discipline.** Pydantic v2 models are the single source of truth. CI runs `python -m apps.api.export_openapi > contracts/openapi.json` and then `openapi-typescript`. CI fails if the git diff is non-empty, which catches contract drift. This fits the repo's "frozen contracts" rule.
- **Charts.** Use ECharts for metric panels with baseline bands, `markLine` onsets and `markArea` anomalies (techniques in the earlier notes). Use Cytoscape.js for the service graph with root-cause highlighting and propagation-path edges. React Flow is unnecessary unless users edit graphs.
- **Vite and ECharts versions.** Vite 8 + plugin-react v6 removes Babel. Pin versions, because Vite 8's Rolldown may break custom Rollup plugins (not needed here). ECharts 6 has breaking changes from v5, so AI agents trained on v5 examples may generate outdated options. Pin 6.1 and review the generated code.

### Gaps
- I did not verify current versions of React (19.x), Cytoscape.js, pnpm or Pydantic as of Oct 2026.
- No source on how to combine uv + pnpm in one repo (task runner: `just`/`make`/`turbo`). The layout above is an inference.
- No benchmark of Cytoscape.js vs React Flow at RCA graph sizes (tens to hundreds of nodes; likely trivial for either).

---

## A6. Packaging, reproducibility and CI on the GitHub Actions free tier

### Takeaway
Combine `uv.lock` (Python), `pnpm-lock.yaml` (web), a multi-stage Docker image, and a `docker compose` demo profile. This gives a one-command reproducible demo (the uv/Docker recipe is in the earlier notes).

Under the 2026 billing model, the GitHub **Free plan includes $12/month of Actions compute**. That is about **2,000 Linux 2-core minutes** at $0.006/min, or 1,200 Windows minutes at $0.010/min. **Public repos run free on standard runners.** If the repo can be public, CI cost is a non-issue.

### Cited Findings
- **GitHub Actions billing** — [GitHub Docs: Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions):
  - Included monthly compute: **Free $12, Pro $18, Team $18, Enterprise Cloud $300**
  - Standard runner rates per minute: Linux 1-core **$0.002**, Linux 2-core **$0.006**, Linux 2-core arm64 **$0.005**, Windows 2-core **$0.010**, macOS **$0.062**
  - **Public repos**: standard GitHub-hosted runners are free
  - Artifact storage: Free plan 500 MB. Cache: **10 GB per repo**
- Hosted-runner price cuts took effect **1 Jan 2026**. The planned **$0.002/min platform charge for self-hosted runners** (originally from 1 Mar 2026) was **postponed** to "re-evaluate our approach" — [GitHub changelog, Dec 2025](https://github.blog/changelog/2025-12-16-coming-soon-simpler-pricing-and-a-better-experience-for-github-actions/). A third-party guide (Aug 2026) claims the fee is in effect, which conflicts with GitHub's current docs (self-hosted is free) — [thepricer](https://www.thepricer.org/how-much-does-github-actions-cost/)

### Inferences
- **CI plan.** Run CI on `ubuntu-latest` only; don't add Windows CI unless a Windows-specific bug appears. A lean pipeline should take about 3–6 min per run (estimate):
  - `uv sync --locked`
  - `ruff` + `pytest -q` on golden fixtures
  - `pnpm i --frozen-lockfile` + `tsc --noEmit` + `vitest`
  - the contract-drift check

  At 6 min/run, a private repo on the Free plan allows about 330 runs a month. Cache `~/.cache/uv` and the pnpm store (10 GB per repo cache limit).
- **Reproducibility hooks to keep from v1:** a sha256 run manifest, exact quantiles, sorted tie-breaks, DuckDB `threads=1` for final scoring, and the LLM outside the decision path. Extend them to **live** mode by snapshotting each analysed window to Parquet before scoring.
- **Devcontainer and Nix.** A `.devcontainer/devcontainer.json` with uv + Node + Docker-in-Docker would equalize the three Windows laptops. Nix adds learning cost with little payoff on Windows/WSL for a 1-month build. This is judgement; I did not research it.

### Gaps
- I did not research devcontainer feature images or Nix on WSL2.
- I did not check GitHub Actions **ubuntu-latest image version** or Docker layer caching limits.

---

## B1. The 2025–2026 AI RCA / "AI SRE" landscape: claims, pricing, openness, evidence of accuracy, practitioner complaints

### Takeaway
By Oct 2026 every hyperscaler and observability major ships an AI SRE agent:
- **AWS DevOps Agent**: GA Mar 2026, $0.0083/agent-second
- **Azure SRE Agent**: GA ~Aug 2026, billed in Azure Agent Units
- **Datadog Bits AI SRE**
- **Dynatrace Intelligence** (Jan 2026)
- **New Relic SRE Agent / Autopilot** (Feb and Jun 2026)
- **Grafana Assistant Investigations**: GA Jul 2026, billed from 1 Oct 2026
- **PagerDuty SRE Agent**: staged early access through 2026

Google's **Gemini Cloud Assist investigations** remain in preview.

Well-funded startups compete hard, led by Resolve AI (~$1–1.5B valuation) and Traversal (Fortune-100 deployments).

Open-source options are **HolmesGPT** (CNCF Sandbox, Oct 2025), **k8sgpt** (CNCF Sandbox, 2023), **Coroot** (Apache-2.0 core, AI RCA paid or cloud-assisted) and **Rootly AI Labs** benchmarks.

Vendor accuracy claims of 90–95% are all **self-reported**. Independent benchmarks show agents fully resolve **≤42%** of SRE scenarios (ITBench-AA) and recover the exact root-cause set in only **~21%** of cases (OpenRCA 2.0). The dominant practitioner concern is **trust**: 60% cite it as the main barrier, and 59% want near-perfect accuracy.

### Cited Findings

#### Hyperscalers

**AWS DevOps Agent** (GA 31 Mar 2026; earlier notes)
- Pricing — [AWS DevOps Agent pricing](https://aws.amazon.com/devops-agent/pricing/):
  - **$0.0083 per agent-second** (≈$29.88/agent-hour) for investigations, evaluations and on-demand SRE tasks, billed only for active time
  - 2-month trial with 20 h investigations, 15 h evaluations and 20 h on-demand per month, up to 10 agent spaces
  - examples: 10 investigations × 8 min = **$39.84/month**; 500 incidents + evaluations + tasks = **$2,365.50/month**
  - AWS Support spend converts to DevOps Agent credits (30–100% depending on support tier)
  - connected services such as CloudWatch Logs Insights are billed separately
- AWS docs note there is **no built-in spending cap**. Use Budgets or Cost Explorer — [AWS re:Post](https://www.repost.aws/articles/ARCVOaW7ZDSjeLYPl5nMeeVg/how-do-i-monitor-and-control-aws-devops-agent-costs)

**Azure SRE Agent**
- A Microsoft update (AZ569760, 26 Aug 2026) lists **GA plus a 30-day trial**. Customers "pay only for Azure Agent Units (AAUs) consumed" — [M365/Azure message center mirror](https://mc.merill.net/message/AZ569760)
- Pricing pages describe a fixed always-on component plus a token-based active component. One version says **4 AAU/hour baseline per agent + 0.25 AAU/second per task**. Some locale pages still say "preview" — [Azure SRE Agent pricing](https://azure.microsoft.com/en-us/pricing/details/sre-agent/)
- I found no dollar price per AAU.

**Google Gemini Cloud Assist investigations**
- **Still "Public preview"**. There is no charge in preview, and "charges will apply when it becomes generally available" — [Gemini Cloud Assist product page](https://cloud.google.com/products/gemini/cloud-assist?hl=en); [Managed Spark docs](https://docs.cloud.google.com/managed-spark/docs/guides/ai-investigations-with-gca)
- Apr 2026: creating investigations was restricted to Premium Support customers or those granted access by their account team. May 2026: added background investigations on alert and cost triggers — [Gemini for Google Cloud release notes](https://docs.cloud.google.com/gemini/docs/release-notes?hl=es)

#### Observability majors

**Datadog Bits AI SRE**
- The press release (2 Dec 2025) calls it Generally Available to all Datadog users. iTWire reported "Limited Availability", so sources conflict — [Datadog press release](https://www.datadoghq.com/about/latest-news/press-releases/datadog-launches-bits-ai-sre-agent-to-resolve-incidents-faster/); [iTWire](https://itwire.com/business-it-news/data/datadog-launches-bits-ai-sre-agent-to-resolve-incidents-faster)
- The 5 Mar 2026 "deeper reasoning" update claims it is "more accurate on internal benchmarks" and "approximately twice as fast", **with no figures**. It evaluates competing hypotheses and was tested against 2,000+ customer environments — [Datadog blog: deeper reasoning](https://datadoghq.com/blog/bits-ai-sre-deeper-reasoning)
- Pricing (AI credits, ~6.5 credits per investigation) is in the earlier notes.

**Dynatrace Intelligence** (Perform 2026, 28 Jan 2026)
- "Fuses deterministic and agentic AI": Davis causal RCA over the Smartscape topology plus domain agents for SRE, dev and security, with MCP-based developer tooling — [Dynatrace press release](https://www.dynatrace.com/news/press-release/dynatrace-intelligence-redefines-observability/); [Business Wire](https://www.businesswire.com/news/home/20260128774932/en)
- Dynatrace says Davis RCA analyses more than 3M problems every 24 h — [Dynatrace blog](https://www.dynatrace.com/news/blog/shaping-the-future-autonomous-intelligence)
- This is still a closed platform tied to OneAgent/Grail.

**New Relic**
- SRE Agent preview (24 Feb 2026): "deterministic analytical methods with AIOps functions". Intelligent RCA searches a **topology graph** with probabilistic ranking — [New Relic press release](https://newrelic.com/press-release/20260224)
- New Relic's own docs say suggested interventions "should be reviewed by an engineer before implementation" — [New Relic SRE Agent docs](https://docs.newrelic.com/docs/agentic-ai/sre-agent/overview/)
- **Autopilot** (an automated SRE agent) and **Ground Truth** (data for custom agents) were announced 23 Jun 2026 — [New Relic press release, Jun 2026](https://newrelic.com/pt/press-release/20260623-2)

**Grafana Labs**
- Grafana Assistant reached GA and Assistant Investigations entered public preview on 8 Oct 2025 — [Grafana press release, Oct 2025](https://grafana.com/press/2025/10/08/grafana-labs-revolutionizes-ai-powered-observability-with-ga-of-grafana-assistant-and-introduces-assistant-investigations/)
- **Investigations reached GA 29 Jul 2026** — [Grafana what's new](https://grafana.com/whats-new/2026-07-29-assistant-investigations-is-now-generally-available-in-grafana-cloud/)
- **Metering started 1 Oct 2026**, billed in tokens from a shared per-user allowance — [Grafana Assistant pricing docs](https://grafana.com/docs/grafana-cloud/platform/pricing-and-usage/assistant/)
- A third-party tracker reports a 40M tokens/user/month allowance (unverified) — [UsagePricing](https://usagepricing.com/blueprint/grafana)

**PagerDuty**
- The AI agent suite launched 8 Oct 2025, with GA projected for Q4 2025 — [Business Wire, Oct 2025](https://www.businesswire.com/news/home/20251008279706/en/PagerDuty-Launches-Industrys-First-End-to-End-AI-Agent-Suite-Slashing-Incident-Response-Times-and-Empowering-Teams-to-Innovate)
- The Spring 2026 release (12 Mar 2026) positions the **SRE Agent as a "virtual responder"** placed in schedules and escalation policies:
  - virtual-responder early access in Q2 2026
  - fully autonomous version in early access in H2 2026
  - interoperates with AWS DevOps Agent and Azure SRE Agent

  — [PagerDuty newsroom](https://pagerduty.com/newsroom/pagerduty-operations-cloud-spring-2026-release)
- From 5 Aug 2026 the agent can be triggered via incident workflows (GA), with escalation-policy triggering in EA — [PagerDuty blog](https://www.pagerduty.com/blog/ai/meet-your-virtual-responder-pagerdutys-sre-agent-for-ai-driven-reliability/)

#### Startups (closed source)

**Resolve AI**
- **$125M Series A at a $1B valuation**, confirmed 4 Feb 2026 — [TechCrunch, Feb 2026](https://techcrunch.com/2026/02/04/ai-sre-resolve-ai-confirms-125m-raise-unicorn-valuation/)
- A reported **$40M extension at $1.5B** (16 Apr 2026, DST Global and Salesforce Ventures) — [beri.net](https://www.beri.net/article/resolve-ai-190m-ai-sre-production-incidents-2026) (secondary)

**Traversal**
- Pitches "AI agents + causal machine learning" — [Traversal launch post](https://traversal.com/blog/launch-announcement)
- Amex Ventures made a strategic investment and American Express is deploying it — [Traversal: Amex announcement](https://www.traversal.com/blog/american-express-announcement)
- Incident Workers went GA and Alert Workers launched in 2026 — [01net/Business Wire](https://www.01net.it/traversal-makes-incident-workers-generally-available-and-launches-alert-workers/)
- A Cloudways executive's ">95% accuracy" is a customer testimonial, not a benchmark — [Traversal launch post](https://traversal.com/blog/launch-announcement)
- Traversal publicly argues that OpenRCA scores are not a proxy for enterprise RCA — [Traversal blog: OpenRCA isn't RCA](https://www.traversal.com/blog/openrca-isnt-root-cause-analysis-why-that-matters)

**Causely**
- The causal-reasoning engine is proprietary. The MCP server launched Nov 2025 — [press release via FinancialContent](https://markets.financialcontent.com/dowtheoryletters/article/bizwire-2025-11-6-causely-introduces-mcp-server-for-automated-remediation-across-kubernetes-and-application-code)
- It was upgraded at AGNTCon + MCPCon NA 2026 and is listed in the GitHub MCP Registry. It works with Claude Code, Cursor, Codex and **HolmesGPT**. Background-agent examples are open-sourced at github.com/causely-oss — [01net/Business Wire](https://www.01net.it/?p=9017920894)

**Komodor Klaudia**
- Claims ">95%" RCA accuracy and 50+ specialized agents. Both are self-reported with no published methodology — [Komodor blog](https://komodor.com/blog/komodor-ai-sre-vs-oss-ai-agent-a-technical-comparison-of-agentic-ai-for-kubernetes-troubleshooting/); [Komodor vs Azure SRE Agent](https://komodor.com/compare/compare-komodor-vs-azure-sre-agent/)
- Klaudia Memory launched Jul 2026 — [Komodor blog](https://komodor.com/blog/klaudia-memory-launch/)

**incident.io**
- "90%+" accuracy is self-reported and unvalidated — [Augment Code review](https://www.augmentcode.com/tools/best-ai-sre-tools). Another guide gives 94% with no methodology — [NeuBird](https://neubird.ai/blog/top-ai-sre-tools)
- The product exposes "supporting sources and rejected theories" — [ai.engineer profile](https://www.ai.engineer/orgs/incident-io)
- It uses post-incident "time travel" evals — [Product Talk](https://www.producttalk.org/when-ai-becomes-your-sre-how-incident-io-is-automating-incident-response/)

#### Open source

**HolmesGPT** (Robusta)
- **CNCF Sandbox (accepted Oct 2025)**, with major contributions from Microsoft. It works through toolsets, MCP servers, runbooks and custom evals, uses any OpenAI-compatible LLM including local models, and reads Prometheus, K8s events, logs and pod specs — [CNCF blog, 7 Jan 2026](https://www.cncf.io/blog/2026/01/07/holmesgpt-agentic-troubleshooting-built-for-the-cloud-native-era/)
- Licensed **Apache-2.0** — [HolmesGPT README mirror](https://gitee.com/ymjake/holmesgpt)
- The CNCF post gives **no accuracy results** and does not discuss hallucination safeguards.

**k8sgpt**
- CNCF Sandbox since **19 Dec 2023** — [k8sgpt.ai](https://k8sgpt.ai)
- Latest release **v0.4.35 (1 Jul 2026)**, bug fixes only — [newreleases](https://newreleases.io/project/github/k8sgpt-ai/k8sgpt/release/v0.4.35)
- Rule-based analyzers (14+ default) plus LLM explanation — [stackpick](https://stackpick.net/tools/k8sgpt/)

**Coroot**
- AI RCA is in Enterprise (**from $1/CPU core/month**) or for Community Edition via Coroot Cloud (**10 free investigations/month**). Coroot "sends only its findings to the selected model, not all the raw telemetry", explicitly to avoid relying on LLMs for the RCA itself — [Coroot AI docs](https://docs.coroot.com/ai/overview)
- Blog, 30 Jun 2026 — [Coroot blog](https://coroot.com/blog/hard-part-of-ai-root-cause-analysis-is-no-longer-the-model/):
  - "The hard part is the harness". A deterministic pipeline produces findings, and the model receives about 9.8K tokens with "no tools, no agent loop".
  - On **one** Chaos Mesh incident across 11 models, three frontier models passed, Gemma 4 31B was the only self-hostable pass, and cost ranged **$0.0012–$0.0743 per incident**.
  - The author concedes one incident is not a benchmark.

**Rootly AI Labs**
- All projects are Apache-2.0 — [Rootly docs: open source](https://docs.rootly.com/open-source/overview)
- **SRE-skills-bench** has 4 tests of about 1,200 samples per model and is now in Groq OpenBench — [Rootly blog](https://rootly.com/blog/rootly-joins-groq-openbench-with-an-sre-focused-benchmark)

#### Independent evidence on accuracy

Some of this may overlap with `sota_rca_methods.md`.
- **ITBench** (ICML 2025): agents resolved **13.8%** of SRE scenarios — [PMLR](https://proceedings.mlr.press/v267/jha25a.html)
- **ITBench-AA** (Artificial Analysis): top pass rate **41.81%** (Claude Opus 4.7, about 68 turns), and "pass rates remain below 42%" — [Artificial Analysis ITBench-AA](https://artificialanalysis.ai/evaluations/itbench-aa)
- **OpenRCA 2.0** (Jun 2026, 500 instances): across 11 LLMs, the exact root-cause set was recovered **20.7%** on average. At least one correct service was found **76.0%** of the time, but grounded in a verified propagation path only **61.5%** — [papers.cool arXiv 2606.27154](https://papers.cool/arxiv/2606.27154)
- **ORCA-bench** (Jul 2026): best RCA accuracy **25.3%** (Medium) and **10.0%** (Hard) across Opus 4.7, Sonnet 4.6, GPT-5.5, GLM-5 and DeepSeek-V4-Pro — [alphaXiv 2607.28545](https://www.alphaxiv.org/abs/2607.28545.md)

#### Practitioner sentiment

The Register × NeuBird survey (Apr 2026, n=696), via a NeuBird-sponsored article — [The Next Platform, 15 Jul 2026](https://nextplatform.com/control/2026/07/15/sres-to-ai-agents-prove-yourself-before-you-touch-production/5271533):
- **73%** are not using AIOps, 19% are piloting and 8% are in production
- **60%** cite lack of trust as the main barrier
- **59%** require near-perfect accuracy; about 30% accept ~80%
- **62%** prefer a co-pilot
- 75% want answers within 10 minutes
- **52% would switch telemetry tools if AI insights worked across any back-end**

Other signals:
- Rootly (15 Sep 2026), from a vendor: agents work for summaries, similar-incident retrieval and **deploy↔regression correlation**. They fail at novel failures, give "a plausible cause delivered with the same tone as a correct one", and point elsewhere when a cause is uninstrumented — [Rootly blog](https://rootly.com/blog/do-ai-sre-agents-actually-work)
- Xurrent (8 Oct 2026, vendor): SREs at SREDay Bangalore (8 people, informal) all said no to letting agents change production. Wanted: reasoning shown before action, reversible actions, measurable performance. Also relays Gartner's prediction that human-in-the-loop in IT ops falls from 95% (2025) to 40% (2028) — [Xurrent blog](https://www.xurrent.com/blog/ai-sre-agent-survey)
- CSO Online's view: "supervised-by-design", not autonomous-by-default — [CSO Online](https://www.csoonline.com/article/4183666/what-sre-teams-need-before-they-trust-ai-agents.html)
- InfoWorld: fluent agents lacking context "sound convincing" while giving dangerous advice — [InfoWorld](https://www.infoworld.com/article/4195114/how-to-teach-sre-ai-agents-to-fail-safely-and-earn-your-teams-trust.html)

### Inferences
- **Pricing has converged on usage-metered agent time or tokens:** AWS per agent-second, Azure AAUs, Grafana tokens, Datadog credits. A free, local, deterministic engine has a clear cost contrast. The AWS example works out to ~$4 per 8-minute investigation.
- **"Deterministic core + LLM narration" is no longer unique.** Dynatrace, New Relic ("deterministic analytical methods"), Coroot ("findings only to the LLM") and k8sgpt (analyzers + LLM) all use it. Veyltrace must differentiate on *openness, reproducibility, verifiability and published evaluation*, not on the architecture alone.
- **Every vendor's 90–95% accuracy number is unaudited.** Independent benchmarks sit at 10–42%. A public, reproducible scorecard (per dataset, per fault type, with failure cases) would be rare in this market.
- **The interoperability layer is MCP.** AWS uses BYO-MCP (earlier notes), Causely an MCP server, Dynatrace MCP tooling, and HolmesGPT toolsets via MCP. Exposing Veyltrace as an MCP evidence/verification server lets it *complement* agents rather than compete head-on.

### Gaps
- No per-AAU dollar price for Azure SRE Agent. Its GA status conflicts across Microsoft pages.
- No GA date for Gemini Cloud Assist investigations; it is still preview as of the latest found notes (May 2026).
- No PagerDuty Fall 2026 launch details, so whether the SRE Agent is GA is unconfirmed.
- No independent, cross-vendor accuracy evaluation exists. All product accuracy numbers are self-reported or testimonials.
- Resolve AI's $1.5B extension is from a secondary source only. I did not research Cleric's 2026 product claims, Splunk ITSI/Elastic AI or NeuBird in depth.
- I found no Reddit or Hacker News practitioner threads in this session. Sentiment comes from surveys and trade press, several of them vendor-sponsored.

---

## B2. What gap can an open, reproducible, verifier-backed RCA engine credibly own?

### Takeaway
The defensible gap is **"auditable, reproducible RCA evidence that any agent or human can verify, run locally on open telemetry, with published accuracy."** No commercial or OSS product found offers all of the following together:
1. an OTLP-native, backend-neutral engine that runs on a laptop
2. deterministic, replayable diagnoses with a run manifest
3. per-claim **verifiers** that check each hypothesis against telemetry and change events, with abstention
4. **public benchmark scores with failure cases**
5. an **MCP/HTTP interface** so commercial AI SRE agents can call it as a grounding and verification layer.

### Cited Findings
- Trust is the top adoption barrier (60%) and 59% require near-perfect accuracy. **52% would switch telemetry tools for AI that works across any back-end** — [The Next Platform (NeuBird-sponsored), Jul 2026](https://nextplatform.com/control/2026/07/15/sres-to-ai-agents-prove-yourself-before-you-touch-production/5271533)
- Independent agent accuracy is low: ITBench-AA <42% — [Artificial Analysis](https://artificialanalysis.ai/evaluations/itbench-aa). OpenRCA 2.0 gives 20.7% for the exact set and only 61.5% for causal-path grounding — [papers.cool](https://papers.cool/arxiv/2606.27154)
- Vendors' own docs require human review of agent suggestions (New Relic) — [New Relic docs](https://docs.newrelic.com/docs/agentic-ai/sre-agent/overview/). incident.io exposes "rejected theories" — [ai.engineer](https://www.ai.engineer/orgs/incident-io). Rootly advises buyers to ask vendors to "show it being wrong" — [Rootly blog](https://rootly.com/blog/do-ai-sre-agents-actually-work). This shows market demand for falsifiable evidence.
- Coroot argues the bottleneck is the harness (data preparation), not the model — [Coroot blog](https://coroot.com/blog/hard-part-of-ai-root-cause-analysis-is-no-longer-the-model/)
- Open-source competitors (HolmesGPT, k8sgpt) are **LLM-centric, Kubernetes-centric agents** with no published accuracy results — [CNCF HolmesGPT blog](https://www.cncf.io/blog/2026/01/07/holmesgpt-agentic-troubleshooting-built-for-the-cloud-native-era/); [k8sgpt](https://k8sgpt.ai). Coroot's AI RCA is paywalled or cloud-metered — [Coroot docs](https://docs.coroot.com/ai/overview)
- Major platforms remain lock-in-shaped: Dynatrace Smartscape/Grail, Datadog Bits, Grafana Cloud tokens — [Dynatrace](https://www.dynatrace.com/news/press-release/dynatrace-intelligence-redefines-observability/); [Grafana pricing docs](https://grafana.com/docs/grafana-cloud/platform/pricing-and-usage/assistant/)
- Change correlation ("deploy ↔ regression") is one of the few tasks practitioners say AI SRE tools reliably help with — [Rootly blog](https://rootly.com/blog/do-ai-sre-agents-actually-work). OTel now has RC-level CI/CD and VCS conventions to standardize it — [semconv releases](https://github.com/open-telemetry/semantic-conventions/releases)

### Inferences
**Positioning statement (draft):** "Veyltrace is the open, reproducible evidence engine for incident RCA. It ingests OTLP and change events, ranks root-cause candidates deterministically, and attaches machine-checkable verdicts to every claim: *supported*, *refuted* or *insufficient data*. Diagnoses replay bit-for-bit from a manifest, and the engine's accuracy is published on public benchmarks. Use it directly, or plug it into your AI SRE agent via MCP to ground and verify that agent's hypotheses."

**What to claim:**
- **Reproducibility.** Every live diagnosis is snapshotted and replayable, which no vendor offers publicly.
- **Verifiability.**
  - Each hypothesis carries explicit checks: temporal precedence via ASOF (change before onset), propagation-path consistency on the span graph, and a counterfactual/peer comparison (other instances or flag variants unaffected).
  - Abstention when evidence is insufficient directly addresses the "confident wrong answer" complaint.
- **Published scorecard.** Report AC@k/Avg@k on RCAEval and similar public datasets, and include failure cases. The honest numbers contrast with unaudited 90–95% vendor claims and with the 10–42% agent results on independent benchmarks.
- **Backend-neutral, laptop-runnable, $0 marginal cost.** Compare with $0.0083/agent-second (AWS) and token or credit metering elsewhere.
- **Complement, not competitor.** An MCP tool such as `verify_hypothesis(service, cause, window)` lets HolmesGPT, AWS DevOps Agent and others call Veyltrace. This mirrors how Causely sells "causal intelligence for agents", but open.

**What not to claim:**
- "First deterministic/causal RCA". Dynatrace, Causely, Traversal and New Relic already pitch it.
- "Autonomous remediation".
- Accuracy numbers beyond what the team's own benchmark runs show.

**Risk.** Coroot and HolmesGPT could add reproducibility or verifier features. The moat is research rigor (benchmarks, verifier design, a published evaluation harness), not code.

### Gaps
- I found no product that exposes "per-claim verifiers with abstention" publicly. That absence comes from these searches, not an exhaustive review; the closest public feature is incident.io's "rejected theories".
- No market data quantifies demand for *reproducible* RCA specifically. The trust and accuracy figures are the closest proxy.
- No data on whether AI SRE vendors would integrate third-party MCP verification tools. AWS BYO-MCP and Causely↔HolmesGPT compatibility suggest it is technically feasible.
