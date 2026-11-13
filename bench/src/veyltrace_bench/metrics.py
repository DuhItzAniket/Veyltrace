"""Case-level scoring of the RCA accuracy metrics (04 §7; aggregation: `summary`, #64).

Pure functions over plain values: no run directory, no answer-key file. R_i = the method's ``ranks``
(``verdict.ranks_rcaeval`` or a baseline's) after RCAEval's coarse transform, de-duplicated in order;
the fine ranking is RCAEval's ``indicator_ranks``, raw and not de-duplicated (rcaeval_facts "Ground
truth and scoring"; RCAEval benchmark/scoring.py). Positions are list positions: the method's own
order already breaks ties (02 §6.9). Denominators are the full split: a non-``ok`` run is a miss
(04 §7 "Failed runs"), and so is an **unranked** run (04 §7 "Unranked runs", added by #14), an ``ok``
run with empty ``ranks`` or a slate with ``rankers_active == []``: that slate orders U (06 §2.1) by
tie-break only (A→Z on the R-00 stubs, packages/causatrix/README.md), so nothing built on it is
scored. No-fault cases and normal windows have no truth: null hits (03 §13.2), outside every accuracy
denominator. Onset error (04 §7) = |t_onset − t_inject| / 1e6 of an ``ok`` run; the runner passes
t_onset only under the detected protocol, and a case without an injection time has none (#215).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import get_args

from veyltrace_contracts.models import AnswerKeyRow, BenchResultRow
from veyltrace_core.errors import ContractValidationError

RANK_SEPARATOR = "_"  # RCAEval rank entries are "{service}_{indicator}" (03 §1; 04 §7)
DB_SUFFIX = "-db"  # removed by RCAEval's coarse transform x.split("_")[0].replace("-db", "")
NO_INDICATOR = "unknown"  # indicator_ranks' indicator of an entry without one (RCAEval scoring.py)
AC_KS = (1, 2, 3, 4, 5)  # Avg@5 = mean of AC@1…AC@5 (04 §7, RCAEval's definition)
HIT_COLUMN_KS = (1, 3, 5)  # per_case.csv hit_at_<k> columns (03 §13.2)
#: The per_case.csv columns a CaseScore fills besides ranks and hits (03 §13.2).
FIELD_COLUMNS = ("retrieval_hit", "pool_hit", "in_set", "set_size", "fault_class_hit", "onset_error_ms")
OK = "ok"  # the only scored run outcome (04 §7 "Failed runs")
NS_PER_MS = 1_000_000  # onset error is in ms: "/ 1e6" of a nanosecond difference (04 §7)
CODE_MODE = "code"  # RE3 F1-F5 have no fault class: fault type is scored as mode = code (04 §7)
RUN_OUTCOMES: frozenset[str] = frozenset(get_args(BenchResultRow.model_fields["run_outcome"].annotation))


def coarse_service(rank: str) -> str:
    """RCAEval's service-level transform of one rank entry or service name (04 §7)."""
    return rank.partition(RANK_SEPARATOR)[0].replace(DB_SUFFIX, "")


def coarse_ranking(ranks: Iterable[str]) -> tuple[str, ...]:
    """R_i: coarse services of ``ranks``, first occurrence kept, order kept (04 §7)."""
    return tuple(dict.fromkeys(coarse_service(r) for r in ranks))


def fine_ranking(ranks: Iterable[str]) -> tuple[tuple[str, str], ...]:
    """RCAEval's indicator_ranks: (``x.split("_")[0]``, ``x.split("_")[1]`` or "unknown")."""
    parts = (r.split(RANK_SEPARATOR) for r in ranks)
    return tuple((p[0], p[1] if len(p) > 1 else NO_INDICATOR) for p in parts)


def position_of[T](ranking: Sequence[T], truth: T) -> int | None:
    """1-based position of the first ``truth`` in ``ranking``; None when it is absent."""
    return ranking.index(truth) + 1 if truth in ranking else None


def chance_at(k: int, n: int) -> float:
    """min(k, n)/n, the AC@k of a uniformly random order of n candidates holding the root (04 §7);
    an empty universe counts 0, as in RCAEval's Evaluator.chance_accuracy."""
    if k < 1 or n < 0:
        raise ValueError(f"chance_at needs k >= 1 and n >= 0, got k={k}, n={n}")
    return min(k, n) / n if n else 0.0


@dataclass(frozen=True, slots=True)
class Truth:
    """The scored part of one case's answer (03 §13.1); ``root_service`` None = no truth."""

    root_service: str | None
    indicator: str | None = None
    fault_class: str | None = None
    mode: str | None = None
    t_inject_ns: int | None = None  # answer_key.t_inject_ns; None = no injection time (e.g. no fault)

    @classmethod
    def from_answer_key(cls, row: AnswerKeyRow) -> Truth:
        """A no-fault row has no truth; a fault row without a root service is refused, since it
        would silently leave every denominator (04 §7: denominators are the full split)."""
        if row.is_no_fault:
            return cls(None)
        if row.root_service is None:
            raise ContractValidationError("answer_key", f"fault case {row.case_id} has no root_service")
        return cls(row.root_service, row.indicator, row.fault_class, row.mode, row.t_inject_ns)


@dataclass(frozen=True, slots=True)
class MethodOutput:
    """One method's output on one case. ``None`` = the method has no such output (a baseline has no
    slate, pool, set or verdict); ``()`` = it has an empty one. Services: slate ``candidates``, verdict
    ``ranked`` (the decision pool) and ``candidate_set``."""

    outcome: str = OK
    ranks: tuple[str, ...] = ()
    rankers_active: tuple[str, ...] | None = None
    slate: tuple[str, ...] | None = None
    pool: tuple[str, ...] | None = None
    candidate_set: tuple[str, ...] | None = None
    has_verdict: bool = False
    root_fault_class: str | None = None
    root_mode: str | None = None
    slate_k: int | None = None
    t_onset_ns: int | None = None  # onsets.t_onset_ns, set by the runner only under the detected protocol


@dataclass(frozen=True, slots=True)
class CaseScore:
    """The scored outcome of one method on one case: `columns` are one per_case.csv row's metric
    columns; n_candidates, in_universe and slate_k only feed the summary.json aggregation (#64)."""

    outcome: str
    has_truth: bool
    unranked: bool
    ranks: tuple[str, ...]
    position: int | None
    fine_position: int | None
    fine_applicable: bool
    retrieval_hit: bool | None
    pool_hit: bool | None
    in_set: bool | None
    set_size: int | None
    fault_class_hit: bool | None
    n_candidates: int | None
    in_universe: bool | None
    slate_k: int | None
    onset_error_ms: float | None = None

    def hit_at(self, k: int) -> bool | None:
        """1[r_i ∈ R_i[:k]]; None without a truth."""
        return self.position is not None and self.position <= k if self.has_truth else None

    def fine_hit_at(self, k: int) -> bool | None:
        """(service, indicator) in the first k fine entries; None when not applicable."""
        applies = self.has_truth and self.fine_applicable
        return self.fine_position is not None and self.fine_position <= k if applies else None

    def columns(self) -> dict[str, object]:
        """The bench_result columns this score fills (03 §13.2); the runner (#67) adds the rest."""
        hits = {f"hit_at_{k}": self.hit_at(k) for k in HIT_COLUMN_KS}
        return {"ranks": list(self.ranks), **hits, **{c: getattr(self, c) for c in FIELD_COLUMNS}}


def _member(services: Sequence[str] | None, root: str | None, scored: bool = True) -> bool | None:
    """Truth in a service list; None without the list or a truth; a miss when not scored."""
    if services is None or root is None:
        return None
    return scored and root in {coarse_service(s) for s in services}


def _onset_error_ms(t_onset_ns: int | None, t_inject_ns: int | None) -> float | None:
    """|t_onset − t_inject| in ms (04 §7); None when either time is missing."""
    if t_onset_ns is None or t_inject_ns is None:
        return None
    return abs(t_onset_ns - t_inject_ns) / NS_PER_MS


def score_case(truth: Truth, out: MethodOutput, *, universe: Sequence[str] | None = None) -> CaseScore:
    """Score one method's output on one case (04 §7). ``universe`` = the case's candidate services
    (n_i = its size, for Chance@k), None when unknown; it never depends on the method's ranking."""
    if out.outcome not in RUN_OUTCOMES:
        raise ValueError(f"run outcome {out.outcome!r} is not in {sorted(RUN_OUTCOMES)}")
    ran = out.outcome == OK
    unranked = ran and (not out.ranks or out.rankers_active == ())
    scored = ran and not unranked
    root = truth.root_service
    ranks = tuple(out.ranks) if scored else ()
    fine_applicable = root is not None and truth.indicator is not None
    pair = None  # (predicted, true) fault type: the fault class, or mode = code for RE3 (04 §7)
    if truth.fault_class is not None:
        pair = (out.root_fault_class, truth.fault_class)
    elif truth.mode == CODE_MODE:
        pair = (out.root_mode, truth.mode)
    return CaseScore(
        outcome=out.outcome,
        has_truth=root is not None,
        unranked=unranked,
        ranks=ranks,
        position=position_of(coarse_ranking(ranks), root) if root is not None else None,
        fine_position=position_of(fine_ranking(ranks), (root, truth.indicator)) if fine_applicable else None,
        fine_applicable=fine_applicable,
        retrieval_hit=_member(out.slate, root, scored),
        pool_hit=_member(out.pool, root, scored),
        in_set=_member(out.candidate_set, root, scored),
        set_size=len(out.candidate_set) if scored and out.candidate_set is not None else None,
        fault_class_hit=scored and pair[0] == pair[1] if out.has_verdict and root and pair else None,
        n_candidates=None if universe is None else len(universe),
        in_universe=_member(universe, root),
        slate_k=out.slate_k,
        onset_error_ms=_onset_error_ms(out.t_onset_ns, truth.t_inject_ns) if ran else None,
    )
