"""Engine entry point of Causatrix (registered as `veyltrace.engines:causatrix`).

R-00 stub: reads `evidence`, `graph.nodes`, `graph.edges` and `case_manifest` (07 §2.1) and writes
a schema-valid `slate.json` over the case's candidate universe with no ranker votes
(`veyltrace_causatrix.stub`). R-09 replaces the stub with the six rankers, gated RRF and the rule
table; the signature `run(ctx: RunContext) -> EngineResult` is fixed (AGENTS §5).
"""

from veyltrace_causatrix.stub import run_stub
from veyltrace_core.context import EngineResult, RunContext


def run(ctx: RunContext) -> EngineResult:
    """Pipeline step 6 (R-00 stub): the slate over U, every ranker abstaining (see `stub`)."""
    return run_stub(ctx)
