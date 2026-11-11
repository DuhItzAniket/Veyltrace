"""Rankers and their votes: the ranker type, competition ranks and gating (07 §3.1–§3.3).

A ranker votes only if its channel exists for the case (gated RRF, `rrf.gate`) and its quantised
scores are not constant over U (`abstain_on_constant`: a constant vote carries no information).
Ranks are competition ranks on `round(x, 12)`: tied services share a rank, no name leaks in.

Rankers are declared under the entry-point group `veyltrace.rankers` (bench enumerates them).
Engines may not import importlib.metadata (02 §9), so the engine resolves a name to
`veyltrace_causatrix.rankers.<name>.RANKER`; a test pins each entry point to exactly that object.
"""

from __future__ import annotations

import bisect
import importlib
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from veyltrace_core.errors import ConfigError

if TYPE_CHECKING:
    from veyltrace_causatrix.config import CausatrixConfig
    from veyltrace_causatrix.views import EvidenceView, GraphView
    from veyltrace_contracts.models import Sources

#: Scores are compared after rounding to this many decimals (07 §3.1 step 3; §5).
RANK_DECIMALS: Final = 12
#: Why a ranker abstained: its channel is missing (07 §3.3) or its scores are constant (§3.2).
NO_CHANNEL: Final = "no_channel"
CONSTANT: Final = "constant"
RANKERS_PACKAGE: Final = "veyltrace_causatrix.rankers"
_NAME: Final = re.compile(r"^[a-z][a-z0-9_]*$")

Channel = Callable[["EvidenceView", "GraphView", "Sources", "CausatrixConfig"], bool]
Scorer = Callable[["EvidenceView", "GraphView", "CausatrixConfig"], Mapping[str, float]]


@dataclass(frozen=True)
class Ranker:
    """A named ranker: `channel` says whether its evidence channel exists for the case, `score`
    gives a finite score for every service in U (higher = more likely the root)."""

    name: str
    channel: Channel
    score: Scorer


@dataclass(frozen=True)
class Vote:
    """One ranker's outcome on a case: scores and ranks over U, or the reason it abstained."""

    ranker: str
    abstained: str | None
    scores: Mapping[str, float] = field(default_factory=dict[str, float])
    ranks: Mapping[str, int] = field(default_factory=dict[str, int])

    @property
    def active(self) -> bool:
        return self.abstained is None


def competition_ranks(scores: Mapping[str, float]) -> dict[str, int]:
    """rank(s) = 1 + |{t : q(score(t)) > q(score(s))}| with q(x) = round(x, 12) (07 §3.1 step 3)."""
    quantised = {s: round(x, RANK_DECIMALS) for s, x in scores.items()}
    ascending = sorted(quantised.values())
    n = len(ascending)
    return {s: 1 + n - bisect.bisect_right(ascending, q) for s, q in sorted(quantised.items())}


def load_ranker(name: str) -> Ranker:
    """The `RANKER` of module `veyltrace_causatrix.rankers.<name>`; ConfigError if there is none."""
    module_name = f"{RANKERS_PACKAGE}.{name}"
    if not _NAME.match(name):
        msg = f"ranker name {name!r} is not lower snake case"
        raise ConfigError(msg)
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        msg = f"causatrix.rankers.enabled names {name!r}, but no such ranker is installed"
        raise ConfigError(msg) from exc
    ranker: object = getattr(module, "RANKER", None)
    if not isinstance(ranker, Ranker) or ranker.name != name:
        msg = f"{module_name}.RANKER must be a Ranker named {name!r}"
        raise ConfigError(msg)
    return ranker


def vote(ranker: Ranker, ev: EvidenceView, graph: GraphView, sources: Sources, cfg: CausatrixConfig) -> Vote:
    """Gate, score and rank one ranker over U (07 §3.2–§3.3)."""
    if cfg.gate and not ranker.channel(ev, graph, sources, cfg):
        return Vote(ranker.name, NO_CHANNEL)
    raw = ranker.score(ev, graph, cfg)
    if set(raw) != set(ev.universe) or not all(math.isfinite(x) for x in raw.values()):
        msg = f"ranker {ranker.name} must give a finite score to exactly the services of U"
        raise ValueError(msg)
    scores = {s: float(raw[s]) for s in ev.universe}
    if cfg.abstain_on_constant and len({round(x, RANK_DECIMALS) for x in scores.values()}) <= 1:
        return Vote(ranker.name, CONSTANT)
    return Vote(ranker.name, None, scores, competition_ranks(scores))
