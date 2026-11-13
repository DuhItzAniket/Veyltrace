"""Leakage scrubbing (01 §3.6, principle P7): no artefact after Infralume carries the answer.

What is removed: attribute keys on the deny-list (`feature_flag.*`, segments `chaos*`, `fault*`,
`inject*`), telemetry rows of fault-tool services, chaos events, and folder tokens (the canonical
case key, the case path and its label-bearing directory names), which are replaced by `<case>`
in every string column and JSON value. Flag keys in `flag` events are hashed, never dropped. Log
bodies are otherwise kept verbatim: rewriting words like "fault" would destroy evidence.
Every function is idempotent (scrubbing twice equals scrubbing once; property-tested), and the
`dropped_*` counts feed `case_manifest.scrub` (03 §2.1).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import Any, Final, cast

import pyarrow as pa
import pyarrow.compute as pc

from veyltrace_core.canonical import canonical_json_str, normalize

__all__ = ["CASE_TOKEN", "ScrubRules", "Scrubber", "folder_tokens"]

#: What a folder token becomes (01 §3.6).
CASE_TOKEN: Final = "<case>"
#: Flag keys are reduced to the first 8 hex of their SHA-256, as the lab packager does (05 §7).
FLAG_HEX: Final = 8
_HEX8: Final = re.compile(r"[0-9a-f]{8}")
_CHAOS: Final = "chaos"
#: pyarrow-stubs type pyarrow.compute with Unknown overloads; core uses the same alias (io.py).
_pc: Any = pc


@dataclass(frozen=True)
class ScrubRules:
    """`scrub.*` of config/infralume.yaml (01 §4)."""

    rules_version: str
    deny_key_patterns: tuple[str, ...]
    drop_services: frozenset[str]

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any]) -> ScrubRules:
        section = cast("Mapping[str, Any]", cfg["scrub"])
        return cls(
            rules_version=str(section["rules_version"]),
            deny_key_patterns=tuple(str(p).lower() for p in section["deny_key_patterns"]),
            drop_services=frozenset(str(s).lower() for s in section["drop_services"]),
        )

    def denied(self, key: str) -> bool:
        """A pattern with a dot (`feature_flag.*`) matches the whole key; one without matches any
        dot-separated segment (`chaos*` hits `k8s.chaos.kind`). Case-insensitive."""
        low = key.lower()
        segments = low.split(".")
        return any(
            fnmatchcase(low, p) if "." in p else any(fnmatchcase(s, p) for s in segments)
            for p in self.deny_key_patterns
        )


def folder_tokens(canonical_key: str, relpath: str) -> tuple[str, ...]:
    """The strings that would reveal a case's folder: its canonical key, its path relative to the
    data root, and each directory name that carries a label (contains `_`, as RCAEval's
    `{service}_{fault}` does). Longest first, so a path is replaced before the key inside it."""
    parts = [p for p in PurePosixPath(relpath).parts if "_" in p]
    tokens = {t.lower() for t in (canonical_key, relpath, *parts) if t}
    return tuple(sorted(tokens, key=lambda t: (-len(t), t)))


def _contains_chaos(value: object) -> bool:
    if isinstance(value, dict):
        items = cast("dict[str, object]", value).items()
        return any(_CHAOS in k.lower() or _contains_chaos(v) for k, v in items)
    if isinstance(value, list):
        return any(_contains_chaos(v) for v in cast("list[object]", value))
    return isinstance(value, str) and _CHAOS in value.lower()


@dataclass
class Scrubber:
    """Scrubs one case with `rules` and its `tokens`, counting what it drops."""

    rules: ScrubRules
    tokens: Sequence[str] = ()
    dropped_attributes: int = 0
    dropped_rows: int = 0
    _pattern: re.Pattern[str] | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if self.tokens:
            self._pattern = re.compile("|".join(re.escape(t) for t in self.tokens), re.IGNORECASE)

    @property
    def counts(self) -> tuple[str, int, int]:
        """(`rules_version`, `dropped_attributes`, `dropped_rows`) for CanonicalCase.scrub."""
        return self.rules.rules_version, self.dropped_attributes, self.dropped_rows

    def text(self, value: str) -> str:
        """`value` with every folder token replaced by `<case>`."""
        return value if self._pattern is None else self._pattern.sub(CASE_TOKEN, value)

    def text_column(
        self, column: pa.Array[Any] | pa.ChunkedArray[Any]
    ) -> pa.Array[Any] | pa.ChunkedArray[Any]:
        """A string column with folder tokens replaced (Arrow's RE2, case-insensitive)."""
        if self._pattern is None:
            return column
        return _pc.replace_substring_regex(column, "(?i)" + self._pattern.pattern, CASE_TOKEN)

    def _clean(self, value: object) -> object:
        if isinstance(value, dict):
            out: dict[str, object] = {}
            for key, item in cast("dict[str, object]", value).items():
                if self.rules.denied(key):
                    self.dropped_attributes += 1
                else:
                    out[self.text(key)] = self._clean(item)
            return out
        if isinstance(value, list):
            return [self._clean(v) for v in cast("list[object]", value)]
        return self.text(value) if isinstance(value, str) else value

    def attrs(self, attrs: Mapping[str, object] | None) -> str | None:
        """Canonical JSON of `attrs` without deny-listed keys and folder tokens; None if empty."""
        if not attrs:
            return None
        cleaned = cast("dict[str, object]", self._clean(dict(attrs)))
        return canonical_json_str(normalize(cleaned)) if cleaned else None

    def attrs_json(self, value: str | None) -> str | None:
        """`attrs`, for an attrs_json string (None stays None)."""
        return None if value is None else self.attrs(cast("dict[str, object]", json.loads(value)))

    def drop_rows(self, table: pa.Table, columns: Iterable[str]) -> pa.Table:
        """`table` without rows whose value in any of `columns` is a fault-tool service."""
        if table.num_rows == 0 or not self.rules.drop_services:
            return table
        banned = pa.array(sorted(self.rules.drop_services), type=pa.string())
        hit = None
        for name in columns:
            mask = _pc.fill_null(_pc.is_in(table.column(name), value_set=banned), False)
            hit = mask if hit is None else _pc.or_(hit, mask)
        if hit is None:
            return table
        kept = table.filter(_pc.invert(hit))
        self.dropped_rows += table.num_rows - kept.num_rows
        return kept

    def event_detail(self, kind: str, detail: Mapping[str, object]) -> str | None:
        """Scrubbed `detail_json` of one event, or None if the event is a chaos object (dropped
        and counted). A `flag` event's `flag` key is hashed to 8 hex unless it already is."""
        if _contains_chaos(detail):
            self.dropped_rows += 1
            return None
        cleaned = cast("dict[str, object]", self._clean(dict(detail)))
        flag = cleaned.get("flag")
        if kind == "flag" and isinstance(flag, str) and _HEX8.fullmatch(flag) is None:
            cleaned["flag"] = hashlib.sha256(flag.encode("utf-8")).hexdigest()[:FLAG_HEX]
        return canonical_json_str(normalize(cleaned))
