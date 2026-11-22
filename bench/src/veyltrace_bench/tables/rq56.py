"""RQ5 cost and RQ6 replay tables (11 §5.5, §5.6).

Table 8 holds the cost percentiles of the RE2 oracle RQ1 and RQ2 experiments per system and method
(nearest-rank p50/p95 over the group's rows, 03 §13.3); Table A1 holds them for every experiment
that lists `cost`, so the cost of every reported number is on record (04 §6 "RQ5 cost is recorded
on every run"). Table 9 holds the RQ6 replay rates of `bench/results/replay/<role>/` (#440).
"""

from __future__ import annotations

from veyltrace_bench.tables import cells
from veyltrace_bench.tables.context import Context
from veyltrace_bench.tables.render import Row, Table
from veyltrace_bench.tables.rq1 import methods
from veyltrace_contracts.models import ReplayTier1

MAIN = ("re2-oracle-rq1-v1", "re2-oracle-rq2-v1")  # Table 8: the deterministic and AI paths on RE2
COST = (
    ("Wall p50 (ms)", "wall_ms_p50"), ("Wall p95 (ms)", "wall_ms_p95"),
    ("Peak RSS p50 (MiB)", "peak_rss_mb_p50"), ("Peak RSS p95 (MiB)", "peak_rss_mb_p95"),
    ("Tokens in p50", "tokens_in_p50"), ("Tokens in p95", "tokens_in_p95"),
    ("Tokens out p50", "tokens_out_p50"), ("Tokens out p95", "tokens_out_p95"), ("Rows with cost", "n_cost"),
)  # fmt: skip
COLUMNS8 = ("Experiment", "System", "Method", *(c for c, _ in COST))


def _cost_rows(ctx: Context, experiment_ids: tuple[str, ...]) -> list[Row]:
    rows: list[Row] = []
    for eid in experiment_ids:
        exp, res = ctx.spec(eid), ctx.get(eid)
        for part in exp.dataset.parts:
            sys = res.system_of(part)
            for m in methods(exp):
                values = [res.metric(part, sys, m, "cost", key) for _, key in COST]
                rows.append(Row((cells.text(eid), cells.text(sys), cells.text(m), *values), res))
    return rows


def cost(ctx: Context) -> list[Table]:
    caption = (
        "Nearest-rank p50 and p95 over each group's rows (03 §13.3); wall time per case and method, "
        "peak RSS of the run in MiB (per_case.csv peak_rss_mb), LLM tokens of AI arms. Laptop specs: "
        "docs/team/*.md."
    )
    every = tuple(e.experiment_id for e in ctx.experiments if "cost" in e.metrics)
    key = (0, 1, 2)  # experiment, system, method
    main, all_ = tuple(_cost_rows(ctx, MAIN)), tuple(_cost_rows(ctx, every))
    return [
        Table("t08-rq5-cost", "Table 8: RQ5 cost on RE2", caption, COLUMNS8, main, key=key),
        Table("a1-cost-all", "Table A1: cost of every experiment", caption, COLUMNS8, all_, key=key),
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
