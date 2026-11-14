"""Pins and command builders for the `ob` profile.

Every kubectl and helm command names the kind context explicitly, so the lab can never act on
another cluster the laptop is configured for (lab/AGENTS.md: faults stay in the local lab).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from vlab import LAB_DIR

OB_DIR = LAB_DIR / "ob"
PINS_FILE = OB_DIR / "pins.yaml"


def load_pins(path: Path = PINS_FILE) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        pins: dict[str, Any] = yaml.safe_load(fh)
    return pins


def context(pins: Mapping[str, Any]) -> str:
    return f"kind-{pins['cluster_name']}"


def kubectl(pins: Mapping[str, Any], *args: str) -> list[str]:
    return ["kubectl", "--context", context(pins), *args]


def helm(pins: Mapping[str, Any], *args: str) -> list[str]:
    return ["helm", "--kube-context", context(pins), *args]


def node_exec(pins: Mapping[str, Any], script: str) -> list[str]:
    """A shell command inside the kind node container."""
    return ["docker", "exec", str(pins["node_container"]), "sh", "-c", script]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def manifest_path(pins: Mapping[str, Any]) -> Path:
    return OB_DIR / str(pins["online_boutique"]["manifest"])


def sums_path(pins: Mapping[str, Any]) -> Path:
    return manifest_path(pins).parent / "SHA256SUMS"


def manifest_problem(pins: Mapping[str, Any]) -> str | None:
    """Why the vendored OB manifest cannot be used, or None if it matches SHA256SUMS."""
    manifest, sums = manifest_path(pins), sums_path(pins)
    if not manifest.is_file() or not sums.is_file():
        return f"{manifest.relative_to(LAB_DIR)} is not vendored yet: run `lab/up.py --vendor`"
    expected = sums.read_text(encoding="utf-8").split()[0]
    actual = sha256_file(manifest)
    if actual != expected:
        return f"{manifest.name} hash {actual} does not match SHA256SUMS {expected}"
    return None


def deployments(pins: Mapping[str, Any]) -> list[str]:
    """Names of the app Deployments in the vendored OB manifest, sorted ([] if it is absent)."""
    path = manifest_path(pins)
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as fh:
        return sorted(
            str(doc["metadata"]["name"])
            for doc in yaml.safe_load_all(fh)
            if isinstance(doc, dict) and doc.get("kind") == "Deployment"
        )


def cpu_limits(pins: Mapping[str, Any], field: str = "limits") -> dict[str, str]:
    """CPU limit of each Deployment's first container in the vendored OB manifest ({} if absent).

    F11 cuts the target's limit and restores exactly this value, so the restore never depends on
    reading the live cluster.
    """
    path = manifest_path(pins)
    if not path.is_file():
        return {}
    limits: dict[str, str] = {}
    with path.open(encoding="utf-8") as fh:
        for doc in yaml.safe_load_all(fh):
            if isinstance(doc, dict) and doc.get("kind") == "Deployment":
                container = doc["spec"]["template"]["spec"]["containers"][0]
                cpu = container.get("resources", {}).get(field, {}).get("cpu")
                if cpu is not None:
                    limits[str(doc["metadata"]["name"])] = str(cpu)
    return limits
