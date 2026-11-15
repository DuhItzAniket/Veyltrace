"""Gateway settings from `config/gateway.yaml` and the bind rule (06 §3.6, §6).

Why: v1 has no authentication, so the gateway must listen on loopback unless the operator asks for
a LAN bind on purpose (`--allow-lan`, split demo). Every value is checked here, before a socket is
opened, and a bad value is a ConfigError (exit 4), never a silent default.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from veyltrace_core.config import load_section_file
from veyltrace_core.errors import ConfigError
from veyltrace_core.ids import AI_MODES, AIMode

__all__ = ["LOOPBACK_NAMES", "GatewaySettings", "check_bind", "is_loopback", "load_settings"]

SECTION: Final = "gateway"
#: Host names that always mean this machine (06 §3.6); IP literals are checked with ipaddress.
LOOPBACK_NAMES: Final = frozenset({"localhost"})
_MAX_PORT: Final = 65535


@dataclass(frozen=True)
class GatewaySettings:
    """The gateway keys X-00 reads (06 §6)."""

    host: str
    port: int
    cors_origins: tuple[str, ...]
    default_ai_mode: AIMode
    live_enabled: bool


def _get(body: Mapping[str, Any], dotted: str) -> object:
    node: object = body
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            msg = f"config/gateway.yaml: missing key {dotted}"
            raise ConfigError(msg)
        node = cast(Mapping[str, object], node)[part]
    return node


def settings_from(body: Mapping[str, Any]) -> GatewaySettings:
    """Validate the section body; every key is required (no hidden defaults)."""
    host, port = _get(body, "api.host"), _get(body, "api.port")
    origins, mode, live = (
        _get(body, "api.cors_origins"),
        _get(body, "jobs.default_ai_mode"),
        _get(body, "live.enabled"),
    )
    if not isinstance(host, str) or not host:
        raise ConfigError(f"gateway.api.host must be a non-empty string, got {host!r}")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port <= _MAX_PORT:
        raise ConfigError(f"gateway.api.port must be an int in 1..{_MAX_PORT}, got {port!r}")
    if not isinstance(origins, list | tuple) or not all(isinstance(o, str) and o for o in origins):
        raise ConfigError(f"gateway.api.cors_origins must be a list of origins, got {origins!r}")
    if mode not in AI_MODES:
        raise ConfigError(f"gateway.jobs.default_ai_mode must be one of {AI_MODES}, got {mode!r}")
    if not isinstance(live, bool):
        raise ConfigError(f"gateway.live.enabled must be a bool, got {live!r}")
    return GatewaySettings(
        host=host,
        port=port,
        cors_origins=tuple(cast(list[str], origins)),
        default_ai_mode=cast(AIMode, mode),
        live_enabled=live,
    )


def load_settings(config_dir: Path | None = None) -> GatewaySettings:
    """`config/gateway.yaml` (found from the CWD unless `config_dir` is given)."""
    return settings_from(load_section_file(SECTION, config_dir=config_dir))


def is_loopback(host: str) -> bool:
    """True for `localhost` and loopback IP literals (127.0.0.0/8, ::1); no DNS lookup."""
    if host.lower() in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def check_bind(host: str, *, allow_lan: bool) -> None:
    """Refuse a non-loopback bind unless `--allow-lan` was given (06 §3.6)."""
    if not allow_lan and not is_loopback(host):
        msg = f"refusing to bind {host!r}: the gateway has no authentication; pass --allow-lan for a LAN demo"
        raise ConfigError(msg)
