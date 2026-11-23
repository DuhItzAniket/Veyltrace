"""`uv run python -m veyltrace_gateway [--host H] [--port P] [--allow-lan]`: serve the API (06 §2).

Binds `api.host:api.port` from `config/gateway.yaml` (default 127.0.0.1:8000) and, with
`live.enabled`, the OTLP receiver on `live.otlp_host:live.otlp_port` (default 127.0.0.1:4319). A
non-loopback host is refused before any socket is opened unless `--allow-lan` is given, because
v1 has no authentication (06 §3.6). The receiver runs in a daemon thread, so Ctrl+C on the API
server stops both.
"""

from __future__ import annotations

import argparse
import sys
import threading
from collections.abc import Sequence
from dataclasses import replace

from veyltrace_core.errors import ConfigError
from veyltrace_gateway.buffer import LiveBuffer
from veyltrace_gateway.settings import GatewaySettings, check_bind, load_settings


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m veyltrace_gateway", description=__doc__)
    ap.add_argument("--host", help="bind address (default: gateway.api.host)")
    ap.add_argument("--port", type=int, help="port (default: gateway.api.port)")
    ap.add_argument("--allow-lan", action="store_true", help="allow a non-loopback bind (split demo)")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(argv)
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
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return int(exc.exit_code)
    if args.allow_lan:
        print(f"warning: serving on {settings.host}: no authentication in v1", file=sys.stderr)
    import uvicorn

    from veyltrace_gateway.app import create_app

    buffer = _start_receiver(settings) if settings.live_enabled else None
    uvicorn.run(create_app(settings, live=buffer), host=settings.host, port=settings.port)
    return 0


def _start_receiver(settings: GatewaySettings) -> LiveBuffer:
    """Serve the OTLP receiver in a daemon thread; return the buffer it fills."""
    import uvicorn

    from veyltrace_core.config import load_section_file
    from veyltrace_gateway.otlp import create_otlp_app

    live = settings.live
    buffer = LiveBuffer(live.buffer_minutes, live.buffer_max_mb)
    # The converter arrives with O-07 (#24); until then the receiver answers 503.
    app = create_otlp_app(buffer, None, load_section_file("infralume"), max_body_mb=live.max_body_mb)
    server = uvicorn.Server(uvicorn.Config(app, host=live.otlp_host, port=live.otlp_port))
    threading.Thread(target=server.run, name="veyltrace-otlp", daemon=True).start()
    return buffer


if __name__ == "__main__":
    raise SystemExit(main())
