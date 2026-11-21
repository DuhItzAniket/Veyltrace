"""`brief` mode (08 §3.2): one constrained model call, at most one repair, then salvage.

The controller is code, not the model: small models act on their previous result too rarely to be
trusted with the loop. Every outcome is written down. A provider error or an unusable reply gives
`status = failed` with no proposals and the run goes on, exactly as with AI off on this evidence.
Budgets use only recorded usage and latency, so replay reproduces every decision (08 §5.1).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

from veyltrace_contracts import models
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import io
from veyltrace_core.context import AIManifest, EngineResult, RunContext
from veyltrace_core.errors import ContractValidationError
from veyltrace_core.hashing import sha256_bytes, sha256_json
from veyltrace_core.rng import rng
from veyltrace_faultloom.cards import evidence_cards
from veyltrace_faultloom.validation import read_domain
from veyltrace_llm.client import JsonReply, LLMClient
from veyltrace_llm.errors import ProviderError
from veyltrace_llm.providers import Provider
from veyltrace_llm.request import Completion, LLMRequest, Message
from veyltrace_llm.settings import settings_from as llm_settings
from veyltrace_relentra.normalize import normalize_asks, normalize_proposals
from veyltrace_relentra.prompt import (
    fit_prompt,
    load_prompt_files,
    pool_context,
    render_messages,
    repair_messages,
)
from veyltrace_relentra.reply import CheckedReply, Problem, check_reply
from veyltrace_relentra.schema import CaseEnums, build_enums, build_schema, schema_sha256
from veyltrace_relentra.settings import BriefSettings, brief_settings, sampler_params

__all__ = ["PURPOSE", "run_brief"]

ENGINE: Final = "relentra"
#: The cassette purpose of every brief-mode call (08 §5.2), repairs included.
PURPOSE: Final = "relentra.brief"
_LINE_FIELDS: Final = (
    "request_sha256", "response_sha256", "tool", "args", "result_sha256", "summary", "state", "detail",
)  # fmt: skip


class _Trace:
    """Lines of `agent_trace.jsonl`; the writer fills `seq` and the hash chain (08 §5.3)."""

    def __init__(self, writer: io.JsonlWriter) -> None:
        self._writer = writer

    def state(self, name: str, detail: str | None = None) -> None:
        self._writer.append({**dict.fromkeys(_LINE_FIELDS), "type": "state", "state": name, "detail": detail})

    def call(self, key: str, response_sha256: str) -> None:
        line = {"request_sha256": key, "response_sha256": response_sha256}
        self._writer.append({**dict.fromkeys(_LINE_FIELDS), "type": "llm_call", **line})


@dataclass
class _Budget:
    """`budget_used`, summed from what the cassette records (03 §9.1)."""

    turns: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    wall_ms: float = 0.0

    def add(self, completion: Completion | None) -> None:
        self.turns += 1
        if completion is not None:
            self.tokens_in += completion.usage.tokens_in
            self.tokens_out += completion.usage.tokens_out
            self.wall_ms += completion.latency_ms

    def as_json(self) -> dict[str, Any]:
        return {
            "turns": self.turns,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "wall_ms": self.wall_ms,
        }


@dataclass(frozen=True)
class _Prompt:
    """What one value of `k` produced: the case enums and schema go with its messages."""

    enums: CaseEnums
    schema: dict[str, Any]
    messages: tuple[Message, ...]


def _slate_order(slate: models.Slate, case_id: str, settings: BriefSettings) -> list[str] | None:
    """A case-seeded order of the cards for the permutation ablation (08 §3.5), else rank order."""
    if not settings.permute_slate:
        return None
    services = [c.service for c in slate.candidates]
    return [services[int(i)] for i in rng(case_id, "relentra.permute").permutation(len(services))]


def _problems(reply: JsonReply, checked: CheckedReply) -> Sequence[Problem]:
    if reply.parse_error is not None:
        return (Problem("reply", reply.parse_error),)
    return checked.problems


def run_brief(ctx: RunContext, provider: Provider | None = None) -> EngineResult:
    """Pipeline step 7 in `brief` mode; `provider` replaces the configured one in tests."""
    settings = brief_settings(ctx.config)
    manifest = ctx.read_model("case_manifest", models.CaseManifest)
    slate = ctx.read_model("slate", models.Slate)
    if slate.case_id != manifest.case_id:
        msg = f"slate is for case {slate.case_id}, case_manifest for {manifest.case_id}"
        raise ContractValidationError("slate", msg)
    domain = read_domain(ctx)
    llm = llm_settings(ctx.config.section("llm"))
    client = LLMClient(llm, ctx.ai_mode, ctx.cassette_dir, provider=provider, force_record=ctx.force_record)
    files = load_prompt_files(manifest.system, ctx.dataset, domain.nodes, settings)
    params = sampler_params(settings.sampler, manifest.case_id)
    order = _slate_order(slate, manifest.case_id, settings)
    pool = pool_context(slate, settings.pool_context_n)
    prompts: dict[int, _Prompt] = {}

    def build(k: int) -> tuple[Message, ...]:
        deck = evidence_cards(slate, k, ctx=ctx, order=order)
        atoms = [a["atom_id"] for card in deck.candidates for a in card["atoms"]]
        enums = build_enums(domain.nodes, domain.signals, atoms, settings)
        schema = build_schema(enums, settings)
        prompts[k] = _Prompt(enums, schema, render_messages(files, deck.text, pool, schema))
        return prompts[k].messages

    budget = _Budget()
    proposals: list[dict[str, Any]] = []
    asks: list[dict[str, str]] = []
    schema_hash: str | None = None
    with io.JsonlWriter("agent_trace", ctx.run_dir) as writer:
        trace = _Trace(writer)
        trace.state("start")
        fitted = fit_prompt(build, settings)
        status = "budget_exhausted"
        if fitted is None:
            trace.state("budget_context")
        else:
            prompt = prompts[fitted.k]
            schema_hash = schema_sha256(prompt.schema)
            trace.state("cards_built")
            trace.state("prompt_built")

            def call(messages: Sequence[Message]) -> JsonReply | None:
                key = LLMRequest(PURPOSE, llm.model, tuple(messages), params, prompt.schema).key
                try:
                    reply = client.call_json(PURPOSE, messages, prompt.schema, params)
                except ProviderError as exc:
                    budget.add(exc.completion)
                    error = {"kind": exc.error.kind, "message": exc.error.message}
                    trace.call(key, sha256_json(error))
                    trace.state("provider_error")
                    return None
                budget.add(reply.completion)
                trace.call(key, sha256_bytes((reply.completion.content or "").encode("utf-8")))
                return reply

            messages: Sequence[Message] = prompt.messages
            parsed: CheckedReply | None = None
            valid = reachable = False
            for attempt in range(settings.max_repairs + 1):
                reply = call(messages)
                reachable = reply is not None
                if reply is None:
                    break
                checked = check_reply(reply.value, prompt.enums, domain, settings)
                if reply.parse_error is None:
                    parsed = checked
                problems = _problems(reply, checked)
                if not problems:
                    valid = True
                    trace.state("validated")
                    break
                trace.state("validation_failed")
                if attempt < settings.max_repairs:
                    trace.state("repair")
                    content = reply.completion.content or ""
                    messages = repair_messages(files, messages, content, problems)
            status = "failed"
            if reachable and parsed is not None:
                if not valid:
                    for drop in parsed.drops:
                        trace.state(drop.kind, drop.detail)
                proposals = normalize_proposals(parsed.proposals, settings)
                asks = normalize_asks(parsed.asks)
                if valid or proposals:
                    status = "complete"
                else:
                    asks = []
        trace.state("failed" if status == "failed" else "done")
    document = {
        "schema_version": CONTRACTS["proposals"].version,
        "case_id": manifest.case_id,
        "status": status,
        "mode": "brief",
        "model": {
            "provider": llm.provider,
            "name": llm.model.name,
            "gguf_sha256": llm.model.gguf_sha256,
            "params": params,
        },
        "budget_used": budget.as_json(),
        "proposals": proposals,
        "asks": asks,
    }
    outputs = (("proposals", ctx.write("proposals", document)), ("agent_trace", writer.close()))
    return EngineResult(
        engine=ENGINE,
        status="degraded" if status == "failed" else "ok",
        outputs=outputs,
        metrics={"proposals": len(proposals), "turns": budget.turns},
        notes=(f"brief mode: {status}",),
        ai_manifest=AIManifest(
            provider=llm.provider,
            model=llm.model.name,
            gguf_sha256=llm.model.gguf_sha256,
            prompts=files.hashes,
            schemas=((PURPOSE, schema_hash),) if schema_hash is not None else (),
        ),
    )
