# RCAEval and benchmark facts (committed extract)

> Benchmark, method and tooling facts the v2 engine specs cite, extracted 2026-10-30 from the v1 research session (sources read 22 Oct 2026; those notes are not in git). Every fact keeps its **primary source**. "Our count" = computed from the official `cases.parquet` index ([HF datasets-server](https://datasets-server.huggingface.co/rows?dataset=phamquiluan/RCAEval&config=cases&split=train)). "Design rule" = a Veyltrace choice with no published result behind it.
> Abbreviations: OB Online Boutique, SS Sock Shop, TT Train Ticket. Paper = [RCAEval arXiv 2412.17015 v5](https://arxiv.org/pdf/2412.17015v5); README = [RCAEval GitHub](https://github.com/phamquiluan/RCAEval); HF card = [Hugging Face dataset card](https://huggingface.co/datasets/phamquiluan/RCAEval); PRISM = [arXiv 2601.21359](https://arxiv.org/html/2601.21359) (single-author preprint, no code released).

## Datasets and telemetry per system

| Dataset | Cases | Faults | Metrics / case | Logs | Traces |
|---|---|---|---|---|---|
| RE1-OB / SS / TT | 125 each | cpu, mem, disk, delay, loss | 49–59 / 57–63 / 198–238 | no | no |
| RE2-OB / SS / TT | 90 each | the 5 above + socket | 69–77 / 74–82 / 340–376 | yes (RE2-TT: 89 of 90) | OB and TT only |
| RE3-OB / SS / TT | 30 each | code faults f1–f5 (OB), f1–f4 (SS, TT) | 68–101 / 80–107 / 294–322 | yes | OB and TT only |

Source: README table; RE2-TT log count: HF card.

- 735 cases. RE1 = 5 faults × 5 services × 5 repetitions per system; RE2 = 6 × 5 × 3 (README). RE3 is not a uniform grid (HF card).
- RE3 codes: F1 incorrect parameter values, F2 missing parameters, F3 missing function call, F4 incorrect return values, F5 missing exception handlers (paper §3.2).
- **Sock Shop has no traces anywhere**: "I couldn't make the tracing work with my setup" ([issue #70](https://github.com/phamquiluan/RCAEval/issues/70)).
- System sizes: OB 12 services (gRPC), SS 15 (HTTP), TT 64 (paper §3.1).
- Faults: `stress-ng` for cpu, mem, disk, socket; Linux `tc` for delay and loss; source mutation for code faults. Load 10–200 requests/s; metrics from Prometheus, cAdvisor and Istio; logs via Vector/Loki; traces via Jaeger (paper §3.2–3.3).

## Dataset layout

Three physical layouts:

- **Zenodo** record 14590730 (read by `main.py`): `data/RE{n}/RE{n}-{SYS}/{service}_{fault}/{rep}/`. RE1: `data.csv` + `inject_time.txt`. RE2/RE3: `simple_metrics.csv` (clean), `metrics.csv` (raw), `logs.csv`, `traces.csv`, `inject_time.txt`, plus extras (`pod-node-*.csv`, `*.png`, `*.log`) ([RE3-SS preview](https://zenodo.org/records/14590730/preview/RE3-SS.zip); [issue #80](https://github.com/phamquiluan/RCAEval/issues/80)). `main.py` maps RE1 to the older ASE'24 record 13305663 ([main.py](https://github.com/phamquiluan/RCAEval/blob/main/main.py)).
- **Hugging Face** Parquet: `{suite}{system}_{service}_{fault}_{rep}/` (e.g. `re2tt_ts-order-service_cpu_1/`) with `metrics.parquet` (`time` int64 + one float64 column per metric), `logs.parquet`, `traces.parquet`, `inject_time.txt`, plus a `cases.parquet` index holding the ground truth. Conversion is lossless: metric timestamps are unioned, never resampled or filled; unobserved points are null; trace/span IDs stay strings (HF card, "Layout" and "Format note").
- **figshare** 31048672 `RCAEval-v2.zip`: `{benchmark}_{service}_{fault}_{instance}/` with `metrics.json`, `logs.csv`, `traces.csv`, `inject_time.txt` ([figshare API](https://api.figshare.com/v2/articles/31048672)).

Columns and units:

- **Metrics**, wide, one row per second: `time` + `{service}_{cpu|mem|diskio|socket|workload|error|latency-50|latency-90}` ([legacy/simple_metrics.csv](https://github.com/phamquiluan/RCAEval/blob/main/legacy/simple_metrics.csv)). RE1 has no `_diskio` or `_socket` ([issue #77](https://github.com/phamquiluan/RCAEval/issues/77)). `mem` is bytes; latency p90 is `histogram_quantile(0.90, …istio_request_duration_milliseconds_bucket…[1m]) / 1000`, i.e. seconds over a trailing minute ([issue #80](https://github.com/phamquiluan/RCAEval/issues/80)). The CPU unit is undocumented (unverified). Raw `metrics.csv` holds series such as `ts-ui-dashboard_istio-latency-90` (issue #80).
- **Logs**: `time` (HH:MM string), `timestamp` (ns), `container_name`, `message`, … ; a multi-line stack trace sits in one `message` cell ([multi-source-rca-demo.ipynb](https://github.com/phamquiluan/RCAEval/blob/main/docs/multi-source-rca-demo.ipynb); [code-level-rca.ipynb](https://github.com/phamquiluan/RCAEval/blob/main/docs/code-level-rca.ipynb)).
- **Traces**: `time`, `traceID`, `spanID`, `serviceName`, `methodName`, `operationName`, `startTimeMillis` (ms), `startTime` (µs), `duration` (µs), `statusCode`, `parentSpanID` (NaN for roots) (multi-source notebook). OB traces call the frontend `frontendservice`, metrics and logs call it `frontend`; RCAEval's own PDiagnose remaps it ([e2e/pdiagnose.py](https://github.com/phamquiluan/RCAEval/blob/main/RCAEval/e2e/pdiagnose.py)).
- **`inject_time.txt`**: one 10-digit Unix timestamp in seconds, read with `int(f.readlines()[0].strip())` (main.py).
- Derived `logts.csv`, `tracets_err.csv`, `tracets_lat.csv` aggregate at 15 s ([docs/TORAI.md](https://github.com/phamquiluan/RCAEval/blob/main/docs/TORAI.md)).

## Ground truth and scoring

- **The label is the folder name** `{root_cause_service}_{fault}` ([issue #49](https://github.com/phamquiluan/RCAEval/issues/49); HF card). The only label files are HF `cases.parquet` and an optional `root_cause.txt` in 8 RE3-SS cases.
- Method contract: `f(data, inject_time, dataset, **kwargs) -> {"ranks": [...]}`, each rank `"{service}_{indicator}"` ([docs/EXTENDING.md](https://github.com/phamquiluan/RCAEval/blob/main/docs/EXTENDING.md)).
- Coarse (service) scoring uses `x.split("_")[0].replace("-db", "")`, deduplicated, order kept; fine scoring compares `(service, x.split("_")[1])`. Fine answers: cpu → `cpu`, mem → `mem`, delay → `latency`, **loss → `latency`**, socket → `socket`, disk → `diskio` (`latency` on RE1) (main.py L559–618). So a service name must not contain `_`.
- AC@k = root in top k (one root per case); Avg@5 = mean of AC@1…AC@5 ([evaluation.py](https://github.com/phamquiluan/RCAEval/blob/main/RCAEval/benchmark/evaluation.py); paper §4.2). Printed results are service-level.
- **Oracle alert:** every method receives the injection time (`--tdelta` adds a detection lag); `--length 20` gives 10 min on each side (main.py L311–425).
- Chance AC@k = min(k, n)/n (`--report-chance`); `--report-decomposition K` prints Retrieval@K and Rerank@1 (evaluation.py).
- Reference baselines: BARO fits `RobustScaler` on the normal part and scores each column by its max transformed anomalous value; `nsigma` is the same with `StandardScaler` ([e2e/baro.py](https://github.com/phamquiluan/RCAEval/blob/main/RCAEval/e2e/baro.py); [e2e/\_\_init\_\_.py](https://github.com/phamquiluan/RCAEval/blob/main/RCAEval/e2e/__init__.py)).
- `main.py` never prints RE3 f1–f5 results (from reading main.py L579–662, not executed), so RE3 needs our own scorer.

## Metric step and windows

- Metrics are 1 s rows from Prometheus `query_range` with `step=1`, while Prometheus scraped every **15 s**, so values are step-held and change about every 15 s; gaps are NaN, never forward-filled (author, [issue #80](https://github.com/phamquiluan/RCAEval/issues/80), stated for RE2-TT; other suites likely used the same collector, unverified). mmBARO keeps every 15th row ([e2e/baro.py](https://github.com/phamquiluan/RCAEval/blob/main/RCAEval/e2e/baro.py)).
- Rows before / after injection at 1 s (our count): RE2 and RE3-OB/SS 720/721 (12 + 12 min); RE3-TT 900/901; RE1-OB/SS 360/361; RE1-TT 480/481 (some 360); 48 RE1-OB cases 2100/2101.
- Pre-injection data may be used as fault-free data ("Yes, that's what you should do"); one failure per case ([issue #49](https://github.com/phamquiluan/RCAEval/issues/49)).
- Per-case medians (our count): logs RE2-OB ≈ 175k, RE2-SS ≈ 86k, RE2-TT ≈ 268k lines; spans RE2-OB ≈ 399k, RE2-TT ≈ 778k (max 1.54 M). Per system, RE2 has 8.6–26.9 M log lines and 39.6–76.7 M traces (paper Table 2).
- Timestamps are Unix epoch UTC: seconds (metrics, `inject_time`), ns (log `timestamp`), µs (trace `startTime`, `duration`) (multi-source notebook).
- RE2-TT campaign: faults last 12 min; the next case starts ≈ 1.5 min later with no return-to-baseline check; pods are not restarted (issue #80).

## Downloads and licence

- HF `phamquiluan/RCAEval`: 3.44 GB in total; per-case median RE2-OB 10.7 MB, RE2-SS 1.1 MB, RE2-TT 23.0 MB (max 38.7 MB) ([HF tree API](https://huggingface.co/api/datasets/phamquiluan/RCAEval/tree/main?recursive=true)). Zenodo 14590730 zips total ≈ 5.2 GB and expand to ≈ 38 GB (README; [Zenodo API](https://zenodo.org/api/records/14590730)).
- Licence: code MIT; data MIT on HF and figshare, **CC BY 4.0 on Zenodo** (Zenodo API); cite the RCAEval paper either way.
- Harness Python: `main.py` exits unless Python is 3.8, 3.12 or 3.14; RCD and TORAI need a separate 3.8 env (main.py L41–89). A plain `pip install RCAEval` installs no dependencies; use the `[default]` extra ([setup.py](https://github.com/phamquiluan/RCAEval/blob/main/setup.py)).

## Data quirks

- `re1ob_currencyservice_loss_1` has an 8-digit `inject_time` (0 normal rows); `re1ob_productcatalogservice_cpu_3` has its inject time after the data ends; 4 cases have truncated anomaly windows (our count).
- `re2tt_ts-auth-service_cpu_1` has no logs; 3 RE1 and 13 RE3-SS cases ship a header-only `logs.csv` or `traces.csv` (HF card, "Known data notes").
- RE3-TT on Zenodo had a folder `ts-route-service_f6` that is really F3 ([issue #43](https://github.com/phamquiluan/RCAEval/issues/43)).
- 50 RE1-OB cases have a duplicate `time` header (read as `time.1`) (README changelog; main.py L291–294).
- RE1 has no disk metric; RE1 disk cases are scored against `latency` ([issue #77](https://github.com/phamquiluan/RCAEval/issues/77)).
- Repetitions are not independent (shared deployments and DB state); the author suggests grouping by deployment for any split, and an anomalous window may carry the previous fault's tail (issue #80).

## Harness requirements

Design rules derived from the facts above (no separate source):

- Never open label-bearing files in engines: folder names, `cases.parquet`, `root_cause.txt`.
- Flag cases with zero normal or zero faulty rows; never forward-fill NaN metric points; a missing or header-only file means "modality absent".
- Normalise service names across modalities (`frontendservice` → `frontend`; `-db` suffix → base service) and keep `_` out of service names.
- Run every baseline ourselves in one harness (published numbers differ by pipeline).
- Split calibration and test cases by deployment, not by case.

## Published baseline numbers

Numbers from different pipelines are not comparable.

- **Paper Table 6, RE2-TT, service level, AC@1 / AC@3 / Avg@5:** BARO .67/.82/.80 (Avg@5 per fault: CPU .72, MEM .99, DISK 1.0, SOCKET .83, DELAY .63, LOSS .64); multi-source BARO .69/.82/.81; TraceRCA .66/.79/.77 (DELAY Avg@5 .88); PDiagnose .48/.70/.67; MicroRank .16/.37/.31.
- **ASE'24** ([arXiv 2408.13729](https://arxiv.org/html/2408.13729)): runtime per TT case BARO 0.01 s, N-Sigma 0.01 s, RCD 12.4 s, CIRCA 3,792 s; random ("Dummy") Avg@5 ≈ 0.25 on OB and ≈ 0.07 on TT.
- **PRISM** over all 735 cases: .68/.91/.87 vs BARO .19/.74/.63 as run by PRISM; Top-1 per dataset RE2-OB .90, RE2-SS .86, RE2-TT .51, RE3-SS .20; ≈ 8 ms per case. Our arithmetic gives ≈ .65–.66 from the per-dataset values, so the .68 headline is unverified.
- BARO Top-1 on RE2-TT is .67 in RCAEval's pipeline but .32 in PRISM's ([Fang et al., arXiv 2510.04711](https://arxiv.org/html/2510.04711v2); PRISM).
- **SimpleRCA** (alert counting: metric alert at 3-sigma or above the history P95, trace alert at P95 latency ≈ 3× baseline, log alert on ERROR/FAIL/EXCEPTION counts; most alerts ranks first) Top-1: RE2-OB .47, RE2-SS .24, RE2-TT .80, RE3-OB .30, RE3-SS .83, RE3-TT .83, vs BARO .14, .14, .67, 0, 0, .50 (Fang et al.).
- **Telemetry-free prior:** a ranker that reads no telemetry puts the culprit in its top 5 on 99.7% of held-out incidents (Avg@5 0.488 vs 0.137 random) because faults hit 5 services per system ([Buljić, arXiv 2609.27069](https://arxiv.org/abs/2609.27069)).

## Anomaly scoring methods

- **PRISM:** deviation `S(x) = |x − c| / s` with location and scale fitted on pre-fault data (z-score default, IQR allowed); scores max-pooled into an internal score (cpu, memory, disk I/O, socket) and an external score (latency, error rate); default combination `M = S_I + S_E − log(1 + S_I + S_E)`, alternative `min(S_I, S_E)`; a threshold ε = 3 for z appears only in the theory; ranking by the internal score alone is worst (Top-1 .15) (PRISM).
- PRISM's failure example: for a DISK fault in currencyservice, BARO ranked emailservice latency first with a score of 4.6 × 10¹⁴ (division by a near-zero scale) (PRISM). No published ablation isolates a scale floor.
- **Early window:** with the first 10% of post-fault data PRISM reaches 81% Top-1 (68% on the full window) and BARO 46% (19%) (PRISM).
- **BARO:** multivariate BOCPD on latency and error metrics, the first change point is the onset; RobustScorer `|x − median| / IQR` fitted before the onset, metric score = max ([BARO, arXiv 2405.09330](https://arxiv.org/html/2405.09330)). It stayed robust to a 60 s onset error where N-Sigma and CIRCA degraded (ASE'24).
- **BOCPD:** exact online posterior over the run length; a constant hazard 1/λ means geometric gaps between changes ([Adams & MacKay, arXiv 0710.3742](https://arxiv.org/abs/0710.3742)).
- **Conformal p-value** of a score against calibration scores: `p = (1 + #{calibration ≥ s}) / (n + 1)`, floor `1/(n + 1)` ([arXiv 2402.16388](https://arxiv.org/abs/2402.16388)).

## Onset and precedence

- PRISM Table 15 (onset = first post-fault time with z > 3.0, measured at the **true** root): internal-before-external in CPU 76.9% (median −7 s), DISK 73.5% (−6 s), MEM 65.8% (−4 s), SOCKET 64.4% (−5 s), **DELAY 27.4% (+11 s), LOSS 41.3% (+9 s)**, code F1–F4 83.3% (−13 s), overall 60.7% (n = 698) ([PRISM v1](https://arxiv.org/html/2601.21359v1)).
- No paper ranks services by onset order on RCAEval; precedence was measured only at the known root (gap).

## Traces: spectrum and timing

- TraceRCA: a service on more abnormal and fewer normal traces is more suspicious ([IEEE 9521340](https://ieeexplore.ieee.org/abstract/document/9521340)); MicroRank uses Ochiai spectrum scores as personalised-PageRank teleport weights ([survey, arXiv 2407.01710](https://arxiv.org/pdf/2407.01710)).
- Ochiai outperformed other similarity coefficients in an industrial SBFL study ([Abreu et al., JSS 2009](https://webarchive.di.uminho.pt/haslab.uminho.pt/ruimaranhao/files/jss09.pdf)).
- Client/server timing: network time ≈ server receive − client send ([Spring Cloud Sleuth docs](https://docs.spring.io/spring-cloud-sleuth/docs/2.2.8.RELEASE/reference/html/)); the client–server gap also holds connection setup, pool waits, proxies and retries, and clock skew is the main practical problem ([OneUptime](https://oneuptime.com/blog/post/2026-09-29-explain-client-server-span-duration-differences/markdown)).
- Graph-based baselines score low on RCAEval (Top-1: PC-PageRank .09, Simple-Traversal .09, Smooth-Traversal .05), and RCAEval ships no dependency graph (PRISM).
- Rebuilding parents by time containment when `parentSpanID` is missing is a design rule (RCAEval traces do carry `parentSpanID`).

## Logs

- RE3 faults "can be diagnosed through telemetry such as stack traces in logs or response codes in traces" (README).
- Unseen log events dominate anomalous periods ([SemPCA, arXiv 2308.12612](https://arxiv.org/pdf/2308.12612)).
- The error lexicon and caller-blame extraction (a frontend line naming cartservice is evidence about cartservice) are design rules, not published results.

## Engineering: DuckDB and Drain3

- **Drain3** defaults: `sim_th` 0.4, `depth` 4 (minimum 3), `max_children` 100, `max_clusters` unlimited; `add_log_message` returns a `change_type` such as `cluster_created` ([Drain3](https://github.com/logpai/Drain3)). Drain is an online algorithm, so templates depend on input order (feeding distinct masked messages in a fixed order is a design rule). A blanket `\d+` mask merged `svc1…svc39` into one string in a local test on 2026-10-22 (not a published result).
- **DuckDB:** multi-threaded floating-point aggregates can differ between runs; use `SET threads = 1` and `ORDER BY ALL` ([non-deterministic behaviour](https://duckdb.org/docs/2.0/operations_manual/non-deterministic_behavior.html)). `approx_quantile` has no determinism guarantee; `quantile_cont` is Hyndman–Fan type 7 ([aggregates](https://duckdb.org/docs/2.0/sql/functions/aggregates)). `regexp_replace` replaces every match only with the `'g'` flag ([regex functions](https://duckdb.org/docs/current/sql/functions/regular_expressions)).
- **Statistics cost:** robust z over 500 series × 1,200 points took ≈ 9 ms with NumPy in a local benchmark (2026-10-22).
