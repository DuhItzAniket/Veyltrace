"""Engine entry point of Causentra (registered as `veyltrace.engines:causentra`).

Pipeline step 9 (09 §3.1): read the inputs, run trials T1–T4 on every decision-pool candidate,
compute V, order, set and status, and write `verdict.json` with its `verdict_hash`. R-12 adds
T5–T10 and the conformal set. The signature `run(ctx: RunContext) -> EngineResult` is fixed
(AGENTS §5).
"""

from __future__ import annotations

from typing import Final

from veyltrace_causentra.config import ENGINE, config_from
from veyltrace_causentra.decision import decide
from veyltrace_causentra.inputs import DECIMALS, load_inputs
from veyltrace_causentra.outcome import no_fault, status_of
from veyltrace_causentra.verdict import build_verdict
from veyltrace_core.context import EngineResult, RunContext
from veyltrace_core.hashing import sha256_json

#: Inputs whose absence fails the step (09 §6: "slate or evidence: status failed; no verdict").
REQUIRED: Final = ("slate", "evidence")


def _alpha_mismatch(ctx: RunContext, alpha: float) -> str | None:
    """Why the calibration's q_hat cannot be used at `alpha` (its q_hat is the ceil((n+1)(1-alpha))-th score
    at the file's own alpha, 09 §3.7), treated like the arm/protocol mismatch of 09 §3.15."""
    calibration = ctx.config.calibration
    if calibration is None or round(calibration.alpha, DECIMALS) == round(alpha, DECIMALS):
        return None
    return (
        f"calibration {ctx.config.calibration_family} was fitted at alpha={calibration.alpha}, the run's "
        f"causentra.alpha is {alpha}: its q_hat does not apply (09 §3.7, §3.15)"
    )


def run(ctx: RunContext) -> EngineResult:
    """Pipeline step 9: the verdict (09 §6: no slate or evidence fails; so does a foreign alpha)."""
    if ctx.engine != ENGINE:
        msg = f"causentra called with a context for engine {ctx.engine!r}"
        raise ValueError(msg)
    missing = [name for name in REQUIRED if not ctx.exists(name)]
    if missing:
        return EngineResult(
            engine=ENGINE,
            status="failed",
            notes=(f"missing input(s) {', '.join(missing)}: no verdict (09 §6)",),
        )
    cfg = config_from(ctx.config, ctx.config.core)
    mismatch = _alpha_mismatch(ctx, cfg.alpha)
    if mismatch is not None:
        return EngineResult(engine=ENGINE, status="failed", notes=(mismatch,))
    inp = load_inputs(ctx, cfg)
    d = decide(inp, cfg)
    status, level = status_of(d, no_fault(inp), cfg)
    verdict = build_verdict(
        run_id=ctx.run_id,
        inp=inp,
        cfg=cfg,
        d=d,
        status=status,
        level=level,
        calibration={"family": ctx.config.calibration_family, "sha256": ctx.config.calibration_sha256},
        params_sha256=sha256_json(dict(ctx.config)),  # 09 §2.2: the effective causentra section
    )
    digest = ctx.write("verdict", verdict)
    metrics: dict[str, int | float] = {
        "decision_pool": len(d.ranked),
        "proposals": 0 if inp.proposals is None else len(inp.proposals.proposals),
        "proposals_admitted": len(d.admitted),
        "claim_atoms": len(inp.claims),
        "set_size": len(verdict["candidate_set"]),
        "asks": len(verdict["asks"]),
    }
    return EngineResult(
        engine=ENGINE,
        status="degraded" if inp.degraded else "ok",
        outputs=(("verdict", digest),),
        metrics=metrics,
        notes=inp.notes,
    )
