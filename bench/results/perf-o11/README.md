# perf-o11: pipeline time and peak memory per case (O-11, #36)

Output of `scripts/observe/perf_check.py --passes 2 --out <host>.csv` (#542), AI off, engine code at
tag `results-code-v1` (`9e553e1c`). One row per case and pass: `wall_ms` is the whole pipeline in a
child process, `peak_rss_mb` that process's peak resident set size in MiB, and each `<step>_ms`
column one pipeline step. Pass 1 may convert raw files (cold or part-warm Infralume cache); pass 2
is the warm pass that H5 (04 §2) is read against. This is not bench output: no experiment YAML, no
`summary.json`, and the figures below are the script's printed summaries (nearest-rank p95).

| File | Machine | Cases (sample rule) | Run |
|---|---|---|---|
| `i5-1135g7.csv` | laptop 1, the slowest: i5-1135G7, Windows 11, 8 logical CPUs, Python 3.12.15 (`docs/team/cl.md`) | the first 10 case ids of each RE2 system, 30 cases × 2 passes | 26 Nov 2026, C Lakshanaa (#36) |
| `m4-arm64.csv` | Observe laptop: Apple M4, macOS 15.5 arm64, 10 logical CPUs, Python 3.12.16 | the three RE2 development cases (one per system), 3 cases × 2 passes | 26 Nov 2026, Annapurna S |

Pass 2 on the slowest laptop, against 30 s and 3 GB (2,861 MiB at 3 × 10⁹ bytes):

| System | median | p95 (= max of 10) | peak RSS max | time | memory |
|---|---|---|---|---|---|
| re2-ob | 20.8 s | 22.9 s | 521 MiB | within | within |
| re2-ss | 14.5 s | 15.3 s | 268 MiB | within | within |
| re2-tt | 72.8 s | 87.9 s | 1,087 MiB | **over** | within |

Limits. It is a 10-case sample per system, so the p95 is the maximum. An earlier sample of the same
cases on the same laptop (25 Nov, summaries only, on #36) was about 1.6 times slower (pass-2 p95:
OB 40.2 s, SS 27.1 s, TT 145.6 s), which put OB over the budget; the cause of the gap was not
measured (the laptop's thermal and power state is the suspect). TT is over the budget in both, and
memory is within it in both. In this file pass 2 is slower than pass 1, so the cache was already
warm and the machine slowed during the run.
