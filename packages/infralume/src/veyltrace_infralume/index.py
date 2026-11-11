"""The private case index `${VEYLTRACE_DATA}/index/<dataset>.json` (01 §2): `case_id → relative path`.

Why: the fetcher knows where each case landed, the adapter needs to find it again from an opaque
`case_id`, and the path itself carries the label (the RCAEval folder name), so it lives only in
this file under the data root, never in a run directory. The file is canonical JSON with sorted
keys, so re-fetching the same cases rewrites identical bytes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Final, cast

from veyltrace_core import textio
from veyltrace_core.canonical import canonical_json
from veyltrace_core.errors import ConfigError, UsageError
from veyltrace_core.ids import is_case_id

__all__ = ["INDEX_DIR", "index_path", "read_index", "resolve_entry", "write_index"]

#: Directory of the per-dataset index files under the data root (01 §2).
INDEX_DIR: Final = "index"


def index_path(data_root: Path, dataset: str) -> Path:
    """`<data root>/index/<dataset>.json`."""
    return Path(data_root) / INDEX_DIR / f"{dataset}.json"


def _check_relpath(relpath: str, where: Path) -> None:
    path = PurePosixPath(relpath)
    if not relpath or path.is_absolute() or ".." in path.parts or "\\" in relpath:
        msg = f"{where}: {relpath!r} is not a relative POSIX path under the data root"
        raise ConfigError(msg)


def read_index(data_root: Path, dataset: str) -> dict[str, str]:
    """The index of `dataset` (empty if never fetched); ConfigError if the file is malformed."""
    path = index_path(data_root, dataset)
    if not path.is_file():
        return {}
    raw: object = json.loads(textio.read_text(path))
    if not isinstance(raw, dict):
        msg = f"{path}: expected a JSON object of case_id -> relative path"
        raise ConfigError(msg)
    entries: dict[str, str] = {}
    for key, value in cast("dict[object, object]", raw).items():
        if not isinstance(key, str) or not is_case_id(key) or not isinstance(value, str):
            msg = f"{path}: entry {key!r} needs a 12-hex case_id and a string path"
            raise ConfigError(msg)
        _check_relpath(value, path)
        entries[key] = value
    return dict(sorted(entries.items()))


def write_index(data_root: Path, dataset: str, entries: Mapping[str, str]) -> Path:
    """Write `entries` (merged over the existing index) as canonical JSON; returns the path."""
    path = index_path(data_root, dataset)
    merged = read_index(data_root, dataset)
    for key, value in entries.items():
        if not is_case_id(key):
            msg = f"index key {key!r} is not a 12-hex case_id"
            raise ValueError(msg)
        _check_relpath(value, path)
        merged[key] = value
    textio.write_bytes(path, canonical_json(dict(sorted(merged.items()))))
    return path


def resolve_entry(data_root: Path, dataset: str, case_id: str) -> Path:
    """The case directory of `case_id`; UsageError if the dataset index does not list it."""
    entries = read_index(data_root, dataset)
    if case_id not in entries:
        hint = "" if entries else f" (no {index_path(data_root, dataset)}: run `veyltrace data fetch`)"
        msg = f"case {case_id!r} is not in the {dataset} index{hint}"
        raise UsageError(msg)
    return Path(data_root).joinpath(*PurePosixPath(entries[case_id]).parts)
