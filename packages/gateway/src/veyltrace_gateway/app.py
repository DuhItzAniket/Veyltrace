"""The gateway's FastAPI app (06 §2, §3): `GET /api/v1/health` (X-00) and the read-only artifact
routes of finished runs (X-04, `veyltrace_gateway.runs`).

The gateway holds no analysis logic (package rule 1). Health is computed once, when the app is
created, from config and the code commit; a request handler never calls an LLM or starts a run.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from veyltrace_core.config import load_section_file
from veyltrace_core.errors import ConfigError
from veyltrace_core.pipeline import code_commit, runs_root
from veyltrace_gateway import __version__
from veyltrace_gateway.api_models import ErrorBody, Health, HealthAI, HealthLive
from veyltrace_gateway.cases import case_router
from veyltrace_gateway.errors import add_error_handlers
from veyltrace_gateway.jobs import JobRunner
from veyltrace_gateway.runs import run_router
from veyltrace_gateway.settings import GatewaySettings, load_settings
from veyltrace_gateway.submit import submit_router

__all__ = ["API_PREFIX", "build_health", "create_app"]

API_PREFIX: Final = "/api/v1"
LLM_SECTION: Final = "llm"
#: Every API route documents the 06 §3.1 error envelope, so OpenAPI shows the body actually sent.
ERRORS: Final[dict[int | str, dict[str, Any]]] = {c: {"model": ErrorBody} for c in (404, 409, 422, 503)}


def build_health(settings: GatewaySettings, llm: Mapping[str, Any], commit: str) -> Health:
    """The health envelope. Live receiving is false until the OTLP receiver exists (X-10)."""
    provider, model = llm.get("provider"), llm.get("model")
    name = model.get("name") if isinstance(model, Mapping) else None
    if not isinstance(provider, str) or not isinstance(name, str):
        msg = f"config/llm.yaml needs provider and model.name strings, got {provider!r}, {name!r}"
        raise ConfigError(msg)
    return Health(
        status="ok",
        version=__version__,
        code_commit=commit,
        ai=HealthAI(default_mode=settings.default_ai_mode, provider=provider, model=name, reachable=None),
        live=HealthLive(enabled=settings.live_enabled, receiving=False),
    )


def create_app(
    settings: GatewaySettings | None = None,
    *,
    config_dir: Path | None = None,
    runs: Path | None = None,
    jobs: JobRunner | None = None,
) -> FastAPI:
    """The ASGI app; `settings` default to `config/gateway.yaml`, `runs` to core's runs root (the
    directory `run_case` writes, `config/core.yaml` paths.runs), `jobs` to a runner over that root."""
    resolved = settings if settings is not None else load_settings(config_dir)
    health = build_health(resolved, load_section_file(LLM_SECTION, config_dir=config_dir), code_commit()[0])
    app = FastAPI(title="Veyltrace gateway", version=__version__, docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    add_error_handlers(app)

    @app.get(f"{API_PREFIX}/health", response_model=Health)
    def get_health() -> Health:
        return health

    root = runs if runs is not None else runs_root()
    app.include_router(case_router(resolved, root), prefix=API_PREFIX, responses=ERRORS)
    runner = jobs if jobs is not None else JobRunner(root, config_dir=config_dir)
    app.include_router(submit_router(resolved, root, runner), prefix=API_PREFIX, responses=ERRORS)
    app.include_router(run_router(resolved, root, runner), prefix=API_PREFIX, responses=ERRORS)
    return app
