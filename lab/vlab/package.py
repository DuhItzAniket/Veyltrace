"""Package a raw capture for Infralume's `veyllab` adapter (05 §9, §10, §11).

Output: ``<data root>/veyllab/<dataset>/<capture_id>/`` with ``otlp/{traces,metrics,logs}.jsonl``
(scrubbed, protobuf-JSON mapping), ``events.jsonl`` (``telemetry.events`` rows, 03 §2.5),
``oracle_alert.json`` and ``capture.json``. Nothing in it names a fault, target or tool: every file
is post-scanned against the deny-list and any hit removes the package.
"""

from __future__ import annotations

import getpass
import json
import re
import shutil
import socket
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from vlab.answer_key import canonical_json

SIGNALS = {"traces": "resourceSpans", "metrics": "resourceMetrics", "logs": "resourceLogs"}
RECORDS = {"resourceSpans": ("scopeSpans", "spans"), "resourceMetrics": ("scopeMetrics", "metrics"),
           "resourceLogs": ("scopeLogs", "logRecords")}  # fmt: skip
#: 05 §11 deny-list: tools, CRD kinds and words that would reveal an injection, plus every
#: OpenTelemetry Demo flag key named in 05 §6. Word-start matches, so "default" is not "fault".
DENY_TOKENS = ("chaos", "stress-ng", "netem", "inject", "fault", "decoy")
FLAG_KEYS = ("emailMemoryLeak", "recommendationCacheFailure", "paymentFailure", "cartFailure", "adFailure",
             "productCatalogFailure", "productCatalogLockContention", "kafkaQueueProblems")  # fmt: skip
#: Artefacts of how a tool injects, not of the fault itself: Chaos Mesh pod-failure swaps the
#: container image for this placeholder, and kubelet then logs pulling it (seen on the live F08 run).
TOOL_ARTEFACTS = ("google-containers/pause",)
_WORDS = "|".join(map(re.escape, DENY_TOKENS + FLAG_KEYS))
DENY = re.compile(rf"(?i)\b(?:{_WORDS})|" + "|".join(map(re.escape, TOOL_ARTEFACTS)))
DROP_ATTR = re.compile(r"^(feature_flag\.|chaos-mesh\.org/)")
DROP_NAMESPACES = frozenset({"chaos-mesh"})
DROP_SERVICES = frozenset({"flagd"})
#: k8s Event reasons that record a container or pod stopping (05 §7: restart records). A failed
#: probe (Unhealthy) is not a restart: it stays a k8s_event, and the Killing that may follow is one.
RESTART_REASONS = frozenset({"Killing", "BackOff", "OOMKilling"})


def _attrs(items: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items or ():
        value = item.get("value", {})
        out[str(item["key"])] = next(iter(value.values()), None) if value else None
    return out


def _strip(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [a for a in items or [] if not DROP_ATTR.match(str(a.get("key", "")))]


def any_value(v: Mapping[str, Any]) -> Any:
    """OTLP AnyValue (protobuf-JSON mapping) to plain Python."""
    if "kvlistValue" in v:
        return {x["key"]: any_value(x.get("value", {})) for x in v["kvlistValue"].get("values", [])}
    if "arrayValue" in v:
        return [any_value(x) for x in v["arrayValue"].get("values", [])]
    if "intValue" in v:
        return int(v["intValue"])
    return next(iter(v.values()), None) if v else None


@dataclass
class Report:
    dropped_resources: int = 0
    dropped_log_records: int = 0
    events: int = 0
    lab_records: int = 0
    deny_hits: list[str] = field(default_factory=list[str])
    #: (deployment, generation) already emitted: kubectl and the controller each send one update
    #: per spec change (seen on the live F11 run), and only the first is the change.
    seen_changes: set[tuple[str, int]] = field(default_factory=set[tuple[str, int]])


@dataclass
class Context:
    """What scrubbing needs to know about the capture."""

    app_namespace: str
    t_capture_start_ns: int
    services: tuple[str, ...]
    replacements: tuple[tuple[str, str], ...] = ()


def host_replacements() -> tuple[tuple[str, str], ...]:
    """Windows user name, host name and LAN IPs → fixed placeholders (05 §11 host identity)."""
    pairs: list[tuple[str, str]] = []
    for value, placeholder in ((getpass.getuser(), "veyllab-user"), (socket.gethostname(), "veyllab-host")):
        if len(value) >= 3:
            pairs.append((value, placeholder))
    try:
        ips = socket.gethostbyname_ex(socket.gethostname())[2]
    except OSError:
        ips = []
    pairs += [(ip, "192.0.2.1") for ip in ips if not ip.startswith("127.")]  # RFC 5737 documentation IP
    return tuple(sorted(pairs, key=lambda p: -len(p[0])))


def service_of(name: str, services: tuple[str, ...]) -> str:
    """Deployment behind a pod / ReplicaSet name: the longest service that prefixes it plus '-'."""
    best = [s for s in services if name == s or name.startswith(f"{s}-")]
    return max(best, key=len) if best else name


def _event(t_ns: int, entity: str, kind: str, detail: Mapping[str, Any]) -> dict[str, Any]:
    return {"t_ns": t_ns, "entity": entity, "kind": kind, "source_system": "k8s",
            "detail_json": canonical_json(dict(detail))}  # fmt: skip


def _deployment_event(obj: Mapping[str, Any], t_ns: int, ctx: Context) -> dict[str, Any] | None:
    """A spec change (generation ahead of observedGeneration) as a deploy / config / restart row."""
    meta = obj.get("metadata", {})
    if meta.get("namespace") != ctx.app_namespace:
        return None
    generation = int(meta.get("generation", 0))
    if generation <= int(obj.get("status", {}).get("observedGeneration", generation)):
        return None
    entries = [e for e in meta.get("managedFields", []) or [] if e.get("operation") == "Update"]
    latest = max(entries, key=lambda e: str(e.get("time", "")), default={})
    fields = json.dumps(latest.get("fieldsV1", {}))
    kind = "deploy" if '"f:image"' in fields else "restart" if "restartedAt" in fields else "config"
    changed = sorted({k for k in ("image", "env", "resources", "replicas") if f'"f:{k}"' in fields})
    detail = {"generation": generation, "manager": latest.get("manager"), "fields": changed}
    return _event(t_ns, str(meta.get("name")), kind, detail)


def _k8s_event(obj: Mapping[str, Any], ctx: Context) -> dict[str, Any] | None:
    involved = obj.get("involvedObject", {}) or obj.get("regarding", {})
    if involved.get("namespace", obj.get("metadata", {}).get("namespace")) != ctx.app_namespace:
        return None
    if "chaos-mesh.org" in str(involved.get("apiVersion", "")):
        return None
    stamp = (
        obj.get("lastTimestamp") or obj.get("eventTime") or obj.get("metadata", {}).get("creationTimestamp")
    )
    t_ns = _rfc3339_ns(str(stamp)) if stamp else 0
    if t_ns < ctx.t_capture_start_ns:  # replays of events from before the capture
        return None
    reason = str(obj.get("reason", ""))
    return _event(t_ns, service_of(str(involved.get("name", "")), ctx.services),
                  "restart" if reason in RESTART_REASONS else "k8s_event",
                  {"reason": reason, "type": obj.get("type"), "object_kind": involved.get("kind"),
                   "message": obj.get("message") or obj.get("note")})  # fmt: skip


def _rfc3339_ns(text: str) -> int:
    """'2026-11-09T08:14:04Z' or with a fraction → ns since the epoch (UTC)."""
    frac = ""
    base = text.rstrip("Z")
    if "." in base:
        base, frac = base.split(".", 1)
    seconds = int(datetime.fromisoformat(base + "+00:00").timestamp())
    return seconds * 1_000_000_000 + int((frac + "000000000")[:9])


def scrub_request(
    req: dict[str, Any], signal: str, ctx: Context, report: Report, events: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Scrub one export request in place; k8sobjects records move to ``events``. None if empty."""
    key = SIGNALS[signal]
    scope_key, rec_key = RECORDS[key]
    kept_resources = []
    for res in req.get(key, []):
        r_attrs = _attrs(res.get("resource", {}).get("attributes"))
        if (
            r_attrs.get("k8s.namespace.name") in DROP_NAMESPACES
            or r_attrs.get("service.name") in DROP_SERVICES
        ):
            report.dropped_resources += 1
            continue
        res.setdefault("resource", {})["attributes"] = _strip(res.get("resource", {}).get("attributes"))
        for scope in res.get(scope_key, []):
            kept = []
            for rec in scope.get(rec_key, []):
                if "attributes" in rec:
                    rec["attributes"] = _strip(rec["attributes"])
                if signal == "logs":
                    body = rec.get("body", {})
                    rec_attrs = _attrs(rec.get("attributes"))
                    if "kvlistValue" in body and rec_attrs.get("event.domain") == "k8s":
                        obj = any_value(body).get("object", {})
                        t_ns = int(rec.get("timeUnixNano") or rec.get("observedTimeUnixNano") or 0)
                        row = (_deployment_event(obj, t_ns, ctx) if obj.get("kind") == "Deployment"
                               else _k8s_event(obj, ctx))  # fmt: skip
                        change = None
                        if row is not None and obj.get("kind") == "Deployment":
                            change = (row["entity"], int(json.loads(row["detail_json"])["generation"]))
                        if row is None or change in report.seen_changes:
                            report.lab_records += 1
                        elif DENY.search(row["detail_json"]):  # e.g. pulling the pod-failure placeholder
                            report.dropped_log_records += 1
                        else:
                            events.append(row)
                            if change is not None:
                                report.seen_changes.add(change)
                        continue
                    if DENY.search(json.dumps(body)):  # e.g. kube-apiserver naming a chaos CRD
                        report.dropped_log_records += 1
                        continue
                kept.append(rec)
            scope[rec_key] = kept
        res[scope_key] = [s for s in res.get(scope_key, []) if s.get(rec_key)]
        if res[scope_key]:
            kept_resources.append(res)
    req[key] = kept_resources
    return req if kept_resources else None


def _replace(text: str, ctx: Context) -> str:
    for value, placeholder in ctx.replacements:
        text = text.replace(value, placeholder)
    return text


def signal_files(otlp_dir: Path, signal: str) -> list[Path]:
    """Rotated backups (``<signal>-<timestamp>.jsonl``) in name order, then the active file."""
    rotated = sorted(otlp_dir.glob(f"{signal}-*.jsonl"))
    active = otlp_dir / f"{signal}.jsonl"
    return rotated + ([active] if active.is_file() else [])


def iter_requests(paths: Iterable[Path]) -> Iterator[dict[str, Any]]:
    for path in paths:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    yield json.loads(line)


def deny_scan(folder: Path) -> list[str]:
    """Every deny-listed token in any packaged file or path, as ``file:line: token``."""
    hits: list[str] = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = path.relative_to(folder).as_posix()
        if m := DENY.search(rel):
            hits.append(f"{rel}: path: {m.group(0)}")
        with path.open(encoding="utf-8") as fh:
            for n, line in enumerate(fh, 1):
                hits += [f"{rel}:{n}: {token}" for token in sorted({m.group(0) for m in DENY.finditer(line)})]
    return hits


def package_capture(
    capture_dir: Path, t_alert_ns: int, out_dir: Path, ctx: Context, system: str = "ob"
) -> Report:
    """Write the packaged capture to ``out_dir``; remove it again and report hits if the scan fails.
    ``t_alert_ns`` is the oracle hint: the injection time, or a no-fault control's reference time."""
    report = Report()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "otlp").mkdir(parents=True)
    events: list[dict[str, Any]] = []
    for signal in SIGNALS:
        with (out_dir / "otlp" / f"{signal}.jsonl").open("w", encoding="utf-8", newline="\n") as out:
            for req in iter_requests(signal_files(capture_dir / "otlp", signal)):
                kept = scrub_request(req, signal, ctx, report, events)
                if kept is not None:
                    out.write(_replace(json.dumps(kept, separators=(",", ":")), ctx) + "\n")
    events.sort(key=lambda e: (e["t_ns"], e["entity"], e["kind"], e["detail_json"]))
    report.events = len(events)
    with (out_dir / "events.jsonl").open("w", encoding="utf-8", newline="\n") as out:
        for row in events:
            out.write(_replace(canonical_json(row), ctx) + "\n")
    (out_dir / "oracle_alert.json").write_text(
        canonical_json({"t_alert_ns": t_alert_ns}) + "\n", encoding="utf-8", newline="\n"
    )
    (out_dir / "capture.json").write_text(
        canonical_json({"capture_id": out_dir.name, "system": system}) + "\n", encoding="utf-8", newline="\n"
    )
    report.deny_hits = deny_scan(out_dir)
    if report.deny_hits:
        shutil.rmtree(out_dir)
    return report
