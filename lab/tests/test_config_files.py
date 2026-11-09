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
    assert container["image"] == load_pins()["collector"]["image"]


def test_scrub_drops_chaos_and_flag_keys() -> None:
    processors = _collector_config()["processors"]
    text = yaml.safe_dump(processors)
    assert "chaos-mesh" in yaml.safe_dump(processors["filter/scrub"])
    assert "feature_flag" in text
    assert "flagd" in text


def test_kind_frontend_is_local_only() -> None:
    (cluster,) = _docs("kind.yaml")
    assert cluster["name"] == load_pins()["cluster_name"]
    (mapping,) = cluster["nodes"][0]["extraPortMappings"]
    assert mapping["listenAddress"] == "127.0.0.1"


def test_overlay_patches_exist() -> None:
    (kust,) = _docs("overlay/kustomization.yaml")
    assert kust["namespace"] == load_pins()["app_namespace"]
    for patch in kust["patches"]:
        assert (OB_DIR / "overlay" / patch["path"]).is_file()
