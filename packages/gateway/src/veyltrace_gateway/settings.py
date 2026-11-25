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

__all__ = ["LOOPBACK_NAMES", "GatewaySettings", "LiveSettings", "check_bind", "is_loopback", "load_settings"]

SECTION: Final = "gateway"
#: Host names that always mean this machine (06 §3.6); IP literals are checked with ipaddress.
LOOPBACK_NAMES: Final = frozenset({"localhost"})
_MAX_PORT: Final = 65535
_MAX_POLL_S: Final = 10  # an event stream that polls less often than this looks stuck


@dataclass(frozen=True)
class LiveSettings:
    """The `live.*` keys of the OTLP receiver and its buffer (06 §3.3, §3.4, §6; X-10)."""

    otlp_host: str
    otlp_port: int
    max_body_mb: int
    buffer_minutes: int
    buffer_max_mb: int
    future_tolerance_s: int
    receiving_s: int
    retry_after_s: int
    snapshot_before_min: int
    ai_modes: tuple[AIMode, ...]


@dataclass(frozen=True)
class GatewaySettings:
    """The gateway keys X-00 reads (06 §6)."""

    host: str
    port: int
    cors_origins: tuple[str, ...]
    default_ai_mode: AIMode
    live_enabled: bool
    page_limit_max: int
    evidence_limit: int
    series_max_points: int
    events_poll_s: float
    live: LiveSettings


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
    limit_max, evidence = _positive(body, "api.page_limit_max"), _positive(body, "api.evidence_limit")
    if evidence > limit_max:
        raise ConfigError(f"gateway.api.evidence_limit {evidence} exceeds api.page_limit_max {limit_max}")
    return GatewaySettings(
        host=host,
        port=port,
        cors_origins=tuple(cast(list[str], origins)),
        default_ai_mode=cast(AIMode, mode),
        live_enabled=live,
        page_limit_max=limit_max,
        evidence_limit=evidence,
        series_max_points=_positive(body, "api.series_max_points"),
        events_poll_s=_poll(body),
        live=_live(body),
    )


def _live(body: Mapping[str, Any]) -> LiveSettings:
    host, port = _get(body, "live.otlp_host"), _get(body, "live.otlp_port")
    if not isinstance(host, str) or not host:
        raise ConfigError(f"gateway.live.otlp_host must be a non-empty string, got {host!r}")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 < port <= _MAX_PORT:
        raise ConfigError(f"gateway.live.otlp_port must be an int in 1..{_MAX_PORT}, got {port!r}")
    return LiveSettings(
        otlp_host=host,
        otlp_port=port,
        max_body_mb=_positive(body, "live.max_body_mb"),
        buffer_minutes=_positive(body, "live.buffer_minutes"),
        buffer_max_mb=_positive(body, "live.buffer_max_mb"),
        future_tolerance_s=_positive(body, "live.future_tolerance_s"),
        receiving_s=_positive(body, "live.receiving_s"),
        retry_after_s=_positive(body, "live.retry_after_s"),
        snapshot_before_min=_positive(body, "live.snapshot_before_min"),
        ai_modes=_live_modes(body),
    )


def _live_modes(body: Mapping[str, Any]) -> tuple[AIMode, ...]:
    """Non-empty, distinct, AI off first (06 §3.4: the AI-off verdict appears first); no replay,
    since a new snapshot has no cassette."""
    modes = _get(body, "live.ai_modes")
    found = tuple(cast(list[object], modes)) if isinstance(modes, list | tuple) else None
    if found not in (("off",), ("off", "record")):
        raise ConfigError(f"gateway.live.ai_modes must be [off] or [off, record], got {modes!r}")
    return cast(tuple[AIMode, ...], found)


def _poll(body: Mapping[str, Any]) -> float:
    workers, poll = _get(body, "jobs.workers"), _get(body, "api.events_poll_s")
    if workers != 1:  # one run at a time: RAM and the single LLM slot (06 §2)
        raise ConfigError(f"gateway.jobs.workers must be 1 in v1, got {workers!r}")
    if isinstance(poll, bool) or not isinstance(poll, int | float) or not 0 < poll <= _MAX_POLL_S:
        raise ConfigError(f"gateway.api.events_poll_s must be in (0, {_MAX_POLL_S}], got {poll!r}")
    return float(poll)


def _positive(body: Mapping[str, Any], dotted: str) -> int:
    value = _get(body, dotted)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"gateway.{dotted} must be an int >= 1, got {value!r}")
    return value


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
