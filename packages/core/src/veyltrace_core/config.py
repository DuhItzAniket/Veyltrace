"""Configuration: resolve config/*.yaml plus overrides into one lock, and build engine views from it.

A run's configuration is one object, `ResolvedConfig`, whose canonical bytes are
`config.lock.json` (03 §12.2). `config_sha256` hashes those bytes and enters `run_id`, so the
lock has to say exactly what the engines computed with. Three rules make that true
(core_api_spec §5; critic gaps "the lock is lossy", "path keys", "config_dir"):

1. **One path for record and replay.** Every `EngineConfig` is built by parsing `lock_bytes()`,
   never from the YAML values directly, so a fresh run and `ResolvedConfig.from_lock` hand the
   engines identical values.
2. **The lock is lossless.** canonical JSON rounds floats to 9 decimals and writes NaN/±inf as
   null, so the loader rejects NaN, ±inf and any float with round(x, 9) != x. Overrides are
   coerced to the base value's type (int widens to float, nothing else changes type), so
   `anomara.slo.k=3` and `=3.0` give the same lock.
3. **The lock is machine-independent.** `core.paths` and every top-level `fetch` subtree are
   environment keys and stay out of the lock, `config/gateway.yaml` never enters it, and
   path-valued keys (`*_path`, `*_dir`, plural forms) must be relative POSIX paths, resolved at
   use time under `data_root()` (D-24).

Config files are parsed from bytes with the YAML 1.2 rules of `veyltrace_core.yaml12` (D-23).
The config directory is the explicit argument, else `$VEYLTRACE_CONFIG_DIR`, else the first
`config/` with a `core.yaml` found walking up from the current directory; its location never
enters the lock. The calibration file is chosen by `veyltrace_core.calibration` (D-8).
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, cast
from urllib.parse import urlsplit

from pydantic import ValidationError

from veyltrace_contracts.models import Calibration, ConfigLock
from veyltrace_contracts.registry import CONTRACTS
from veyltrace_core.calibration import (
    UNCALIBRATED,
    UNCALIBRATED_SHA256,
    CalibrationRef,
    ai_arm_for,
    find_calibration,
    make_family_id,
    parse_json_strict,
    ref_from_lock,
    select_family,
)
from veyltrace_core.canonical import FLOAT_DECIMALS, canonical_json
from veyltrace_core.errors import ArtifactMissing, ConfigError, UsageError
from veyltrace_core.hashing import sha256_bytes, sha256_json
from veyltrace_core.ids import AI_MODES, AIMode
from veyltrace_core.steps import STEPS
from veyltrace_core.textio import read_bytes
from veyltrace_core.yaml12 import load_yaml_bytes, load_yaml_text

__all__ = [
    "CALIBRATION_DIRNAME",
    "CAUSENTRA",
    "CONFIG_DIRNAME",
    "CONFIG_DIR_ENV",
    "CORE",
    "DATA_ENV",
    "DEFAULT_DATA_ROOT",
    "ENGINES",
    "LLM",
    "LOCK_SCHEMA_VERSION",
    "LOCK_SECTIONS",
    "MISSING",
    "PATH_KEY_SUFFIXES",
    "ConfigSource",
    "EngineConfig",
    "FrozenJSON",
    "FrozenValue",
    "ResolvedConfig",
    "check_relative_path",
    "config_sha256",
    "data_path",
    "data_root",
    "env_keys",
    "find_config_dir",
    "load_config",
    "load_section_file",
    "parse_assignment",
    "parse_assignments",
    "resolve_config",
    "section_sha256",
]

#: A config value after freezing: JSON types, with tuples for arrays and read-only mappings.
type FrozenValue = bool | int | float | str | tuple[FrozenValue, ...] | Mapping[str, FrozenValue] | None
#: A frozen config section (values are FrozenValue). Typed as Mapping[str, Any] so engine code under
#: pyright strict can index nested keys without a cast per access.
type FrozenJSON = Mapping[str, Any]

#: Environment variable naming the config directory (critic gap "config_dir is CWD-relative").
CONFIG_DIR_ENV: Final = "VEYLTRACE_CONFIG_DIR"
#: Environment variable naming the data root (02 §4.1); there is deliberately no core.yaml key.
DATA_ENV: Final = "VEYLTRACE_DATA"
#: Data root when VEYLTRACE_DATA is unset (core_api_spec §5).
DEFAULT_DATA_ROOT: Final = "~/veyltrace-data"
#: Directory name searched for when walking up from the current directory.
CONFIG_DIRNAME: Final = "config"
#: Calibration files live in <config_dir>/calibration/ (03 §12.1; packages/core/AGENTS.md).
CALIBRATION_DIRNAME: Final = "calibration"
_CORE_FILE = "core.yaml"
_YAML_SUFFIX = ".yaml"

#: Section names (= file stems, core_api_spec §5): core, the ten engines in pipeline order, llm.
CORE: Final = "core"
LLM: Final = "llm"
#: The engine whose EngineConfig carries the calibration content (core_api_spec §5).
CAUSENTRA: Final = "causentra"
ENGINES: tuple[str, ...] = tuple(dict.fromkeys(s.engine for s in STEPS if s.engine is not None))
#: Every section in config.lock.json (03 §12.2); gateway.yaml is loaded only by the gateway.
LOCK_SECTIONS: tuple[str, ...] = (CORE, *ENGINES, LLM)
#: config_lock schema version stamped into the lock.
LOCK_SCHEMA_VERSION: Final = CONTRACTS["config_lock"].version

#: Key-name suffixes of path-valued keys in lock-bound sections (critic gap "path keys"): their
#: values must be null or relative POSIX paths (infralume.events.overlay_path, anomara.tsfm.
#: weights_path, causalith.topology.static_path, causivra.signing.public_key_path, ...).
PATH_KEY_SUFFIXES: tuple[str, ...] = ("_path", "_paths", "_dir", "_dirs")
# Environment subtrees kept out of the lock (D-24): a `fetch` subtree at any depth (dataset
# download settings, e.g. infralume.sources.fetch), and the top-level `paths` subtree of core only:
# causalith.paths.* (k, max_len, ...) are analysis keys (05-causalith §4) and must be locked.
_ENV_KEY_FETCH = "fetch"
_ENV_KEY_PATHS = "paths"
# Strings that are machine paths whatever their key: POSIX/UNC absolute, home-relative, a drive.
_ABSOLUTE_PATH_RE = re.compile(r"(?:/|\\\\|~[/\\]|[A-Za-z]:[/\\])")

# 03 §1 "Name patterns": dataset.
_DATASET_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# A Windows drive prefix such as "C:".
_DRIVE_RE = re.compile(r"[A-Za-z]:")
_SECTION_NAME_RE = re.compile(r"[a-z][a-z0-9_]*")
_EMPTY: Mapping[str, Any] = MappingProxyType({})
# An override key names a section and at least one key inside it.
_MIN_KEY_PARTS = 2


class _Missing:
    """Type of MISSING, the 'no default' marker of EngineConfig.get_path."""

    def __repr__(self) -> str:
        return "MISSING"


#: Marker for "no default given" in EngineConfig.get_path.
MISSING: Final = _Missing()


# ---------------------------------------------------------------------------------------------
# Plain-JSON trees: thawed (dict/list, used while resolving) and frozen (MappingProxy/tuple).


def _kind(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list | tuple):
        return "list"
    if isinstance(value, Mapping):
        return "map"
    return type(value).__name__


def _to_tree(value: object, where: str) -> Any:
    """Return `value` as a thawed JSON tree (dict/list/scalars); ConfigError for anything else."""
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in cast(Mapping[object, object], value).items():
            if not isinstance(key, str):
                msg = f"{where}: config keys must be strings, got {key!r}"
                raise ConfigError(msg)
            out[key] = _to_tree(item, f"{where}.{key}")
        return out
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        return [_to_tree(item, f"{where}[{i}]") for i, item in enumerate(cast(Sequence[object], value))]
    msg = f"{where}: {type(value).__name__} is not a JSON value"
    raise ConfigError(msg)


def _freeze(value: Any) -> FrozenValue:
    """Return a thawed tree as read-only mappings (keys sorted) and tuples."""
    if isinstance(value, Mapping):
        items = cast(Mapping[str, Any], value)
        return MappingProxyType({k: _freeze(items[k]) for k in sorted(items)})
    if isinstance(value, list | tuple):
        return tuple(_freeze(v) for v in cast(Sequence[Any], value))
    return cast(FrozenValue, value)


def _freeze_map(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], _freeze(value))


def check_relative_path(value: str, where: str) -> str:
    """Return `value` if it is a relative POSIX path that stays under its root; else ConfigError.

    Rejected: empty, backslashes, absolute paths, drive letters, `~`, `$` variables, empty
    segments and `..` (critic gap "path keys": machine paths must never reach the lock).
    """
    bad = (
        not value
        or "\\" in value
        or value.startswith(("/", "~"))
        or _DRIVE_RE.match(value) is not None
        or "$" in value
        or any(seg in ("", "..") for seg in value.split("/"))
    )
    if bad:
        msg = f"{where}: {value!r} must be a relative POSIX path (no backslash, leading / or ~, $ or ..)"
        raise ConfigError(msg)
    return value


def _is_path_key(key: str) -> bool:
    return key.endswith(PATH_KEY_SUFFIXES)


def _check_lock_value(value: Any, where: str, *, path_key: bool = False) -> None:
    """Check one lock-bound value: lossless floats, relative POSIX paths in path keys."""
    if isinstance(value, float):
        if not math.isfinite(value):
            msg = f"{where}: NaN and ±inf are not allowed in config (canonical JSON writes them as null)"
            raise ConfigError(msg)
        if round(value, FLOAT_DECIMALS) != value:
            msg = f"{where}: {value!r} has more than {FLOAT_DECIMALS} decimals and would change in the lock"
            raise ConfigError(msg)
    if isinstance(value, Mapping):
        items = cast(Mapping[str, Any], value)
        for key in sorted(items):
            _check_lock_value(items[key], f"{where}.{key}", path_key=_is_path_key(key))
    elif isinstance(value, list | tuple):
        for i, item in enumerate(cast(Sequence[Any], value)):
            _check_lock_value(item, f"{where}[{i}]", path_key=path_key)
    elif path_key and value is not None:
        if not isinstance(value, str):
            msg = f"{where}: a path key holds a string or null, got {_kind(value)}"
            raise ConfigError(msg)
        check_relative_path(value, where)
    elif isinstance(value, str):
        _check_lock_string(value, where)


def _check_lock_string(value: str, where: str) -> None:
    """No secrets or machine paths in the lock under any key (it is copied into the receipt):
    URLs carrying user:password, and absolute paths (/x, ~/x, C:/x, UNC)."""
    if "://" in value:
        try:
            parts = urlsplit(value)
            userinfo = parts.username is not None or parts.password is not None
        except ValueError:
            userinfo = "@" in value.split("://", 1)[1].split("/", 1)[0]
        if userinfo:
            msg = f"{where}: a URL with credentials must not enter config.lock.json; pass them by environment"
            raise ConfigError(msg)
    elif _ABSOLUTE_PATH_RE.match(value) is not None:
        msg = f"{where}: {value!r} looks like a machine path; lock-bound values must be relative"
        raise ConfigError(msg)


def env_keys(section: str) -> tuple[str, ...]:
    """Top-level keys of `section` that are environment, not config, and never enter the lock.
    (A `fetch` key is environment at any depth too; see _split_environment.)"""
    return (_ENV_KEY_FETCH, _ENV_KEY_PATHS) if section == CORE else (_ENV_KEY_FETCH,)


def _pop_nested_fetch(body: dict[str, Any], prefix: str, environment: dict[str, Any]) -> None:
    """Move every nested `fetch` subtree of `body` into `environment` (keyed by dotted path)."""
    for key in sorted(body):
        value = body[key]
        if not isinstance(value, Mapping):
            continue
        child = dict(cast(Mapping[str, Any], value))
        if _ENV_KEY_FETCH in child:
            environment[f"{prefix}.{key}.{_ENV_KEY_FETCH}"] = child.pop(_ENV_KEY_FETCH)
        _pop_nested_fetch(child, f"{prefix}.{key}", environment)
        body[key] = child


def _split_environment(tree: Mapping[str, Mapping[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a full tree into (lock sections, environment keyed "<section>.<key>")."""
    sections: dict[str, Any] = {}
    environment: dict[str, Any] = {}
    for name in sorted(tree):
        body = dict(tree[name])
        for key in env_keys(name):
            if key in body:
                environment[f"{name}.{key}"] = body.pop(key)
        _pop_nested_fetch(body, name, environment)
        sections[name] = body
    return sections, environment


# ---------------------------------------------------------------------------------------------
# Overrides


def _coerce(base: Any, new: Any, where: str) -> Any:
    """Return `new` in the base value's type: same kind, or int widened to float (critic gap
    "the lock is lossy"). A null base accepts any value; a map keeps base types for its old keys."""
    if base is None:
        return new
    base_kind, new_kind = _kind(base), _kind(new)
    if base_kind == "float" and new_kind == "int":
        widened = float(new)
        if widened != new:
            msg = f"{where}: {new} cannot be represented exactly as a float"
            raise ConfigError(msg)
        return widened
    if base_kind != new_kind:
        msg = f"{where}: expected {base_kind} like the base config, got {new_kind} ({new!r})"
        raise ConfigError(msg)
    if base_kind == "list":
        base_items = cast(list[Any], base)
        kinds = {_kind(v) for v in base_items}
        if len(kinds) == 1:  # homogeneous base list: its elements are the template
            return [_coerce(base_items[0], v, f"{where}[{i}]") for i, v in enumerate(cast(list[Any], new))]
        return new
    if base_kind == "map":
        base_map, new_map = cast(dict[str, Any], base), cast(dict[str, Any], new)
        return {
            k: _coerce(base_map[k], v, f"{where}.{k}") if k in base_map else v for k, v in new_map.items()
        }
    return new


def _as_dict(value: object) -> dict[str, Any] | None:
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _apply_overrides(tree: dict[str, Any], overrides: Mapping[str, object]) -> None:
    """Apply dotted, section-qualified overrides in place (core_api_spec §5 "Overrides").

    The key must exist in the base tree, and its value is replaced whole (lists and maps are not
    merged). Overlapping keys (`a.b` and `a.b.c`) are an error rather than order-dependent.
    """
    keys: list[str] = []
    for key in overrides:
        if not isinstance(key, str):  # pyright: ignore[reportUnnecessaryIsInstance]  # callers pass untyped YAML
            msg = f"override keys must be strings, got {key!r}"
            raise ConfigError(msg)
        keys.append(key)
    key_set = set(keys)
    for key in sorted(keys):
        parts = key.split(".")
        if len(parts) < _MIN_KEY_PARTS or any(not p for p in parts):
            msg = f"override {key!r}: expected <section>.<key>[.<key>...]"
            raise ConfigError(msg)
        for i in range(1, len(parts)):
            prefix = ".".join(parts[:i])
            if prefix in key_set:
                msg = f"overrides {prefix!r} and {key!r} overlap; set one of them"
                raise ConfigError(msg)
        parent = _as_dict(tree.get(parts[0]))
        if parent is None:
            known = ", ".join(sorted(tree))
            msg = f"override {key!r}: unknown section {parts[0]!r} (known: {known})"
            raise ConfigError(msg)
        for part in parts[1:-1]:
            child = _as_dict(parent.get(part))
            if child is None:
                msg = f"override {key!r}: unknown key (no mapping {part!r} in the base config)"
                raise ConfigError(msg)
            parent = child
        leaf = parts[-1]
        if leaf not in parent:
            msg = f"override {key!r}: unknown key (add it with a default to config/{parts[0]}.yaml first)"
            raise ConfigError(msg)
        parent[leaf] = _coerce(parent[leaf], _to_tree(overrides[key], key), key)


def parse_assignment(text: str) -> tuple[str, FrozenValue]:
    """Parse one CLI `--set key=value`; the value is YAML 1.2 (`3`, `0.5`, `off`, `[a, b]`, `null`).

    Raises UsageError for a malformed assignment (diagnose exit 2).
    """
    key, sep, raw = text.partition("=")
    key = key.strip()
    if not sep or not key:
        msg = f"--set expects key=value, got {text!r}"
        raise UsageError(msg)
    try:
        value = load_yaml_text(raw, source=f"--set {key}")
        return key, _freeze(_to_tree(value, key))
    except ConfigError as exc:
        raise UsageError(str(exc)) from exc


def parse_assignments(texts: Sequence[str]) -> dict[str, FrozenValue]:
    """Parse several `--set` values into an overrides mapping; a repeated key is a UsageError."""
    out: dict[str, FrozenValue] = {}
    for text in texts:
        key, value = parse_assignment(text)
        if key in out:
            msg = f"--set {key} given twice"
            raise UsageError(msg)
        out[key] = value
    return out


# ---------------------------------------------------------------------------------------------
# Files and directories


def find_config_dir(start: Path | None = None) -> Path:
    """Return the absolute config directory: `$VEYLTRACE_CONFIG_DIR`, else the first
    `<dir>/config/` holding core.yaml walking up from `start` (default: the current directory).

    Raises ConfigError if neither exists, so a run from the wrong directory fails loudly instead
    of reading another checkout's config.
    """
    env = os.environ.get(CONFIG_DIR_ENV, "")
    if env:
        directory = Path(env).expanduser().resolve()
        if not (directory / _CORE_FILE).is_file():
            msg = f"{CONFIG_DIR_ENV}={env!r} has no {_CORE_FILE}"
            raise ConfigError(msg)
        return directory
    here = (start if start is not None else Path.cwd()).resolve()
    for parent in (here, *here.parents):
        candidate = parent / CONFIG_DIRNAME
        if (candidate / _CORE_FILE).is_file():
            return candidate
    msg = f"no {CONFIG_DIRNAME}/{_CORE_FILE} found in {here} or its parents; set {CONFIG_DIR_ENV}"
    raise ConfigError(msg)


def _config_dir(config_dir: Path | None) -> Path:
    if config_dir is None:
        return find_config_dir()
    directory = Path(config_dir).resolve()
    if not (directory / _CORE_FILE).is_file():
        msg = f"config directory {directory} has no {_CORE_FILE}"
        raise ConfigError(msg)
    return directory


def _load_file(directory: Path, name: str) -> dict[str, Any]:
    """Load `<directory>/<name>.yaml` as a thawed section body (an empty file is `{}`)."""
    if _SECTION_NAME_RE.fullmatch(name) is None:
        msg = f"invalid config section name {name!r}"
        raise ConfigError(msg)
    path = directory / f"{name}{_YAML_SUFFIX}"
    try:
        data = read_bytes(path)
    except OSError as exc:
        msg = f"cannot read config file {path}: {exc}"
        raise ConfigError(msg) from exc
    body = load_yaml_bytes(data, source=f"config/{path.name}")
    if body is None:
        return {}
    if not isinstance(body, Mapping):
        msg = f"config/{path.name}: the top level must be a mapping (the section body), got {_kind(body)}"
        raise ConfigError(msg)
    return cast(dict[str, Any], _to_tree(cast(Mapping[str, Any], body), name))


def load_section_file(name: str, *, config_dir: Path | None = None) -> FrozenJSON:
    """Return one config file as a frozen mapping, environment keys included.

    For consumers outside the lock: the gateway (`gateway.yaml`, 06 §6) and fetchers reading a
    `fetch` subtree. Engines never call it; they get their config from ctx.config.
    """
    return _freeze_map(_load_file(_config_dir(config_dir), name))


def data_root() -> Path:
    """Return the absolute data root: `$VEYLTRACE_DATA`, else ~/veyltrace-data (core_api_spec §5).

    Resolved at call time, never stored in the lock. Raises ConfigError if the root lies inside a
    git work tree (a directory with `.git` at or above it), because caches and answer keys written
    there would mark the tree dirty or be committed (01 §3.11; AGENTS Never 6).
    """
    raw = os.environ.get(DATA_ENV, "") or DEFAULT_DATA_ROOT
    try:
        root = Path(raw).expanduser().resolve()
    except RuntimeError as exc:  # expanduser without a home directory
        msg = f"cannot resolve the data root {raw!r}: {exc}"
        raise ConfigError(msg) from exc
    for parent in (root, *root.parents):
        if (parent / ".git").exists():
            msg = f"data root {root} is inside the git work tree {parent}; set {DATA_ENV} outside it"
            raise ConfigError(msg)
    return root


def data_path(relpath: str) -> Path:
    """Resolve a path-valued config key (a relative POSIX path) under data_root() at use time."""
    check_relative_path(relpath, "data path")
    return data_root().joinpath(*relpath.split("/"))


# ---------------------------------------------------------------------------------------------
# Resolved config and engine views


@dataclass(frozen=True)
class ConfigSource:
    """Where a ResolvedConfig came from; None on a config rebuilt from a lock. Never in the lock."""

    config_dir: Path
    dataset: str | None
    ai_mode: AIMode


def _calibration_inputs(sections: Mapping[str, Any]) -> bytes:
    """Canonical bytes of every key the calibration choice depends on."""
    causentra = cast(Mapping[str, Any], sections.get(CAUSENTRA, _EMPTY))
    relentra = cast(Mapping[str, Any], sections.get("relentra", _EMPTY))
    alert = cast(Mapping[str, Any], cast(Mapping[str, Any], sections.get(CORE, _EMPTY)).get("alert", _EMPTY))
    return canonical_json(
        [
            _to_tree(causentra.get("calibration"), "causentra.calibration"),
            _to_tree(alert.get("protocol"), "core.alert.protocol"),
            _to_tree(relentra.get("mode"), "relentra.mode"),
            _to_tree(relentra.get("enabled"), "relentra.enabled"),
        ]
    )


def _select_calibration(sections: Mapping[str, Any], source: ConfigSource) -> CalibrationRef | None:
    """Choose and load the run's calibration file (core_api_spec §5 "Calibration selection")."""
    if source.dataset is None:
        return None
    cal: object = cast(Mapping[str, Any], sections[CAUSENTRA]).get("calibration")
    if not isinstance(cal, Mapping):
        msg = "causentra.calibration must be a mapping with family, family_map and fold"
        raise ConfigError(msg)
    cal_map = cast(Mapping[str, Any], cal)
    family_map: object = cal_map.get("family_map", _EMPTY)
    if not isinstance(family_map, Mapping):
        msg = "causentra.calibration.family_map must be a mapping"
        raise ConfigError(msg)
    family = select_family(source.dataset, cal_map.get("family"), cast(Mapping[str, Any], family_map))
    if family is None:
        return None
    arm = ai_arm_for(source.ai_mode, cast(Mapping[str, Any], sections["relentra"]))
    if arm is None:
        return None
    alert = cast(Mapping[str, Any], cast(Mapping[str, Any], sections[CORE]).get("alert", _EMPTY))
    protocol: object = alert.get("protocol")
    fold: object = cal_map.get("fold")
    if not isinstance(protocol, str) or not isinstance(fold, str):
        msg = "core.alert.protocol and causentra.calibration.fold must be strings"
        raise ConfigError(msg)
    family_id = make_family_id(family, arm, protocol, fold)
    return find_calibration(
        source.config_dir / CALIBRATION_DIRNAME, family_id, ai_arm=arm, alert_protocol=protocol
    )


def _parse_lock(data: bytes, where: str) -> dict[str, Any]:
    obj = parse_json_strict(data, where=where)
    if not isinstance(obj, dict):
        msg = f"{where}: the lock must be a JSON object"
        raise ConfigError(msg)
    return cast(dict[str, Any], obj)


@dataclass(frozen=True, eq=False)
class ResolvedConfig:
    """The fully resolved configuration of one run: lock sections, calibration, environment.

    `sections` holds core, the ten engines and llm, exactly as parsed back from `lock_bytes()`.
    `environment` holds the keys kept out of the lock (`core.paths`, `<section>.fetch`), keyed
    "<section>.<key>"; it is empty on a config rebuilt with from_lock. Two ResolvedConfigs are
    equal when their lock bytes are equal.
    """

    sections: Mapping[str, FrozenJSON]
    calibration: CalibrationRef | None = None
    environment: Mapping[str, Any] = field(default=_EMPTY)
    source: ConfigSource | None = None
    _lock: bytes = field(init=False, repr=False, default=b"")

    def __post_init__(self) -> None:
        names = sorted(self.sections)
        if names != sorted(LOCK_SECTIONS):
            msg = (
                f"config sections must be exactly {', '.join(sorted(LOCK_SECTIONS))}; got {', '.join(names)}"
            )
            raise ConfigError(msg)
        tree: dict[str, Any] = {}
        for name in names:
            body = cast(dict[str, Any], _to_tree(self.sections[name], name))
            leaked = [key for key in env_keys(name) if key in body]
            if leaked:
                msg = f"{name}.{leaked[0]} is an environment subtree and cannot enter the lock"
                raise ConfigError(msg)
            _check_lock_value(body, name)
            tree[name] = body
        lock = {
            "schema_version": LOCK_SCHEMA_VERSION,
            "sections": tree,
            "calibration": None if self.calibration is None else self.calibration.lock_object(),
        }
        data = canonical_json(lock) + b"\n"
        parsed = _parse_lock(data, "config lock")
        object.__setattr__(self, "sections", _freeze_map(cast(dict[str, Any], parsed["sections"])))
        object.__setattr__(self, "environment", _freeze_map(_to_tree(self.environment, "environment")))
        object.__setattr__(self, "_lock", data)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ResolvedConfig) and other._lock == self._lock

    def __hash__(self) -> int:
        return hash(self._lock)

    def lock_bytes(self) -> bytes:
        """The bytes of config.lock.json: canonical JSON of the lock object plus LF (D-11)."""
        return self._lock

    def engine(self, name: str) -> EngineConfig:
        """Return the read-only config view of one section, built by parsing lock_bytes()."""
        parsed = _parse_lock(self._lock, "config lock")
        sections = cast(dict[str, Any], parsed["sections"])
        if name not in sections:
            msg = f"no config section {name!r}; sections are {', '.join(sorted(sections))}"
            raise ConfigError(msg)
        cal: object = parsed["calibration"]
        ref = None if cal is None else ref_from_lock(cast(Mapping[str, Any], cal))
        return EngineConfig(resolved=self, engine=name, sections=_freeze_map(sections), calibration=ref)

    def with_overrides(self, overrides: Mapping[str, object]) -> ResolvedConfig:
        """Return a copy with more overrides applied (same rules as resolve_config).

        The calibration is chosen again when the source is known. On a config rebuilt from a lock
        it is kept, and an override that would change the choice is a ConfigError.
        """
        if not overrides:
            return self
        tree = cast(dict[str, Any], _to_tree(self.sections, "sections"))
        for env_key, value in self.environment.items():
            section, _, key = env_key.partition(".")
            tree[section][key] = _to_tree(value, env_key)
        _apply_overrides(tree, overrides)
        sections, environment = _split_environment(tree)
        if self.source is not None:
            calibration = _select_calibration(sections, self.source)
        elif _calibration_inputs(sections) != _calibration_inputs(self.sections):
            msg = "cannot change calibration selection keys on a config rebuilt from a lock"
            raise ConfigError(msg)
        else:
            calibration = self.calibration
        return ResolvedConfig(sections, calibration, environment, self.source)

    @classmethod
    def from_lock_bytes(cls, data: bytes, *, where: str = "config.lock.json") -> ResolvedConfig:
        """Rebuild a ResolvedConfig from lock bytes; the bytes must be canonical."""
        obj = _parse_lock(data, where)
        try:
            ConfigLock.model_validate(obj)
        except ValidationError as exc:
            msg = f"{where}: not a valid config lock: {exc}"
            raise ConfigError(msg) from exc
        cal: object = obj["calibration"]
        ref = None if cal is None else ref_from_lock(cast(Mapping[str, Any], cal))
        resolved = cls(sections=cast(dict[str, Any], obj["sections"]), calibration=ref)
        if resolved.lock_bytes() != data:
            msg = f"{where}: bytes are not the canonical lock form (re-serialised or hand-edited)"
            raise ConfigError(msg)
        return resolved

    @classmethod
    def from_lock(cls, path: Path) -> ResolvedConfig:
        """Rebuild the run's config from its config.lock.json (replay); never reads config/."""
        try:
            data = read_bytes(path)
        except FileNotFoundError as exc:
            raise ArtifactMissing("config_lock", path) from exc
        return cls.from_lock_bytes(data, where=str(path))


class EngineConfig(Mapping[str, Any]):
    """Read-only view of one config section (ctx.config), plus cross-section access (D-7).

    Mapping access reads the engine's own section (`cfg["duckdb"]["threads"]`); attributes carry
    the core section, the calibration and access to any other lock section. Built only by
    ResolvedConfig.engine, i.e. from the lock bytes.
    """

    __slots__ = ("_calibration", "_engine", "_own", "_resolved", "_sections")

    def __init__(
        self,
        *,
        resolved: ResolvedConfig,
        engine: str,
        sections: Mapping[str, Any],
        calibration: CalibrationRef | None,
    ) -> None:
        self._resolved = resolved
        self._engine = engine
        self._sections = sections
        self._own = cast(Mapping[str, Any], sections[engine])
        self._calibration = calibration

    def __getitem__(self, key: str) -> Any:
        return self._own[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._own)

    def __len__(self) -> int:
        return len(self._own)

    def __repr__(self) -> str:
        keys = sorted(self._own)
        return f"EngineConfig({self._engine!r}, keys={keys!r}, calibration={self.calibration_family!r})"

    @property
    def engine(self) -> str:
        """The section this view reads (engine entry-point name, or "core"/"llm")."""
        return self._engine

    @property
    def core(self) -> FrozenJSON:
        """The core section (alert, windows, thresholds, universe)."""
        return self.section(CORE)

    @property
    def calibration(self) -> Calibration | None:
        """The calibration file content for Causentra; None for other engines and when uncalibrated."""
        if self._engine != CAUSENTRA or self._calibration is None:
            return None
        return self._calibration.content

    @property
    def calibration_family(self) -> str:
        """The calibration family_id, or "uncalibrated" (02 §6.9)."""
        return UNCALIBRATED if self._calibration is None else self._calibration.family_id

    @property
    def calibration_sha256(self) -> str:
        """The calibration file's SHA-256, or the uncalibrated sentinel (03 §12)."""
        return UNCALIBRATED_SHA256 if self._calibration is None else self._calibration.sha256

    def section(self, name: str) -> FrozenJSON:
        """Read-only view of any lock section (D-7), e.g. Anomara reading causalith entry.*."""
        found: object = self._sections.get(name)
        if found is None:
            msg = f"no config section {name!r}"
            raise ConfigError(msg)
        return cast(FrozenJSON, found)

    def get_path(self, dotted: str, default: Any = MISSING) -> Any:
        """Return the value at a dotted path in the own section; ConfigError if absent and no default."""
        node: Any = self._own
        for part in dotted.split("."):
            if not isinstance(node, Mapping) or part not in node:
                if default is MISSING:
                    msg = f"{self._engine}.{dotted}: no such config key"
                    raise ConfigError(msg)
                return default
            node = cast(Mapping[str, Any], node)[part]
        return node

    def for_engine(self, name: str) -> EngineConfig:
        """The view of another section from the same lock (RunContext.with_config)."""
        return self._resolved.engine(name)


# ---------------------------------------------------------------------------------------------
# Entry points


def resolve_config(
    overrides: Mapping[str, object] = _EMPTY,
    *,
    config_dir: Path | None = None,
    dataset: str | None = None,
    ai_mode: AIMode,
) -> ResolvedConfig:
    """Resolve config/*.yaml plus overrides into the run's ResolvedConfig.

    `dataset` (03 §1 pattern) enables the calibration choice; `ai_mode` only decides whether the
    calibration ai_arm is "off" or relentra.mode, so record and replay share one lock.
    Raises ConfigError for any invalid file, key, value or calibration file.
    """
    if ai_mode not in AI_MODES:
        msg = f"ai_mode {ai_mode!r} is not one of {', '.join(AI_MODES)}"
        raise ConfigError(msg)
    if dataset is not None and _DATASET_RE.fullmatch(dataset) is None:
        msg = f"dataset {dataset!r} must match {_DATASET_RE.pattern}"
        raise ConfigError(msg)
    directory = _config_dir(config_dir)
    tree: dict[str, Any] = {name: _load_file(directory, name) for name in LOCK_SECTIONS}
    _apply_overrides(tree, overrides)
    sections, environment = _split_environment(tree)
    source = ConfigSource(config_dir=directory, dataset=dataset, ai_mode=ai_mode)
    return ResolvedConfig(sections, _select_calibration(sections, source), environment, source)


def load_config(
    engine: str,
    overrides: Mapping[str, object] = _EMPTY,
    *,
    config_dir: Path | None = None,
    dataset: str | None = None,
    ai_mode: AIMode = "off",
) -> EngineConfig:
    """Shortcut for resolve_config(...).engine(engine), for tools and tests outside a run."""
    return resolve_config(overrides, config_dir=config_dir, dataset=dataset, ai_mode=ai_mode).engine(engine)


def config_sha256(resolved: ResolvedConfig) -> str:
    """SHA-256 of config.lock.json (run_manifest.config_sha256; enters run_id)."""
    return sha256_bytes(resolved.lock_bytes())


def section_sha256(resolved: ResolvedConfig, section: str) -> str:
    """SHA-256 of one section's canonical JSON (e.g. Causentra's params_sha256)."""
    if section not in resolved.sections:
        msg = f"no config section {section!r}"
        raise ConfigError(msg)
    return sha256_json(resolved.sections[section])
