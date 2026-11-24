"""The live-demo fault file (lab/demo/, docs/06-live-demo.md) is the catalog's own F04 injection."""

from pathlib import Path

import yaml
from vlab.faults import get_fault, injection

DEMO = Path(__file__).resolve().parent.parent / "demo" / "f04-currencyservice-l1.yaml"


def test_demo_manifest_is_the_catalog_f04_l1_injection() -> None:
    fault = get_fault("F04", "currencyservice", "L1")
    built = injection(
        fault,
        target="currencyservice",
        severity="L1",
        name="vl-demo-f04",
        namespace="veyllab-app",
        duration_s=600,
    )
    assert built.apply_args == ()
    assert [yaml.safe_load(DEMO.read_text(encoding="utf-8"))] == list(built.manifests)
