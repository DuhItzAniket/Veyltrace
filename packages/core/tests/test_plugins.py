"""plugins: sorted discovery, duplicate-name errors, load_one, natural_key and preflight."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from veyltrace_core import plugins
from veyltrace_core.errors import ConfigError
from veyltrace_core.plugins import Plugin
from veyltrace_core.steps import select


def _plugin(group: str, name: str, obj: object, dist: str = "fake-dist") -> Plugin:
    return Plugin(group=group, name=name, value=f"fake:{name}", distribution=dist, loader=lambda: obj)


def _patch(monkeypatch: pytest.MonkeyPatch, table: dict[str, list[Plugin]]) -> None:
    def discover(group: str) -> tuple[Plugin, ...]:
        return tuple(sorted(table.get(group, []), key=lambda p: (p.name, p.value)))

    monkeypatch.setattr(plugins, "discover", discover)


def _fn(name: str) -> Callable[..., object]:
    def run(*_: object) -> str:
        return name

    return run


def test_load_is_name_sorted(monkeypatch: pytest.MonkeyPatch) -> None:
    g = plugins.TRIALS
    _patch(monkeypatch, {g: [_plugin(g, n, n.lower()) for n in ("T2", "T10", "T1")]})
    assert list(plugins.load(g)) == ["T1", "T10", "T2"]  # code-point order
    assert sorted(plugins.load(g), key=plugins.natural_key) == ["T1", "T2", "T10"]
    assert plugins.names(g) == ("T1", "T10", "T2")
    assert plugins.load_one(g, "T2") == "t2"


def test_duplicates_name_both_distributions(monkeypatch: pytest.MonkeyPatch) -> None:
    g = plugins.ALERT_DETECTORS
    _patch(monkeypatch, {g: [_plugin(g, "default", 1, "pkg-a"), _plugin(g, "default", 2, "pkg-b")]})
    with pytest.raises(ConfigError, match=r"duplicate.*default.*pkg-a.*pkg-b"):
        plugins.load(g)


def test_load_one_missing_and_bad_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    g = plugins.RANKERS

    def boom() -> object:
        raise ImportError("no module")

    _patch(monkeypatch, {g: [Plugin(g, "r1", "x:y", "d", boom)]})
    with pytest.raises(ConfigError, match="registered: r1"):
        plugins.load_one(g, "r2")
    with pytest.raises(ConfigError, match="cannot load"):
        plugins.load_one(g, "r1")


def test_real_discovery_is_sorted_and_unknown_group_rejected() -> None:
    found = plugins.discover(plugins.ENGINES)
    assert [p.name for p in found] == sorted(p.name for p in found)
    with pytest.raises(ConfigError, match="unknown entry-point group"):
        plugins.discover("veyltrace.nope")


def test_natural_key() -> None:
    assert sorted(["T10", "T9", "T1", "T2"], key=plugins.natural_key) == ["T1", "T2", "T9", "T10"]


ENGINE_NAMES = (
    "infralume",
    "signalyth",
    "anomara",
    "causync",
    "causalith",
    "faultloom",
    "causatrix",
    "relentra",
    "causentra",
    "causivra",
)


def test_preflight_reports_every_missing_name(monkeypatch: pytest.MonkeyPatch) -> None:
    g = plugins.ENGINES
    _patch(
        monkeypatch, {g: [_plugin(g, n, _fn(n)) for n in ENGINE_NAMES if n not in ("causync", "relentra")]}
    )
    with pytest.raises(ConfigError) as err:
        plugins.preflight(select(), ai_mode="record", alert_protocol="detected")
    text = str(err.value)
    assert "veyltrace.engines:causync" in text
    assert "veyltrace.engines:relentra" in text
    assert "alert_detectors:default" in text


def test_preflight_relentra_only_with_ai_and_detector_only_when_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    g = plugins.ENGINES
    _patch(monkeypatch, {g: [_plugin(g, n, _fn(n)) for n in ENGINE_NAMES if n != "relentra"]})
    pre = plugins.preflight(select(), ai_mode="off", alert_protocol="oracle")
    assert sorted(pre.engines) == sorted(n for n in ENGINE_NAMES if n != "relentra")
    assert pre.alert_detector is None
    # Detected protocol but the alert step is not selected: no detector needed.
    plugins.preflight(select("signalyth"), ai_mode="off", alert_protocol="detected")


def test_preflight_loads_detector_and_rejects_non_callables(monkeypatch: pytest.MonkeyPatch) -> None:
    g, d = plugins.ENGINES, plugins.ALERT_DETECTORS
    detector = _fn("det")
    _patch(monkeypatch, {g: [_plugin(g, "infralume", _fn("i"))], d: [_plugin(d, "default", detector)]})
    pre = plugins.preflight(select("infralume", "alert"), ai_mode="off", alert_protocol="detected")
    assert pre.alert_detector is detector
    _patch(monkeypatch, {g: [_plugin(g, "infralume", 42)]})
    with pytest.raises(ConfigError, match="must be callable"):
        plugins.preflight(select("infralume", "alert"), ai_mode="off", alert_protocol="oracle")
