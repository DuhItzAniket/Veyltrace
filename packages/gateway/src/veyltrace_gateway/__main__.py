"""`uv run python -m veyltrace_gateway [--host H] [--port P] [--allow-lan]`: serve the API (06 §2).

Binds `api.host:api.port` from `config/gateway.yaml` (default 127.0.0.1:8000) and, with
`live.enabled`, the OTLP receiver on `live.otlp_host:live.otlp_port` (default 127.0.0.1:4319). A
non-loopback host is refused before any socket is opened unless `--allow-lan` is given, because
v1 has no authentication (06 §3.6). The receiver runs in a daemon thread, so Ctrl+C on the API
server stops both. The receiver decodes OTLP through Infralume's converter
`veyltrace_infralume.otlp` (06 §3.3, O-07), imported at start-up; while it is not installed, start-up
logs `otlp_converter_missing` and the receiver answers 503.
"""

from __future__ import annotations

import argparse
import importlib
import socket
import sys
import threading
from collections.abc import Mapping, Sequence
from dataclasses import replace
from types import ModuleType
from typing import Any, Final, cast

import pyarrow as pa

from veyltrace_core.errors import ConfigError
from veyltrace_core.log import configure as configure_logging
from veyltrace_core.log import get_logger
from veyltrace_gateway.buffer import LiveBuffer
from veyltrace_gateway.otlp import Converts, OtlpConverter, ReceiverCounters
from veyltrace_gateway.settings import GatewaySettings, check_bind, load_settings

#: Infralume's OTLP converter (06 §3.3; 01 §3.9; signatures settled on #24, O-07).
CONVERTER_MODULE: Final = "veyltrace_infralume.otlp"
_CONVERTER_FUNCTIONS: Final = ("spans", "metrics", "logs")
#: An import of the converter that fails on one of these names means O-07 is not installed.
_CONVERTER_PACKAGES: Final = ("veyltrace_infralume", CONVERTER_MODULE)
_LOG: Final = get_logger(__name__)


class _ModuleConverter:
    """The converter module's three functions as the receiver's `OtlpConverter` seam."""

    def __init__(self, module: ModuleType) -> None:
        missing = [n for n in _CONVERTER_FUNCTIONS if not callable(getattr(module, n, None))]
        if missing:
            raise ConfigError(
                f"{module.__name__} has no {', '.join(missing)}(request, settings) (06 §3.3, #24)"
            )
        self._spans = cast(Converts, module.spans)
        self._metrics = cast(Converts, module.metrics)
        self._logs = cast(Converts, module.logs)

    def spans(
        self, request: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> tuple[pa.Table, Mapping[str, int]]:
        return self._spans(request, settings)

    def metrics(
        self, request: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> tuple[pa.Table, Mapping[str, int]]:
        return self._metrics(request, settings)

    def logs(
        self, request: Mapping[str, Any], settings: Mapping[str, Any]
    ) -> tuple[pa.Table, Mapping[str, int]]:
        return self._logs(request, settings)


def load_converter() -> OtlpConverter | None:
    """Infralume's converter, or None while O-07 is not installed (the receiver then answers 503).

    Only the converter module itself being absent means "not installed": a module it imports that
    is missing is a broken install, so that error stops start-up instead of turning into 503s.
    """
    try:
        module = importlib.import_module(CONVERTER_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name not in _CONVERTER_PACKAGES:
            raise
        _LOG.warning(
            "otlp_converter_missing",
            module=CONVERTER_MODULE,
            effect="POST /v1/* answers 503; /api/v1/live/snapshot answers 503 converter_missing",
        )
        return None
    return _ModuleConverter(module)


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m veyltrace_gateway", description=__doc__)
    ap.add_argument("--host", help="bind address (default: gateway.api.host)")
    ap.add_argument("--port", type=int, help="port (default: gateway.api.port)")
    ap.add_argument("--allow-lan", action="store_true", help="allow a non-loopback bind (split demo)")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(argv)
    configure_logging(level="info", fmt="text")  # the defaults of `veyltrace --log-level/--log-format`
    listener: socket.socket | None = None
    converter: OtlpConverter | None = None
    try:
        settings = load_settings()
        settings = replace(
            settings,
            host=args.host if args.host is not None else settings.host,
            port=args.port if args.port is not None else settings.port,
        )
        check_bind(settings.host, allow_lan=args.allow_lan)
        if settings.live_enabled:
            check_bind(settings.live.otlp_host, allow_lan=args.allow_lan)
            if settings.live.otlp_port == settings.port:
                raise ConfigError(f"gateway.live.otlp_port {settings.port} is also the API port")
            converter = load_converter()
            listener = _bind(settings.live.otlp_host, settings.live.otlp_port)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return int(exc.exit_code)
    if args.allow_lan:
        print(f"warning: serving on {settings.host}: no authentication in v1", file=sys.stderr)
    import uvicorn

    from veyltrace_gateway.app import create_app

    buffer, counters = (
        _start_receiver(settings, listener, converter) if listener is not None else (None, None)
    )
    uvicorn.run(create_app(settings, live=buffer, counters=counters), host=settings.host, port=settings.port)
    return 0


def _bind(host: str, port: int) -> socket.socket:
    """Bind in the main thread: a taken port must stop the CLI, not kill the receiver silently."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    try:
        return socket.create_server((host.strip("[]"), port), family=family)
    except OSError as exc:
        raise ConfigError(f"cannot listen for OTLP on {host}:{port}: {exc}") from None


def _start_receiver(
    settings: GatewaySettings, listener: socket.socket, converter: OtlpConverter | None
) -> tuple[LiveBuffer, ReceiverCounters]:
    """Serve the OTLP receiver on `listener` in a daemon thread; return its buffer and counters."""
    import uvicorn

    from veyltrace_core.config import load_section_file
    from veyltrace_gateway.otlp import create_otlp_app

    live = settings.live
    buffer = LiveBuffer(live.buffer_minutes, live.buffer_max_mb, live.future_tolerance_s)
    counters = ReceiverCounters()
    app = create_otlp_app(
        buffer,
        converter,
        load_section_file("infralume"),
        max_body_mb=live.max_body_mb,
        counters=counters,
    )
    server = uvicorn.Server(uvicorn.Config(app, host=live.otlp_host, port=live.otlp_port))
    threading.Thread(target=server.run, args=([listener],), name="veyltrace-otlp", daemon=True).start()
    return buffer, counters


if __name__ == "__main__":
    raise SystemExit(main())
