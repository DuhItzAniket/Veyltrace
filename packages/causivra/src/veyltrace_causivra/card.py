"""Step 10a: `card.json` and `card.md` for one verdict (10 §3.1 steps 1–12), template prose only
(X-03; LLM narration is X-09).

`build_card` is a pure function of the run artifacts it is given and the settings, so the card and
its `card_hash` are byte-stable across runs and machines (10 §5 rule 1). Status, root, confidence
and candidate set are copied from the verdict unchanged (package rule 1).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from veyltrace_causivra import assemble, sections
from veyltrace_causivra.assemble import CardSettings, settings_from
from veyltrace_causivra.playbooks import Playbook, load_playbooks, next_steps
from veyltrace_causivra.prose import summary
from veyltrace_causivra.render_md import render_card
from veyltrace_contracts import models
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core.context import EngineResult, RunContext
from veyltrace_core.errors import ContractValidationError
from veyltrace_core.hashing import self_hash

__all__ = ["CARD_MD", "TEMPLATE_NARRATOR", "build_card", "run_card"]

ENGINE: Final = "causivra"
CARD_MD: Final = "card.md"

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


def _rows(ctx: RunContext, name: str, columns: Sequence[str] | None = None) -> list[dict[str, Any]]:
    """An optional table input as rows; absent → [] (10 §6: missing onsets/changes keep the card valid)."""
    return ctx.read_table(name, columns=columns).to_pylist() if ctx.exists(name) else []


def run_card(ctx: RunContext) -> EngineResult:
    """Step 10a: read the card inputs (10 §2.1) and write `card.json` and `card.md`.

    The `{SVC:…}` lexicon is `graph.nodes.node` plus `case_manifest.services` (the entity lexicon
    of 10 §2.1), so a card stays writable while the graph is empty. The alert hint is never read
    (the run context redacts it from case_manifest).
    """
    settings = settings_from(ctx.config, ctx.config.section("causentra"))
    verdict = ctx.read_model("verdict", models.Verdict)
    manifest = ctx.read_model("case_manifest", models.CaseManifest)
    if verdict.case_id != manifest.case_id:
        raise ContractValidationError(
            "verdict", f"is for case {verdict.case_id}, the run is {manifest.case_id}"
        )
    onsets = ctx.read_model("onsets", models.Onsets) if ctx.exists("onsets") else None
    nodes = {str(r["node"]) for r in _rows(ctx, "graph.nodes", ["node"])} | set(manifest.services)
    card = build_card(
        case_id=manifest.case_id,
        verdict=verdict,
        evidence=_rows(ctx, "evidence"),
        alert=ctx.read_model("alert", models.Alert),
        onsets=onsets,
        changes=_rows(ctx, "changes"),
        paths=_rows(ctx, "graph.paths"),
        nodes=sorted(nodes),
        settings=settings,
        playbooks=load_playbooks(),
    )
    outputs = [("card", ctx.write("card", card))]
    outputs.append((CARD_MD, ctx.write_text(CARD_MD, render_card(card, settings.sig_digits))))
    return EngineResult(engine=ENGINE, status="ok", outputs=tuple(outputs))
