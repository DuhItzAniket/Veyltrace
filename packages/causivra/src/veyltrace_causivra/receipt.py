"""Step 10b: the verdict receipt, an in-toto Statement v1 (10 §3.8 steps 1–5; 03 §11.2).

Why: anyone holding the run directory can re-check a verdict. The receipt binds the run manifest
(inputs, config, environment, every output hash), the exact bytes of `verdict.json`, the verdict
and card self-hashes, and the head of the agent-trace hash chain. It is a pure function of files
in the run directory, written as canonical JSON, so two runs give the same bytes.

Refusals (10 §6): core's manifest must list `verdict.json`, `card.json`, `card.md` and, when the
run has one, `agent_trace.jsonl` (its head goes into the receipt) with the hashes those files
have now; the card must belong to this verdict; and the agent-trace chain must verify. Any
failure stops the run before a receipt exists. Optional minisign signing is X-09.
"""

from __future__ import annotations

from typing import Any, Final

from veyltrace_contracts import models
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core import io
from veyltrace_core.context import EngineResult, RunContext
from veyltrace_core.errors import ContractValidationError
from veyltrace_core.hashing import sha256_file, verify_chain

__all__ = [
    "PREDICATE_TYPE",
    "REQUIRED_OUTPUTS",
    "STATEMENT_TYPE",
    "build_receipt",
    "run_receipt",
    "trace_head",
]

ENGINE: Final = "causivra"
STATEMENT_TYPE: Final = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE: Final = "https://veyltrace.dev/rca-verdict/v1"
CARD_MD: Final = "card.md"
#: Outputs the manifest must list before the receipt may be written (10 §3.8 step 1).
REQUIRED_OUTPUTS: Final = tuple(sorted((CONTRACTS["verdict"].path, CONTRACTS["card"].path, CARD_MD)))
AGENT_TRACE: Final = CONTRACTS["agent_trace"].path


def trace_head(ctx: RunContext) -> str | None:
    """The last line_hash of a verified agent trace; None when the trace is absent or has no
    lines (AI off, or Relentra skipped; #20 spec note). A broken chain raises ChainBroken."""
    if not ctx.exists("agent_trace"):
        return None
    return verify_chain(io.read_lines("agent_trace", ctx.run_dir, models.AgentTraceLine))


def _check_manifest(ctx: RunContext, manifest: models.RunManifest) -> None:
    listed = {o.name: o.sha256 for o in manifest.outputs}
    has_trace = AGENT_TRACE in listed or ctx.exists("agent_trace")
    attested = [*REQUIRED_OUTPUTS, *([AGENT_TRACE] if has_trace else [])]
    missing = [name for name in attested if name not in listed]
    if missing:
        msg = f"outputs lack {missing}; core writes the manifest after step 10a (02 §6.10)"
        raise ContractValidationError("run_manifest", msg)
    changed = [
        name
        for name in attested
        if not (ctx.run_dir / name).is_file() or sha256_file(ctx.run_dir / name) != listed[name]
    ]
    if changed:
        raise ContractValidationError("run_manifest", f"{changed} changed after the manifest was written")


def build_receipt(
    manifest: models.RunManifest,
    verdict_file_sha256: str,
    verdict_hash: str,
    card_hash: str,
    agent_trace_head: str | None,
) -> dict[str, Any]:
    """The Statement exactly as 03 §11.2: one subject, the constant name `verdict.json`."""
    return {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": CONTRACTS["verdict"].path, "digest": {"sha256": verdict_file_sha256}}],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "run_manifest": manifest.model_dump(mode="json", by_alias=True),
            "verdict_hash": verdict_hash,
            "card_hash": card_hash,
            "agent_trace_head": agent_trace_head,
        },
    }


def run_receipt(ctx: RunContext) -> EngineResult:
    """Write `receipt.json` (10 §3.8 steps 1–5)."""
    manifest = ctx.read_model("run_manifest", models.RunManifest)
    _check_manifest(ctx, manifest)
    verdict = ctx.read_model("verdict", models.Verdict)
    card = ctx.read_model("card", models.Card)
    if card.verdict_hash != verdict.verdict_hash:
        msg = (
            f"card is for verdict {card.verdict_hash[:12]}, the run's verdict is {verdict.verdict_hash[:12]}"
        )
        raise ContractValidationError("card", msg)
    receipt = build_receipt(
        manifest,
        sha256_file(ctx.path("verdict")),
        verdict.verdict_hash,
        card.card_hash,
        trace_head(ctx),
    )
    return EngineResult(engine=ENGINE, status="ok", outputs=(("receipt", ctx.write("receipt", receipt)),))
