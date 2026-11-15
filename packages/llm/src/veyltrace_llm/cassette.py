"""The cassette: every LLM call of a run, so replay needs no model (08 §5.2; package rules 3–6).

Layout in the run directory:

- `cassette/<key>.json` = `{key, request, recorded_with, responses: [...]}`: `request` is the
  canonical request whose SHA-256 is `key`; `recorded_with` holds the runtime settings that are
  not part of the key (provider, base_url, timeouts, thread count, …; never a header or API key);
  `responses` are outcomes in occurrence order (the n-th identical call gets the n-th response),
  errors included, so replay reproduces a timeout as a timeout.
- `cassette/index.json` = sorted `[{key, purpose, n}]`.

Every file is canonical JSON, written atomically, with no timestamps, so recording the same calls
twice gives the same bytes. Replay is strict: a missing key, a missing occurrence or an entry whose
request does not hash to its key raises `CassetteMiss`; nothing is ever fetched (rule 4). Record
refuses a non-empty directory unless `force_record` (rule 5), which first clears it.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, Literal, cast

from veyltrace_core import textio
from veyltrace_core.canonical import canonical_json
from veyltrace_core.errors import CassetteMiss as CoreCassetteMiss
from veyltrace_core.errors import UsageError
from veyltrace_core.hashing import sha256_bytes
from veyltrace_llm.errors import LLMError
from veyltrace_llm.request import CallError, Completion, LLMRequest, Runtime, Usage

__all__ = [
    "CASSETTE_DIR",
    "INDEX_FILE",
    "Cassette",
    "CassetteMiss",
    "CassetteNotEmpty",
    "completion_from_json",
]

#: Run-dir subdirectory of the cassette (02 §4.1).
CASSETTE_DIR: Final = "cassette"
INDEX_FILE: Final = "index.json"
_SUFFIX: Final = ".json"
CassetteMode = Literal["record", "replay"]


class CassetteMiss(LLMError, CoreCassetteMiss):
    """Strict replay found no recorded response for a request (core's CassetteMiss: exit 3 in
    `diagnose --ai replay`, exit 2 in `veyltrace replay`)."""

    def __init__(self, key: str, detail: str = "") -> None:
        CoreCassetteMiss.__init__(self, key)
        self.detail = detail

    def __str__(self) -> str:
        return f"no cassette entry for request {self.key}" + (f": {self.detail}" if self.detail else "")

    def __reduce__(self) -> tuple[type[CassetteMiss], tuple[str, str]]:
        return (type(self), (self.key, self.detail))


class CassetteNotEmpty(LLMError, UsageError):
    """Record mode found an existing cassette and `--force-record` was not given (rule 5)."""


def completion_from_json(raw: Mapping[str, Any]) -> Completion:
    """Parse one `responses[]` entry (the inverse of `Completion.as_json`)."""
    usage = cast(Mapping[str, Any], raw["usage"])
    runtime = cast(Mapping[str, Any], raw["runtime"])
    error = cast(Mapping[str, Any] | None, raw["error"])
    return Completion(
        content=cast(str | None, raw["content"]),
        usage=Usage(int(usage["tokens_in"]), int(usage["tokens_out"])),
        latency_ms=float(raw["latency_ms"]),
        runtime=Runtime(str(runtime["provider"]), cast(str | None, runtime["version"])),
        error=None if error is None else CallError(kind=error["kind"], message=str(error["message"])),
    )


class Cassette:
    """One run's cassette directory in record or replay mode."""

    def __init__(
        self,
        directory: Path,
        mode: CassetteMode,
        *,
        force_record: bool = False,
        recorded_with: Mapping[str, Any] | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.mode: CassetteMode = mode
        self._recorded_with = dict(recorded_with or {})
        self._entries: dict[str, dict[str, Any]] = {}
        self._replayed: Counter[str] = Counter()
        if mode == "record":
            self._prepare_record(force_record)
        elif mode != "replay":
            raise ValueError(f"cassette mode must be record or replay, got {mode!r}")

    def _prepare_record(self, force: bool) -> None:
        existing = sorted(self.directory.iterdir()) if self.directory.is_dir() else []
        if existing and not force:
            msg = f"{self.directory} is not empty; pass --force-record to overwrite the recording"
            raise CassetteNotEmpty(msg)
        for path in existing:
            if not path.is_file():
                raise CassetteNotEmpty(f"{self.directory} holds {path.name}, which is not a cassette file")
            path.unlink()
        self.directory.mkdir(parents=True, exist_ok=True)

    # --- record ----------------------------------------------------------------------------
    def record(self, request: LLMRequest, completion: Completion) -> int:
        """Append `completion` as the next occurrence of `request`; returns its 0-based index."""
        if self.mode != "record":
            raise ValueError("record() needs a cassette in record mode")
        key = request.key
        entry = self._entries.setdefault(
            key,
            {
                "key": key,
                "request": request.canonical(),
                "recorded_with": self._recorded_with,
                "responses": [],
            },
        )
        responses = cast(list[dict[str, Any]], entry["responses"])
        responses.append(completion.as_json())
        textio.write_bytes(self.directory / f"{key}{_SUFFIX}", canonical_json(entry))
        self._write_index()
        return len(responses) - 1

    def _write_index(self) -> None:
        index = [
            {"key": key, "purpose": entry["request"]["purpose"], "n": len(entry["responses"])}
            for key, entry in sorted(self._entries.items())
        ]
        textio.write_bytes(self.directory / INDEX_FILE, canonical_json(index))

    # --- replay ----------------------------------------------------------------------------
    def _load(self, key: str) -> dict[str, Any]:
        if key in self._entries:
            return self._entries[key]
        path = self.directory / f"{key}{_SUFFIX}"
        if not path.is_file():
            raise CassetteMiss(key, f"no {path.name} in {self.directory}")
        try:
            entry = cast(dict[str, Any], json.loads(textio.read_bytes(path)))
            request = cast(dict[str, Any], entry["request"])
            cast(list[Any], entry["responses"])
        except (ValueError, KeyError, TypeError) as exc:
            raise CassetteMiss(key, f"{path.name} is not a cassette entry ({exc})") from exc
        if entry.get("key") != key or sha256_bytes(canonical_json(request)) != key:
            raise CassetteMiss(key, f"{path.name} does not hold the request with this key (edited?)")
        self._entries[key] = entry
        return entry

    def lookup(self, request: LLMRequest) -> Completion:
        """The recorded outcome for the next occurrence of `request`; CassetteMiss if none."""
        if self.mode != "replay":
            raise ValueError("lookup() needs a cassette in replay mode")
        key = request.key
        responses = cast(list[dict[str, Any]], self._load(key)["responses"])
        n = self._replayed[key]
        if n >= len(responses):
            raise CassetteMiss(key, f"occurrence {n + 1} was not recorded ({len(responses)} recorded)")
        self._replayed[key] += 1
        try:
            return completion_from_json(responses[n])
        except (ValueError, KeyError, TypeError) as exc:
            raise CassetteMiss(key, f"response {n + 1} is malformed ({exc})") from exc
