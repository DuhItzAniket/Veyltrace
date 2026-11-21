"""RQ5 cost and RQ6 replay tables (11 §5.5, §5.6).

Table 8 holds the cost percentiles of the RE2 oracle RQ1 and RQ2 experiments per system and method
(nearest-rank p50/p95 over the group's rows, 03 §13.3); Table A1 holds them for every experiment
that lists `cost`, so the cost of every reported number is on record (04 §6 "RQ5 cost is recorded
on every run"). Replay rates (Table 9) are not bench output, so its rows say so.
"""

from __future__ import annotations

from veyltrace_bench.tables import cells
from veyltrace_bench.tables.context import Context
from veyltrace_bench.tables.render import Row, Table
from veyltrace_bench.tables.rq1 import methods

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
    "Tier 1, recording laptop",
    "Tier 1, second laptop",
    "Tier 1, CI",
    "Tier 2 regeneration, 50 recorded cases",
)  # 04 §6 cross-cutting, §7 "Replay"
REPLAY_REASON = "replay rates are not bench output: bench_summary 1.1 has no replay entry (03 §13.3)"


def replay(ctx: Context) -> list[Table]:
    del ctx  # no experiment holds replay rates
    rows = tuple(
        Row((cells.text(t), cells.not_run(REPLAY_REASON), cells.not_run(REPLAY_REASON)), None) for t in REPLAY
    )
    caption = (
        "Share of recorded AI runs whose `veyltrace replay` exits 0 (Tier 1) or whose proposals regenerate"
    )
    caption += " byte-identically (Tier 2)."
    return [Table("t09-rq6-replay", "Table 9: RQ6 replay", caption, ("Measurement", "Rate", "Runs"), rows)]
