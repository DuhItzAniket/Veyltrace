"""The symmetric claim pass (06 §3.6 steps 2-5): `claim_check` atoms for every pool candidate.

Why: the model may choose which checks run, but code runs every check for every claim-pass pool
candidate, so a proposal can never favour its own candidate (02 §2 P2). A check's result depends
only on the data, the candidate and the canonical (predicate, args) pair, never on which proposal
asked, how often, or in what order (package rule "Symmetry"). Rejected claims give no atom;
Causentra re-derives their reasons with the same pure `validate` (06 §3.6 step 5).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final

from veyltrace_contracts import models
from veyltrace_core.canonical import canonical_json_str
from veyltrace_faultloom.atoms import Atom, claim_atom
from veyltrace_faultloom.predicates import ClaimView
from veyltrace_faultloom.validation import CaseDomain, Rejection, ValidClaim, validate

__all__ = ["EVALUATED_STATUSES", "claim_atoms", "valid_claims"]

#: proposals.status values whose claims are evaluated (03 §9.1; 09 §3.2 uses the same set).
EVALUATED_STATUSES: Final = frozenset({"complete", "budget_exhausted"})


def valid_claims(
    proposals: models.Proposals | None, domain: CaseDomain
) -> tuple[list[ValidClaim], Mapping[str, int]]:
    """The distinct valid (predicate, canonical args) pairs, sorted by name then canonical args, and
    the rejection count per reason (06 §3.6 step 3). Duplicates are evaluated once."""
    rejected: dict[str, int] = {}
    pairs: dict[tuple[str, str], ValidClaim] = {}
    if proposals is None or proposals.status not in EVALUATED_STATUSES:
        return [], rejected
    claims = sorted(
        ((p.proposal_id, c.claim_id, c.predicate, c.args) for p in proposals.proposals for c in p.claims),
        key=lambda t: (t[0], t[1]),
    )
    for _, _, name, args in claims:
        got = validate(name, args, domain)
        if isinstance(got, Rejection):
            rejected[got.reason] = rejected.get(got.reason, 0) + 1
        else:
            pairs.setdefault((got.predicate.name, canonical_json_str(got.args)), got)
    return [pairs[k] for k in sorted(pairs)], dict(sorted(rejected.items()))


def claim_atoms(view: ClaimView, pool: Iterable[str], claims: Iterable[ValidClaim]) -> list[Atom]:
    """One claim_check atom per (valid claim, pool candidate): the subject is substituted, nothing
    else changes (06 §3.6 step 4). A = {"args": canonical args, "predicate": name} (06 §3.2)."""
    members = sorted(set(pool))
    return [
        claim_atom(claim.predicate, c, claim.args, claim.predicate.evaluate(view, c, claim.args))
        for claim in claims
        for c in members
    ]
