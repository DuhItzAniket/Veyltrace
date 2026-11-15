"""Service-name normalisation (01 §3.4): one name per service across metrics, logs and spans.

Why: sources name the same service differently (OB traces say `frontendservice`, metrics say
`frontend`; pods carry generated suffixes; SS stores `carts-db` next to `carts`), and RCAEval ranks
are `{service}_{indicator}`, so a service name may not contain `_` (03 §1). Normalisation is
idempotent (`n(n(x)) = n(x)`, property-tested), so re-applying it to already canonical input
(OTLP snapshots, lab captures) changes nothing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, cast

__all__ = ["NAME_PATTERN", "InvalidName", "NameRules", "Normalised", "strip_pod_suffix"]

#: Service, component and entity names (03 §1).
NAME_PATTERN: Final = re.compile(r"[a-z0-9][a-z0-9.-]*")
# Kubernetes generated-name suffixes (01 §3.4 step 2): the generator's vowel-free alphabet.
_K8S = "[bcdfghjklmnpqrstvwxz2456789]"
_POD_SUFFIXES: Final = (
    re.compile(rf"-{_K8S}{{6,10}}-{_K8S}{{5}}$"),  # Deployment: <name>-<replicaset hash>-<pod hash>
    re.compile(rf"-{_K8S}{{5}}$"),  # DaemonSet / Job
    re.compile(r"-\d+$"),  # StatefulSet ordinal
)


class InvalidName(ValueError):
    """A name that still breaks the 03 §1 pattern after normalisation: an adapter bug, not data."""


def strip_pod_suffix(name: str) -> str:
    """`name` without its first matching Kubernetes pod suffix (Deployment, then DaemonSet/Job,
    then StatefulSet); unchanged when none matches."""
    for pattern in _POD_SUFFIXES:
        stripped = pattern.sub("", name)
        if stripped != name and stripped:
            return stripped
    return name


@dataclass(frozen=True)
class Normalised:
    """A normalised name: `service`, and `component` (the original container, pod or db name;
    equal to `service` when nothing more specific is known, 03 §2.2)."""

    service: str
    component: str


def _check(name: str, raw: str) -> str:
    if NAME_PATTERN.fullmatch(name) is None:
        msg = f"name {raw!r} normalises to {name!r}, which breaks the 03 §1 pattern"
        raise InvalidName(msg)
    return name


@dataclass(frozen=True)
class NameRules:
    """The normalisation rules of one system: aliases, component suffixes, dropped containers."""

    aliases: Mapping[str, str] = field(default_factory=lambda: {})
    component_suffixes: tuple[str, ...] = ()
    drop_containers: frozenset[str] = frozenset()

    @classmethod
    def from_config(cls, cfg: Mapping[str, Any], system: str) -> NameRules:
        """Rules from `normalise.*` in config/infralume.yaml (01 §4) for `system` (ob, ss, tt, …)."""
        section = cast("Mapping[str, Any]", cfg["normalise"])
        aliases = cast("Mapping[str, Mapping[str, str]]", section["aliases"]).get(system, {})
        return cls(
            aliases={str(k).strip().lower(): str(v).strip().lower() for k, v in aliases.items()},
            component_suffixes=tuple(str(s).lower() for s in section["component_suffixes"]),
            drop_containers=frozenset(str(c).strip().lower() for c in section["drop_containers"]),
        )

    def _alias(self, name: str) -> str:
        seen = {name}
        while (target := self.aliases.get(name)) is not None and target not in seen:
            name = target
            seen.add(name)
        return name

    def _fold(self, name: str) -> str:
        changed = True
        while changed:
            changed = False
            for suffix in self.component_suffixes:
                if name.endswith(suffix) and len(name) > len(suffix):
                    name, changed = name[: -len(suffix)], True
        return name

    def _canonical(self, name: str, raw: str) -> str:
        """Aliases, suffix folding and `_` -> `-` (steps 4–6) up to a fixed point, so that
        normalising a normalised name changes nothing."""
        for _ in range(len(self.aliases) + len(name) + 2):
            nxt = self._fold(self._alias(name)).replace("_", "-")
            if nxt == name:
                return name
            name = nxt
        msg = f"name {raw!r} has no fixed point under the alias and suffix rules"
        raise InvalidName(msg)

    def normalise(self, raw: str, *, pod: bool = False) -> Normalised | None:
        """Steps 1–7 of 01 §3.4 for one raw name; None if the row is to be dropped (a sidecar in
        `drop_containers`). `pod` marks values read from a pod-name field (`pod_name`,
        `k8s.pod.name`): their generated suffix is stripped and the full pod name kept as component.
        A folded suffix keeps the unfolded name as component (`carts-db` -> carts / carts-db)."""
        original = raw.strip().lower()
        name = strip_pod_suffix(original) if pod else original
        service = self._canonical(name, raw)
        if {original, name, service} & self.drop_containers:
            return None
        unfolded = self._alias(name).replace("_", "-")
        if pod:
            component = original.replace("_", "-")
        elif unfolded != service and self._fold(unfolded) != unfolded:
            component = unfolded  # a folded suffix keeps the original, even when an alias then applies
        else:
            component = service
        return Normalised(service=_check(service, raw), component=_check(component, raw))
