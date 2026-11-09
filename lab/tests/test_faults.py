import pytest
from vlab.faults import CATALOG, OB_SERVICES, chaos_manifest, get_fault

#: 03 §1 closed vocabularies.
FAULT_CLASSES = {"cpu", "mem", "disk", "socket", "delay", "loss", "error", "exception", "availability",
                 "config", "dependency", "unknown"}  # fmt: skip
INDICATORS = {"cpu", "mem", "diskio", "socket", "latency", "error", "logs", "workload", "unknown"}


def test_catalog_uses_contract_vocabularies() -> None:
    for fault in CATALOG.values():
        assert fault.fault_class in FAULT_CLASSES
        assert fault.indicator in INDICATORS


def test_f01_stress_levels() -> None:
    fault = get_fault("F01", "productcatalogservice", "L2")
    m = chaos_manifest(fault, target="productcatalogservice", severity="L2", name="vl-1", namespace="ns",
                       duration_s=600)  # fmt: skip
    assert m["kind"] == "StressChaos"
    assert m["spec"]["stressors"] == {"cpu": {"workers": 2, "load": 100}}
    assert m["spec"]["selector"] == {"namespaces": ["ns"], "labelSelectors": {"app": "productcatalogservice"}}
    assert m["spec"]["duration"] == "600s"


def test_f04_delay_with_jitter() -> None:
    fault = get_fault("F04", "currencyservice", "L1")
    m = chaos_manifest(fault, target="currencyservice", severity="L1", name="vl-1", namespace="ns",
                       duration_s=60)  # fmt: skip
    assert m["kind"] == "NetworkChaos"
    assert m["spec"]["action"] == "delay"
    assert m["spec"]["delay"] == {"latency": "200ms", "jitter": "20ms", "correlation": "0"}


@pytest.mark.parametrize(
    ("fault_id", "target", "severity"),
    [("F99", "frontend", "L1"), ("F01", "loadgenerator", "L1"), ("F01", "redis-cart", "L1"),
     ("F01", "frontend", "L3")],
)  # fmt: skip
def test_rejects_unknown_fault_target_or_level(fault_id: str, target: str, severity: str) -> None:
    with pytest.raises(ValueError):
        get_fault(fault_id, target, severity)


def test_loadgenerator_is_never_a_target() -> None:
    assert "loadgenerator" not in OB_SERVICES
