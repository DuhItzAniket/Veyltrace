"""`card.json` for one verdict (10 §3.1 steps 1–11), template prose only (X-03; narration is X-09).

`build_card` is a pure function of the run artifacts it is given and the settings, so the card and
its `card_hash` are byte-stable across runs and machines (10 §5 rule 1). Status, root, confidence
and candidate set are copied from the verdict unchanged (package rule 1).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from veyltrace_causivra import assemble, sections
from veyltrace_causivra.assemble import CardSettings
from veyltrace_causivra.playbooks import Playbook, next_steps
from veyltrace_causivra.prose import summary
from veyltrace_contracts import models
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core.hashing import self_hash

__all__ = ["TEMPLATE_NARRATOR", "build_card"]

#: narrator block of a card whose prose is template prose (10 §2.2): no model, no attempt.
TEMPLATE_NARRATOR: Final[Mapping[str, Any]] = {
    "path": "template",
    "model": None,
    "attempts": 0,
    "checker_failures": 0,
}


def build_card(
    *,
    case_id: str,
    verdict: models.Verdict,
    evidence: Sequence[Mapping[str, Any]],
    alert: models.Alert,
    onsets: models.Onsets | None,
    changes: Sequence[Mapping[str, Any]],
    paths: Sequence[Mapping[str, Any]],
    nodes: Iterable[str],
    settings: CardSettings,
    playbooks: Mapping[str, Playbook],
) -> dict[str, Any]:
    """The card object with its `card_hash` (SHA-256 of the canonical card without it, 03 §11.1)."""
    table = assemble.evidence_table(verdict, evidence, settings)
    atoms = assemble.table_atoms(table, evidence)
    ctx = assemble.fill_context(verdict, atoms, nodes, onsets, settings.sig_digits)
    kinds = {str(r["atom_id"]): str(r["kind"]) for r in evidence if str(r["atom_id"]) in atoms}
    v = verdict.model_dump(mode="json", by_alias=True)
    card: dict[str, Any] = {
        "schema_version": CONTRACTS["card"].version,
        "case_id": case_id,
        "verdict_hash": verdict.verdict_hash,
        "title": assemble.title(verdict),
        "status": v["status"],
        "root": v["root"],
        "confidence": v["confidence"],
        "candidate_set": [{"service": c["service"], "component": c["component"]} for c in v["candidate_set"]],
        "summary": summary(verdict, ctx, kinds),
        "timeline": sections.timeline(verdict, alert, onsets, changes, evidence),
        "path": sections.path(verdict, paths),
        "evidence_table": table,
        "why_not": sections.why_not(verdict, ctx, settings),
        "asks": sections.asks(verdict, settings),
        "next_steps": next_steps(verdict, ctx, playbooks),
        "narrator": dict(TEMPLATE_NARRATOR),
    }
    card["card_hash"] = self_hash("card", card)
    return card
