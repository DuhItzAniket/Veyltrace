"""Engine entry point of FaultLoom (registered as `veyltrace.engines:faultloom`).

FaultLoom runs twice (02 §4): the engine pass at step 5 (`ctx.phase == "main"`) and the claim
pass at step 8 (`ctx.phase == "claim_pass"`); one `run(ctx) -> EngineResult` branches on the
phase (M0 lead decision 2026-11-06, D-5). Until R-08 both phases live in `veyltrace_faultloom.stub`:
the engine pass writes R-06's anomaly atoms, the claim pass is R-00's stub (R-08/R-12 replace it).
The signature is fixed (AGENTS §5).
"""

from veyltrace_core.context import EngineResult, RunContext
from veyltrace_faultloom.stub import ENGINE, run_claim_pass, run_main


def run(ctx: RunContext) -> EngineResult:
    """Run the FaultLoom pass that `ctx.phase` names (main or claim_pass)."""
    if ctx.engine != ENGINE:
        msg = f"FaultLoom called with a context for engine {ctx.engine!r}"
        raise ValueError(msg)
    if ctx.phase == "main":
        return run_main(ctx)
    if ctx.phase == "claim_pass":
        return run_claim_pass(ctx)
    msg = f"FaultLoom has no phase {ctx.phase!r} (main | claim_pass)"
    raise ValueError(msg)
