"""Structured logging for every Veyltrace package: one event per line, on stderr only.

Engines log events with fields (`log.info("drain3_fallback", templates=12)`), not formatted
prose, so bench and CI can grep and parse them. Two rules keep logs out of the determinism
problem (02 §9; packages/core/AGENTS.md Never 2):

- records carry no timestamps, hostnames or user names, so a captured log is itself reproducible;
- logs go to stderr only and never into the run directory: artefacts hold results, not logs.

Built on the standard `logging` module (not logging.config/handlers, which pull networking
modules into sys.modules, 02 §9 isolation), so pytest's caplog and library logs keep working.
Every logger lives under the "veyltrace" namespace; configure() installs the stderr handler and
is called by the CLI, never at import time.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping
from typing import Final, Literal, cast

from veyltrace_core.canonical import JSONValue, canonical_json_str, normalize

__all__ = ["NAMESPACE", "LogFormat", "LogLevel", "StructLogger", "configure", "get_logger"]

NAMESPACE: Final = "veyltrace"
LogLevel = Literal["debug", "info", "warning", "error"]
LogFormat = Literal["json", "text"]

_LEVELS: Final[Mapping[str, int]] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}
# Keys every rendered line has; a field with one of these names is renamed with this prefix.
_RESERVED: Final = frozenset({"event", "level", "logger"})
_FIELD_PREFIX: Final = "field."
# Attribute names used to carry the structured payload on a LogRecord.
_EVENT_ATTR: Final = "veyltrace_event"
_FIELDS_ATTR: Final = "veyltrace_fields"
# Marks the handler configure() installed, so a second call replaces it instead of adding another.
_HANDLER_ATTR: Final = "veyltrace_handler"


def _safe(value: object) -> JSONValue:
    """Normalise a field value; values without a JSON form (paths, exceptions) are logged as str."""
    try:
        return normalize(value)
    except (TypeError, ValueError, RecursionError):
        return str(value)


def _logger_name(name: str) -> str:
    """Map a module or short name into the namespace: "veyltrace_signalyth.api" and "signalyth.api"
    both become "veyltrace.signalyth.api"."""
    if name == NAMESPACE or name.startswith(NAMESPACE + "."):
        return name
    prefix = NAMESPACE + "_"
    if name.startswith(prefix):
        name = name[len(prefix) :]
    return f"{NAMESPACE}.{name}" if name else NAMESPACE


class StructLogger:
    """A logger that emits (event, fields) records; bind() adds fields to every later record."""

    __slots__ = ("_bound", "_logger")

    def __init__(self, logger: logging.Logger, bound: Mapping[str, object] | None = None) -> None:
        self._logger = logger
        self._bound: dict[str, object] = dict(bound or {})

    @property
    def name(self) -> str:
        """The underlying logging name, e.g. "veyltrace.signalyth"."""
        return self._logger.name

    def bind(self, **fields: object) -> StructLogger:
        """Return a logger that adds `fields` (e.g. case_id, step) to every record."""
        return StructLogger(self._logger, {**self._bound, **fields})

    def is_enabled(self, level: LogLevel) -> bool:
        """True if records at `level` would be emitted (skip building costly fields otherwise)."""
        return self._logger.isEnabledFor(_LEVELS[level])

    def debug(self, event: str, /, **fields: object) -> None:
        """Log a debug event."""
        self._emit(logging.DEBUG, event, fields)

    def info(self, event: str, /, **fields: object) -> None:
        """Log an info event."""
        self._emit(logging.INFO, event, fields)

    def warning(self, event: str, /, **fields: object) -> None:
        """Log a warning event (e.g. a fallback an engine also reports in EngineResult.notes)."""
        self._emit(logging.WARNING, event, fields)

    def error(self, event: str, /, *, exc: BaseException | None = None, **fields: object) -> None:
        """Log an error event; `exc` adds an "error" field "<Type>: <message>"."""
        if exc is not None:
            fields = {**fields, "error": f"{type(exc).__name__}: {exc}"}
        self._emit(logging.ERROR, event, fields)

    def _emit(self, level: int, event: str, fields: Mapping[str, object]) -> None:
        if not self._logger.isEnabledFor(level):
            return
        payload = {**self._bound, **fields}
        self._logger.log(level, event, extra={_EVENT_ATTR: event, _FIELDS_ATTR: payload})


def get_logger(name: str) -> StructLogger:
    """Return the structured logger for a package or module, usually get_logger(__name__)."""
    return StructLogger(logging.getLogger(_logger_name(name)))


def _record_parts(record: logging.LogRecord) -> tuple[str, dict[str, JSONValue]]:
    event = getattr(record, _EVENT_ATTR, None)
    raw = getattr(record, _FIELDS_ATTR, None)
    if not isinstance(event, str):
        event = record.getMessage()  # a plain logging call under the namespace
    fields: dict[str, JSONValue] = {}
    if isinstance(raw, Mapping):
        for key, value in cast(Mapping[object, object], raw).items():
            k = str(key)
            fields[_FIELD_PREFIX + k if k in _RESERVED else k] = _safe(value)
    return event, fields


class _Formatter(logging.Formatter):
    """Renders a record as canonical JSON or as `level logger event k=v ...`; never a timestamp."""

    def __init__(self, fmt: LogFormat) -> None:
        super().__init__()
        self._fmt_kind: LogFormat = fmt

    def format(self, record: logging.LogRecord) -> str:
        event, fields = _record_parts(record)
        level = record.levelname.lower()
        if self._fmt_kind == "json":
            return canonical_json_str({**fields, "event": event, "level": level, "logger": record.name})
        pairs = " ".join(f"{k}={canonical_json_str(v)}" for k, v in sorted(fields.items()))
        return f"{level} {record.name} {event}" + (f" {pairs}" if pairs else "")


class _StderrHandler(logging.Handler):
    """Writes to the current sys.stderr at emit time (so stream swaps, e.g. by pytest, are honoured)."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            sys.stderr.write(line + "\n")
            sys.stderr.flush()
        except Exception:
            self.handleError(record)


def configure(*, level: LogLevel = "info", fmt: LogFormat = "json") -> None:
    """Install (or replace) the stderr handler on the "veyltrace" logger and set its level.

    Called by the CLI; libraries and engines never call it. Propagation to the root logger is
    left on, so test log capture still sees every record.
    """
    root = logging.getLogger(NAMESPACE)
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_ATTR, False):
            root.removeHandler(handler)
    handler = _StderrHandler()
    setattr(handler, _HANDLER_ATTR, True)
    handler.setFormatter(_Formatter(fmt))
    root.addHandler(handler)
    root.setLevel(_LEVELS[level])
