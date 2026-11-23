"""Step 10a: `card.json` and `card.md` for one verdict (10 §3.1 steps 1–12). With AI on and
`narration.enabled`, the summary is LLM narration (10 §3.2), else template prose (10 §3.5).

`build_card` is a pure function of the run artifacts it is given and the settings, so the card and
its `card_hash` are byte-stable across runs and machines (10 §5 rule 1); a narrated summary is
replayed from the cassette, so it is stable under replay. Status, root, confidence
and candidate set are copied from the verdict unchanged (package rule 1).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Final

from veyltrace_causivra import assemble, sections
from veyltrace_causivra.assemble import CardSettings, settings_from
from veyltrace_causivra.checker import checker_settings
from veyltrace_causivra.narrate import PURPOSE, Narration, narrate, narration_settings, sampler_params
from veyltrace_causivra.placeholders import FillContext
from veyltrace_causivra.playbooks import Playbook, load_playbooks, next_steps
from veyltrace_causivra.prose import summary
from veyltrace_causivra.render_md import render_card
from veyltrace_contracts import models
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core.context import AIManifest, EngineResult, RunContext
from veyltrace_core.errors import ContractValidationError
from veyltrace_core.hashing import self_hash
from veyltrace_core.log import get_logger
from veyltrace_llm.client import LLMClient
from veyltrace_llm.providers import Provider
from veyltrace_llm.settings import settings_from as llm_settings

__all__ = ["CARD_MD", "TEMPLATE_NARRATOR", "Narrator", "build_card", "run_card"]

ENGINE: Final = "causivra"
_log = get_logger(__name__)
CARD_MD: Final = "card.md"

#: narrator block of a card whose prose is template prose (10 §2.2): no model, no attempt.
TEMPLATE_NARRATOR: Final[Mapping[str, Any]] = {
    "path": "template",
    "model": None,
    "attempts": 0,
    "checker_failures": 0,
}

#: Narrates the summary from the verdict, the filler context, the atom kinds and the root's path.
Narrator = Callable[[models.Verdict, FillContext, Mapping[str, str], Sequence[str]], Narration]


def build_card(
    *,
    verdict: models.Verdict,
    evidence: Sequence[Mapping[str, Any]],
    alert: models.Alert,
    onsets: models.Onsets | None,
    changes: Sequence[Mapping[str, Any]],
    paths: Sequence[Mapping[str, Any]],
    nodes: Iterable[str],
    settings: CardSettings,
    playbooks: Mapping[str, Playbook],
    narrator: Narrator | None = None,
) -> dict[str, Any]:
    """The card object with its `card_hash` (SHA-256 of the canonical card without it, 03 §11.1).

    `case_id` is the verdict's, so the card cannot name a different case than the verdict it copies.
    Without `narrator`, or when narration falls back, the summary is template prose.
    """
    table = assemble.evidence_table(verdict, evidence, settings)
    atoms = assemble.table_atoms(table, evidence)
    ctx = assemble.fill_context(verdict, atoms, nodes, onsets, settings.sig_digits)
    kinds = {str(r["atom_id"]): str(r["kind"]) for r in evidence if str(r["atom_id"]) in atoms}
    path = sections.path(verdict, paths)
    told = narrator(verdict, ctx, kinds, path) if narrator is not None else None
    v = verdict.model_dump(mode="json", by_alias=True)
    card: dict[str, Any] = {
        "schema_version": CONTRACTS["card"].version,
        "case_id": verdict.case_id,
        "verdict_hash": verdict.verdict_hash,
        "title": assemble.title(verdict),
        "status": v["status"],
        "root": v["root"],
        "confidence": v["confidence"],
        "candidate_set": [{"service": c["service"], "component": c["component"]} for c in v["candidate_set"]],
        "summary": told.summary
        if told is not None and told.summary is not None
        else summary(verdict, ctx, kinds, settings.ask_phrases),
        "timeline": sections.timeline(verdict, alert, onsets, changes, evidence),
        "path": path,
        "evidence_table": table,
        "why_not": sections.why_not(verdict, ctx, settings),
        "asks": sections.asks(verdict, settings),
        "next_steps": next_steps(verdict, ctx, playbooks),
        "narrator": dict(told.narrator) if told is not None else dict(TEMPLATE_NARRATOR),
    }
    card["card_hash"] = self_hash("card", card)
    return card


def _rows(ctx: RunContext, name: str, columns: Sequence[str] | None = None) -> list[dict[str, Any]]:
    """An optional table input as rows; absent → [] (10 §6: missing onsets/changes keep the card valid)."""
    return ctx.read_table(name, columns=columns).to_pylist() if ctx.exists(name) else []


def run_card(ctx: RunContext, provider: Provider | None = None) -> EngineResult:
    """Step 10a: read the card inputs (10 §2.1) and write `card.json` and `card.md`. `provider`
    replaces the configured one in tests.

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
    narration = narration_settings(ctx.config.section(ENGINE))
    llm = llm_settings(ctx.config.section("llm"))
    told: list[Narration] = []
    narrator: Narrator | None = None
    if ctx.ai_mode != "off" and narration.enabled:
        # Relentra (step 7) recorded first; narration adds its calls to the same cassette.
        client = LLMClient(
            llm, ctx.ai_mode, ctx.cassette_dir, provider=provider, append=ctx.ai_mode == "record"
        )
        params = sampler_params(ctx.config.section("relentra"), manifest.case_id, narration.max_tokens)
        checker = checker_settings(ctx.config.section(ENGINE))

        def told_by_llm(
            v: models.Verdict, fill: FillContext, kinds: Mapping[str, str], path: Sequence[str]
        ) -> Narration:
            told.append(narrate(verdict=v, ctx=fill, kinds=kinds, path=path, entities=frozenset(nodes),
                client=client, params=params, settings=narration, checker=checker))  # fmt: skip
            return told[-1]

        narrator = told_by_llm

    card = build_card(
        verdict=verdict,
        evidence=_rows(ctx, "evidence"),
        alert=ctx.read_model("alert", models.Alert),
        onsets=onsets,
        changes=_rows(ctx, "changes"),
        paths=_rows(ctx, "graph.paths"),
        nodes=sorted(nodes),
        settings=settings,
        playbooks=load_playbooks(),
        narrator=narrator,
    )
    outputs = [("card", ctx.write("card", card))]
    outputs.append((CARD_MD, ctx.write_text(CARD_MD, render_card(card, settings.sig_digits))))
    ai: AIManifest | None = None
    if told:
        if told[0].cassette_miss:  # 10 §6: template prose; replay reports the card difference (exit 6)
            _log.warning("causivra.narration.cassette_miss", case_id=manifest.case_id)
        ai = AIManifest(provider=llm.provider, model=llm.model.name, gguf_sha256=llm.model.gguf_sha256,
            prompts=told[0].prompts, schemas=((PURPOSE, told[0].schema_sha256),))  # fmt: skip
    return EngineResult(engine=ENGINE, status="ok", outputs=tuple(outputs), ai_manifest=ai)
