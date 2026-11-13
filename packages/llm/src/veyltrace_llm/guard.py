"""The localhost guard (package rule 2; 02 §9; 08 §5.4).

Why: model prompts contain case evidence, and a verdict must never depend on a remote service the
team does not control. A `base_url` whose host is not `localhost`, `127.0.0.1` or `::1` is refused
when the config is loaded, before any connection and without a DNS lookup (a hostname is compared
as text, never resolved), unless the operator sets `VEYLTRACE_ALLOW_REMOTE_LLM=1` for the split
demo. A refusal is a ConfigError, so `diagnose` exits 4 and replay exits 4.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from veyltrace_core.errors import ConfigError

__all__ = ["ALLOW_REMOTE_ENV", "LOOPBACK_HOSTS", "Endpoint", "check_base_url"]

#: The opt-in for a non-loopback endpoint (split demo over LAN, 02 §10).
ALLOW_REMOTE_ENV: Final = "VEYLTRACE_ALLOW_REMOTE_LLM"
#: The only hosts accepted without the opt-in (package rule 2), compared case-insensitively.
LOOPBACK_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1"})
_SCHEMES: Final = {"http": 80, "https": 443}


@dataclass(frozen=True)
class Endpoint:
    """A checked base URL, split for the HTTP transport."""

    scheme: str
    host: str
    port: int
    path: str  # without a trailing slash; "" for the server root

    def url(self, route: str) -> str:
        """`route` (starting with "/") under this endpoint, for audit records and errors."""
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{self.scheme}://{host}:{self.port}{self.path}{route}"


def check_base_url(base_url: str, env: Mapping[str, str] | None = None) -> Endpoint:
    """Parse `base_url` and refuse a non-loopback host unless the opt-in is set (no DNS)."""
    environ = os.environ if env is None else env
    try:
        parts = urlsplit(base_url)
        port = parts.port
    except ValueError as exc:
        raise ConfigError(f"llm.base_url {base_url!r} is not a valid URL: {exc}") from exc
    if parts.scheme not in _SCHEMES or not parts.hostname:
        raise ConfigError(f"llm.base_url must be http(s)://host[:port][/path], got {base_url!r}")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ConfigError(f"llm.base_url may not carry credentials, a query or a fragment: {base_url!r}")
    host = parts.hostname.lower()
    if host not in LOOPBACK_HOSTS and environ.get(ALLOW_REMOTE_ENV) != "1":
        msg = (
            f"llm.base_url host {host!r} is not loopback ({', '.join(sorted(LOOPBACK_HOSTS))}); "
            f"set {ALLOW_REMOTE_ENV}=1 to allow a remote endpoint (split demo only)"
        )
        raise ConfigError(msg)
    return Endpoint(
        scheme=parts.scheme,
        host=host,
        port=port if port is not None else _SCHEMES[parts.scheme],
        path=parts.path.rstrip("/"),
    )
