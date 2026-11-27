# v1.0 retrospective and post-month plan: v1.1 scope listed; venue, arXiv endorser and author order deferred until after v1.0

- **Status:** Accepted (lead, 27 Nov). The lead's decisions of 25 and 27 Nov are in §1, §3, §4 and §5, and Reason's rows show the state on 27 Nov, after R-16's runs ended. The retrospective (30 Nov – 1 Dec) may append to it
- **Date:** 2026-11-25
- **Author:** C Lakshanaa (CL)
- **Deciders:** the lead, with all three lanes at the retrospective
- **Consulted:** Explain (this draft); Observe (rows given by Annapurna S on [#523](https://github.com/DuhItzAniket/Veyltrace/pull/523), 25 Nov); Reason (the lead's rows and items, 27 Nov)
- **Issue / CCR:** #55 (L-07)
- **Supersedes:** none · **Superseded by:** none

## Context

L-07 ([07 §7](../07-roadmap.md#7-release-mon-30-nov--tue-1-dec--m5)) asks for a retrospective and a post-month plan (venue, arXiv endorser, v1.1 scope) recorded in `docs/adr/`. The [ADR README](README.md) also lists "venue, authorship and post-month plan" as needing an ADR. [11 §7](../11-research-paper-plan.md#7-venue-plan-and-arxiv) asks to record the venue and endorser decision here, and [11 §9](../11-research-paper-plan.md#9-authorship-and-contribution-statement) the author order.

This draft is written on Wed 25 Nov, before the bug bash (L-04, Thu 26), M4 (Sun 29) and the retrospective itself (Mon 30 Nov – Tue 1 Dec). Every fact below comes from the repo or GitHub on that date, with its PR, issue or file. Anything not yet known is marked **Open**. Explain's rows are complete.

**Refreshed on Thu 26 Nov.** Explain's rows show the state on 26 Nov. The Observe rows are Annapurna's, as given on #523, and show the state on 25 Nov. The lead's decisions of 25 Nov ([#523](https://github.com/DuhItzAniket/Veyltrace/pull/523) and [#227](https://github.com/DuhItzAniket/Veyltrace/issues/227)) are in §4 and §5. Reason's rows follow after R-16 ends (Sat 28 Nov).

**Refreshed on Fri 27 Nov (Reason).** R-16's last runs ended on 27 Nov, a day early, so Reason's rows of §1 and items of §3 are in, with the state on 27 Nov. As in the other rows, dates are GitHub's (UTC). Every number in them is a GitHub or repo count, or comes from a committed file under `bench/results/`. Each fact was collected with `gh` and `git` and then checked again by a second pass.

How the PR facts were collected: `gh pr list --state merged --label lane:explain` returns 74 merged PRs. #220 (X-02, title "Task 19") has no lane label and is counted separately. `gh issue list --label lane:explain --state all` gives the issue states.

## Decision drivers

- The paper and release report what shipped and what was cut honestly, each cut with an ADR line ([07 §1.1](../07-roadmap.md#11-cut-list-if-a-milestone-slips-by--1-day)).
- v1.1 scope comes from items that the docs and ADRs already defer, not from new wishes.
- No invented numbers. Every count here is a GitHub or repo count, not a benchmark result. Results come only from `bench/results/` (AGENTS §4.8).

## Considered options

1. **One ADR: retrospective, v1.1 scope and the open post-month decisions.** The team fills the open rows at the retro, and the lead accepts it.
2. **Separate ADRs** for the venue, the endorser, the author order and v1.1 scope. This makes four files for one meeting's decisions.
3. **The retrospective in an issue comment, and only the decisions in an ADR.** The "what shipped" record would then live outside the repo the paper cites.

## Decision

We choose **option 1**. Sections 1 to 3 record facts. Section 4 lists the v1.1 scope as the docs defer it, which the lead accepted on 25 Nov. Section 5 records the lead's decision of 25 Nov: venue, arXiv endorser, arXiv category and author order are **deferred until after v1.0** (target 1 Dec). The RK-22 fallback stands.

No code, config or contract changes.

### 1. What shipped vs planned: Explain, per milestone

| Milestone (planned date) | Task (issue) | Shipped (merged PRs) | State on 25 Nov |
|---|---|---|---|
| M0 (Tue 3 Nov) | X-00 stubs, `FakeProvider`, gateway app, console scaffold (#10) | #116, #117, #118, #119, #124, #125, #126, all merged 11 Nov | closed 11 Nov, 8 days after M0 |
| M1 (Sun 8 Nov) | X-01 `veyltrace_llm` (#18) | #146–#150 (13 Nov); follow-ups #231, #234, #237, #239 (#224, #232, #235, #238; 16 Nov) | closed 13 Nov; #224 closed 24 Nov |
| M1 | X-02 Lab v0 (#19) | #220 (9 Nov) | closed 9 Nov |
| M1 | X-03 Causivra v0 card (#20) | #174–#178 (18 Nov); follow-ups #328, #333 (18 Nov), #492 (24 Nov) | closed 18 Nov |
| M2 (Sun 15 Nov) | X-04 Gateway v0 (#29) | #275, #277, #279, #281, #283 (15–16 Nov); follow-up #336 | closed 16 Nov |
| M2 | X-05 Console v0 (#30) | #482–#486 (23 Nov) | closed 24 Nov. Never-cut item (console verdict view) shipped |
| M2 | X-06 Lab v1 (#31) | #221 (9 Nov); fixes #230 (#225) | closed 9 Nov. The OTel Demo profile is not built (cut item 5, see §2) |
| M2 | X-07 Relentra v0, `brief` (#32) | #338, #341, #343, #345, #347 (18 Nov), #354–#356 (21 Nov), #435, #446 (22–23 Nov) | closed 22 Nov. Never-cut item (Relentra `brief`) shipped |
| M3 (Sun 22 Nov) | X-08 Relentra v1 (#41) | budgets, cassette wiring and the trace for brief mode only ([08 §10](../engines/08-relentra.md)); spec synced by #516 | closed 26 Nov. RQ6 Tier 1: recording host 801/801 (#544); second laptop 799/801 with exit 0, verdict hash equal on 800 (#575; script fix #574). The lead accepted the second-laptop run as it ran (review of #575). Its one reproducible difference, last-digit intervention evidence across CPUs, is #576 (v1.1) |
| M3 | X-09 Causivra v1: narration, claim checker, replay (#42) | #434 (replay, 22 Nov), #459, #460, #462, #467 (23 Nov); bug-bash fix #520 (25 Nov) | closed 24 Nov. Never-cut item (replay) shipped |
| M3 | X-10 Live (#43) | #470, #473, #474 (23 Nov), #476, #477, #488, #491, #503, #507 (23–24 Nov), #509, #518, #521 (25 Nov) | closed 26 Nov. Three live runs on laptop 1 on 25 Nov: injection to AI-off verdict on screen in 2 min 12 s, 3 min 17 s and about 2 min 11 s (≤ 5 min: pass), replay exit 0, RAM recorded ([06-live-demo A.1, B.4](../06-live-demo.md)). They ran on local merges of #508 and #509, both on `main` since 25–26 Nov; #530 followed. Never-cut item (live demo on Online Boutique) |
| M3 | X-11 Lab collection (#44) | #222 (validation, night plans, daily report), #230, #517 | closed 25 Nov. 8 of 120 captures (`bench/results/not_run.yaml`). v1.0 scope is the demo captures only ([20261123-cl-explain-scope-cuts](20261123-cl-explain-scope-cuts.md)) |
| M4 (Sun 29 Nov) | X-12 MCP server (#49) | ADR #463 | cut to v1.1. GitHub shows #49 closed on 23 Nov with reason "completed", although the ADR says "not planned" |
| M4 | X-13 Demo script, video, paper sections (#50) | #471 (paper sections on the proposer and narration), #494 (demo script and runbook), #522 (recording record, [06-live-demo A.1](../06-live-demo.md)) | closed 25 Nov. The 2:16 AI-off video is a prerelease asset (`demo-video-2026-11-25`); it moves into the v1.0.0 release assets at L-05 |
| M4 | X-14 VeylLab packaging (#51) | — | closed 24 Nov as "not planned"; moves to v1.1 |
| M4 | L-04 Bug bash and docs review (#52) | #515, #516, #517, #519, #520, #524, #530 | closed 26 Nov. No issue carries `priority:P0` or `priority:P1`; the open `type:bug` issues are listed on #52 |
| M5 (Tue 1 Dec) | L-07 (#55) | this PR | draft |

**Observe rows** (given by Annapurna S on #523, state on 25 Nov):

| Milestone (planned date) | Task (issue) | Shipped | State on 25 Nov |
|---|---|---|---|
| M0 (Tue 3 Nov) | O-00 stubs for the five engines (#8) | with #58 | closed 22 Nov (housekeeping; the stubs were in use from M0) |
| M1 (Sun 8 Nov) | O-01 Infralume: fetcher, `rcaeval` adapter, scrubbing (#11) | 11 sub-issues (#96 … #162), follow-up #233 | closed 13 Nov, 5 days after M1 |
| M1 | O-02 Signalyth metrics and traces (#12) | sub-issues #179–#182 | closed 13 Nov |
| M1 | O-03 Signalyth logs (#13) | sub-issues #248–#251 | closed 14 Nov |
| M2 (Sun 15 Nov) | O-04 Anomara (#21) | 9 sub-issues (#82 … #184) | closed 13 Nov. Follow-up #245 (effective step on near-constant series) open, v1.1 |
| M2 | O-05 Causalith (#22) | sub-issues #193–#195, #198, #210 | closed 13 Nov |
| M2 | O-06 Causync (#23) | sub-issues #257–#263 (PR #270), follow-ups #272, #291 (#271) | closed 15 Nov, on M2 |
| M2 | O-07 OTLP converter, `otlp_live`, `veyllab` adapter (#24) | #500, #501 (24 Nov), #508 (25 Nov) | **open**. Converter and `otlp_live` shipped 9–10 days after M2; the `veyllab` adapter moved to v1.1 |
| M3 (Sun 22 Nov) | O-08 Nezha adapter, FSE'26 adapter (#33) | #436 (adapter), #447 (fetcher, #452) | closed 22 Nov. FSE'26 adapter cut (07 §1.1 item 2). Config keys #448 / PR #450 held as a draft for v1.1 |
| M3 | O-09 robustness hooks (#34) | #323 | closed 18 Nov |
| M3 | O-10 TSFM plugin (#35) | — | cut (07 §1.1 item 1); ADR in #497 (open) |
| M3 | O-11 performance pass (#36) | `perf_check.py` #457 | **open**. Measured 25 Nov on the slowest laptop (10 cases per system): memory within 3 GB; p95 time 27 s on SS, 40 s on OB, 146 s on TT against 30 s. Not fixed in v1.0 (freeze) |
| M3 | O-13 RCAEval-C decoy generator (#39) | #320 | closed 18 Nov |
| M3 | O-14 `bench/stats` (#40) | #350, follow-up #426 (#423) | closed 20 Nov |
| M4 (Sun 29 Nov) | O-12 docs final, fixtures, paper sections (#48) | specs #505, #506 (approved, open); paper §3.1 #513 (approved, open), §5.4 and §5.5 #539 (merged 25 Nov) | **open**. Fixtures need the recording host (#256) |
| M5 | L-06 REPRODUCE.md on a clean clone (#54) | — | **open**; waits for R-17's tables. The Observe laptop lacks the disk for a full RE2 re-run (comment of 24 Nov) |

60 merged PRs carry `lane:observe` on 25 Nov.

Changed since 25 Nov (Explain's note, from GitHub on 26 Nov): #497 merged 26 Nov ([20261124-as-observe-cuts-v1-1](20261124-as-observe-cuts-v1-1.md)); #36 closed 25 Nov, and the per-case CSVs are in `bench/results/perf-o11/`, including a second laptop-1 run on 26 Nov; #506 merged 26 Nov and #513 merged 25 Nov; #505 is still open.

**Reason rows** (state on 27 Nov; dates in UTC, as above):

| Milestone (planned date) | Task (issue) | Shipped (merged PRs) | State on 27 Nov |
|---|---|---|---|
| M0 (Tue 3 Nov) | L-00 GitHub setup (#1) | #56 (lane logins, CODEOWNERS; 6 Nov). Protection, labels, milestones and the board were set up outside PRs | closed 8 Nov, 5 days after M0. `main` requires 11 checks, strict, with 1 approval and Code Owners. The board's Board, Table and Roadmap views were never set up (only its default table exists). Linear history was turned off on 13 Nov so stacked PRs can merge (L-09, #242, #244) |
| M0 | L-03 CI workflow (#7) | #61 (8 Nov, top of the #58 → #59 → #60 stack) | closed 8 Nov, 5 days after M0. Every job was green at its merge. Of 314 CI push runs on `main` since 30 Oct, 6 failed, the last on 21 Nov |
| M0 | R-00 stubs (#9) | #60 (8 Nov); stubs removed by #171 and #207 (16 Nov) | closed 8 Nov, 5 days after M0 |
| M0 | R-01 contracts v0.1 (#4) | #57 (6 Nov) | closed 6 Nov, 3 days after M0. Its acceptance (`contracts-in-sync` passes) only held from 8 Nov, when the job first ran (#58) |
| M0 | R-02 workspace skeleton (#5) | #58 (8 Nov); follow-ups #99 (#98) and #219 (#218), 9 Nov | closed 8 Nov, 5 days after M0. `uv sync --all-packages` was checked on the lead's clean checkout only; there is no per-laptop record |
| M0 | R-03 synth generator (#6) | #59 (8 Nov) | closed 8 Nov, 5 days after M0. Hashes are equal across processes. synth-01's delay is 8 → 20 ms, not 8 → 12 ms, because 12 ms raised no alert |
| M1 (Sun 8 Nov) | R-04 bench harness v0 (#14) | #70–#73 (9 Nov), #74 and #81 (11 Nov); follow-ups #183, #217 (13 Nov), #246, #247 (14 Nov, CCR #69) | closed 11 Nov, 3 days after M1 |
| M1 | R-05 baselines (#15) | #292–#295 (16 Nov) | closed 16 Nov, 8 days after M1 (it waited on O-01, closed 13 Nov). BARO on RE2-TT gives AC@1 0.667, AC@3 0.822 and Avg@5 0.800, equal to RCAEval's Table 6 (`bench/results/re2-oracle-baselines-r05/`) |
| M1 | R-06 FaultLoom v0 (#16) | #62 (8 Nov) | closed 8 Nov, on M1. Goldens on a hand-made case, since synth anomalies stayed empty until Anomara |
| M1 | R-07 contracts 1.0 freeze (#17) | ADR #306 (16 Nov), #321 and #334 (18 Nov); tag `contracts-1.0` (18 Nov) | tag 10 days after M1; #17 closed 23 Nov. No record of the planned all-lane review on 4 Nov. Observe's change request on #306 was fixed before merge. The ADR's status still reads Proposed |
| M2 (Sun 15 Nov) | R-08 FaultLoom v1 (#25) | #122, #139 (9 Nov); #156, #168–#170, #185, #186 (15 Nov) | closed 15 Nov, on M2. Each of the 10 predicates is tested true, false and null on a synth-01-shaped fixture |
| M2 | R-09 Causatrix v1 (#26) | #109, #121 (9 Nov), #138 (11 Nov), #141, #157, #160 (13 Nov), #229 (15 Nov), #164, #171 (16 Nov) | GitHub shows it closed on 9 Nov: every stack PR said "closes #26", so the first merge closed it. The work ended 16 Nov, 1 day after M2. rq1 (#465) scores each ranker alone. `change_prox` ranks no case on any system, and `cp_sbfl` none on SS |
| M2 | R-10 Causentra v1 (#27) | #200–#204, #206, #207 (16 Nov); fixes #290 (#216) and #317 (#226), 16 Nov | closed 16 Nov, 1 day after M2. Acceptance **half met**: the determinism gate passes on synth in CI, but nothing records it on 3 real cases. `scripts/ci_real_case.json` was never committed, and the gate pins one real case, not three. The nearest real-data check is RQ6 replay on the recording host (801/801, #544) |
| M2 | R-11 alert protocols, full RE2 run, scorecard (#28) | pre-registration stack #307–#313 and #318 (16 Nov); #331 (18 Nov); #363, #365 (20 Nov); rq1 #465 (23 Nov); detected rq1 #568 (26 Nov) | **open**, 12 days after M2. Both runs are on `main`, and the table waits for R-17. Under the detected protocol, no alert fires on OB 29/89, SS 17/89 and TT 89/89: TT's traced entries are sparse trace roots (#571, v1.1) |
| M3 (Sun 22 Nov) | R-12 Causentra v2 (#37) | #362 (20 Nov); #364, #366–#368, #430 (21 Nov) | closed 25 Nov, 3 days after M3: the code was in before M3, and the issue closed when #548 measured it. Held-out coverage is 0.910 pooled [0.862, 0.948], inside 0.85–0.95. NO_FAULT **not met**: the held-out false-alarm rate is 1.0 on every fold, and τ_nf stays at 1.386 (04 §12, row logged 26 Nov) |
| M3 | R-13 calibration fitting (#38) | #382, #384, #385, #395, #396, #402, #411, #414, #415 (21 Nov); fitted files #548 (25 Nov) and #636 | closed 25 Nov, 3 days after M3. The fitted files are kept with their results, in `bench/results/<experiment>/calibration/`, not in `config/calibration/` as 07 says. #610 and #626 left the LOSO and transfer files out; #636 adds them, each matching its manifest's SHA-256 |
| M4 (Sun 29 Nov) | R-16 full experiment matrix (#45) | runner and cut list #406–#408, #417, #420, #424 (21 Nov); rq1 #465 (23 Nov); rq2 #528, the AI-arm cut #533 (merged locally during the GitHub outage), #544 and #548 (25 Nov); #554, #560, #562, #564, #568 (26 Nov); 21 CPU-lane results PRs #580–#634 (26–27 Nov); fixes #616 and #630 and the RE3, transfer and Nezha results #620, #626, #632 (27 Nov) | **open**, M4 in 2 days. Of the 55 pre-registered YAMLs, 30 have results on `main`, 2 were replaced by AI-off revisions whose results are on `main` (04 §12, 25 Nov), and 23 are in `not_run.yaml`. Left: H6a's CI replay site has neither a result nor a `not_run.yaml` entry. Four derived code tags (`results-code-v1-cpu`, `-prior`, `-baselines`, `-baselines-2`) each add 1–2 bench-only commits to `results-code-v1` |
| M4 | R-17 tables and figures, result freeze tag (#46) | generator #383, #390, #392, #394, #401, #403, #418 (21 Nov), #439, #441–#445 (22 Nov); interval inputs #546, #556 (25–26 Nov) and #636 | **open**. No tables are committed, and no tag freezes the results |
| M4 | R-18 paper draft v1 (#47) | lead #386–#389 (21 Nov), #552 (25 Nov); lanes #471, #513, #539; #570 open | **open**. In the built paper, 37 lead questions, 73 number blanks and 30 table or figure placeholders wait for R-17. `explain-narration.tex` (#471) has no slot yet |
| M5 (Tue 1 Dec) | L-05 release (#53) | — | **open**, for 30 Nov – 1 Dec. towncrier and 314 fragments are in place. `CITATION.cff` still says 0.0.1 with no DOI, and there is no `v1.0.0` tag and no Zenodo record |

165 merged PRs carry `lane:reason` on 27 Nov, and none is open.

Milestone tags: `git tag` shows `contracts-1.0` (18 Nov), `prereg-v1` (17 Nov), `results-code-v1` (23 Nov), the four derived code tags of R-16 (26–27 Nov), `results-replay-v1` (26 Nov) and Explain's `demo-video-2026-11-25`. The planned `v0.0.1`–`v0.3.0` milestone tags ([07 §1](../07-roadmap.md#1-phases-and-milestones)) and `v0.9.0` were not cut. **Decided (lead, 27 Nov):** the retro records this as a slip, not a deliberate change. No decision dropped those tags; they were not cut while the milestones slipped. Nothing the paper cites depends on them: the paper cites the purpose tags above. R-17's result-freeze tag takes the place of `v0.9.0`, and `v1.0.0` is cut at L-05.

### 2. What was cut, and why

| Cut | Basis (cut-list item or new) | Where recorded |
|---|---|---|
| FSE'26 TrainTicket adapter; `fse26-oracle-rq1-v1` not run | 07 §1.1 item 2 | [20261121-ak-r16-cut-list](20261121-ak-r16-cut-list.md), `not_run.yaml` |
| Relentra `investigate` mode; `re2-oracle-investigate-v1`, `re2-oracle-rq3-investigate-v1` not run | 07 §1.1 item 3 (`brief` kept) | same |
| Five RCAEval-C AI mid-grid cells (π = 0.5 and rate 2/h); the 4 corner cells kept | new cut: LLM budget | same |
| ±30 s brief shift cells (`re2-shift-m30-brief-v1`, `re2-shift-p30-brief-v1`) | new cut: exploratory in 04 §2; LLM budget | same |
| `cloud-opsbench/agent-only` | optional in 04 §3; no experiment YAML | `not_run.yaml` |
| VeylLab experiments `veyllab-oracle-rq1-v1`, `veyllab-oracle-rq2-v1` | 8 of 120 captures, no adapter yet | [cut-list addendum, 22 Nov](20261121-ak-r16-cut-list.md#addendum-22-nov-2026-the-two-veyllab-experiments) |
| X-12 MCP server | 07 §1.1 item 4 | [20261123-cl-explain-scope-cuts](20261123-cl-explain-scope-cuts.md) |
| X-11 beyond the demo captures; X-14 VeylLab release | 07 §1.1 item 6 | same, and the cut-list addendum |
| Inside X-10: alert watcher, Cytoscape evidence graph, ECharts timeline, receipt view, server-sent events | new cut, proposed by Explain and agreed by the lead on [#227, 23 Nov](https://github.com/DuhItzAniket/Veyltrace/issues/227#issuecomment-7107226133), on condition that X-10's ≤ 5 min check holds and the watcher comes back first if Thu's rehearsal leaves time | **not on `main` yet**: the lead asked for an addendum to 20261123-cl-explain-scope-cuts in a new PR, and none exists ([06-live-demo](../06-live-demo.md) says the same). Follow-up below |
| OTel Demo lab profile | 07 §1.1 item 5 (keep Online Boutique) | **no ADR line yet** ([05 §4](../05-fault-lab-and-dataset.md#4-profile-otel-opentelemetry-demo-310-on-compose)). Follow-up below |
| Anomara TSFM plugin (O-10); `veyllab` adapter half of O-07 | 07 §1.1 item 1; moves with X-14 | [20261124-as-observe-cuts-v1-1](20261124-as-observe-cuts-v1-1.md) (#497, merged 26 Nov) |
| The remaining LLM-heavy AI arms: detected-alert rq2, RE3 rq2, Nezha brief, the ±60/±120 s brief shifts, the RCAEval-C AI cells, the brief arm of rq3 and LOSO (rq3 and LOSO run AI-off) | new cut: LLM budget; lead's decision of 25 Nov | #532 (PR #533), `not_run.yaml`; candidates for **v1.2** |

"Run if time remains" (cut-list ADR): the Nezha AI cells, then the remaining RCAEval-C AI cells, then the ±30 s brief cells. **Settled on 25 Nov:** none of them runs in v1.0, and all are in `not_run.yaml`. The lead's cut of the LLM-heavy arms (#532) makes the Nezha and RCAEval-C AI cells v1.2 candidates (row above). The ±30 s cells stay cut as exploratory.

### 3. What went well and what went badly (process)

**Went well**

- **Lanes and contracts held.** Explain changes outside its paths went through the `cross-lane` label, for example the X-07 fixture cascade (#227, 18 Nov) and `SPEC_ENGINE_DEPS` in #460.
- **Reviews found real bugs.** Lakshanaa's Claude reviewed 40 PRs from Aniket's sessions (Explain and Reason). Its 10 change requests all reproduced ([#227 §3](https://github.com/DuhItzAniket/Veyltrace/issues/227)).
- **One coordination issue settled ownership.** #227 named which agent pushes which branch, and seven decisions (D1–D7). Explain answered its share the same day (11 Nov), and lanes posted "taking X" notes there before starting.
- **Small slices merged fast.** X-04, X-05, X-07, X-09 and X-10 were split into issue-sized PRs. Of the 51 lane-labelled Explain PRs that CL opened, 48 merged on the day they were opened or the next day (median 0 days, maximum 4).
- **Cuts were decided by the protocol, not the clock.** Every cut so far was made before M4, with a reason the paper prints (`not_run.yaml`, `bench/tests/test_not_run_register.py`).
- **The never-cut items for Explain all exist.** Relentra `brief`, replay, the console verdict view and the live demo. The live demo passed its ≤ 5 min check twice in the dry run.

**Went badly**

- **Stacked PRs waited.** The 23 Explain PRs opened by Aniket's sessions on 8 Nov took 0 to 10 days to merge (median 5). The stacks conflicted with `main` after squash merges and waited on change requests lower in the stack ([#227 §2](https://github.com/DuhItzAniket/Veyltrace/issues/227)). The fix (merge `main` into shared stacked branches, never rebase) is D7.
- **Explain milestones slipped.** X-00 closed 8 days after M0, X-05 9 days after M2, X-09 2 days after M3, and X-10's dry run was 3 days after M3 (§1).
- **The plan assumed laptops we did not have.** The lab laptop is not free overnight (#227 D5). There is no Laptop 2 (#511), so the LLM runs on the recording host and the demo video is AI off. X-11 reached 8 of the 120 captures it targeted.
- **Integration bugs surfaced late.** The 25 Nov dry run found that Infralume dropped every lab metric and log record, because the resources had no `service.name`. #518 fixed this in the Collector. The OTLP converter path was wired only on 24–25 Nov (#507, #509).
- **Small hygiene slips.** A "closes #21" in a handoff line closed O-04 early (#97). A squash merge kept the title "Task 19" (#220). #49's close reason does not match its ADR.
- **The live verdict did not name the injected service.** Both dry-run verdicts were INCONCLUSIVE with frontend leading and the injected `currencyservice` second ([06-live-demo B.4](../06-live-demo.md)). Diagnostic accuracy is not part of X-10's acceptance. **Decided (lead, 27 Nov):** yes, after v1.0, as part of the H1a/H1b follow-up in §4: the verified leader is right less often than the fused slate it verifies (Reason's items, below), and this verdict is one more case of that pattern.

**Observe's items** (given by Annapurna S on #523, 25 Nov)

Went well

- **Small sub-issues.** O-01 to O-06 were split into 4–11 sub-issues each, one PR per sub-issue under 400 lines; Anomara and Causalith closed two days before M2 and Causync on it.
- **Real-data checks caught what goldens could not**: the Hugging Face mirror stores log times in seconds (O-01), Nezha's `inject_timestamp` is eight hours off on two days and its minute-file names leak the fault minute (O-08, lead's review of #436).

Went badly

- **O-07 was started too late** (24 Nov for an M2 task), so the live demo's ingest path was wired one day before the rehearsal.
- **O-11 was measured after the freeze.** The earlier profile on a fast laptop looked fine; the slowest laptop's numbers came on 25 Nov, when nothing could be changed.
- **The Nezha artefact (#514) was found three days after the adapter merged**: the adapter's tests check the tables, and nobody ran the anomaly step over all 101 cases until the bug-bash dry run.
- **Cross-platform last digits (#256)** mean the arm64 laptop cannot regenerate goldens, so every Observe change that touches a config hash waits for the lead's machine (#450).

**Reason's items** (the lead, 27 Nov)

Went well

- **Pre-registration held.** `prereg-v1` came before every Veyltrace-arm result; only the R-05 baselines, which 04 §1 allows, are older. Six later commits changed 04 (#413 twice, #440, #532, #549, #561), and each one has a §12 row. One convention was logged five days late (the row of 21 Nov, logged 26 Nov).
- **Small PRs merged fast once the stacks cleared.** 140 of the 165 `lane:reason` PRs merged on the day they were opened or the next day (median 0 days). Of the 132 not opened on 9 Nov, 130 did.
- **Replay was exact where it was recorded, and the one miss was explained the same day.** On the recording host, Tier 1 gave 801/801 (#544). The second laptop gave 800/801 (#575). The cause was traced the same day to OpenBLAS choosing its kernel per CPU (#576, v1.1), and REPRODUCE.md got the caveat (#578). The frozen results were not touched.
- **The protocol made the cuts, and results were reported as they came.** The cuts are in an ADR and in `not_run.yaml`. The missed hypotheses are named in their results PRs (e.g. #548, #554), not left out.
- **Review went both ways.** The lead reviewed 96 of the 98 teammate PRs and asked for changes on 17. Teammates asked for changes on 10 Reason PRs, and all of them reproduced (#227 §3).
- **Decisions were written down:** 18 lead ADRs, and the R-16 decisions on #45.

Went badly

- **Every Reason milestone up to M3 slipped.** All the M0 work landed on 8 Nov in one stack. `prereg-v1` and `contracts-1.0` came 10 days after M1, R-05 8 days after it, and R-11 is still open (§1).
- **The 9 Nov stacks waited.** The 33 Reason PRs opened that day took a median of 4 days to merge, and nine took 8. They conflicted with `main` after squash merges and waited on change requests lower in the stack (#227 §2; fix D7).
- **Most Reason PRs merged unreviewed, by their author.** 114 of the 165 have no review, and the lead admin-merged every one, by deliberate practice when teammates were busy. This departs from AGENTS §4.9. **Open** for the retro: restore a teammate review for engine and protocol PRs in v1.1, or amend §4.9.
- **R-16 found harness gaps that a dry run of every YAML would have caught.** Each gap cost a re-run, a new derived code tag, or both:
  - `prior-only` was not built (#561, #562);
  - `bench/baselines.yaml` had no RCAEval entries for RE3 and Nezha (#615, #616);
  - the Nezha entries then pointed RCAEval's `main.py` at the wrong folder, so it downloaded RE2 and scored that, and all 96 Nezha cases failed (#627, #630);
  - the LOSO and transfer results went in without their fitted calibration files, and the interval script refused three folds (#635, #636).
- **Some acceptance checks closed without a record.** R-02 was checked on one laptop only. R-10's 3 real cases and R-07's all-lane review have no record. R-01 closed two days before its check first ran.
- **The compute host set the pace.** A kept RE2 experiment takes about 30 GB, so from 26 Nov the lanes deleted each experiment's runs after rc 0 (stated in the 24 results PRs). A network drop also stopped one run (#627).
- **The headline accuracy hypotheses missed.** These are R-18's to report; the retro records only the pattern. H1a and H1b missed: the verified leader is right less often than RCAEval's N-Sigma and than the fused slate it verifies. On RE2-OB/SS/TT, `veyltrace:off` has AC@1 0.528 / 0.472 / 0.584 against `causatrix:rrf`'s 0.787 / 0.809 / 0.876 (re2-oracle-rq1-v1). SC-4's NO_FAULT also missed (§1, R-12). What held is calibrated coverage (H3a) and replay on the recording host (H6a). Under the detected protocol, no alert fires on RE2-TT (#568, #571); R-11's design did not foresee this.

### 4. v1.1 scope (every item the docs defer to v1.1)

| # | Item | Lane | Source |
|---|---|---|---|
| 1 | X-11: lab collection to ≥ 120 validated cases | Explain | [20261123-cl-explain-scope-cuts](20261123-cl-explain-scope-cuts.md); [05 §12](../05-fault-lab-and-dataset.md#12-dataset-release-plan) |
| 2 | X-14: VeylLab release (Parquet, answer keys, Croissant draft, `lab/release.py`, datasheet) | Explain | 07 §1.1 item 6; [cut-list addendum](20261121-ak-r16-cut-list.md); [05 §12](../05-fault-lab-and-dataset.md#12-dataset-release-plan); [11 §8](../11-research-paper-plan.md#8-reproducibility-and-artifact-checklist) |
| 3 | `veyllab` adapter (O-07 second half) and the two VeylLab experiments | Observe, Reason | [20261124-as-observe-cuts-v1-1](20261124-as-observe-cuts-v1-1.md); `not_run.yaml` |
| 4 | X-12: MCP server (`diagnose`, `verify_hypothesis`, `get_receipt`); reopen #49 | Explain | [20261123-cl-explain-scope-cuts](20261123-cl-explain-scope-cuts.md); [08](../engines/08-relentra.md) OQ-10 |
| 5 | Alert watcher, with its own settle (`live.manual_settle_s`) | Explain | #227 (23 Nov); `config/gateway.yaml`; [06 §3.4](../06-gateway-and-console.md) |
| 6 | Console live view (`/live`) with a "Diagnose now" button | Explain | [06 §5.2](../06-gateway-and-console.md#52-views); [06-live-demo](../06-live-demo.md) |
| 7 | Run-view sections e (Cytoscape evidence graph), f (ECharts timeline), i (receipt view and Replay button) | Explain | #227 (23 Nov); [06 §5.2](../06-gateway-and-console.md#52-views) |
| 8 | Server-sent live events, live series and event-stream routes | Explain | #227 (23 Nov); `packages/gateway/tests/test_openapi.py` |
| 9 | Run-view section h: card summary with cite chips and the narrator line ("template" or "LLM, checked"), then an AI-on (cassette) shot in the demo | Explain | [06 §5.2](../06-gateway-and-console.md#52-views) h; [06-live-demo](../06-live-demo.md) ("Narration is not in the video") |
| 10 | Relentra `investigate` mode and its two experiments | Explain, Reason | 07 §1.1 item 3; [08 §3.3](../engines/08-relentra.md) (purpose list marks it v1.1) |
| 11 | OTel Demo lab profile | Explain | 07 §1.1 item 5; [05 §4](../05-fault-lab-and-dataset.md#4-profile-otel-opentelemetry-demo-310-on-compose) ("design stays for v1.1") |
| 12 | Anomara TSFM plugin (O-10) | Observe | [20261124-as-observe-cuts-v1-1](20261124-as-observe-cuts-v1-1.md) |
| 14 | Cross-CPU last digits in intervention evidence (RQ6 second laptop, one card) | Reason | #576 |
| 13 | Mondrian conformal per (family × modality pattern) | Reason | [20261030-ak-conformal-abstention](20261030-ak-conformal-abstention.md) ("candidate for v1.1") |

**Candidates that no doc marks v1.1 yet** (the team decides at the retro):

- `veyltrace replay --full` is not built and exits 1 ([10 §3.9](../engines/10-causivra.md)).
- Protobuf OTLP bodies get 415 until `opentelemetry-proto` is a dependency ([06-live-demo](../06-live-demo.md), G3).
- `lab/up.py` does not restart the Collector when only the ConfigMap changes ([06-live-demo B.4](../06-live-demo.md)).
- An in-gateway run took 82 s against 25 s standalone; the cause is not profiled ([06-live-demo B.4](../06-live-demo.md)).
- The Explain "run if time remains" cells that did not run by M4 (§2).
- VeylLab as a NeurIPS 2027 E&D paper, if it reaches ≥ 300 validated cases ([07 §8](../07-roadmap.md#8-after-the-month)).
- Why the verified leader is right less often than the fused slate it verifies (H1a, H1b; the live verdict in §3). Its v1.1 issue opens with the others after v1.0 (lead, 27 Nov).
- The determinism gate on real cases: commit `scripts/ci_real_case.json` and run the arm on 3 cases, as R-10 asked (§1).

**Decided (lead, 25 Nov, #227):** v1.1 scope is the list above. The AI arms cut on 25 Nov (§2) are candidates for **v1.2**, not v1.1. The v1.1 release date and the order of the items are deferred until after v1.0, like §5.

### 5. Post-month plan: venue, arXiv endorser, author order

**Decision (lead, 25 Nov, on #523):** Aniket has exams, and the aim is to finish v1.0 by 1 Dec; everything else comes after it. Venue, arXiv endorser, arXiv category and author order are therefore **deferred until after v1.0**. This is a decision, not an open item, so #55 can close on this ADR. The **RK-22 fallback stands** ([12](../12-risks.md)): the Zenodo DOI ships with v1.0.0, and arXiv follows once someone endorses. Aniket has endorsement requests drafted; no endorser is confirmed yet (#227, 25 Nov).

The options stay as written, for when the decision is taken:

| Venue and track | Deadline (per 11 §7) | 11 §7 verdict |
|---|---|---|
| KDD 2027 cycle 2 (Research) | Feb 2027, exact date unconfirmed | primary target, if RQ1 meets SC-3(b) and RQ3 holds |
| ISSRE 2027 research | ~Apr 2027, inferred | primary alternative, and fallback if results are mixed |
| FSE 2027 Industry | 23 Jan 2027 | only with industrial data or a partner |
| NeurIPS 2027 Evaluations & Datasets | ~May 2027, inferred | VeylLab only (second paper, C5), at ≥ 300 validated cases |

`paper/main.tex` uses `acmart` sigconf for KDD. Switching to ISSRE changes only `main.tex` and the bibliography style ([paper/README.md](../../paper/README.md)).

- **arXiv endorser:** since 21 Jan 2026, a first-time submitter without an accepted paper in the domain needs a personal endorsement ([11 §7](../11-research-paper-plan.md#7-venue-plan-and-arxiv)). The options named there are a faculty advisor at RV University, or an outside researcher with cs.SE, cs.DC or cs.LG arXiv history.
- **arXiv category:** cs.SE primary with a cs.DC or cs.LG cross-list (*proposal*, 11 §7).
- **Author order:** 11 §9 suggests a rule (CRediT contribution, then alphabetical with an equal-contribution footnote; an advisor or endorser is listed only for a CRediT role beyond endorsement) and a provisional CRediT table.

| Decision | Options | Decided |
|---|---|---|
| Venue | KDD 2027 c2 · ISSRE 2027 · FSE 2027 Industry · (VeylLab) NeurIPS 2027 E&D | **Deferred until after v1.0** (lead, 25 Nov) |
| arXiv endorser | RV University faculty advisor · outside researcher (cs.SE/cs.DC/cs.LG) | **Deferred until after v1.0**; RK-22 fallback: Zenodo DOI with v1.0.0, arXiv once endorsed |
| arXiv category | cs.SE + cs.DC or cs.LG cross-list (*proposal*) | **Deferred until after v1.0** |
| Preprint timing vs venue anonymity policy | before or alongside submission, per the venue's policy (11 §7) | **Deferred until after v1.0**, with the venue |
| Author order | 11 §9 rule as written, or amended | **Deferred until after v1.0** |
| v1.1 scope and date | §4 | scope **decided** (§4, lead, 25 Nov); date **deferred until after v1.0** |

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Separate ADRs per decision | each decision is findable by slug | four files for one meeting; the retrospective facts would sit in none of them | L-07 asks for one record |
| Retrospective in an issue comment | quick | not versioned with the paper; the ADR README asks for an ADR | the paper's threats section and the release need a stable file to cite |

## Consequences

- **Positive:** one file records what shipped, what was cut and why, and what v1.1 holds. The deferred decisions sit in one table, with the options ready for after v1.0.
- **Negative / costs:** venue and author order stay undecided past the month, so the paper keeps its KDD template until then. Reason's rows show the state on 27 Nov, before R-17, R-18 and L-05.
- **Follow-ups:**
  - Explain: the addendum to [20261123-cl-explain-scope-cuts](20261123-cl-explain-scope-cuts.md) for the five X-10 sub-cuts, as the lead asked on #227 (23 Nov).
  - Explain: an ADR line for the OTel Demo profile cut (07 §1.1 item 5).
  - Explain: correct #49's close reason to "not planned", or note why it stays "completed".
  - Reason, before #45 closes: run H6a's CI replay site, or give it a `not_run.yaml` entry with its reason.
  - Reason, at L-05: add `results-code-v1-baselines` and `-baselines-2` to REPRODUCE.md's tag table.
  - After v1.0: take the deferred decisions in §5 and open v1.1 issues for §4.

## Confirmation

Reason's rows are in. The lead sets the status to Accepted and merges, which ticks #55's acceptance ("ADR merged"). The deferred decisions of §5 are taken after v1.0, and the v1.1 issues follow, one per §4 row the team keeps.

## Evidence

- [07](../07-roadmap.md) §1, §1.1, §7, §8; [11 §7, §9](../11-research-paper-plan.md#7-venue-plan-and-arxiv); [12](../12-risks.md) RK-22; [05 §4, §12](../05-fault-lab-and-dataset.md); [06](../06-gateway-and-console.md) §3.4, §5.2; [06-live-demo](../06-live-demo.md) B.4.
- [20261121-ak-r16-cut-list](20261121-ak-r16-cut-list.md) and its 22 Nov addendum; [20261123-cl-explain-scope-cuts](20261123-cl-explain-scope-cuts.md); `bench/results/not_run.yaml`.
- #227 (coordination: §2, §3, §6; comments of 11, 23 and 25 Nov); #523 (the lead's decision and Observe's rows, 25 Nov); GitHub issue and PR lists of 25 and 26 Nov, queried as described in Context.
