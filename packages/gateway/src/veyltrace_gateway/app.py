"""The gateway's FastAPI app (06 §2, §3). X-00: an empty app with `GET /api/v1/health`.

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
from veyltrace_core.pipeline import code_commit
from veyltrace_gateway import __version__
from veyltrace_gateway.api_models import Health, HealthAI, HealthLive
from veyltrace_gateway.settings import GatewaySettings, load_settings

__all__ = ["API_PREFIX", "build_health", "create_app"]

API_PREFIX: Final = "/api/v1"
LLM_SECTION: Final = "llm"


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


def create_app(settings: GatewaySettings | None = None, *, config_dir: Path | None = None) -> FastAPI:
    """The ASGI app; `settings` default to `config/gateway.yaml`."""
    resolved = settings if settings is not None else load_settings(config_dir)
    health = build_health(resolved, load_section_file(LLM_SECTION, config_dir=config_dir), code_commit()[0])
    app = FastAPI(title="Veyltrace gateway", version=__version__, docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.get(f"{API_PREFIX}/health", response_model=Health)
    def get_health() -> Health:
        return health

    return app
