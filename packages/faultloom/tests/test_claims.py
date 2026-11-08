"""The symmetric claim pass (06 §3.6, §7): claim atom ids, dedup, rejections and symmetry."""

from __future__ import annotations

import json
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from veyltrace_contracts import models
from veyltrace_core.config import load_config
from veyltrace_core.testing.fixtures import repo_root
from veyltrace_faultloom.claims import claim_atoms, valid_claims
from veyltrace_faultloom.predicates import LIBRARY, ClaimView
from veyltrace_faultloom.validation import CaseDomain, ValidClaim, domain_of

#: (predicate, args) options: valid, a float/int duplicate, and invalid ones (no atom).
OPTIONS = [
    ("zscore_above", {"signal": "cpu", "k": 4.0}),
    ("zscore_above", {"signal": "cpu", "k": 4}),  # the same canonical claim as above
    ("onset_before", {"other_service": "b"}),
    ("silent", {}),
    ("edge_anomalous", {"callee": "ghost"}),  # unknown_entity
    ("zscore_above", {"signal": "gpu", "k": 4.0}),  # bad_args (the schema already enumerates names)
    ("silent", {"subject": "a"}),  # bad_args
]


def _proposals(groups: list[tuple[str, list[int]]], status: str = "complete") -> models.Proposals:
    example = json.loads((repo_root() / "contracts/examples/proposals.example.json").read_text("utf-8"))
    template = example["proposals"][0]
    proposals = []
    for i, (service, picks) in enumerate(groups):
        pid = f"P{i:08x}"
        claims = [
            {"claim_id": f"{pid}-{j + 1}", "predicate": OPTIONS[k][0], "args": OPTIONS[k][1], "cites": []}
            for j, k in enumerate(picks)
        ]
        hypothesis = {**template["hypothesis"], "service": service}
        proposals.append({**template, "proposal_id": pid, "hypothesis": hypothesis, "claims": claims})
    return models.Proposals.model_validate({**example, "status": status, "proposals": proposals})


def _domain(view: Any) -> CaseDomain:
    return domain_of(view, load_config("faultloom"))


def _view(hm: Any) -> ClaimView:
    rows = (
        hm.anomaly("a|a-1|cpu|metrics", "internal", score=9.0),
        hm.anomaly("b|b|cpu|metrics", "internal", score=1.0),
    )
    inputs = hm.view(anomalies=rows, onsets=(hm.onset("a", internal=0), hm.onset("b", ext=60)))
    nodes = tuple(hm.node(n) for n in ("a", "b", "c"))
    return ClaimView(hm.view(**{**inputs.__dict__, "nodes": nodes, "signals": frozenset({"cpu"})}), ())


def test_claim_atom_id_reproduces_the_worked_example(hm: Any) -> None:
    # 06 §3.8: zscore_above(·, signal="cpu", k=4) for checkoutservice hashes to E7d69a580cc.
    claim = ValidClaim(LIBRARY["zscore_above"], {"k": 4.0, "signal": "cpu"})
    (atom,) = claim_atoms(ClaimView(hm.view(), ()), ["checkoutservice"], [claim])
    assert atom["atom_id"] == "E7d69a580cc"
    assert (atom["args_json"], atom["kind"], atom["origin"]) == (
        '{"k":4.0,"signal":"cpu"}',
        "claim_check",
        "claim_check",
    )
    assert (atom["holds"], atom["value"], atom["unit"], atom["window"]) == (None, 0.0, "z", "incident")


def test_valid_claims_are_deduplicated_and_rejections_counted(hm: Any) -> None:
    view = _view(hm)
    claims, rejected = valid_claims(
        _proposals([("a", [0, 1, 2]), ("ghost", [3, 4, 5, 6, 3])]), _domain(view.inputs)
    )
    assert [(c.predicate.name, dict(c.args)) for c in claims] == [
        ("onset_before", {"other_service": "b"}),
        ("silent", {}),
        ("zscore_above", {"k": 4.0, "signal": "cpu"}),
    ]
    assert rejected == {"bad_args": 2, "unknown_entity": 1}
    atoms = claim_atoms(view, ["a", "b"], claims)
    got = {(a["predicate"], a["candidate"]): a["holds"] for a in atoms}
    assert got == {
        ("onset_before", "a"): True,  # a (0 s) before b (60 s)
        ("onset_before", "b"): None,  # subject = other
        ("silent", "a"): None,  # no silence atoms in this view
        ("silent", "b"): None,
        ("zscore_above", "a"): True,
        ("zscore_above", "b"): False,
    }


def test_only_complete_or_budget_exhausted_proposals_are_evaluated(hm: Any) -> None:
    domain = _domain(_view(hm).inputs)
    assert valid_claims(None, domain) == ([], {})
    assert valid_claims(_proposals([("a", [0])], status="failed"), domain) == ([], {})
    assert len(valid_claims(_proposals([("a", [0])], status="budget_exhausted"), domain)[0]) == 1


_groups = st.lists(
    st.tuples(
        st.sampled_from(("a", "b", "c", "ghost")), st.lists(st.integers(0, len(OPTIONS) - 1), max_size=4)
    ),
    max_size=4,
)


@settings(max_examples=60)
@given(first=_groups, data=st.data())
def test_claim_atoms_depend_only_on_the_distinct_claims_and_the_pool(
    hm: Any, first: Any, data: st.DataObject
) -> None:
    # 06 §7: which proposal named which service, how often and in what order must not matter.
    view = _view(hm)
    picks = [k for _, ks in first for k in ks]
    services = data.draw(st.lists(st.sampled_from(("a", "b", "c", "ghost")), min_size=1, max_size=3))
    shuffled = data.draw(st.permutations(picks + picks[:1]))  # reordered, with a duplicate
    second = [(services[i % len(services)], [k]) for i, k in enumerate(shuffled)]
    domain = _domain(view.inputs)
    claims_1, _ = valid_claims(_proposals(first), domain)
    claims_2, _ = valid_claims(_proposals(second), domain)
    assert claims_1 == claims_2
    assert claim_atoms(view, ["c", "a", "b"], claims_1) == claim_atoms(view, ["a", "b", "c", "a"], claims_2)
