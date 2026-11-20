"""Engine entry point of Relentra (registered as `veyltrace.engines:relentra`).

`brief` mode runs when Relentra is enabled and the slate has candidates (`veyltrace_relentra.brief`).
Otherwise no model is called and `stub` writes the honest `skipped` outputs: AI disabled for this
engine, an empty slate (08 §3.1 step 4), or `investigate` mode, which X-08 adds. The signature
`run(ctx: RunContext) -> EngineResult` is fixed (AGENTS §5).
"""

from veyltrace_contracts import models
from veyltrace_core.context import EngineResult, RunContext
from veyltrace_relentra.brief import run_brief
from veyltrace_relentra.stub import run_stub, settings_from


def run(ctx: RunContext) -> EngineResult:
    """Pipeline step 7."""
    if ctx.ai_mode != "off":
        settings = settings_from(ctx.config)
        slate = ctx.read_model("slate", models.Slate)
        if settings.enabled and settings.mode == "brief" and slate.candidates:
            return run_brief(ctx)
    return run_stub(ctx)
