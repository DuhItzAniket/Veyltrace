"""RQ1 tables (11 §5.1, §4): Table 3 (datasets), Table 5 (accuracy per benchmark and alert
protocol) and the paired comparisons of H1a/H1b, plus the floor rows other accuracy tables reuse.

Table 5 shows every system next to its floors (04 §10.3): the chance floor, prior-only on RE2 and
RE3 (the benchmarks with cross-fit folds), N-Sigma, BARO and the alert-count baseline SimpleRCA,
then each Causatrix ranker alone, the fused slate and the pipeline. Pooled rows (system as
stratum) come after the per-system rows, because per-system results are primary (04 §8). A floor
taken from another experiment is shown only when that experiment ran the same cases; otherwise
its row says "different case set".
"""

from __future__ import annotations

from collections.abc import Sequence

from veyltrace_bench.experiment import Experiment
from veyltrace_bench.tables import cells
from veyltrace_bench.tables.cells import Cell
from veyltrace_bench.tables.context import Context
from veyltrace_bench.tables.render import Row, Table
from veyltrace_bench.tables.results import REVISION_ROW, Results
from veyltrace_contracts.models import SummaryComparison

#: Table 5 variants: (file suffix, benchmark and protocol, RQ1 experiment, prior-only experiment).
ACCURACY = (
    ("re2-oracle", "RE2, oracle alert", "re2-oracle-rq1-v1", "re2-oracle-prior-only-v1"),
    ("re2-detected", "RE2, detected alert", "re2-detected-rq1-v1", "re2-oracle-prior-only-v1"),
    ("re3-oracle", "RE3, oracle alert", "re3-oracle-rq1-v1", "re3-oracle-prior-only-v1"),
    ("nezha-oracle", "Nezha, oracle alert", "nezha-oracle-rq1-v1", None),
    ("veyllab-oracle", "VeylLab, oracle alert", "veyllab-oracle-rq1-v1", None),
    ("fse26-oracle", "FSE'26 TT, oracle alert", "fse26-oracle-rq1-v1", None),
)  # prior-only reads no telemetry and no alert, so it is the floor of both RE2 protocols (04 §10.3)
#: The experiment that adds normal windows (04 §5.4) on the full case set of each benchmark; a
#: benchmark missing here has none. VeylLab's are captured no-fault cases.
NORMAL_WINDOWS = {"re2": "re2-oracle-rq3-v1", "veyllab": "veyllab-oracle-rq1-v1"}
NO_FAULT_CASES = frozenset({"veyllab"})
Metric = tuple[str, str, str]  # (column, summary entry, key)
#: Table 5's columns (04 §7). Fine-grained AC@k has its own denominator, the fault cases with an
#: answer-key indicator (`n_fine`), so its count follows it; Retrieval@K is the slate's, then the
#: decision pool's (`pool_hit`).
METRICS: tuple[Metric, ...] = (
    ("AC@1", "ac_at_k", "ac_at_1"), ("AC@3", "ac_at_k", "ac_at_3"), ("AC@5", "ac_at_k", "ac_at_5"),
    ("Avg@5", "avg_at_5", "avg_at_5"), ("MRR", "mrr", "mrr"),
    ("Fine AC@1", "fine_ac_at_k", "fine_ac_at_1"), ("Fine AC@3", "fine_ac_at_k", "fine_ac_at_3"),
    ("Fine AC@5", "fine_ac_at_k", "fine_ac_at_5"), ("Fine cases", "fine_ac_at_k", "n_fine"),
    ("Retrieval@K", "retrieval_at_k", "retrieval_at_k"),
    ("Pool retrieval", "retrieval_at_k", "pool_retrieval"), ("Rerank@1", "rerank_at_1", "rerank_at_1"),
    ("Lift@1", "lift", "lift_at_1"), ("AC@1 − Chance@1", "lift", "chance_diff_at_1"),
)  # fmt: skip
#: The onset error of the detected protocol (04 §7: median, max and count over the ok runs of cases
#: with an injection time), shown in the tables of a detected-alert experiment.
ONSET: tuple[Metric, ...] = (
    ("Onset n", "onset_error", "n_onset"),
    ("Onset error median (ms)", "onset_error", "onset_error_median_ms"),
    ("Onset error max (ms)", "onset_error", "onset_error_max_ms"),
)
#: Group counts shown as a metric column, and the key of the entry they belong to: the count is
#: shown only where that entry is (04 §7 denominators).
GROUP_COUNTS = {"n_fine": "fine_ac_at_1"}
DETECTED = "detected"
#: Method kinds that build no Causatrix slate (RCAEval baselines, prior-only, SimpleRCA,
#: naive-change), so the slate columns do not apply to them (R2).
SLATELESS = frozenset({"rcaeval", "internal_baseline"})
SLATE_ENTRIES = frozenset({"retrieval_at_k", "rerank_at_1"})
NO_SLATE = "builds no slate, so Retrieval@K, pool retrieval and Rerank@1 do not apply (04 §7)"
#: A Causatrix arm has no verdict: the decision pool, set and fault type belong to the verifier (runner).
NO_POOL = (
    "a Causatrix arm is scored on its slate and has no verdict, so no decision pool (pool_hit empty, 04 §7)"
)
NO_POOLED_RATIO = (
    "no pooled value in the committed results: summary.json pools case means only, and this is a "
    "ratio of them (04 §8 asks for a pooled interval)"
)
NO_POOLED_ONSET = "summary.json reports onset error per system only (04 §7), so it has no pooled value"
NO_ONSET = "null in summary.json: no ok run of this group has an onset (Onset n = 0; 04 §7)"
NO_VALUE = "no value"  # a cell whose value no committed file has, with the reason in its note
#: The note of a floor run under the oracle alert in a detected-alert table (04 §10.3).
READS_NO_ALERT = (
    "prior-only reads no alert, so {prior} (oracle alert) is the floor of both RE2 protocols (its YAML "
    "header, 04 §10.3); it has no no_alert miss, unlike the rows run under the detected alert"
)
OUTCOMES = ("ok", "failed", "timeout", "no_alert", "rejected")  # 03 §13.2 run_outcome order
AC_KEYS = frozenset(f"ac_at_{k}" for k in range(1, 6))  # the keys the chance floor has a counterpart for
PER_SEED = "Per-seed AC@1 (mean ± SD)"
NO_PER_SEED = "bench_summary 1.1 has no per-seed groups"
KIND_ORDER = ("rcaeval", "internal_baseline", "causatrix", "agent_only", "veyltrace")  # floors first
FLOORS = ("rcaeval:nsigma", "rcaeval:baro", "simplerca")  # 04 §10.3, besides chance and prior-only
FUSED = "causatrix:rrf"
OURS = "veyltrace:off"
POOLED = "pooled"
OTHER_CASES = "different case set"
Line = tuple[str, Results | None, list[Cell]]  # (method label, source, cells after the label)


def n_a(why: str) -> Cell:
    """A cell whose column does not apply to its row."""
    return cells.not_applicable(why)


def methods(exp: Experiment) -> list[str]:
    """The experiment's method ids, floors first, single rankers before the fused slate."""
    order = sorted(
        enumerate(exp.methods), key=lambda im: (KIND_ORDER.index(im[1].kind), im[1].id == FUSED, im[0])
    )
    return [m.id for _, m in order]


def seeded(exp: Experiment) -> frozenset[str]:
    """The methods with AI seeds: their group pools cases × seeds rows (04 §8)."""
    return frozenset(m.id for m in exp.methods if m.ai.seeds)


def same_cases(ctx: Context, a: str, b: str) -> bool:
    """Whether two experiments ran the same cases: by their manifests when both ran, else by the
    dataset spec (parts, case list, exclusions)."""
    ra, rb = ctx.get(a), ctx.get(b)
    if ra.manifest is not None and rb.manifest is not None and ra.reason is None and rb.reason is None:
        return {(d.dataset, tuple(d.cases)) for d in ra.manifest.datasets} == {
            (d.dataset, tuple(d.cases)) for d in rb.manifest.datasets
        }
    da, db = ctx.spec(a).dataset, ctx.spec(b).dataset
    return (da.parts, da.cases, da.exclude) == (db.parts, db.cases, db.exclude)


def outcomes(res: Results, part: str, method: str) -> Cell:
    if (why := res.missing(part, res.system_of(part), method)) is not None:
        return cells.not_run(why)
    group = res.group(part, res.system_of(part), method)
    assert group is not None
    return cells.text("/".join(str(getattr(group.outcomes, o)) for o in OUTCOMES))


def tail(res: Results, part: str, method: str, *, seeds: bool, per_seed: bool) -> list[Cell]:
    """Per-seed, fault-case runs, unranked runs and outcomes of one group."""
    sys = res.system_of(part)
    spread = [cells.not_run(NO_PER_SEED) if seeds else n_a("deterministic method: one run per case")]
    counts = [res.count(part, sys, method, "n_fault"), res.count(part, sys, method, "n_unranked")]
    return [*(spread if per_seed else []), *counts, outcomes(res, part, method)]


def width(per_seed: bool) -> int:
    return 4 if per_seed else 3


def kinds(exp: Experiment) -> dict[str, str]:
    """Method id -> kind."""
    return {m.id: m.kind for m in exp.methods}


def no_value(note: str) -> Cell:
    return Cell(NO_VALUE, note)


def _why_missing(cell: Cell, entry: str, key: str, kind: str | None) -> Cell:
    """A slate cell without a value names why when the method's kind explains it (R2)."""
    if cell.text != cells.UNDEFINED:
        return cell
    if kind in SLATELESS and entry in SLATE_ENTRIES:
        return n_a(NO_SLATE)
    if kind == "causatrix" and key == "pool_retrieval":
        return n_a(NO_POOL)
    if entry == "onset_error" and cell.note == cells.UNDEFINED_NOTE:
        return Cell(cells.UNDEFINED, NO_ONSET)
    return cell


def value(res: Results, part: str, method: str, entry: str, key: str, kind: str | None = None) -> Cell:
    """One metric cell of a group; a group count (GROUP_COUNTS) where its entry has a value."""
    sys = res.system_of(part)
    if (anchor := GROUP_COUNTS.get(key)) is not None:
        cell = res.metric(part, sys, method, entry, anchor)
        missing = cell.text in (cells.UNDEFINED, cells.NOT_RUN, cells.REVISED, cells.NOT_TABULATED)
        return cell if missing else res.count(part, sys, method, key)
    return _why_missing(res.metric(part, sys, method, entry, key), entry, key, kind)


def method_line(
    res: Results, part: str, method: str, metrics: Sequence[Metric], *, seeds: bool, per_seed: bool,
    kind: str | None = None,
) -> Line:  # fmt: skip
    values = [value(res, part, method, entry, key, kind) for _, entry, key in metrics]
    return method, res, [*values, *tail(res, part, method, seeds=seeds, per_seed=per_seed)]


def na_line(method: str, why: str, metrics: Sequence[Metric], per_seed: bool) -> Line:
    return method, None, [n_a(why)] * (len(metrics) + width(per_seed))


def chance_line(ctx: Context, eid: str, part: str, metrics: Sequence[Metric], per_seed: bool) -> Line:
    """Chance@k of the experiment's cases, from its first group (every group of a part shares the
    cases, so the same denominators as AC@k, 04 §7); columns other than AC@k do not apply."""
    res, exp = ctx.get(eid), ctx.spec(eid)
    method = OURS if OURS in methods(exp) else methods(exp)[0]
    sys = res.system_of(part)
    values = [
        res.metric(part, sys, method, "chance", key.replace("ac_", "chance_"))
        if key in AC_KEYS else n_a("the chance floor is defined for AC@k only (04 §7)")
        for _, _, key in metrics
    ]  # fmt: skip
    rest = [n_a("chance is computed, not run")] * (1 if per_seed else 0)
    count = res.count(part, sys, method, "n_fault")
    return (
        "chance",
        res,
        [*values, *rest, count, n_a("chance is computed, not run"), n_a("chance is computed, not run")],
    )


def floor_lines(
    ctx: Context, eid: str, part: str, metrics: Sequence[Metric], *, prior: str | None, base: str | None,
    per_seed: bool, omitted: str = "not run under this protocol",
) -> list[Line]:  # fmt: skip
    """The 04 §10.3 floors of one part of `eid`: chance, prior-only (from `prior`) and the
    FLOORS baselines the experiment does not run itself (from `base`, or `omitted` without one),
    each only where its experiment ran the same cases."""
    lines = [chance_line(ctx, eid, part, metrics, per_seed)]
    if prior is not None:
        if same_cases(ctx, eid, prior):
            known = kinds(ctx.spec(prior))
            lines += [
                method_line(ctx.get(prior), part, m, metrics, seeds=False, per_seed=per_seed, kind=known[m])
                for m in methods(ctx.spec(prior))
            ]
        else:
            lines.append(na_line("prior-only", OTHER_CASES, metrics, per_seed))
    own = set(methods(ctx.spec(eid)))
    for floor in (f for f in FLOORS if f not in own):
        if base is None:
            lines.append(na_line(floor, omitted, metrics, per_seed))
        elif same_cases(ctx, eid, base):
            kind = kinds(ctx.spec(base)).get(floor)
            lines.append(
                method_line(ctx.get(base), part, floor, metrics, seeds=False, per_seed=per_seed, kind=kind)
            )
        else:
            lines.append(na_line(floor, OTHER_CASES, metrics, per_seed))
    return lines


POOLED_COUNTS = "pooled rows report the per-system counts above"


def _pooled_value(res: Results, bench: str, method: str, entry: str, key: str, kind: str | None) -> Cell:
    if (why := res.why(method)) is not None:
        return cells.not_run(why)
    if key in GROUP_COUNTS:
        return n_a(POOLED_COUNTS)
    if kind in SLATELESS and entry in SLATE_ENTRIES:
        return n_a(NO_SLATE)
    if key in ("rerank_at_1", "lift_at_1"):
        return no_value(NO_POOLED_RATIO)
    if entry == "onset_error":
        return no_value(NO_POOLED_ONSET)
    return _why_missing(res.pooled(bench, method, key), entry, key, kind)


def _pooled_row(
    res: Results, bench: str, method: str, per_seed: bool, metrics: Sequence[Metric], kind: str | None
) -> Row:
    values = [_pooled_value(res, bench, method, entry, key, kind) for _, entry, key in metrics]
    counts = [n_a(POOLED_COUNTS)] * width(per_seed)
    return Row((cells.text(POOLED), cells.text(method), *values, *counts), res)


def columns(seeds: bool, per_seed: bool = True, metrics: Sequence[Metric] = METRICS) -> tuple[str, ...]:
    runs = "Fault-case runs (cases × seeds)" if seeds else "Fault cases"
    return (
        *(c for c, _, _ in metrics),
        *([PER_SEED] if per_seed else []),
        runs,
        "Unranked",
        "Outcomes " + "/".join(OUTCOMES),
    )


def accuracy_table(
    ctx: Context,
    name: str,
    title: str,
    experiment_id: str,
    prior_id: str | None = None,
    base_id: str | None = None,
) -> Table:
    """Per system: the floors (chance, prior-only from `prior_id`, the FLOORS baselines the
    experiment lacks from `base_id`), then every method of the experiment; then the pooled rows."""
    exp, res = ctx.spec(experiment_id), ctx.get(experiment_id)
    ids, arms, known = methods(exp), seeded(exp), kinds(exp)
    metrics = (*METRICS, *ONSET) if exp.protocol.alert == DETECTED else METRICS
    other_alert = prior_id is not None and ctx.spec(prior_id).protocol.alert != exp.protocol.alert
    prior = ctx.get(prior_id) if prior_id is not None else None
    rows: list[Row] = []
    for part in exp.dataset.parts:
        lines = floor_lines(ctx, experiment_id, part, metrics, prior=prior_id, base=base_id, per_seed=True)
        lines += [
            method_line(res, part, m, metrics, seeds=m in arms, per_seed=True, kind=known[m]) for m in ids
        ]
        sys = cells.text(res.system_of(part))
        for label, src, body in lines:
            note = READS_NO_ALERT.format(prior=prior_id) if other_alert and src is prior else None
            rows.append(Row((sys, Cell(label, note), *body), src))
    bench = exp.dataset.parts[0].split("-")[0]
    rows += [_pooled_row(res, bench, m, True, metrics, known[m]) for m in ids]
    alert = f"; prior-only reads no alert, so its floor is the oracle run {prior_id}" if other_alert else ""
    caption = (
        f"Protocol: {res.protocol}. AC@k on ranks_rcaeval (status ignored, 04 §7); fine AC@k over the "
        "fault cases with an answer-key indicator (Fine cases); 95% cluster-bootstrap intervals in "
        "brackets; failed, timed-out, no-alert, rejected and unranked runs count as misses; a seeded arm's "
        f"group pools its cases × seeds rows (04 §8){alert}."
    )
    cols = ("System", "Method", *columns(bool(arms), metrics=metrics))
    return Table(name, title, caption, cols, tuple(rows), key=(0, 1))


def accuracy(ctx: Context) -> list[Table]:
    """Table 5, one per benchmark and alert protocol."""
    return [
        accuracy_table(ctx, f"t05-rq1-{suffix}", f"Table 5: RQ1 accuracy, {label}", rq1, prior)
        for suffix, label, rq1, prior in ACCURACY
    ]


def _windows(ctx: Context, part: str) -> tuple[Cell, Results | None]:
    """The normal-window count of a part, from the experiment that adds them (H2 of the review);
    when that experiment did not run but a 04 §12 revision of it did, from the revision, which
    the cell names with what it revises (R1)."""
    bench = part.split("-", maxsplit=1)[0]
    if (eid := NORMAL_WINDOWS.get(bench)) is None:
        return n_a("this experiment adds no normal windows; no experiment adds them for this benchmark"), None
    res, exp, revised = ctx.get(eid), ctx.spec(eid), ""
    if res.revised_as and len(news := ctx.revisions_of(eid)) == 1:  # one revision replaces it
        res, exp, revised = ctx.get(news[0]), ctx.spec(news[0]), f", revises {eid}, {REVISION_ROW}"
    method = OURS if OURS in methods(exp) else methods(exp)[0]
    cell = res.count(part, res.system_of(part), method, "n_no_truth")
    kind = "no-fault cases" if bench in NO_FAULT_CASES else "normal windows"
    if res.why(method) is not None or cell.text == cells.NOT_RUN:
        return cell, res
    return cells.Cell(f"{cell.text} {kind} (from {res.experiment_id}{revised})", cell.note), res


def datasets(ctx: Context) -> list[Table]:
    """Table 3: the case counts of every dataset part, from the manifest of its first (oracle) RQ1
    experiment in ACCURACY; normal windows from the experiment that adds them."""
    rows: list[Row] = []
    seen: set[str] = set()
    for _, _, rq1_id, _ in ACCURACY:
        exp, res = ctx.spec(rq1_id), ctx.get(rq1_id)
        found = (
            {d.dataset: d for d in res.manifest.datasets}
            if res.manifest is not None and res.reason is None
            else {}
        )
        for part in (p for p in exp.dataset.parts if p not in seen):
            seen.add(part)
            sys = res.system_of(part)
            if (entry := found.get(part)) is None:
                counts = [cells.not_run(res.reason or f"its manifest.json has no {part} dataset")] * 3
            else:
                counts = [
                    cells.count(len(v)) for v in (entry.cases, entry.excluded, entry.cases_without_inputs)
                ]
            window, also = _windows(ctx, part)
            cases = res.count(part, sys, OURS, "n_fault")
            rows.append(
                Row((cells.text(part), cells.text(sys), *counts, cases, window), res, (also,) if also else ())
            )
    columns_ = ("Dataset", "System", "Cases", "Excluded", "Without inputs", "Fault cases", "Normal windows")
    caption = (
        f"Case counts per dataset part from the manifest of its RQ1 experiment; fault cases are those of "
        f"{OURS}; normal windows (04 §5.4) come from the experiment that adds them. Development cases are "
        "excluded (04 §10.5)."
    )
    return [Table("t03-datasets", "Table 3: datasets", caption, columns_, tuple(rows), key=(0, 1))]


def _interval_note(c: SummaryComparison, skipped: dict[str, str]) -> str:
    """Why a comparison has no interval: the not_run entry of its scope, else "no interval"."""
    scopes = [f"{c.dataset} pooled intervals"] if c.system is None else []
    scopes += sorted(s for s in skipped if c.dataset in s)
    for scope in scopes:
        if scope in skipped:
            return f"no interval: {scope} {skipped[scope]}"
    return "no interval in summary.json"


def _mcnemar(c: SummaryComparison, arms: frozenset[str], on: bool) -> tuple[Cell, Cell]:
    """The McNemar counts and p of a comparison, or the reason it has none (verification, R-17)."""
    if {c.method_a, c.method_b} & arms:
        why = "a seeded arm's per-case hit is a mean over seeds, not boolean, so no McNemar (04 §8)"
    elif not on:
        why = "McNemar is off (the experiment's statistics.mcnemar is false)"
    elif c.n_pairs == 0:
        why = "no paired cases"
    elif c.mcnemar_only_a is None or c.mcnemar_only_b is None:
        why = "null in summary.json: the hits are not boolean (03 §13.3)"
    else:
        return cells.text(f"{c.mcnemar_only_a}/{c.mcnemar_only_b}"), cells.p_value(c.mcnemar_p)
    return n_a(why), n_a(why)


def _comparison_cells(res: Results, arms: frozenset[str], mcnemar_on: bool = True) -> list[tuple[Cell, ...]]:
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
        if c.low is not None and c.high is not None:
            difference = cells.rate(c.difference, (c.low, c.high))
        else:
            difference = cells.rate(c.difference, note=_interval_note(c, skipped))
        holm = cells.p_value(c.holm_p)
        if c.holm_p is None and c.family is None:
            holm = n_a("no Holm family: non-inferiority and exploratory comparisons are unadjusted (04 §8)")
        elif c.holm_p is None and (r := skipped.get(f"holm {c.family}")) is not None:
            holm = cells.not_run(r)
        sign_flip = cells.p_value(c.sign_flip_p)
        if c.kind == "noninferiority":
            sign_flip = n_a(
                "non-inferiority is decided by the unadjusted 95% interval against the margin (04 §8)"
            )
        mcnemar, mcnemar_p = _mcnemar(c, arms, mcnemar_on)
        out.append((
            cells.text(where), cells.text(c.metric), cells.text(f"{c.method_a} − {c.method_b}"),
            cells.text(c.kind + (f" ({c.family})" if c.family else "")),
            cells.rate(c.margin) if c.margin is not None else cells.text("none"),
            difference, cells.count(c.n_pairs), cells.count(c.n_clusters), sign_flip, mcnemar, mcnemar_p,
            holm,
        ))  # fmt: skip
    return out


COMPARISON_COLUMNS = (
    "Scope", "Metric", "A − B", "Kind", "Margin", "Difference", "Pairs", "Clusters",
    "Sign-flip p (unadjusted)", "McNemar only A/B", "McNemar p", "Holm p",
)  # fmt: skip


def comparisons(ctx: Context, name: str, title: str, experiment_ids: tuple[str, ...]) -> Table:
    """The paired comparisons of the experiments, as summary.json orders them (03 §13.3)."""
    rows = [
        Row(c, ctx.get(i))
        for i in experiment_ids
        for c in _comparison_cells(ctx.get(i), seeded(ctx.spec(i)), ctx.spec(i).statistics.mcnemar)
    ]
    caption = (
        "Paired differences A − B over the cases both methods scored: non-inferiority is decided by the "
        "unadjusted 95% interval against the margin, superiority by the Holm-adjusted sign-flip p within "
        "its family; McNemar counts discordant cases (04 §8). Protocol: see Sources."
    )
    return Table(name, title, caption, COMPARISON_COLUMNS, tuple(rows), key=(0, 1, 2, 3))


def rq1_comparisons(ctx: Context) -> list[Table]:
    title = "Table 5c: RQ1 comparisons (H1a, H1b)"
    return [comparisons(ctx, "t05c-rq1-comparisons", title, ("re2-oracle-rq1-v1",))]
