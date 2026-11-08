"""Engine entry point of Causentra (registered as `veyltrace.engines:causentra`).

R-02 bootstrap stub: the pipeline, the e2e test and the determinism gate need every engine
to resolve before the real one exists (M0 lead decision 2026-11-06, bootstrap).
The Reason lane replaces this module in R-00; the signature
`run(ctx: RunContext) -> EngineResult` is fixed (AGENTS §5).
"""

from veyltrace_core.context import EngineResult, RunContext
from veyltrace_core.stubs import run_stub


def run(ctx: RunContext) -> EngineResult:
    """Stub (R-02 bootstrap): writes schema-valid placeholder outputs.

    The owning lane (Reason) replaces it in R-00.
    """
    return run_stub(ctx, "causentra")
