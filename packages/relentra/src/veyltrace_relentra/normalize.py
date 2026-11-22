"""Normalise checked proposals into their contract form (08 §3.6; 03 §9.1).

Why everything is ordered by content: the output must depend on the set of things the model proposed,
never on the order it wrote them in, so a reordered but equal reply gives byte-identical
`proposals.json`. Merging and capping therefore walk the proposals in canonical order, and ids are
content hashes.

The one exception is `rank` (proposals 1.1, #409): the model's order is what bench's agent-only arm
measures (04 §4), so each kept proposal records where it first appeared in the reply. It changes no
other field, no id and not the file order.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Final, get_args

from veyltrace_contracts import models
from veyltrace_core.canonical import canonical_json, canonical_json_str
from veyltrace_core.hashing import sha256_json
from veyltrace_relentra.reply import CheckedAsk, CheckedClaim, CheckedProposal
from veyltrace_relentra.schema import MAX_ASKS, MAX_CITES, MAX_TRIALS
from veyltrace_relentra.settings import BriefSettings

__all__ = ["normalize_asks", "normalize_proposals"]

_TRIAL_ORDER: Final = {t: i for i, t in enumerate(get_args(models.TrialId))}
_PROPOSAL_ID_HEX: Final = 8


def _args_key(args: Any) -> str:
    return canonical_json_str(dict(args))


def _claim_dict(claim: CheckedClaim) -> dict[str, Any]:
    return {"predicate": claim.predicate, "args": dict(claim.args), "cites": sorted(claim.cites)}


def _content_key(proposal: CheckedProposal) -> bytes:
    """Canonical bytes of a whole checked proposal: the order-free walk order."""
    return canonical_json(
        {
            "service": proposal.service,
            "fault_class": proposal.fault_class,
            "indicator": proposal.indicator,
            "claims": sorted((_claim_dict(c) for c in proposal.claims), key=canonical_json),
            "requested_trials": sorted(proposal.requested_trials),
            "rationale": proposal.rationale,
        }
    )


def _merge_claims(claims: Iterable[CheckedClaim], limit: int) -> list[dict[str, Any]]:
    """One claim per (predicate, args) with the union of its cites, sorted, cut to `limit`."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for claim in claims:
        key = (claim.predicate, _args_key(claim.args))
        entry = merged.setdefault(
            key, {"predicate": claim.predicate, "args": dict(claim.args), "cites": set()}
        )
        entry["cites"].update(claim.cites)
    out: list[dict[str, Any]] = []
    for key in sorted(merged)[:limit]:
        entry = merged[key]
        out.append({**entry, "cites": sorted(entry["cites"])[:MAX_CITES]})
    return out


def _finish(group: Sequence[CheckedProposal], settings: BriefSettings) -> dict[str, Any]:
    """One contract proposal from all checked proposals of one (service, fault_class)."""
    first = group[0]
    indicator = next((p.indicator for p in group if p.indicator is not None), None)
    hypothesis = {
        "service": first.service,
        "component": None,  # always null in v0.1 (08 §2.2)
        "fault_class": first.fault_class,
        "indicator": indicator,
    }
    claims = _merge_claims((c for p in group for c in p.claims), settings.max_claims_per_proposal)
    proposal_id = "P" + sha256_json({"hypothesis": hypothesis, "claims": claims})[:_PROPOSAL_ID_HEX]
    trials = sorted({t for p in group for t in p.requested_trials}, key=_TRIAL_ORDER.__getitem__)
    return {
        "proposal_id": proposal_id,
        "hypothesis": hypothesis,
        "claims": [{"claim_id": f"{proposal_id}-{i}", **c} for i, c in enumerate(claims, start=1)],
        "requested_trials": trials[:MAX_TRIALS],
        "rationale": first.rationale,
    }


def normalize_proposals(
    proposals: Iterable[CheckedProposal], settings: BriefSettings
) -> list[dict[str, Any]]:
    """Merge by (service, fault_class), deduplicate, cap, sort, assign ids and rank (08 §3.6; #409).

    `proposals` is the validated reply in the model's order, after drops. A merged proposal ranks at
    its members' first position; the kept ones are renumbered 1..k in that order after the cap.
    """
    groups: dict[tuple[str, str], list[CheckedProposal]] = {}
    first: dict[tuple[str, str], int] = {}
    for position, proposal in sorted(enumerate(proposals, start=1), key=lambda ip: _content_key(ip[1])):
        key = (proposal.service, proposal.fault_class)
        groups.setdefault(key, []).append(proposal)
        first[key] = min(first.get(key, position), position)
    keys = sorted(groups)[: settings.max_hypotheses]
    rank = {key: i for i, key in enumerate(sorted(keys, key=first.__getitem__), start=1)}
    kept = [{**_finish(groups[key], settings), "rank": rank[key]} for key in keys]
    return sorted(
        kept,
        key=lambda p: (p["hypothesis"]["service"], p["hypothesis"]["fault_class"], p["proposal_id"]),
    )


def normalize_asks(asks: Iterable[CheckedAsk]) -> list[dict[str, str]]:
    """Unique asks sorted by (kind, target), then `why`; at most `MAX_ASKS` (03 §9.1)."""
    unique = {(a.kind, a.target, a.why) for a in asks}
    return [{"kind": k, "target": t, "why": w} for k, t, w in sorted(unique)[:MAX_ASKS]]
