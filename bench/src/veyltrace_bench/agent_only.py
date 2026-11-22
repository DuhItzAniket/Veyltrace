"""`agent-only:brief` (04 §4; R-16 B3b, #398): the model's proposals as a ranking, no verifier.

"Same model and evidence cards; the model's hypotheses in order are the ranking, then the remaining
slate order; no verifier; bench reads proposals.json" (04 §4). So an `agent_only` method makes no
run and no model call of its own: it scores the run of its **source**, the earlier `veyltrace`
method of the experiment with the same `ai` block and overrides, for the same case and seed, and
shares that run's cost (as `causatrix:rrf` shares `veyltrace:off`'s, #172). The ranking is the
proposals' hypothesis services in the model's order, `proposals[].rank` (proposals 1.1, CCR #409:
the 1-based position in the validated reply), de-duplicated, each as `{service}_{indicator}` (the
slate's indicator when the hypothesis names none), then the slate's own ranking without them.
`proposals.json` itself is sorted by service (03 §9.1), so its file order would measure the
alphabet; when any proposal's rank is null (the order is unknown: a 1.0 file or a Relentra
without #409), the case is unranked (a miss, 04 §7) and the reason is logged. No proposals (a
skipped or failed Relentra step) leaves the slate's ranking.
"""

from __future__ import annotations

from typing import cast

from veyltrace_bench.experiment import Experiment, MethodSpec
from veyltrace_bench.metrics import RANK_SEPARATOR, MethodOutput
from veyltrace_contracts.models import Proposals, Slate
from veyltrace_core.errors import ConfigError
from veyltrace_core.log import get_logger

KIND = "agent_only"
SOURCE_KIND = "veyltrace"
NO_INDICATOR = "unknown"  # RCAEval's indicator of an entry without one (metrics.NO_INDICATOR)
RANK = "rank"  # proposals[].rank (proposals 1.1, CCR #409); read by name until the models have it

_log = get_logger(__name__)


def source_of(exp: Experiment, method: MethodSpec) -> MethodSpec:
    """The earlier veyltrace method whose runs `method` scores; a ConfigError before any run if none."""
    earlier = exp.methods[: exp.methods.index(method)]
    for m in earlier:
        if m.kind == SOURCE_KIND and m.ai == method.ai and m.overrides == method.overrides:
            return m
    raise ConfigError(
        f"method {method.id}: kind agent_only scores the proposals of an earlier veyltrace method with the"
        f" same ai block and overrides (04 §4); none precedes it"
    )


def ranks(
    proposals: Proposals | None, slate_ranking: tuple[str, ...], slate: Slate
) -> tuple[str, ...] | None:
    """The proposals' services in rank order, then the slate's ranking without them; None (unranked)
    when a proposal's rank is null, since the model's order is then unknown."""
    indicator = {c.service: c.indicator for c in slate.candidates}
    listed = list(proposals.proposals) if proposals is not None else []
    order = [getattr(p, RANK, None) for p in listed]
    if any(not isinstance(r, int) for r in order):
        _log.info(
            "bench.agent_only_unranked", case_id=proposals.case_id if proposals else None, why="null rank"
        )
        return None
    by_rank = sorted(range(len(listed)), key=lambda i: (cast("int", order[i]), i))
    head: dict[str, str] = {}
    for p in (listed[i] for i in by_rank):
        service = p.hypothesis.service
        if service not in head:
            head[service] = p.hypothesis.indicator or indicator.get(service, NO_INDICATOR)
    rest = (r for r in slate_ranking if r.partition(RANK_SEPARATOR)[0] not in head)
    return (*(f"{s}{RANK_SEPARATOR}{i}" for s, i in head.items()), *rest)


def output(
    outcome: str, proposals: Proposals | None, slate: Slate | None, slate_ranking: tuple[str, ...]
) -> MethodOutput:
    """The method's output: ranks only (no slate, pool, set or fault type of its own, 04 §4); a run
    without a slate is a miss, and a slate no ranker scored stays unranked (04 §7)."""
    if outcome != "ok" or slate is None:
        return MethodOutput(outcome=outcome)
    return MethodOutput(
        outcome=outcome,
        ranks=ranks(proposals, slate_ranking, slate) or (),  # () is unranked (04 §7)
        rankers_active=tuple(slate.rankers_active),
    )
