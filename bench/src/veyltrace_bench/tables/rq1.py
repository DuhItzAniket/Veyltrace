"""RQ1 tables (11 §5.1, §4): Table 3 (datasets), Table 5 (accuracy per benchmark and alert
protocol) and the paired comparisons of H1a/H1b.

Table 5 shows every system next to its floors (04 §10.3): the chance floor, prior-only on RE2 and
RE3 (the benchmarks with cross-fit folds), N-Sigma, BARO and the alert-count baseline SimpleRCA,
then each Causatrix ranker alone, the fused slate and the pipeline. Pooled rows (system as
stratum) come after the per-system rows, because per-system results are primary (04 §8).
"""

from __future__ import annotations

from veyltrace_bench.experiment import Experiment
from veyltrace_bench.tables import cells
from veyltrace_bench.tables.cells import Cell
from veyltrace_bench.tables.context import Context
from veyltrace_bench.tables.render import Row, Table
from veyltrace_bench.tables.results import Results

#: Table 5 variants: (file suffix, benchmark and protocol, RQ1 experiment, prior-only experiment).
ACCURACY = (
    ("re2-oracle", "RE2, oracle alert", "re2-oracle-rq1-v1", "re2-oracle-prior-only-v1"),
    ("re2-detected", "RE2, detected alert", "re2-detected-rq1-v1", None),
    ("re3-oracle", "RE3, oracle alert", "re3-oracle-rq1-v1", "re3-oracle-prior-only-v1"),
    ("nezha-oracle", "Nezha, oracle alert", "nezha-oracle-rq1-v1", None),
    ("veyllab-oracle", "VeylLab, oracle alert", "veyllab-oracle-rq1-v1", None),
    ("fse26-oracle", "FSE'26 TT, oracle alert", "fse26-oracle-rq1-v1", None),
)
#: (column, summary entry, key) of Table 5; the case means among them get their interval.
METRICS = (
    ("AC@1", "ac_at_k", "ac_at_1"), ("AC@3", "ac_at_k", "ac_at_3"), ("AC@5", "ac_at_k", "ac_at_5"),
    ("Avg@5", "avg_at_5", "avg_at_5"), ("MRR", "mrr", "mrr"),
    ("Retrieval@K", "retrieval_at_k", "retrieval_at_k"), ("Rerank@1", "rerank_at_1", "rerank_at_1"),
)  # fmt: skip
OUTCOMES = ("ok", "failed", "timeout", "no_alert", "rejected")  # 03 §13.2 run_outcome order
COLUMNS = ("System", "Method", *(c for c, _, _ in METRICS), "Fault cases", "Outcomes " + "/".join(OUTCOMES))
KIND_ORDER = ("rcaeval", "internal_baseline", "causatrix", "agent_only", "veyltrace")  # floors first
FUSED = "causatrix:rrf"
OURS = "veyltrace:off"  # its group carries the chance floor of the cases
POOLED = "pooled"


def n_a(why: str) -> Cell:
    """A cell whose column does not apply to its row."""
    return Cell(cells.UNDEFINED, f"not applicable: {why}")


def system_of(part: str) -> str:
    """The benchmark system of a dataset part (`re2-ob` → `ob`, 03 §2.1)."""
    return part.split("-", 1)[1]


def methods(exp: Experiment) -> list[str]:
    """The experiment's method ids, floors first, single rankers before the fused slate."""
    order = sorted(
        enumerate(exp.methods), key=lambda im: (KIND_ORDER.index(im[1].kind), im[1].id == FUSED, im[0])
    )
    return [m.id for _, m in order]


def outcomes(res: Results, part: str, method: str) -> Cell:
    if (why := res.missing(part, system_of(part), method)) is not None:
        return cells.not_run(why)
    group = res.group(part, system_of(part), method)
    assert group is not None
    return cells.text("/".join(str(getattr(group.outcomes, o)) for o in OUTCOMES))


def _method_row(res: Results, part: str, method: str) -> Row:
    sys = system_of(part)
    values = [res.metric(part, sys, method, entry, key) for _, entry, key in METRICS]
    return Row(
        (
            cells.text(sys),
            cells.text(method),
            *values,
            res.count(part, sys, method, "n_fault"),
            outcomes(res, part, method),
        ),
        res,
    )


def _chance_row(res: Results, part: str) -> Row:
    sys = system_of(part)
    chance = [res.metric(part, sys, OURS, "chance", f"chance_at_{k}") for k in (1, 3, 5)]
    rest = [n_a("the chance floor is defined for AC@k only (04 §7)")] * (len(METRICS) - 3)
    return Row(
        (
            cells.text(sys),
            cells.text("chance"),
            *chance,
            *rest,
            res.count(part, sys, OURS, "n_fault"),
            n_a("chance is computed, not run"),
        ),
        res,
    )


def _pooled_row(res: Results, bench: str, method: str) -> Row:
    values = [
        res.pooled(bench, method, key)
        if key != "rerank_at_1"
        else n_a("Rerank@1 is a ratio; bench_summary pools case means only")
        for _, _, key in METRICS
    ]
    counts = [n_a("pooled rows report the per-system counts above")] * 2
    return Row((cells.text(POOLED), cells.text(method), *values, *counts), res)


def accuracy_table(
    ctx: Context, name: str, title: str, protocol: str, experiment_id: str, prior_id: str | None = None
) -> Table:
    """Per system: the chance floor, the prior-only rows of `prior_id`, then every method of the
    experiment; then the pooled rows. `protocol` states alert, shift, sources and AI arm (04 §10.4)."""
    exp, res = ctx.spec(experiment_id), ctx.get(experiment_id)
    ids = methods(exp)
    rows: list[Row] = []
    for part in exp.dataset.parts:
        rows.append(_chance_row(res, part))
        if prior_id is not None:
            rows += [_method_row(ctx.get(prior_id), part, m) for m in methods(ctx.spec(prior_id))]
        rows += [_method_row(res, part, m) for m in ids]
    rows += [_pooled_row(res, exp.dataset.parts[0].split("-")[0], m) for m in ids]
    caption = (
        f"{protocol}. AC@k on ranks_rcaeval (status ignored, 04 §7); 95% cluster-bootstrap intervals in "
        "brackets; failed, timed-out and unranked runs count as misses; AI arms pool their seeds' rows."
    )
    return Table(name, title, caption, COLUMNS, tuple(rows))


def accuracy(ctx: Context) -> list[Table]:
    """Table 5, one per benchmark and alert protocol."""
    return [
        accuracy_table(
            ctx,
            f"t05-rq1-{suffix}",
            f"Table 5: RQ1 accuracy, {label}",
            f"{label}, no shift, all sources",
            rq1,
            prior,
        )
        for suffix, label, rq1, prior in ACCURACY
    ]


def datasets(ctx: Context) -> list[Table]:
    """Table 3: the case counts of every dataset part, from the manifest of its first (oracle) RQ1
    experiment in ACCURACY."""
    rows: list[Row] = []
    seen: set[str] = set()
    for _, _, rq1_id, _ in ACCURACY:
        exp, res = ctx.spec(rq1_id), ctx.get(rq1_id)
        found = {d.dataset: d for d in res.manifest.datasets} if res.manifest is not None else {}
        for part in (p for p in exp.dataset.parts if p not in seen):
            seen.add(part)
            sys = system_of(part)
            if (entry := found.get(part)) is None:
                why = res.reason or f"its manifest.json has no {part} dataset"
                counts = [cells.not_run(why)] * 3
            else:
                counts = [
                    cells.count(len(entry.cases)),
                    cells.count(len(entry.excluded)),
                    cells.count(len(entry.cases_without_inputs)),
                ]
            truth = [res.count(part, sys, OURS, key) for key in ("n_fault", "n_no_truth")]
            rows.append(Row((cells.text(part), cells.text(sys), *counts, *truth), res))
    columns = ("Dataset", "System", "Cases", "Excluded", "Without inputs", "Fault cases", "Normal windows")
    caption = (
        "Case counts per dataset part from the manifest of its RQ1 experiment; fault cases and normal "
        f"windows are those of {OURS}. Development cases are excluded (04 §10.5)."
    )
    return [Table("t03-datasets", "Table 3: datasets", caption, columns, tuple(rows))]


def _comparison_cells(res: Results) -> list[tuple[Cell, ...]]:
    if res.summary is None or res.stats_reason is not None:
        return [
            tuple([cells.not_run(res.stats_reason or res.reason or "no results")] * len(COMPARISON_COLUMNS))
        ]
    stats = res.summary.statistics
    assert not isinstance(stats, str)
    if not stats.comparisons:
        scopes = (
            "; ".join(f"{n.scope}: {n.reason}" for n in stats.not_run) or "summary.json has no comparisons"
        )
        return [tuple([cells.not_run(scopes)] * len(COMPARISON_COLUMNS))]
    skipped = {n.scope: n.reason for n in stats.not_run}
    out: list[tuple[Cell, ...]] = []
    for c in stats.comparisons:
        where = f"{c.dataset} {c.system}" if c.system is not None else f"{c.dataset} {POOLED}"
        ci = (c.low, c.high) if c.low is not None and c.high is not None else None
        holm = cells.p_value(c.holm_p)
        if c.holm_p is None and c.family is None:
            holm = n_a("no Holm family: non-inferiority and exploratory comparisons are unadjusted (04 §8)")
        elif c.holm_p is None and (r := skipped.get(f"holm {c.family}")) is not None:
            holm = cells.not_run(r)
        mcnemar = f"{c.mcnemar_only_a}/{c.mcnemar_only_b}" if c.mcnemar_only_a is not None else None
        out.append((
            cells.text(where), cells.text(c.metric), cells.text(f"{c.method_a} − {c.method_b}"),
            cells.text(c.kind + (f" ({c.family})" if c.family else "")),
            cells.rate(c.margin) if c.margin is not None else cells.text("none"),
            cells.rate(c.difference, ci), cells.count(c.n_pairs), cells.count(c.n_clusters),
            cells.p_value(c.sign_flip_p), cells.text(mcnemar) if mcnemar else n_a("McNemar is off"),
            cells.p_value(c.mcnemar_p), holm,
        ))  # fmt: skip
    return out


COMPARISON_COLUMNS = (
    "Scope", "Metric", "A − B", "Kind", "Margin", "Difference", "Pairs", "Clusters", "Sign-flip p",
    "McNemar only A/B", "McNemar p", "Holm p",
)  # fmt: skip


def comparisons(ctx: Context, name: str, title: str, experiment_ids: tuple[str, ...]) -> Table:
    """The paired comparisons of the experiments, as summary.json orders them (03 §13.3)."""
    rows = [Row(c, ctx.get(i)) for i in experiment_ids for c in _comparison_cells(ctx.get(i))]
    caption = (
        "Paired differences A − B over the cases both methods scored: non-inferiority is decided by the "
        "unadjusted 95% interval against the margin, superiority by the Holm-adjusted sign-flip p within "
        "its family; McNemar counts discordant cases (04 §8)."
    )
    return Table(name, title, caption, COMPARISON_COLUMNS, tuple(rows))


def rq1_comparisons(ctx: Context) -> list[Table]:
    return [
        comparisons(
            ctx, "t05c-rq1-comparisons", "Table 5c: RQ1 comparisons (H1a, H1b)", ("re2-oracle-rq1-v1",)
        )
    ]
