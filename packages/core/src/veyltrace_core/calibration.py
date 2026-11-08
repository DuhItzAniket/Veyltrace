"""Calibration files: naming, selection, strict loading and the uncalibrated sentinel.

Bench fits Causentra's conformal threshold q_hat and NO_FAULT threshold tau_nf on calibration
splits and writes one file per combination to `config/calibration/<family_id>.json`, where
family_id = `<benchmark family>.<ai_arm>.<alert_protocol>.<fold>` (03 §12.1; core_api_spec D-8).
Causentra reads the content through `ctx.config.calibration`; engines never open the file.

Byte rules (critic gap "replay reads the wrong calibration source"): a calibration file is
exactly `canonical_json(content) + b"\\n"`, where content is the validated `Calibration` model.
The loader rejects any other bytes (CRLF, other key order, ints where the schema has floats), so
the file hash is a function of the content alone. The lock stores the content and that hash, and
replay re-checks the hash from the lock content without opening `config/calibration/`.

Without a file the run is uncalibrated: family "uncalibrated" and the sentinel hash
`sha256_json({"family": "uncalibrated"})`, the same value as verdict.calibration.sha256 and
run_manifest.calibration_sha256 (02 §6.9; 03 §12).
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

from pydantic import ValidationError

from veyltrace_contracts.models import AiArm, AlertProtocol, Calibration, FamilyId
from veyltrace_core.canonical import JSONValue, canonical_json
from veyltrace_core.errors import ConfigError
from veyltrace_core.hashing import sha256_bytes, sha256_json
from veyltrace_core.ids import AIMode
from veyltrace_core.textio import read_bytes, write_bytes

__all__ = [
    "AI_ARMS",
    "ALERT_PROTOCOLS",
    "CALIBRATION_SUFFIX",
    "UNCALIBRATED",
    "UNCALIBRATED_SHA256",
    "CalibrationRef",
    "ai_arm_for",
    "calibration_bytes",
    "calibration_path",
    "find_calibration",
    "is_family_id",
    "load_calibration",
    "make_family_id",
    "parse_json_strict",
    "ref_from_lock",
    "select_family",
    "write_calibration",
]

#: verdict.calibration.family of an uncalibrated run (02 §6.9).
UNCALIBRATED = "uncalibrated"
#: calibration_sha256 of an uncalibrated run (03 §12 run_manifest.calibration_sha256).
UNCALIBRATED_SHA256 = sha256_json({"family": UNCALIBRATED})
#: File name suffix under config/calibration/ (03 §12.1).
CALIBRATION_SUFFIX = ".json"

#: The ai_arm vocabulary (03 §1), from the generated contracts.
AI_ARMS: tuple[str, ...] = get_args(AiArm)
#: The alert protocol vocabulary (03 §2.6), from the generated contracts.
ALERT_PROTOCOLS: tuple[str, ...] = get_args(AlertProtocol)
#: The ai_arm of every run with AI off, and of runs where Relentra is disabled.
_ARM_OFF = "off"

# The family_id pattern of the generated contracts (calibration.schema.json $defs.family_id), so
# there is one definition of the four-part id.
_FAMILY_ID_RE = re.compile(next(m.pattern for m in get_args(FamilyId)[1:] if getattr(m, "pattern", None)))
# First part (benchmark family, optionally "-<system>" for Mondrian) and fourth part (fold,
# "foldA" or "loso-<system>"), 03 §12.1; the same alphabets as in the family_id pattern.
_FAMILY_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_FOLD_RE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")


@dataclass(frozen=True)
class CalibrationRef:
    """The calibration file selected for a run: its family_id, the SHA-256 of its canonical bytes
    and its validated content (03 §12.2 config_lock.calibration)."""

    family_id: str
    sha256: str
    content: Calibration

    def __post_init__(self) -> None:
        if not is_family_id(self.family_id):
            msg = f"not a calibration family_id: {self.family_id!r}"
            raise ConfigError(msg)
        if self.content.family != self.family_id:
            msg = f"calibration content.family {self.content.family!r} != family_id {self.family_id!r}"
            raise ConfigError(msg)
        expected = sha256_bytes(calibration_bytes(self.content))
        if self.sha256 != expected:
            msg = (
                f"calibration {self.family_id}: sha256 {self.sha256} does not match its content ({expected})"
            )
            raise ConfigError(msg)

    def lock_object(self) -> dict[str, JSONValue]:
        """The `calibration` entry of config.lock.json."""
        return {
            "family_id": self.family_id,
            "sha256": self.sha256,
            "content": self.content.model_dump(mode="json", by_alias=True),
        }


def is_family_id(value: object) -> bool:
    """True if `value` is a four-part calibration family_id (03 §12.1)."""
    return isinstance(value, str) and _FAMILY_ID_RE.fullmatch(value) is not None


def make_family_id(family: str, ai_arm: str, alert_protocol: str, fold: str) -> str:
    """Return `<family>.<ai_arm>.<alert_protocol>.<fold>`; raises ConfigError for a bad part."""
    if _FAMILY_RE.fullmatch(family) is None:
        msg = f"calibration family {family!r} must match {_FAMILY_RE.pattern}"
        raise ConfigError(msg)
    if ai_arm not in AI_ARMS:
        msg = f"ai_arm {ai_arm!r} is not one of {', '.join(AI_ARMS)}"
        raise ConfigError(msg)
    if alert_protocol not in ALERT_PROTOCOLS:
        msg = f"alert protocol {alert_protocol!r} is not one of {', '.join(ALERT_PROTOCOLS)}"
        raise ConfigError(msg)
    if _FOLD_RE.fullmatch(fold) is None:
        msg = f"calibration fold {fold!r} must match {_FOLD_RE.pattern}"
        raise ConfigError(msg)
    family_id = f"{family}.{ai_arm}.{alert_protocol}.{fold}"
    if not is_family_id(family_id):  # the generated pattern is the authority
        msg = f"not a calibration family_id: {family_id!r}"
        raise ConfigError(msg)
    return family_id


def select_family(dataset: str, family: object, family_map: Mapping[str, Any]) -> str | None:
    """Return the benchmark family for `dataset`, or None if nothing matches.

    An explicit `family` (causentra.calibration.family) wins. Otherwise an exact family_map key
    wins over globs, and globs are tried in sorted order with case-sensitive fnmatchcase, so the
    choice is the same on Windows and Linux (M0 lead decision 2026-11-06).
    """
    if family is not None:
        if not isinstance(family, str):
            msg = f"causentra.calibration.family must be a string or null, got {family!r}"
            raise ConfigError(msg)
        return family
    chosen: object = family_map.get(dataset)
    if chosen is None:
        chosen = next((family_map[p] for p in sorted(family_map) if fnmatch.fnmatchcase(dataset, p)), None)
    if chosen is not None and not isinstance(chosen, str):
        msg = f"causentra.calibration.family_map values must be strings, got {chosen!r}"
        raise ConfigError(msg)
    return chosen


def ai_arm_for(ai_mode: AIMode, relentra: Mapping[str, Any]) -> str | None:
    """Return the calibration ai_arm of a run, or None if the run has no calibratable arm.

    AI off, or Relentra disabled (no proposals reach the verifier), is arm "off". With AI on
    (record and replay alike, so both share one family_id) the arm is `relentra.mode`. A mode
    outside the ai_arm vocabulary (e.g. agent_only) has no calibration family: None.
    """
    if ai_mode == "off" or relentra.get("enabled", True) is False:
        return _ARM_OFF
    mode: object = relentra.get("mode")
    if not isinstance(mode, str):
        msg = f"relentra.mode must be a string when AI is on, got {mode!r}"
        raise ConfigError(msg)
    return mode if mode in AI_ARMS else None


def calibration_bytes(content: Calibration) -> bytes:
    """The only valid bytes of a calibration file: canonical JSON of the content plus LF."""
    return canonical_json(content) + b"\n"


def calibration_path(calibration_dir: Path, family_id: str) -> Path:
    """`<calibration_dir>/<family_id>.json`."""
    return calibration_dir / f"{family_id}{CALIBRATION_SUFFIX}"


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            msg = f"duplicate key {key!r}"
            raise ConfigError(msg)
        out[key] = value
    return out


def parse_json_strict(data: bytes, *, where: str) -> object:
    """Parse UTF-8 JSON bytes, rejecting duplicate keys and NaN/Infinity literals.

    json.loads silently keeps the last of two equal keys, so a hand-edited lock or calibration
    file could carry a value nobody sees; config files must never be ambiguous. Raises ConfigError.
    """

    def _no_constant(name: str) -> object:
        msg = f"{name} is not valid JSON"
        raise ConfigError(msg)

    try:
        return json.loads(
            data.decode("utf-8"), object_pairs_hook=_reject_duplicates, parse_constant=_no_constant
        )
    except ConfigError as exc:
        msg = f"{where}: {exc}"
        raise ConfigError(msg) from exc
    except (UnicodeDecodeError, ValueError) as exc:  # JSONDecodeError is a ValueError
        msg = f"{where}: not valid JSON: {exc}"
        raise ConfigError(msg) from exc


def _parse_content(data: bytes, where: str) -> Calibration:
    obj = parse_json_strict(data, where=where)
    try:
        content = Calibration.model_validate(obj)
    except ValidationError as exc:
        msg = f"{where}: not a valid calibration file: {exc}"
        raise ConfigError(msg) from exc
    if calibration_bytes(content) != data:
        msg = f"{where}: bytes are not canonical_json(content) + LF; rewrite it with write_calibration"
        raise ConfigError(msg)
    return content


def load_calibration(path: Path) -> CalibrationRef:
    """Load and check one calibration file; its stem must be its family_id.

    Raises ConfigError for unreadable, invalid or non-canonical files and for a stem that is not
    the content's family; FileNotFoundError if the file is missing.
    """
    data = read_bytes(path)
    family_id = path.name.removesuffix(CALIBRATION_SUFFIX)
    content = _parse_content(data, f"calibration {path.name}")
    if content.family != family_id:
        msg = f"calibration {path.name}: content.family is {content.family!r}, expected {family_id!r}"
        raise ConfigError(msg)
    return CalibrationRef(family_id=family_id, sha256=sha256_bytes(data), content=content)


def find_calibration(
    calibration_dir: Path, family_id: str, *, ai_arm: str, alert_protocol: str
) -> CalibrationRef | None:
    """Load `<calibration_dir>/<family_id>.json` for a run, or None if there is no such file.

    A file whose ai_arm or alert_protocol disagrees with the run is a hard error (03 §12.1;
    09-causentra §3.15). The name must match exactly, case included: NTFS would otherwise find
    `…foldA.json` for `…FOLDa` on Windows while Linux reports no calibration, so the same config
    and files would behave differently per OS.
    """
    path = calibration_path(calibration_dir, family_id)
    if not path.is_file() or path.name not in set(os.listdir(calibration_dir)):
        return None
    ref = load_calibration(path)
    if ref.content.ai_arm != ai_arm or ref.content.alert_protocol != alert_protocol:
        msg = (
            f"calibration {family_id}: file is for ai_arm={ref.content.ai_arm}, "
            f"alert_protocol={ref.content.alert_protocol}, run is ai_arm={ai_arm}, "
            f"alert_protocol={alert_protocol}"
        )
        raise ConfigError(msg)
    return ref


def ref_from_lock(obj: Mapping[str, Any]) -> CalibrationRef:
    """Rebuild the CalibrationRef stored in config.lock.json, re-checking its hash from the content.

    Replay uses this instead of opening config/calibration/ (critic gap "replay reads the wrong
    calibration source").
    """
    try:
        content = Calibration.model_validate(obj["content"])
        family_id: object = obj["family_id"]
        sha: object = obj["sha256"]
    except (KeyError, ValidationError) as exc:
        msg = f"config lock: invalid calibration entry: {exc}"
        raise ConfigError(msg) from exc
    if not isinstance(family_id, str) or not isinstance(sha, str):
        msg = "config lock: calibration family_id and sha256 must be strings"
        raise ConfigError(msg)
    return CalibrationRef(family_id=family_id, sha256=sha, content=content)


def write_calibration(calibration_dir: Path, content: Calibration | Mapping[str, Any]) -> Path:
    """Write a calibration file in its one valid byte form (for bench); returns its path."""
    try:
        model = content if isinstance(content, Calibration) else Calibration.model_validate(content)
    except ValidationError as exc:
        msg = f"not a valid calibration: {exc}"
        raise ConfigError(msg) from exc
    if not is_family_id(model.family):
        msg = f"not a calibration family_id: {model.family!r}"
        raise ConfigError(msg)
    path = calibration_path(calibration_dir, model.family)
    write_bytes(path, calibration_bytes(model))
    return path
