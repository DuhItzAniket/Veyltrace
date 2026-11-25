"""Static checks on the committed `ob` profile files (05 §3, §11)."""

from typing import Any

import yaml
from vlab.cluster import OB_DIR, load_pins

SCRUB = ("filter/scrub", "transform/scrub")


def _docs(name: str) -> list[dict[str, Any]]:
    with (OB_DIR / name).open(encoding="utf-8") as fh:
        return [d for d in yaml.safe_load_all(fh) if d]


def _collector_config() -> dict[str, Any]:
    cm = next(d for d in _docs("collector.yaml") if d["kind"] == "ConfigMap")
    config: dict[str, Any] = yaml.safe_load(cm["data"]["config.yaml"])
    return config


def test_every_pipeline_scrubs_and_spools() -> None:
    pipelines = _collector_config()["service"]["pipelines"]
    assert set(pipelines) == {"traces", "metrics", "logs"}
    for signal, pipe in pipelines.items():
        assert all(p in pipe["processors"] for p in SCRUB), signal
        assert pipe["processors"][0] == "memory_limiter"
        assert pipe["exporters"] == [f"file/{signal}"]


def test_collector_is_single_replica_with_memory_limit() -> None:
    dep = next(d for d in _docs("collector.yaml") if d["kind"] == "Deployment")
    assert dep["spec"]["replicas"] == 1  # k8sobjects must run once (05 §3.3)
    container = dep["spec"]["template"]["spec"]["containers"][0]
    assert container["resources"]["limits"]["memory"] == "512Mi"
    pinned = load_pins()["collector"]
    assert container["image"] == f"{pinned['image']}@{pinned['digest']}"


def test_scrub_drops_chaos_and_flag_keys() -> None:
    processors = _collector_config()["processors"]
    text = yaml.safe_dump(processors)
    assert "chaos-mesh" in yaml.safe_dump(processors["filter/scrub"])
    assert "feature_flag" in text
    assert "flagd" in text


def test_kind_frontend_is_local_only() -> None:
    (cluster,) = _docs("kind.yaml")
    pins = load_pins()
    assert cluster["name"] == pins["cluster_name"]
    node = pins["kind_node"]
    assert cluster["nodes"][0]["image"] == f"{node['image']}@{node['digest']}"
    (mapping,) = cluster["nodes"][0]["extraPortMappings"]
    assert mapping["listenAddress"] == "127.0.0.1"


def test_overlay_patches_exist() -> None:
    (kust,) = _docs("overlay/kustomization.yaml")
    assert kust["namespace"] == load_pins()["app_namespace"]
    for patch in kust["patches"]:
        assert (OB_DIR / "overlay" / patch["path"]).is_file()
    # kustomize loads resources outside the overlay only as directories with a kustomization.
    for resource in kust["resources"]:
        if resource.startswith(".."):
            assert (OB_DIR / "overlay" / resource / "kustomization.yaml").is_file(), resource


def test_app_metrics_and_logs_are_named_by_their_deployment() -> None:
    """kubelet_stats and file_log resources carry no `service.name`, and Infralume drops a resource
    without one (01 §3.9), so every lab metric and log was dropped (#43). The pods are found by
    uid (their connection IP is the node's), and an app pod is named after its deployment."""
    config = _collector_config()
    association = config["processors"]["k8s_attributes"]["pod_association"]
    sources = [s for rule in association for s in rule["sources"]]
    assert {"from": "resource_attribute", "name": "k8s.pod.uid"} in sources
    assert {"from": "connection"} in sources  # OTLP pushed by the app keeps the IP association
    namespace = load_pins()["app_namespace"]
    transform = config["processors"]["transform/service_name"]
    assert set(transform) == {"error_mode", "metric_statements", "log_statements"}
    for signal in ("metric", "log"):
        [block] = transform[f"{signal}_statements"]
        assert block["context"] == "resource"
        [statement] = block["statements"]
        assert statement.startswith(
            'set(attributes["service.name"], attributes["k8s.deployment.name"]) where '
        )
        assert 'attributes["service.name"] == nil' in statement
        assert 'attributes["k8s.deployment.name"] != nil' in statement
        assert f'attributes["k8s.namespace.name"] == "{namespace}"' in statement
    pipelines = config["service"]["pipelines"]
    for signal in ("metrics", "logs"):
        procs = pipelines[signal]["processors"]
        order = [procs.index(p) for p in ("k8s_attributes", "transform/service_name", "filter/scrub")]
        assert order == sorted(order), signal
    assert "transform/service_name" not in pipelines["traces"]["processors"]
