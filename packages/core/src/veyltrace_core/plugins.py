"""Entry-point discovery for engines, adapters, fetchers, rankers, trials, predicates and detectors.

Every pluggable object is declared in its owning package's pyproject.toml, never in a registry
in core (packages/core/AGENTS.md Never 1). Discovery is name-sorted (code-point order) so nothing
downstream depends on sys.path order, and a name claimed twice (two packages, or a stale editable
install next to the current one) is a ConfigError naming the distributions, instead of a silent
sys.path-order pick (critic gap, accepted). `preflight` resolves everything a pipeline run needs
before step 0, so a missing engine or alert detector is a config error (exit 4) and not a
KeyError mid-run.

Not engine-facing: this module imports importlib.metadata, which pulls networking modules into
sys.modules; engines never import it (core_api_spec §0).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from veyltrace_core.errors import ConfigError

if TYPE_CHECKING:
    from veyltrace_core.adapters import DetectAlert
    from veyltrace_core.context import EngineResult, RunContext
    from veyltrace_core.steps import Step

__all__ = [
    "ALERT_DETECTORS",
    "ALERT_DETECTOR_NAME",
    "COMMANDS",
    "ENGINES",
    "GROUPS",
    "EngineFn",
    "Plugin",
    "Preflight",
    "discover",
    "load",
    "load_one",
    "names",
    "natural_key",
    "preflight",
]

ENGINES = "veyltrace.engines"
ADAPTERS = "veyltrace.adapters"
FETCHERS = "veyltrace.fetchers"
RANKERS = "veyltrace.rankers"
TRIALS = "veyltrace.trials"
PREDICATES = "veyltrace.predicates"
ALERT_DETECTORS = "veyltrace.alert_detectors"
COMMANDS = "veyltrace.commands"
#: Every entry-point group Veyltrace defines (core_api_spec §9).
GROUPS: tuple[str, ...] = (
    ENGINES,
    ADAPTERS,
    FETCHERS,
    RANKERS,
    TRIALS,
    PREDICATES,
    ALERT_DETECTORS,
    COMMANDS,
)
#: The one alert detector the detected protocol uses (D-2; Anomara declares it in O-04).
ALERT_DETECTOR_NAME = "default"

#: An engine's `run(ctx) -> EngineResult` (AGENTS §5).
EngineFn = Callable[["RunContext"], "EngineResult"]

_NATURAL_SPLIT = re.compile(r"(\d+)")


@dataclass(frozen=True)
class Plugin:
    """One discovered entry point: its name, `module:attr` value, declaring distribution and a
    loader. Tests build these directly (with a loader returning an in-test object) and patch
    `discover`; real ones come from importlib.metadata via `from_entry_point`."""

    group: str
    name: str
    value: str
    distribution: str | None
    loader: Callable[[], object]

    @classmethod
    def from_entry_point(cls, ep: EntryPoint) -> Plugin:
        """Wrap an importlib.metadata entry point."""
        dist = ep.dist.name if ep.dist is not None else None
        return cls(group=ep.group, name=ep.name, value=ep.value, distribution=dist, loader=ep.load)

    def load(self) -> object:
        """Import and return the object; any import error becomes a ConfigError naming it."""
        try:
            return self.loader()
        except Exception as exc:
            msg = f"cannot load {self.group}:{self.name} = {self.value!r} ({self.distribution}): {exc}"
            raise ConfigError(msg) from exc


def discover(group: str) -> tuple[Plugin, ...]:
    """All entry points of `group` from installed distributions, sorted by (name, value, dist).

    The single seam to importlib.metadata; tests monkeypatch it to register fake plugins.
    """
    if group not in GROUPS:
        msg = f"unknown entry-point group {group!r}; expected one of {', '.join(GROUPS)}"
        raise ConfigError(msg)
    found = [Plugin.from_entry_point(ep) for ep in entry_points(group=group)]
    return tuple(sorted(found, key=lambda p: (p.name, p.value, p.distribution or "")))


def _unique(group: str, plugins: Iterable[Plugin]) -> Mapping[str, Plugin]:
    by_name: dict[str, list[Plugin]] = {}
    for plugin in plugins:
        by_name.setdefault(plugin.name, []).append(plugin)
    clashes = {name: found for name, found in by_name.items() if len(found) > 1}
    if clashes:
        parts = [
            f"{name}: " + ", ".join(f"{p.value} ({p.distribution})" for p in found)
            for name, found in sorted(clashes.items())
        ]
        msg = f"duplicate entry-point names in {group}: " + "; ".join(parts)
        raise ConfigError(msg)
    return {name: found[0] for name, found in sorted(by_name.items())}


def names(group: str) -> tuple[str, ...]:
    """The sorted names registered in `group`, without importing anything (duplicates raise)."""
    return tuple(_unique(group, discover(group)))


def load(group: str) -> dict[str, object]:
    """Load every entry point of `group`, as a dict in code-point name order."""
    return {name: plugin.load() for name, plugin in _unique(group, discover(group)).items()}


def load_one(group: str, name: str) -> object:
    """Load one entry point; ConfigError if `name` is not registered (listing what is)."""
    registered = _unique(group, discover(group))
    plugin = registered.get(name)
    if plugin is None:
        known = ", ".join(registered) or "none"
        msg = f"no entry point {group}:{name} is installed (registered: {known})"
        raise ConfigError(msg)
    return plugin.load()


def natural_key(name: str) -> tuple[tuple[int, int | str], ...]:
    """Sort key that orders digit runs numerically: T1 < T2 < T10 (Causentra trials)."""
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part) for part in _NATURAL_SPLIT.split(name) if part
    )


@dataclass(frozen=True)
class Preflight:
    """Everything a run resolved before step 0: engine callables by entry-point name, and the
    alert detector when the detected protocol needs one."""

    engines: Mapping[str, EngineFn]
    alert_detector: DetectAlert | None


def _callable(group: str, name: str, obj: object) -> Callable[..., object]:
    if not callable(obj):
        msg = f"{group}:{name} must be callable, got {type(obj).__name__}"
        raise ConfigError(msg)
    return obj


def preflight(steps: Iterable[Step], *, ai_mode: str, alert_protocol: str) -> Preflight:
    """Resolve every engine the selected sub-steps run, and the alert detector when needed.

    Relentra is needed only with AI on (02 §4 step 7). The detector `alert_detectors:default` is
    needed only when the alert step runs under the detected protocol; until Anomara registers it
    (O-04) that is a ConfigError, not NoAlert. All missing names are reported at once.
    """
    selected = tuple(steps)
    wanted = sorted(
        {
            s.engine
            for s in selected
            if s.engine is not None and not (s.engine == "relentra" and ai_mode == "off")
        }
    )
    need_detector = alert_protocol == "detected" and any(s.name == "alert" for s in selected)

    engines_found = _unique(ENGINES, discover(ENGINES))
    missing = [f"{ENGINES}:{name}" for name in wanted if name not in engines_found]
    detector_plugin: Plugin | None = None
    if need_detector:
        detector_plugin = _unique(ALERT_DETECTORS, discover(ALERT_DETECTORS)).get(ALERT_DETECTOR_NAME)
        if detector_plugin is None:
            missing.append(
                f"{ALERT_DETECTORS}:{ALERT_DETECTOR_NAME} (the detected alert protocol needs "
                "Anomara's detector, registered from O-04)"
            )
    if missing:
        msg = "the run cannot start; not installed: " + "; ".join(missing)
        raise ConfigError(msg)

    engines: dict[str, EngineFn] = {}
    for name in wanted:
        fn = _callable(ENGINES, name, engines_found[name].load())
        engines[name] = cast("EngineFn", fn)
    detector: DetectAlert | None = None
    if detector_plugin is not None:
        obj = _callable(ALERT_DETECTORS, ALERT_DETECTOR_NAME, detector_plugin.load())
        detector = cast("DetectAlert", obj)
    return Preflight(engines=MappingProxyType(engines), alert_detector=detector)
