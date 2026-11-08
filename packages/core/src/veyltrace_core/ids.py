"""Identifiers: case, run, atom, change/template and snapshot ids (03 §1 Identifiers).

Every id is a prefix of a SHA-256, so it is a pure function of its inputs: the same case,
config, code and AI mode always give the same run directory, and the same evidence always gives
the same atom id. Changing any definition here changes every hash downstream and needs an ADR
(packages/core/AGENTS.md).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any, get_args

from pydantic import BaseModel

from veyltrace_contracts.models import AiMode
from veyltrace_core.canonical import JSONLike
from veyltrace_core.hashing import is_sha256, sha256_json

__all__ = [
    "AI_MODES",
    "ATOM_ID_HEX",
    "CASE_ID_HEX",
    "DERIVED_RUN_HEX",
    "DIRTY_HEX",
    "RUN_ID_HEX",
    "SNAPSHOT_ID_HEX",
    "AIMode",
    "atom_id",
    "case_id",
    "derived_run_id",
    "dirty_commit",
    "is_atom_id",
    "is_case_id",
    "is_code_commit",
    "is_run_id",
    "run_id",
    "short_id",
    "snapshot_id",
]

#: The run's AI mode (03 §1 vocabulary `ai_mode`); one definition, from the generated contracts.
AIMode = AiMode
AI_MODES: tuple[str, ...] = get_args(AiMode)

# Hex lengths, all from 03 §1 Identifiers unless noted.
CASE_ID_HEX = 12
RUN_ID_HEX = 16
ATOM_ID_HEX = 10
DERIVED_RUN_HEX = 12  # "-x<12 hex>" suffix of a derived verify_hypothesis run (02 §4.1)
SNAPSHOT_ID_HEX = 32  # 06 §3.4
DIRTY_HEX = 12  # "+dirty.<12 hex>" suffix of a dirty tree's code commit (M0 lead decision 2026-11-06)
_SHA256_HEX = 64

_CASE_ID_RE = re.compile(rf"[0-9a-f]{{{CASE_ID_HEX}}}")
_BASE_RUN_ID_RE = re.compile(rf"[0-9a-f]{{{RUN_ID_HEX}}}")
_RUN_ID_RE = re.compile(rf"[0-9a-f]{{{RUN_ID_HEX}}}(?:-x[0-9a-f]{{{DERIVED_RUN_HEX}}})?")
_ATOM_ID_RE = re.compile(rf"E[0-9a-f]{{{ATOM_ID_HEX}}}")
# A git sha (SHA-1 or SHA-256 object format), "fixture" in golden fixtures or "unknown" outside a
# git checkout, optionally with the dirty-tree suffix (run_manifest.code.commit, 03 §12).
_CODE_COMMIT_RE = re.compile(
    rf"(?:[0-9a-f]{{40}}|[0-9a-f]{{64}}|fixture|unknown)(?:\+dirty\.[0-9a-f]{{{DIRTY_HEX}}})?"
)


def is_case_id(value: object) -> bool:
    """True if `value` matches `^[0-9a-f]{12}$` (whole string; a trailing newline does not pass)."""
    return isinstance(value, str) and _CASE_ID_RE.fullmatch(value) is not None


def is_run_id(value: object) -> bool:
    """True if `value` matches `^[0-9a-f]{16}(-x[0-9a-f]{12})?$` (base or derived run id)."""
    return isinstance(value, str) and _RUN_ID_RE.fullmatch(value) is not None


def is_atom_id(value: object) -> bool:
    """True if `value` matches `^E[0-9a-f]{10}$`."""
    return isinstance(value, str) and _ATOM_ID_RE.fullmatch(value) is not None


def is_code_commit(value: object) -> bool:
    """True if `value` is a valid run_manifest.code.commit string (see dirty_commit)."""
    return isinstance(value, str) and _CODE_COMMIT_RE.fullmatch(value) is not None


def case_id(canonical_key: str) -> str:
    """Return the 12-hex case id of an adapter's canonical case key, hashed verbatim as UTF-8 with
    no normalisation (01 §3.2). For synth the key is the case name: case_id("synth-01")."""
    if not canonical_key:
        msg = "canonical case key must be a non-empty string"
        raise ValueError(msg)
    return hashlib.sha256(canonical_key.encode("utf-8")).hexdigest()[:CASE_ID_HEX]


def dirty_commit(commit: str, diff_sha256: str) -> str:
    """Return the code commit of a dirty work tree: "<commit>+dirty.<first 12 hex of diff_sha256>".

    `diff_sha256` hashes the git diff plus untracked files under packages/, contracts/ and
    config/ (excluding config/calibration/, bench/results/, runs/), so uncommitted edits change
    run_id and a stale finished run is never reused (M0 lead decision 2026-11-06).
    """
    if not is_code_commit(commit) or "+dirty." in commit:
        msg = f"commit must be a clean code commit, got {commit!r}"
        raise ValueError(msg)
    if not is_sha256(diff_sha256):
        msg = f"diff_sha256 must be a lowercase 64-hex sha256, got {diff_sha256!r}"
        raise ValueError(msg)
    return f"{commit}+dirty.{diff_sha256[:DIRTY_HEX]}"


def run_id(case_id: str, config_sha256: str, code_commit: str, ai_mode: AIMode) -> str:
    """Return the 16-hex run id: sha256_json([case_id, config_sha256, code_commit, ai_mode])[:16]
    (02 §4.1). The run directory is named after it."""
    if not is_case_id(case_id):
        msg = f"case_id must match ^[0-9a-f]{{12}}$, got {case_id!r}"
        raise ValueError(msg)
    if not is_sha256(config_sha256):
        msg = f"config_sha256 must be a lowercase 64-hex sha256, got {config_sha256!r}"
        raise ValueError(msg)
    if not is_code_commit(code_commit):
        msg = f"code_commit must be a git sha, 'fixture' or 'unknown' (+dirty.<12 hex>), got {code_commit!r}"
        raise ValueError(msg)
    if ai_mode not in AI_MODES:
        msg = f"ai_mode must be one of {AI_MODES}, got {ai_mode!r}"
        raise ValueError(msg)
    return sha256_json([case_id, config_sha256, code_commit, ai_mode])[:RUN_ID_HEX]


def derived_run_id(run_id: str, external_proposal: Mapping[str, Any] | BaseModel) -> str:
    """Return the id of a derived verify_hypothesis run: "<run_id>-x<12 hex of the proposal>" (02 §4.1)."""
    if _BASE_RUN_ID_RE.fullmatch(run_id) is None:
        msg = f"run_id must be a base 16-hex run id, got {run_id!r}"
        raise ValueError(msg)
    return f"{run_id}-x{sha256_json(external_proposal)[:DERIVED_RUN_HEX]}"


def atom_id(kind: str, candidate: str, args: Mapping[str, JSONLike]) -> str:
    """Return an evidence atom id: "E" + sha256_json([kind, candidate, args])[:10] (06 §3.2).

    The caller builds `args` (for claim_check: {"args": ..., "predicate": ...}). Ints and floats
    hash differently: k=4 and k=4.0 give different atoms (06 §3.8).
    """
    return "E" + sha256_json([kind, candidate, args])[:ATOM_ID_HEX]


def short_id(prefix: str, n: int, obj: JSONLike) -> str:
    """Return `prefix` + the first `n` hex of sha256_json(obj).

    template_id = short_id("T", 8, [service, template]) and change_id = short_id("C", 10, {...})
    (02 §3.5; 04 §3.5).
    """
    if isinstance(n, bool) or not 1 <= n <= _SHA256_HEX:
        msg = f"n must be an int in [1, {_SHA256_HEX}], got {n!r}"
        raise ValueError(msg)
    return prefix + sha256_json(obj)[:n]


def snapshot_id(file_hashes: Sequence[str], t_trigger_ns: int) -> str:
    """Return a live snapshot id: sha256_json([sorted(file_hashes), t_trigger_ns])[:32] (06 §3.4).

    The hashes are sorted, so the id does not depend on file discovery order.
    """
    if isinstance(file_hashes, str):
        msg = "file_hashes must be a sequence of sha256 strings, not one string"
        raise TypeError(msg)
    for digest in file_hashes:
        if not is_sha256(digest):
            msg = f"file hashes must be lowercase 64-hex sha256, got {digest!r}"
            raise ValueError(msg)
    # Runtime guard for untyped callers (gateway JSON): a float would hash differently from the int.
    if isinstance(t_trigger_ns, bool) or not isinstance(t_trigger_ns, int):  # pyright: ignore[reportUnnecessaryIsInstance]
        msg = f"t_trigger_ns must be an int, got {t_trigger_ns!r}"
        raise TypeError(msg)
    return sha256_json([sorted(file_hashes), t_trigger_ns])[:SNAPSHOT_ID_HEX]
