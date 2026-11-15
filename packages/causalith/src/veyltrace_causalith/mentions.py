"""Service mentions in log lines and event hints, with the ambiguity rule (05-causalith §3.5).

Why: a frontend line "failed to get cart from cartservice:7070" is evidence of the call frontend →
cartservice even without traces (rcaeval_facts §Logs), which is how Sock Shop (no traces) gets
edges. Why the ambiguity rule: names like `carts`, `orders` or `user` are ordinary English, so a
name matching `^[a-z]+$` counts only as host:port, URL or gRPC package, never as a plain word.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

__all__ = ["TOPOLOGY_KINDS", "Matcher", "log_edges", "mentioned", "topology_edges"]

_PLAIN_AMBIGUOUS = re.compile(r"^[a-z]+$")
#: Dotted package path ending in a capitalised class name: `hipstershop.CartService`.
_GRPC = re.compile(r"\b[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*\.([A-Z]\w*)\b")
_SUFFIX = "service"
#: Event kinds whose details carry topology hints (05 §3.4).
TOPOLOGY_KINDS = frozenset({"deploy", "config"})


@dataclass(frozen=True)
class Matcher:
    """Compiled patterns for every known service, built from the sorted service list."""

    services: tuple[str, ...]
    patterns: Mapping[str, Sequence[re.Pattern[str]]]

    @classmethod
    def build(cls, services: Iterable[str]) -> Matcher:
        names = tuple(sorted(set(services)))
        patterns: dict[str, list[re.Pattern[str]]] = {}
        for n in names:
            e = re.escape(n)
            forms = [
                rf"(?<![\w.-]){e}(?:\.[a-z0-9-]+)*:\d{{2,5}}\b",  # host:port, optional DNS suffix
                # URL; the host ends at a non-name character, so carts-db is not carts
                rf"[a-z][a-z0-9+.-]*://{e}(?:\.[a-z0-9-]+)*(?::\d+)?(?![\w-])",
            ]
            if not _PLAIN_AMBIGUOUS.match(n):
                forms.append(rf"(?<![\w.-]){e}(?![\w-])")  # plain word, unambiguous names only
            patterns[n] = [re.compile(f, re.IGNORECASE) for f in forms]
        return cls(names, patterns)

    def grpc_names(self, text: str) -> set[str]:
        """Known services named by a gRPC package path (`oteldemo.CartService` → cart)."""
        found: set[str] = set()
        known = set(self.services)
        for m in _GRPC.finditer(text):
            last = m.group(1).lower()
            for name in (last, last.removesuffix(_SUFFIX)):
                if name in known:
                    found.add(name)
        return found

    def mentions(self, text: str, speaker: str | None = None) -> set[str]:
        """Known services `text` mentions, never the speaker itself (a line counts once per service)."""
        found = self.grpc_names(text)
        for name, forms in self.patterns.items():
            if name not in found and any(f.search(text) for f in forms):
                found.add(name)
        found.discard(speaker or "")
        return found


def mentioned(matcher: Matcher, texts: Iterable[str], speaker: str | None = None) -> set[str]:
    """Union of the services mentioned in several strings (event `detail_json` values)."""
    out: set[str] = set()
    for text in texts:
        out |= matcher.mentions(text, speaker)
    return out


def _strings(value: object) -> list[str]:
    """Every string value inside a decoded JSON value, depth first in key order."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        mapping = cast("Mapping[str, object]", value)
        return [s for key in sorted(mapping) for s in _strings(mapping[key])]
    if isinstance(value, list):
        return [s for item in cast("list[object]", value) for s in _strings(item)]
    return []


def log_edges(
    counts: Iterable[tuple[str, str, int]], nodes: frozenset[str], matcher: Matcher, min_mentions: int
) -> list[tuple[str, str]]:
    """A → B for every logging node A whose lines mention node B at least `min_mentions` times
    (05 §3.4); `counts` are (service, distinct body, lines) over baseline and incident."""
    lines: dict[tuple[str, str], int] = {}
    for service, body, n in counts:
        if service not in nodes:
            continue  # logs never create nodes
        for target in matcher.mentions(body, service):
            if target in nodes:
                lines[service, target] = lines.get((service, target), 0) + n
    return sorted(pair for pair, n in lines.items() if n >= min_mentions)


def topology_edges(
    events: Iterable[tuple[str, str, str]], nodes: frozenset[str], matcher: Matcher
) -> list[tuple[str, str]]:
    """A → B for every `deploy`/`config` event on node A whose `detail_json` strings mention node B."""
    found: set[tuple[str, str]] = set()
    for entity, kind, detail in events:
        if kind not in TOPOLOGY_KINDS or entity not in nodes:
            continue
        try:
            decoded: object = json.loads(detail)
        except json.JSONDecodeError:
            continue
        found |= {(entity, b) for b in mentioned(matcher, _strings(decoded), entity) if b in nodes}
    return sorted(found)
