# v1.0 retrospective and post-month plan: v1.1 scope listed; venue, arXiv endorser and author order open for the retro

- **Status:** Proposed (draft for the L-07 retrospective; the team fills the decisions marked **Open**)
- **Date:** 2026-11-25
- **Author:** C Lakshanaa (CL)
- **Deciders:** the lead, with all three lanes at the retrospective
- **Consulted:** Explain (this draft). Reason and Observe add their own rows where marked *to fill*
- **Issue / CCR:** #55 (L-07)
- **Supersedes:** none · **Superseded by:** none

## Context

L-07 ([07 §7](../07-roadmap.md#7-release-mon-30-nov--tue-1-dec--m5)) asks for a retrospective and a post-month plan (venue, arXiv endorser, v1.1 scope) recorded in `docs/adr/`. The [ADR README](README.md) also lists "venue, authorship and post-month plan" as needing an ADR. [11 §7](../11-research-paper-plan.md#7-venue-plan-and-arxiv) asks to record the venue and endorser decision here, and [11 §9](../11-research-paper-plan.md#9-authorship-and-contribution-statement) the author order.

This draft is written on Wed 25 Nov, before the bug bash (L-04, Thu 26), M4 (Sun 29) and the retrospective itself (Mon 30 Nov – Tue 1 Dec). Every fact below comes from the repo or GitHub on that date, with its PR, issue or file. Anything not yet known is marked **Open**. Explain's rows are complete. Reason and Observe fill their own rows.

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

We choose **option 1**. Sections 1 to 3 record facts. Section 4 lists the v1.1 scope as the docs defer it. Section 5 lists the venue, endorser and author-order options, each marked **Open: team decides at the retro**, because no doc records a decision yet.

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
| M3 (Sun 22 Nov) | X-08 Relentra v1 (#41) | budgets, cassette wiring and the trace for brief mode only ([08 §10](../engines/08-relentra.md)); spec synced by #516 | **open**. Acceptance "100% replay on recorded RE2 cases" waits for the RQ6 replay: no `bench/results/replay/` on `main` yet (lead's plan on #227, 23 Nov: files Thu 26, second-laptop replay Fri 27, *estimate*) |
| M3 | X-09 Causivra v1: narration, claim checker, replay (#42) | #434 (replay, 22 Nov), #459, #460, #462, #467 (23 Nov); bug-bash fix #520 (25 Nov) | closed 24 Nov. Never-cut item (replay) shipped |
| M3 | X-10 Live (#43) | #470, #473, #474 (23 Nov), #476, #477, #488, #491, #503, #507 (23–24 Nov), #509, #518, #521 (25 Nov) | **open**. Dry run 25 Nov on laptop 1: injection to AI-off verdict on screen in 2 min 12 s and 3 min 17 s (≤ 5 min: pass), replay exit 0, RAM recorded ([06-live-demo B.4](../06-live-demo.md)). It ran on a local branch that also had Observe's #508 (`otlp_live`, not merged yet). Never-cut item (live demo on Online Boutique) |
| M3 | X-11 Lab collection (#44) | #222 (validation, night plans, daily report), #230, #517 | **open**. 8 of 120 captures (`bench/results/not_run.yaml`). v1.0 scope is the demo captures only ([20261123-cl-explain-scope-cuts](20261123-cl-explain-scope-cuts.md)) |
| M4 (Sun 29 Nov) | X-12 MCP server (#49) | ADR #463 | cut to v1.1. GitHub shows #49 closed on 23 Nov with reason "completed", although the ADR says "not planned" |
| M4 | X-13 Demo script, video, paper sections (#50) | #471 (paper sections on the proposer and narration), #494 (demo script and runbook); #522 open (the video was recorded 25 Nov, 2:16, AI off) | **open**. The video is not yet in the release assets |
| M4 | X-14 VeylLab packaging (#51) | — | closed 24 Nov as "not planned"; moves to v1.1 |
| M4 | L-04 Bug bash and docs review (#52) | #516, #517, #520 merged; #515, #519 open | **open** (bug bash is Thu 26) |
| M5 (Tue 1 Dec) | L-07 (#55) | this PR | draft |

*Reason lane rows (R-xx, L-00, L-03, L-05): to fill by Reason.* *Observe lane rows (O-xx, L-06): to fill by Observe.*

Milestone tags: `git tag` shows `contracts-1.0` (18 Nov), `prereg-v1` (18 Nov) and `results-code-v1` (23 Nov). The planned `v0.0.1`–`v0.3.0` milestone tags ([07 §1](../07-roadmap.md#1-phases-and-milestones)) were not cut. **Open:** say whether the retro records this as a slip or as a deliberate change.

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
| Anomara TSFM plugin (O-10); `veyllab` adapter half of O-07 | 07 §1.1 item 1; moves with X-14 | Observe's ADR in #497 (open) |

"Run if time remains" (cut-list ADR): the Nezha AI cells, then the remaining RCAEval-C AI cells, then the ±30 s brief cells. **Open until M4:** which of them ran.

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
- **The live verdict did not name the injected service.** Both dry-run verdicts were INCONCLUSIVE with frontend leading and the injected `currencyservice` second ([06-live-demo B.4](../06-live-demo.md)). Diagnostic accuracy is not part of X-10's acceptance. **Open:** whether the retro wants a v1.1 issue to look into it.

*Reason and Observe add their own items: to fill.*

### 4. v1.1 scope (every item the docs defer to v1.1)

| # | Item | Lane | Source |
|---|---|---|---|
| 1 | X-11: lab collection to ≥ 120 validated cases | Explain | [20261123-cl-explain-scope-cuts](20261123-cl-explain-scope-cuts.md); [05 §12](../05-fault-lab-and-dataset.md#12-dataset-release-plan) |
| 2 | X-14: VeylLab release (Parquet, answer keys, Croissant draft, `lab/release.py`, datasheet) | Explain | 07 §1.1 item 6; [cut-list addendum](20261121-ak-r16-cut-list.md); [05 §12](../05-fault-lab-and-dataset.md#12-dataset-release-plan); [11 §8](../11-research-paper-plan.md#8-reproducibility-and-artifact-checklist) |
| 3 | `veyllab` adapter (O-07 second half) and the two VeylLab experiments | Observe, Reason | #497 (open); `not_run.yaml` |
| 4 | X-12: MCP server (`diagnose`, `verify_hypothesis`, `get_receipt`); reopen #49 | Explain | [20261123-cl-explain-scope-cuts](20261123-cl-explain-scope-cuts.md); [08](../engines/08-relentra.md) OQ-10 |
| 5 | Alert watcher, with its own settle (`live.manual_settle_s`) | Explain | #227 (23 Nov); `config/gateway.yaml`; [06 §3.4](../06-gateway-and-console.md) |
| 6 | Console live view (`/live`) with a "Diagnose now" button | Explain | [06 §5.2](../06-gateway-and-console.md#52-views); [06-live-demo](../06-live-demo.md) |
| 7 | Run-view sections e (Cytoscape evidence graph), f (ECharts timeline), i (receipt view and Replay button) | Explain | #227 (23 Nov); [06 §5.2](../06-gateway-and-console.md#52-views) |
| 8 | Server-sent live events, live series and event-stream routes | Explain | #227 (23 Nov); `packages/gateway/tests/test_openapi.py` |
| 9 | Run-view section h: card summary with cite chips and the narrator line ("template" or "LLM, checked"), then an AI-on (cassette) shot in the demo | Explain | [06 §5.2](../06-gateway-and-console.md#52-views) h; [06-live-demo](../06-live-demo.md) ("Narration is not in the video") |
| 10 | Relentra `investigate` mode and its two experiments | Explain, Reason | 07 §1.1 item 3; [08 §3.3](../engines/08-relentra.md) (purpose list marks it v1.1) |
| 11 | OTel Demo lab profile | Explain | 07 §1.1 item 5; [05 §4](../05-fault-lab-and-dataset.md#4-profile-otel-opentelemetry-demo-310-on-compose) ("design stays for v1.1") |
| 12 | Anomara TSFM plugin (O-10) | Observe | #497 (open) |
| 13 | Mondrian conformal per (family × modality pattern) | Reason | [20261030-ak-conformal-abstention](20261030-ak-conformal-abstention.md) ("candidate for v1.1") |

**Candidates that no doc marks v1.1 yet** (the team decides at the retro):

- `veyltrace replay --full` is not built and exits 1 ([10 §3.9](../engines/10-causivra.md)).
- Protobuf OTLP bodies get 415 until `opentelemetry-proto` is a dependency ([06-live-demo](../06-live-demo.md), G3).
- `lab/up.py` does not restart the Collector when only the ConfigMap changes ([06-live-demo B.4](../06-live-demo.md)).
- An in-gateway run took 82 s against 25 s standalone; the cause is not profiled ([06-live-demo B.4](../06-live-demo.md)).
- The Explain "run if time remains" cells that did not run by M4 (§2).
- VeylLab as a NeurIPS 2027 E&D paper, if it reaches ≥ 300 validated cases ([07 §8](../07-roadmap.md#8-after-the-month)).

**Open:** the v1.1 release date and the order of the items above.

### 5. Post-month plan: venue, arXiv endorser, author order

**Venue: Open, team decides at the retro.** The options in [11 §7](../11-research-paper-plan.md#7-venue-plan-and-arxiv) (dates unconfirmed or inferred there; check each official CFP):

| Venue and track | Deadline (per 11 §7) | 11 §7 verdict |
|---|---|---|
| KDD 2027 cycle 2 (Research) | Feb 2027, exact date unconfirmed | primary target, if RQ1 meets SC-3(b) and RQ3 holds |
| ISSRE 2027 research | ~Apr 2027, inferred | primary alternative, and fallback if results are mixed |
| FSE 2027 Industry | 23 Jan 2027 | only with industrial data or a partner |
| NeurIPS 2027 Evaluations & Datasets | ~May 2027, inferred | VeylLab only (second paper, C5), at ≥ 300 validated cases |

`paper/main.tex` uses `acmart` sigconf for KDD. Switching to ISSRE changes only `main.tex` and the bibliography style ([paper/README.md](../../paper/README.md)). 11 §7's recommendation is an arXiv preprint and the Zenodo `v1.0.0` artifact in December 2026, then KDD cycle 2, or ISSRE if results are mixed.

**arXiv endorser: Open, team decides at the retro.** Since 21 Jan 2026, a first-time submitter without an accepted paper in the domain needs a personal endorsement ([11 §7](../11-research-paper-plan.md#7-venue-plan-and-arxiv)). The options named there are a faculty advisor at RV University, or an outside researcher with cs.SE, cs.DC or cs.LG arXiv history. The action was Aniket's, due M2 (15 Nov). No issue, PR or doc records an endorser yet; a GitHub search for "endorser" finds only #55. Risk RK-22's trigger is "no endorser by 1 Dec", and its fallback is the Zenodo DOI now, then arXiv when endorsed ([12](../12-risks.md)). The arXiv category is cs.SE primary with a cs.DC or cs.LG cross-list (*proposal*, 11 §7, due M4); **Open**.

**Author order: Open, team decides at the retro.** 11 §9 suggests a rule (CRediT contribution, then alphabetical with an equal-contribution footnote; an advisor or endorser is listed only for a CRediT role beyond endorsement) and a provisional CRediT table to revise at M4.

| Decision | Options | Decided |
|---|---|---|
| Venue | KDD 2027 c2 · ISSRE 2027 · FSE 2027 Industry · (VeylLab) NeurIPS 2027 E&D | **Open** |
| arXiv endorser | RV University faculty advisor · outside researcher (cs.SE/cs.DC/cs.LG) | **Open** |
| arXiv category | cs.SE + cs.DC or cs.LG cross-list (*proposal*) | **Open** |
| Preprint timing vs venue anonymity policy | before or alongside submission, per the venue's policy (11 §7) | **Open** |
| Author order | 11 §9 rule as written, or amended | **Open** |
| v1.1 scope and date | §4 | **Open** |

## Alternatives considered

| Option | Pros | Cons | Why not chosen |
|---|---|---|---|
| Separate ADRs per decision | each decision is findable by slug | four files for one meeting; the retrospective facts would sit in none of them | L-07 asks for one record |
| Retrospective in an issue comment | quick | not versioned with the paper; the ADR README asks for an ADR | the paper's threats section and the release need a stable file to cite |

## Consequences

- **Positive:** one file records what shipped, what was cut and why, and what v1.1 holds. The open decisions sit in one table for the retro.
- **Negative / costs:** written three days before M4. §1 and §2 change once the bug bash, R-16 and X-13 finish, so they need a refresh before acceptance.
- **Follow-ups:**
  - Explain: the addendum to [20261123-cl-explain-scope-cuts](20261123-cl-explain-scope-cuts.md) for the five X-10 sub-cuts, as the lead asked on #227 (23 Nov).
  - Explain: an ADR line for the OTel Demo profile cut (07 §1.1 item 5).
  - Explain: correct #49's close reason to "not planned", or note why it stays "completed".
  - All lanes: fill the Reason and Observe rows of §1 and §3, and refresh §1 and §2 after M4.
  - At the retro: fill every **Open** cell in §5. Then open v1.1 issues for §4 and set the lead's status to Accepted.

## Confirmation

The retro fills every **Open** cell. The lead sets the status to Accepted and merges, which ticks #55's acceptance ("ADR merged"). The v1.1 issues exist on the board, one per §4 row the team keeps.

## Evidence

- [07](../07-roadmap.md) §1, §1.1, §7, §8; [11 §7, §9](../11-research-paper-plan.md#7-venue-plan-and-arxiv); [12](../12-risks.md) RK-22; [05 §4, §12](../05-fault-lab-and-dataset.md); [06](../06-gateway-and-console.md) §3.4, §5.2; [06-live-demo](../06-live-demo.md) B.4.
- [20261121-ak-r16-cut-list](20261121-ak-r16-cut-list.md) and its 22 Nov addendum; [20261123-cl-explain-scope-cuts](20261123-cl-explain-scope-cuts.md); `bench/results/not_run.yaml`.
- #227 (coordination: §2, §3, §6; comments of 11 Nov and 23 Nov); GitHub issue and PR lists of 25 Nov, queried as described in Context.
