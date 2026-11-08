"""Engine entry point of Anomara (registered as `veyltrace.engines:anomara`).

R-02 bootstrap stub: the pipeline, the e2e test and the determinism gate need every engine
to resolve before the real one exists (M0 lead decision 2026-11-06, bootstrap).
The Observe lane replaces this module in O-00; the signature
`run(ctx: RunContext) -> EngineResult` is fixed (AGENTS §5).
"""

from veyltrace_core.context import EngineResult, RunContext
from veyltrace_core.stubs import run_stub


def run(ctx: RunContext) -> EngineResult:
    """Stub (R-02 bootstrap): writes schema-valid placeholder outputs.

    The owning lane (Observe) replaces it in O-00.
    """
    return run_stub(ctx, "anomara")
