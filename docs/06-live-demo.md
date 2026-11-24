# 06a · Live demo script and X-10 rehearsal runbook

> Status: v0.1 · Lane: Explain · Issues: X-13 (#50), X-10 (#43) · Parent spec: [06 Gateway and console](06-gateway-and-console.md) · Lab: [05](05-fault-lab-and-dataset.md), [docs/team/cl.md](team/cl.md) (laptop 1) · Last updated: 2026-11-24

Part A is the 3-minute video, which a person records after the rehearsal. Part B is the Thu 26 Nov rehearsal that checks X-10's acceptance: injected fault → AI-off verdict on screen in ≤ 5 min, with RAM measured and recorded. Every command below exists on `main` at 4252d202 unless §0 lists it as missing.

## 0. What exists today and what is still missing (24 Nov, `main` 4252d202)

The gateway's live path is merged: the receiver, buffer, snapshot writer, `/api/v1/live/{status,snapshot,diagnose}` and the round-trip test (#473, #474, #476, #477, #491). **It does not yet run end to end against the lab.** The rehearsal can only start once gates G1–G3 below are closed:

| Gate | Today on `main` | Closed by | How to check |
|---|---|---|---|
| G1 converter and adapter | No OTLP converter is installed. The only converter is the test stub in `veyltrace_gateway.testing` (tests only), and there is no `otlp_live` adapter, so `POST /live/diagnose` answers 503 `adapter_missing` | O-07 `veyltrace_infralume.otlp` and the `otlp_live` adapter (Observe lane, #24, open) | `uv run python -c "import veyltrace_infralume.otlp"` exits 0, and `uv run python -c "from veyltrace_core.adapters import find_adapter; print(find_adapter('live'))"` prints an adapter, not `None` |
| G2 converter wired into the CLI | Wired (#504): `python -m veyltrace_gateway` imports `veyltrace_infralume.otlp` at start-up and passes it to the receiver. Until O-07 is installed (G1), start-up logs `otlp_converter_missing`, every `POST /v1/*` answers 503 and `/live/snapshot` answers 503 `converter_missing` | closes with G1, with no further gateway change | start-up logs no `otlp_converter_missing` line, and `requests.accepted` in `/live/status` grows (B.1 step 8) |
| G3 Collector → gateway | `lab/ob/collector.yaml` has only `file/*` exporters; how the Collector in kind reaches the gateway is unsettled (06 §11 OQ-7) | #489 (Explain, open): `otlphttp` exporter with `encoding: json` (protobuf bodies get 415 until `opentelemetry-proto` is a dependency) and the OQ-7 route | `/api/v1/health` shows `live.receiving: true` while Online Boutique runs |

The console on `main` has the case list (`/`) and the run view (`/runs/:runId`): run progress (polled every 2 s), status banner, candidate set, ranked table with trial badges and trial drawer, evidence table with atom drawer, and the card's propagation path and timeline as plain lists. **It has no live view, no "Diagnose now" button, no receipt or replay view and no card summary or narrator line.** So in both parts the live status and "Diagnose now" are calls to the gateway API from a terminal, the receipt is the JSON route opened in a browser tab, and replay is the CLI. The alert watcher is cut to v1.1 (#227), so a person triggers every diagnosis. No ADR on `main` records the console cuts; [20261123-cl-explain-scope-cuts](adr/20261123-cl-explain-scope-cuts.md) covers only X-11 and X-12.

If any of this lands before Thu (a console live view, for example), update the shot list rather than showing a terminal for it.

**Demo fault.** F04 network delay, L1 (200 ms, 10% jitter) on `currencyservice`, from `lab/plans/x02-smoke.yaml`. F04 is one of the 7 types validated on laptop 1 ([ADR 20261110-cl-lab-validation](adr/20261110-cl-lab-validation.md)) and needs `sch_netem`, which loads there ([cl.md](team/cl.md)). The manifest is [lab/demo/f04-currencyservice-l1.yaml](../lab/demo/f04-currencyservice-l1.yaml); `lab/tests/test_demo_manifest.py` checks it equals what `vlab.faults.injection()` builds, so the demo injects exactly the catalog fault. It ends by itself after 600 s.

**Narration is not in the video.** The console does not show the card summary or narrator line (06 §5.2 h is not built), and laptop 1 has no LLM (Ollama runs on laptop 2), so the video is AI off. Add an AI-on shot (cassette replay) only after the console shows the narration.

**When to click "Diagnose now".** The click time is the alert time. Core's windows are baseline [t − 20 min, t − 2 min] and incident [t − 2 min, t + 8 min], clamped to the data ([02 §5.1](02-architecture.md#51-alert-time-and-windows)), and a manual snapshot holds only data up to the click. So: (1) the gateway must have received data for at least 20 min before the injection; (2) click about 90 s after the injection, so the onset lies inside the last 2 min and some degraded data exists. The 90 s is *a priori*; adjust it from the rehearsal.

## Part A · 3-minute demo script

Setup before recording: everything in B.1 done, the 20-min warm-up passed, the fault not yet injected, one finished run already in the case list (for example the rehearsal's own live run). Screen: browser on the left (console tab, Online Boutique tab, receipt tab), PowerShell on the right in the repo root. `[cut]` marks a wait the editor removes; the on-screen clock (`Get-Date`) shows the real elapsed time across cuts.

| Time | On screen | Do (exact command or click) | Say |
|---|---|---|---|
| 0:00–0:15 | Console case list, `http://127.0.0.1:5173/` | open the tab | "This is Veyltrace, a root-cause engine for microservice outages. Statistical rankers propose candidates, a deterministic verifier decides, and every verdict can be replayed." |
| 0:15–0:35 | Online Boutique at `http://127.0.0.1:8080/`, then the terminal | `Invoke-RestMethod http://127.0.0.1:8000/api/v1/live/status` | "Online Boutique runs on a kind cluster on this laptop. Its OpenTelemetry Collector streams traces, metrics and logs to the gateway, which keeps the last 30 minutes in memory. `receiving` is true." |
| 0:35–0:55 | Terminal | `Get-Date -Format o; kubectl --context kind-veyllab apply -f lab/demo/f04-currencyservice-l1.yaml` | "Now we break something: Chaos Mesh adds 200 milliseconds of network delay to one service. Veyltrace is not told which one." |
| `[cut]` | | wait about 90 s | |
| 0:55–1:10 | Terminal | `Get-Date -Format o; $run = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/live/diagnose -ContentType 'application/json' -Body '{}'; $run` | "Diagnose now. The click time becomes the alert time. The gateway writes the last 20 minutes to disk as a content-addressed snapshot, so this live case can be replayed like any benchmark case, and queues the AI-off run." |
| 1:10–1:20 | Console run view | open `http://127.0.0.1:5173/runs/<run_id>` with `$run.run_id` | "The run view shows the pipeline's progress, step by step." |
| `[cut]` | | until the banner appears | |
| 1:20–1:45 | Status banner and candidate set | scroll to the top | "This is the verdict with AI off: a status word, a confidence level and a split-conformal candidate set, not a probability. The banner also shows AI mode off and the live alert protocol." |
| 1:45–2:05 | Ranked table, then a trial drawer | click one trial badge of the top candidate | "Each candidate gets ten code-run trials. Each badge says pass, fail or untestable, and opens the evidence behind it." |
| 2:05–2:25 | Evidence table, atom drawer, path and timeline lists | click one atom link, then scroll to the path | "Every number links to an evidence atom: one row computed from the telemetry. Below are the propagation path and the timeline, each citing atoms." |
| 2:25–2:40 | Receipt tab | open `http://127.0.0.1:8000/api/v1/runs/<run_id>/receipt` | "The receipt records the hash of every input, the config, the code commit and the verdict." |
| 2:40–3:00 | Terminal | `uv run veyltrace replay runs/live/$($run.case_id)/$($run.run_id)/receipt.json; $LASTEXITCODE` | "Replay checks the inputs against the receipt and recomputes the verdict. Exit code zero: the same verdict, bit for bit." |

After recording: `kubectl --context kind-veyllab -n veyllab-app delete networkchaos vl-demo-f04 --ignore-not-found`.

## Part B · Thu 26 Nov X-10 rehearsal runbook

Acceptance for #43: injected fault → AI-off verdict on screen ≤ 5 min; RAM measured and recorded. Run on laptop 1, **on mains power** (on battery the laptop entered Modern Standby under lab load, [cl.md](team/cl.md)).

### B.1 Pre-flight checklist (start ≥ 40 min before the injection)

1. [ ] Gates G1–G3 of §0 are closed on the branch you run, and `uv sync --all-packages` and `pnpm -C console install` have run on it.
2. [ ] Local edits to `config/gateway.yaml`, **not committed**: `live.enabled: true`, and `live.ai_modes: ["off"]` (laptop 1 has no LLM; 06 §3.4). If the OQ-7 route from #489 needs a non-loopback `live.otlp_host`, set it as #489 records.
3. [ ] `$env:VEYLTRACE_DATA` is unset (default `~/veyltrace-data`) or points outside the repo; the data root refuses a path inside a git work tree.
4. [ ] Docker Desktop is running. `uv run python lab/up.py --profile ob` ends with `up: profile ob ready; frontend at http://127.0.0.1:8080/`.
5. [ ] `uv run python lab/campaign.py --cleanup` (removes leftover chaos objects and restores the overlay; run it before the warm-up, as it restarts the app), then `kubectl --context kind-veyllab -n veyllab-obs rollout status deploy/veyllab-collector` and `(Invoke-WebRequest http://127.0.0.1:8080/ -UseBasicParsing).StatusCode` → 200.
6. [ ] Gateway, in its own terminal: `uv run python -m veyltrace_gateway` (add `--allow-lan` only if the OQ-7 route needs it; it prints a no-auth warning).
7. [ ] Console, in its own terminal: `pnpm -C console dev`, then open `http://127.0.0.1:5173/`.
8. [ ] `Invoke-RestMethod http://127.0.0.1:8000/api/v1/health` shows `live.enabled` and `live.receiving` true; `(Invoke-RestMethod http://127.0.0.1:8000/api/v1/live/status).requests` shows `accepted` growing and `rejected` at 0.
9. [ ] Gateway PID (the Python process that owns port 8000; the OTLP receiver and the job runner run inside it): `$gw = (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess; $gw`.
10. [ ] Warm-up of ≥ 20 min of buffered data: `$s = Invoke-RestMethod http://127.0.0.1:8000/api/v1/live/status; ($s.newest_ns - $s.oldest_ns) / 6e10` prints ≥ 20 (minutes).

### B.2 Stopwatch points

Take every time with `Get-Date -Format o` in the same terminal, so all points share one clock.

| Point | Event | Action | Where the time comes from |
|---|---|---|---|
| T0 | injection | `Get-Date -Format o; kubectl --context kind-veyllab apply -f lab/demo/f04-currencyservice-l1.yaml` | the printed time |
| T1 | "Diagnose now" (≈ T0 + 90 s) | `Get-Date -Format o; $run = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/live/diagnose -ContentType 'application/json' -Body '{}'; Get-Date -Format o; $run` | the first printed time |
| T2 | snapshot on disk, run queued | the same call returns after the snapshot is written | the second printed time; `(Invoke-RestMethod http://127.0.0.1:8000/api/v1/live/status).snapshots` lists the id |
| T3 | run done | repeat `Get-Date -Format o; (Invoke-RestMethod http://127.0.0.1:8000/api/v1/runs/$($run.run_id)).state` until `done` (or `failed`: record `error`) | the time printed with `done` |
| T4 | verdict on screen | open `http://127.0.0.1:5173/runs/<run_id>`; press the stopwatch when the status banner appears (the page polls every 2 s) | a phone stopwatch started at T0 |

**Pass:** T4 − T0 ≤ 5 min. The deliberate wait T1 − T0 counts. 06 §8 *estimates* a deterministic path of ≤ 30 s; record what you measure.

Then check replay and remove the fault:

```powershell
uv run veyltrace replay runs/live/$($run.case_id)/$($run.run_id)/receipt.json; $LASTEXITCODE
```

```powershell
kubectl --context kind-veyllab -n veyllab-app delete networkchaos vl-demo-f04 --ignore-not-found
```

Replay exit codes ([10 §3.9](engines/10-causivra.md#39-replay)): 0 reproduced, 1 malformed receipt or exception, 2 verdict or trace hash differs, 3 inputs changed, 4 config, 5 environment drift, 6 only the card differs.

### B.3 Peak RAM

The job runner is a thread of the gateway process (`jobs.workers = 1`), so the gateway's peak covers the receiver, the 30-min buffer and the AI-off pipeline run. Restart the gateway before each measured attempt, because the peak counts from process start, and read it after T3.

| What | Command | Notes |
|---|---|---|
| Gateway + pipeline, peak and current (Windows) | `Get-Process -Id $gw \| Select-Object Id, @{n='peak_MiB';e={[math]::Round($_.PeakWorkingSet64/1MB)}}, @{n='now_MiB';e={[math]::Round($_.WorkingSet64/1MB)}}` | peak working set since start |
| Gateway in WSL instead (OQ-7 fallback) | `ss -ltnp 'sport = :8000'` for the PID, then `grep -E 'VmHWM\|VmRSS' /proc/<pid>/status` | VmHWM is the peak resident set |
| Lab: kind node (app, Chaos Mesh, Collector) | `docker stats --no-stream veyllab-control-plane` | as measured on 9–10 Nov (1.71 GiB idle) |
| WSL / Docker VM as a whole | `Get-Process vmmem* \| Select-Object Name, @{n='MiB';e={[math]::Round($_.WorkingSet64/1MB)}}` | the VM process is `vmmem` or `vmmemWSL`, depending on the setup |
| Buffer bytes (Arrow, not RSS) | `(Invoke-RestMethod http://127.0.0.1:8000/api/v1/live/status).bytes` | cap `live.buffer_max_mb` = 512 |

`scripts/observe/perf_check.py` measures the pipeline alone (peak RSS per case in a child process, budget 3 GB). It reads cases through the dataset adapter's `list_cases`, so `uv run python scripts/observe/perf_check.py live --runs-root <temp dir>` works only if the O-07 `otlp_live` adapter lists snapshots. That is unverified until O-07 lands; if it does not, record "not measured" for that row.

### B.4 Results (fill in on Thu 26 Nov; copy into #43)

| Item | Attempt 1 | Attempt 2 |
|---|---|---|
| Branch and commit | | |
| Gates G1–G3 closed by (PRs) | | |
| OQ-7 route used | | |
| T0 injection | | |
| T1 Diagnose now (T1 − T0) | | |
| T2 snapshot written (T2 − T1) | | |
| T3 run done (T3 − T2) | | |
| T4 verdict on screen; **T4 − T0 (≤ 5 min?)** | | |
| Verdict status, confidence level, candidate set | | |
| Replay exit code | | |
| Gateway peak MiB / now MiB | | |
| kind node MiB (`docker stats`) | | |
| VM MiB (`vmmem*`) | | |
| Buffer MiB, `requests.rejected`, `dropped` | | |
| `perf_check.py` pipeline peak MiB (or "not measured") | | |
| Power, other apps open | | |

### B.5 If it fails

Record the failure in the table; never fill in a time that was not measured.

| Symptom | Meaning |
|---|---|
| 503 `live_disabled` | `live.enabled` is not true in the local `config/gateway.yaml` |
| 503 `converter_missing` / `adapter_missing` | G1 is not closed (O-07's converter / `otlp_live` adapter is not installed; start-up also logs `otlp_converter_missing`): no live demo on this branch |
| `live.receiving` false, `accepted` stays 0 | G3: the Collector does not reach the receiver; check the #489 route |
| 409 `buffer_empty` | no data in the last 20 min of the buffer |
| 409 `snapshot_conflict` | two different rows with one key across requests; attach the message to #24 |
| run `failed` | read `error` in `GET /api/v1/runs/<run_id>`; the run directory keeps the steps that finished |
