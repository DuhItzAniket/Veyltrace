"""05 §13: packager on a tiny synthetic OTLP capture; planted leaks must fail packaging."""

import json
from pathlib import Path
from typing import Any

from vlab.package import Context, package_capture, service_of

T0 = 1_800_000_000_000_000_000  # capture start, ns
SERVICES = ("frontend", "cartservice", "redis-cart")
CTX = Context("veyllab-app", T0, SERVICES, (("SCM Testing", "veyllab-user"),))


def _kv(d: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"key": k, "value": {"stringValue": v}} for k, v in d.items()]


def _any(v: Any) -> dict[str, Any]:
    if isinstance(v, dict):
        return {"kvlistValue": {"values": [{"key": k, "value": _any(x)} for k, x in v.items()]}}
    if isinstance(v, list):
        return {"arrayValue": {"values": [_any(x) for x in v]}}
    if isinstance(v, int):
        return {"intValue": str(v)}
    return {"stringValue": v}


def _span_req(res: dict[str, str], span_attrs: dict[str, str]) -> dict[str, Any]:
    span = {
        "name": "GET /",
        "kind": 2,
        "startTimeUnixNano": str(T0 + 1),
        "endTimeUnixNano": str(T0 + 2),
        "attributes": _kv(span_attrs),
    }
    return {"resourceSpans": [{"resource": {"attributes": _kv(res)}, "scopeSpans": [{"spans": [span]}]}]}


def _log_req(res: dict[str, str], records: list[dict[str, Any]]) -> dict[str, Any]:
    return {"resourceLogs": [{"resource": {"attributes": _kv(res)}, "scopeLogs": [{"logRecords": records}]}]}


def _k8s_record(obj: dict[str, Any], t_ns: int) -> dict[str, Any]:
    return {
        "observedTimeUnixNano": str(t_ns),
        "body": _any({"type": "MODIFIED", "object": obj}),
        "attributes": _kv({"event.domain": "k8s", "event.name": obj["metadata"]["name"]}),
    }


def _deployment(name: str, ns: str, generation: int, observed: int, fields: dict[str, Any]) -> dict[str, Any]:
    managed = [
        {"manager": "kubectl-set", "operation": "Update", "time": "2026-11-09T10:00:00Z", "fieldsV1": fields}
    ]
    return {
        "kind": "Deployment",
        "metadata": {"name": name, "namespace": ns, "generation": generation, "managedFields": managed},
        "status": {"observedGeneration": observed},
    }


def _event_obj(reason: str, pod: str, stamp: str, ns: str = "veyllab-app") -> dict[str, Any]:
    return {
        "kind": "Event",
        "metadata": {"name": f"{pod}.1", "namespace": ns},
        "reason": reason,
        "type": "Normal",
        "message": "Stopping container server",
        "lastTimestamp": stamp,
        "involvedObject": {"kind": "Pod", "name": pod, "namespace": ns, "apiVersion": "v1"},
    }


def _write_capture(tmp: Path, extra_span_attrs: dict[str, str] | None = None) -> Path:
    cap = tmp / "raw" / ("c" * 32)
    (cap / "otlp").mkdir(parents=True)
    traces = [
        _span_req(
            {"service.name": "frontend", "k8s.namespace.name": "veyllab-app"},
            {"http.route": "/", "feature_flag.key": "x", **(extra_span_attrs or {})},
        ),
        _span_req({"service.name": "chaos-controller", "k8s.namespace.name": "chaos-mesh"}, {}),
    ]
    logs = [
        _log_req(
            {"k8s.namespace.name": "kube-system"},
            [
                {"body": {"stringValue": "quota admission added evaluator for: networkchaos.chaos-mesh.org"}},
                {"body": {"stringValue": "GET /healthz 200 from C:/Users/SCM Testing/x"}},
            ],
        ),
        _log_req(
            {"k8s.namespace.name": "veyllab-app"},
            [
                _k8s_record(
                    _deployment(
                        "frontend",
                        "veyllab-app",
                        5,
                        4,
                        {"f:spec": {"f:template": {"f:spec": {"f:containers": {"f:resources": {}}}}}},
                    ),
                    T0 + 10,
                ),
                _k8s_record(_deployment("frontend", "veyllab-app", 5, 5, {}), T0 + 11),  # status only
                _k8s_record(
                    _deployment("veyllab-collector", "veyllab-obs", 9, 8, {}), T0 + 12
                ),  # lab machinery
                _k8s_record(
                    _event_obj("Killing", "cartservice-6b4b97d848-w5png", "2027-01-15T08:00:01Z"), T0 + 13
                ),
                _k8s_record(_event_obj("Pulled", "frontend-1-2", "2020-01-01T00:00:00Z"), T0 + 14),  # replay
                _k8s_record(_event_obj("Unhealthy", "frontend-1-2", "2027-01-15T08:00:02Z"), T0 + 15),
                # Regression (live F08 run): pod-failure's placeholder image must not survive.
                _k8s_record(
                    {
                        **_event_obj("Pulling", "frontend-1-2", "2027-01-15T08:00:03Z"),
                        "message": 'Pulling image "gcr.io/google-containers/pause:latest"',
                    },
                    T0 + 16,
                ),
            ],
        ),
    ]
    for name, reqs in (("traces", traces), ("logs", logs), ("metrics", [])):
        (cap / "otlp" / f"{name}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in reqs), encoding="utf-8"
        )
    return cap


def test_scrubs_moves_change_records_and_writes_the_layout(tmp_path: Path) -> None:
    cap = _write_capture(tmp_path)
    out = tmp_path / "pkg" / cap.name
    report = package_capture(cap, {"t_inject_ns": T0 + 5}, out, CTX)
    assert report.deny_hits == []
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()) == [
        "capture.json",
        "events.jsonl",
        "oracle_alert.json",
        "otlp/logs.jsonl",
        "otlp/metrics.jsonl",
        "otlp/traces.jsonl",
    ]
    traces = (out / "otlp" / "traces.jsonl").read_text(encoding="utf-8")
    assert "feature_flag" not in traces and "chaos-mesh" not in traces and "/" in traces
    logs = (out / "otlp" / "logs.jsonl").read_text(encoding="utf-8")
    assert "healthz" in logs and "SCM Testing" not in logs and "veyllab-user" in logs
    assert report.dropped_log_records == 2  # the apiserver line and the placeholder-image pull
    assert report.dropped_resources == 1
    events = [json.loads(line) for line in (out / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(e["entity"], e["kind"], e["source_system"]) for e in events] == [
        ("frontend", "config", "k8s"),
        ("cartservice", "restart", "k8s"),
        ("frontend", "k8s_event", "k8s"),  # a failed probe is not a restart
    ]
    assert json.loads(events[0]["detail_json"])["fields"] == ["resources"]
    assert json.loads((out / "oracle_alert.json").read_text(encoding="utf-8")) == {"t_alert_ns": T0 + 5}
    assert json.loads((out / "capture.json").read_text(encoding="utf-8")) == {
        "capture_id": cap.name,
        "system": "ob",
    }


def test_a_planted_leak_fails_packaging_and_removes_the_package(tmp_path: Path) -> None:
    planted = {
        "note": "paymentFailure flag on",
        "tool": "stress-ng",
        "image": "gcr.io/google-containers/pause:1",
    }
    cap = _write_capture(tmp_path, planted)
    out = tmp_path / "pkg" / cap.name
    report = package_capture(cap, {"t_inject_ns": T0 + 5}, out, CTX)
    found = {hit.split(": ")[-1] for hit in report.deny_hits}
    assert found >= {"paymentFailure", "stress-ng", "google-containers/pause"}
    assert not out.exists()


def test_service_of_pod_and_replicaset_names() -> None:
    assert service_of("cartservice-6b4b97d848-w5png", SERVICES) == "cartservice"
    assert service_of("redis-cart-6fdc7894b7-cv2w9", SERVICES) == "redis-cart"
    assert service_of("frontend", SERVICES) == "frontend"
    assert service_of("unknown-pod", SERVICES) == "unknown-pod"
