"""Engine entry point of Causentra (registered as `veyltrace.engines:causentra`).

R-00: the package-owned stub (`stub.run`) replaces core's R-02 bootstrap placeholder; R-10 and
R-12 replace the stub with the trials and the decision function (09 §10). The signature
`run(ctx: RunContext) -> EngineResult` is fixed (AGENTS §5).
"""

from veyltrace_causentra import stub
from veyltrace_core.context import EngineResult, RunContext


def run(ctx: RunContext) -> EngineResult:
    """Write verdict.json for this run (R-00 stub: INCONCLUSIVE, no trials; see `stub`)."""
    if ctx.engine != stub.ENGINE:
        msg = f"causentra called with a context for engine {ctx.engine!r}"
        raise ValueError(msg)
    return stub.run(ctx)
