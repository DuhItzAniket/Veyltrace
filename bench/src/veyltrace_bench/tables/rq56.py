"""RQ5 cost and RQ6 replay tables (11 §5.5, §5.6).

Table 8 holds the cost percentiles of the RE2 oracle RQ1 and RQ2 experiments per system and method
(nearest-rank p50/p95 over the group's rows, 03 §13.3); Table A1 holds them for every experiment,
so the cost of every reported number is on record (04 §6 "RQ5 cost is recorded on every run").
Two committed side results complete RQ5 (lead rule R4): Table 8b is the AI path's recorded model
time and tokens (`bench/results/rq5-ai-cost`, since the AI arms' bench rows are replays without
model time), and Table 8c the slowest laptop's per-case pipeline time and memory, per step, that
H5 is read against (`bench/results/perf-o11`, O-11). Both are printed as their files hold them;
the tables compute no new statistics (R3). Table 9 holds the RQ6 replay rates of
`bench/results/replay/<role>/` (#440).
"""

from __future__ import annotations

import csv
from typing import cast

from veyltrace_bench.experiment import Experiment
from veyltrace_bench.tables import cells
from veyltrace_bench.tables.cells import Cell
from veyltrace_bench.tables.context import Context
from veyltrace_bench.tables.render import Row, Table
from veyltrace_bench.tables.results import (
    AI_COST_DIR,
    PER_CASE,
    PERF_DIR,
    SUMMARY,
    UNLISTED,
    Results,
    load_ai_cost,
    load_perf,
)
from veyltrace_bench.tables.rq1 import methods, no_value
from veyltrace_contracts.models import ReplayTier1
from veyltrace_core import textio

MAIN = ("re2-oracle-rq1-v1", "re2-oracle-rq2-v1")  # Table 8: the deterministic and AI paths on RE2
COST = (
    ("Wall p50 (ms)", "wall_ms_p50"), ("Wall p95 (ms)", "wall_ms_p95"),
    ("Peak RSS p50 (MiB)", "peak_rss_mb_p50"), ("Peak RSS p95 (MiB)", "peak_rss_mb_p95"),
    ("Tokens in p50", "tokens_in_p50"), ("Tokens in p95", "tokens_in_p95"),
    ("Tokens out p50", "tokens_out_p50"), ("Tokens out p95", "tokens_out_p95"), ("Rows with cost", "n_cost"),
)  # fmt: skip
COLUMNS8 = ("Experiment", "System", "Method", *(c for c, _ in COST))
WALL = frozenset({"wall_ms_p50", "wall_ms_p95"})
#: A slate-scored method's summary cost is null by design (04 §12 row of 2026-11-21).
SLATE_REUSE = (
    "a slate-scored causatrix method reuses the veyltrace:off run's upstream steps, so its summary cost "
    "is null by design and RQ5 cost comes from veyltrace:off (04 §12 row of 2026-11-21; ADR "
    "20261121-ak-slate-method-upstream-reuse)"
)
AI_REPLAY = "replay"  # per_case.csv ai_mode of a replayed AI-arm row (bench ai_arms)
#: An AI arm replayed from kept record runs has no model time, memory or token columns (ai_arms).
REPLAYED = (
    "not applicable: every row of this AI arm was replayed from a kept record run (per_case.csv ai_mode "
    "replay) and has an empty wall_ms, so the summary has no run cost for it{}"
)
RECORDED = "; the recording's model time and tokens are in Table 8b (bench/results/rq5-ai-cost)"
NOT_RECORDED = "; no committed file has the recording's cost for this experiment"
#: Held-out runs of a calibration fit restart from their calibration run (ADR calibration-fit-conventions).
RESTART_SCHEMES = frozenset({"crossfit2", "loso"})
HELD_OUT_SUM = (
    "the wall time of a held-out run here is that run plus the calibration run it restarts from (ADR "
    "20261121-ak-calibration-fit-conventions), so it is not comparable with a solo run; RQ5 cost comes "
    "from re2-oracle-rq1-v1"
)


def _replayed(res: Results) -> frozenset[str]:
    """The methods whose per_case.csv rows were all replayed (ai_mode replay) without a wall time."""
    if res.path is None or not (res.path / PER_CASE).is_file():
        return frozenset()
    modes: dict[str, set[tuple[str, bool]]] = {}
    for row in csv.DictReader(textio.read_text(res.path / PER_CASE).splitlines()):
        modes.setdefault(row.get("method", ""), set()).add((row.get("ai_mode", ""), bool(row.get("wall_ms"))))
    return frozenset(m for m, found in modes.items() if found == {(AI_REPLAY, False)})


def _cost_cell(
    exp: Experiment, res: Results, part: str, sys: str, method: str, key: str, ai: str | None
) -> Cell:
    """One cost value, or why it has none: unlisted, slate reuse, or a replayed AI arm (R2)."""
    if "cost" not in exp.metrics:
        why = res.why(method)
        return (
            cells.not_run(why)
            if why is not None and res.old is None
            else cells.not_applicable(UNLISTED.format("cost"))
        )
    cell = res.metric(part, sys, method, "cost", key)
    group = res.group(part, sys, method)
    kind = next((m.kind for m in exp.methods if m.id == method), None)
    if group is not None and group.metrics.cost is None and kind == "causatrix":
        return cells.not_applicable(SLATE_REUSE)
    if ai is not None and cell.note == cells.UNDEFINED_NOTE:
        return Cell(cells.UNDEFINED, ai)
    if key in WALL and cell.note is None and exp.calibration.fit and exp.split.scheme in RESTART_SCHEMES:
        return Cell(cell.text, HELD_OUT_SUM)
    return cell


def _cost_rows(ctx: Context, experiment_ids: tuple[str, ...]) -> list[Row]:
    recorded = _ai_cost(ctx)
    rows: list[Row] = []
    for eid in experiment_ids:
        exp, res = ctx.spec(eid), ctx.get(eid)
        replayed = _replayed(res)
        tail = RECORDED if recorded is not None and recorded[1] == eid else NOT_RECORDED
        for part in exp.dataset.parts:
            sys = res.system_of(part)
            for m in methods(exp):
                ai = REPLAYED.format(tail) if m in replayed else None
                values = [_cost_cell(exp, res, part, sys, m, key, ai) for _, key in COST]
                rows.append(Row((cells.text(eid), cells.text(sys), cells.text(m), *values), res))
    return rows


def _side(ctx: Context, name: str) -> Results | None:
    return next((s.source for s in ctx.sides if s.source.experiment_id == name), None)


def _ai_cost(ctx: Context) -> tuple[Results, str] | None:
    """The rq5-ai-cost side result and the experiment it is the recording of, when committed."""
    side = _side(ctx, AI_COST_DIR)
    if side is None or side.path is None or not (side.path / SUMMARY).is_file():
        return None
    return side, load_ai_cost(side.path).experiment_id


AI_COLUMNS = (
    ("Model wall p50 (ms)", "model_wall_ms_p50"), ("Model wall p95 (ms)", "model_wall_ms_p95"),
    ("Tokens in p50", "tokens_in_p50"), ("Tokens in p95", "tokens_in_p95"),
    ("Tokens out p50", "tokens_out_p50"), ("Tokens out p95", "tokens_out_p95"),
    ("Turns p50", "turns_p50"), ("Turns p95", "turns_p95"), ("Runs", "n"),
)  # fmt: skip
COLUMNS8B = ("Stage", "Experiment", "System", "Method", *(c for c, _ in AI_COLUMNS), "Runs by status")
PROPOSER, NARRATION = "Relentra brief proposer (recorded)", "Causivra narration"
NO_AI_COST = f"no value: no committed bench/results/{AI_COST_DIR}/{SUMMARY} (scripts/rq5_ai_cost.py)"
NARRATED = (
    "every checked R-16 card is template-narrated, with no model call (#520), as scripts/rq5_ai_cost.py "
    f"(which wrote bench/results/{AI_COST_DIR}) records; no committed file has a narration timing"
)


def _number(value: object) -> Cell:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return cells.count(value)
    return cells.rate(None) if value is None else cells.text(str(value))


def _ai_rows(ctx: Context) -> list[Row]:
    """Table 8b: the recorded model time and tokens of the AI arm per system, and narration."""
    found = _ai_cost(ctx)
    width = len(COLUMNS8B) - 4
    if found is None:
        gap = no_value(NO_AI_COST)
        return [
            Row(
                (cells.text(PROPOSER), *map(cells.text, ("—", "all", "veyltrace:brief")), *[gap] * width),
                None,
            )
        ]
    side, eid = found
    assert side.path is not None
    cost, res = load_ai_cost(side.path), ctx.get(eid)
    arms = ", ".join(m.id for m in ctx.spec(eid).methods if m.ai.seeds)
    rows: list[Row] = []
    for system, entry in cost.systems.items():
        status = entry.get("status")
        counts = sorted(cast(dict[str, object], status).items()) if isinstance(status, dict) else []
        runs = ", ".join(f"{k} {v}" for k, v in counts) or "—"
        values = [_number(entry.get(key)) for _, key in AI_COLUMNS]
        labels = map(cells.text, (PROPOSER, eid, system, arms))
        rows.append(Row((*labels, *values, cells.text(runs)), side, (res,)))
    narrated = cells.not_applicable(NARRATED)
    rows.append(Row((*map(cells.text, (NARRATION, eid, "all", arms)), *[narrated] * width), side, (res,)))
    return rows


SLOWEST = "i5-1135g7.csv"  # laptop 1, the slowest (bench/results/perf-o11/README.md)
WARM_PASS = "2"  # the warm pass H5 (04 §2) is read against (perf-o11/README.md)
NO_PERF = f"no value: no committed bench/results/{PERF_DIR}/{SLOWEST} (scripts/observe/perf_check.py, O-11)"
EMPTY = "empty in the file"


def _perf_rows(ctx: Context) -> tuple[tuple[str, ...], list[Row]]:
    """Table 8c's step columns and rows: the slowest laptop's warm pass, one row per case."""
    side = _side(ctx, PERF_DIR)
    path = side.path / SLOWEST if side is not None and side.path is not None else None
    if side is None or path is None or not path.is_file():
        return (), [Row((cells.text("—"), *[no_value(NO_PERF)] * 4), None)]
    steps, found = load_perf(path)
    rows: list[Row] = []
    for r in (r for r in found if r["pass"] == WARM_PASS):
        values = [
            _number(float(r[c])) if r.get(c) else cells.not_applicable(EMPTY)
            for c in ("wall_ms", "peak_rss_mb", *steps)
        ]
        rows.append(
            Row((cells.text(r["case"]), cells.text(r["system"]), cells.text(r["outcome"]), *values), side)
        )
    return steps, rows


def cost(ctx: Context) -> list[Table]:
    caption = (
        "Nearest-rank p50 and p95 over each group's rows (03 §13.3); wall time per case and method, "
        "peak RSS of the run in MiB (per_case.csv peak_rss_mb), LLM tokens of AI arms. No committed file "
        "records the machine of these runs (bench_manifest has no host field; docs/team/*.md lists the "
        "laptops); the slowest laptop's measurement, which H5 is read against, is Table 8c. Replayed AI "
        "arms have no run cost; the recorded model time and tokens are Table 8b. Slate-scored causatrix "
        "methods have no cost by design (04 §12 row of 2026-11-21)."
    )
    caption_a1 = caption + (
        " Every experiment YAML is listed; one that does not list `cost` is n/a. In calibration-fit "
        "experiments with held-out restarts (crossfit2, loso), a held-out run's wall time includes its "
        "calibration run."
    )
    every = tuple(e.experiment_id for e in ctx.experiments)
    key = (0, 1, 2)  # experiment, system, method
    main, all_ = tuple(_cost_rows(ctx, MAIN)), tuple(_cost_rows(ctx, every))
    caption_b = (
        "The AI path's model cost per system as its recording logged it, from bench/results/"
        f"{AI_COST_DIR}/{SUMMARY} (scripts/rq5_ai_cost.py; nearest-rank p50 and p95, 03 §13.3; source "
        "named in the file: the recording's tier-1 replay rows). agent-only:brief reads the same "
        "proposals (04 §4), so it shares this cost. H5 budgets ≤ 180 s (Relentra brief) plus ≤ 60 s "
        "(Causivra narration) p95 (04 §2 RQ5). Percentiles carry no interval."
    )
    steps, perf = _perf_rows(ctx)
    columns_c = (
        "Case",
        "System",
        "Outcome",
        "Wall (ms)",
        "Peak RSS (MiB)",
        *(s.removesuffix("_ms") + " (ms)" for s in steps),
    )
    caption_c = (
        f"Pipeline wall time, peak RSS and per-step time per case on the slowest laptop, from bench/results/"
        f"{PERF_DIR}/{SLOWEST}, pass {WARM_PASS} (the warm pass H5 is read against, against 30 s and 3 GB; "
        f"machine, sample rule and date in bench/results/{PERF_DIR}/README.md). Not bench output: no "
        "experiment YAML and no summary.json, AI off; a 10-case sample per RE2 system, so its p95 is the "
        "maximum. The tables compute no percentiles from it (R3)."
    )
    return [
        Table("t08-rq5-cost", "Table 8: RQ5 cost on RE2", caption, COLUMNS8, main, key=key),
        Table(
            "t08b-rq5-ai-cost", "Table 8b: RQ5 AI path model cost", caption_b, COLUMNS8B, tuple(_ai_rows(ctx))
        ),
        Table("t08c-rq5-slowest-laptop", "Table 8c: RQ5 slowest laptop", caption_c, columns_c, tuple(perf)),
        Table("a1-cost-all", "Table A1: cost of every experiment", caption_a1, COLUMNS8, all_, key=key),
    ]


REPLAY = (
    ("Tier 1, recording laptop", "recording", 1),
    ("Tier 1, second laptop", "second-laptop", 1),
    ("Tier 1, CI", "ci", 1),
    ("Tier 2 regeneration, 50 recorded cases", "recording", 2),
)  # 04 §6 cross-cutting, §7 "Replay": (row, bench/results/replay/<role>, tier)
COLUMNS9 = ("Measurement", "Rate", "Runs", "Verdict reproduced", "Exit codes")


def _replay_row(ctx: Context, label: str, role: str, tier: int) -> Row:
    got = ctx.replays.get(role)
    entry = (
        None if got is None or got.summary is None else got.summary.tier1 if tier == 1 else got.summary.tier2
    )
    source = got.source if got is not None else None
    if entry is None:
        why = (
            got.source.reason
            if got is not None and got.source.reason
            else f"tier {tier} was not run at {role}"
        )
        return Row((cells.text(label), *(cells.not_run(why) for _ in COLUMNS9[1:])), source)
    interval = (
        (entry.ci_low, entry.ci_high) if entry.ci_low is not None and entry.ci_high is not None else None
    )
    codes = "—"
    if isinstance(entry, ReplayTier1):  # the 04 §7 exit-code histogram, non-zero counts only
        codes = (
            ", ".join(f"{k}: {v}" for k, v in entry.outcomes.model_dump(by_alias=True).items() if v) or "—"
        )
    return Row(
        (
            cells.text(label),
            cells.rate(entry.rate, interval),
            cells.text(f"{entry.k}/{entry.n}"),
            cells.text(f"{entry.k_verdict}/{entry.n}"),
            cells.text(codes),
        ),
        source,
    )


def replay(ctx: Context) -> list[Table]:
    """Table 9 from the committed replay summaries (03 §13.6; 04 §12 row of 22 Nov)."""
    rows = tuple(_replay_row(ctx, label, role, tier) for label, role, tier in REPLAY)
    caption = (
        "Tier 1: share of recorded AI runs whose `veyltrace replay` exits 0, with its exact (Clopper–Pearson)"
        " 95% interval; verdict reproduced counts recomputed `verdict_hash` equal to the recorded one."
        " Tier 2: share of a fixed sample whose regenerated proposals are byte-identical (on the recording's"
        " own provider, 04 §12). Exit codes as 10 §3.9."
    )
    return [Table("t09-rq6-replay", "Table 9: RQ6 replay", caption, COLUMNS9, rows)]
