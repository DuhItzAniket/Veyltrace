import pytest
from vlab import answer_key
from vlab.faults import CATALOG, CONTAINER, OB_SERVICES, get_fault, injection

from veyltrace_contracts.models import AnswerKeyRow

#: 03 §1 closed vocabularies.
FAULT_CLASSES = {
    "cpu",
    "mem",
    "disk",
    "socket",
    "delay",
    "loss",
    "error",
    "exception",
    "availability",
    "config",
    "dependency",
    "unknown",
}
INDICATORS = {"cpu", "mem", "diskio", "socket", "latency", "error", "logs", "workload", "unknown"}
MODES = {"resource", "network", "code", "change", "dependency", "unknown", None}


def _target(fault_id: str) -> str:
    return CATALOG[fault_id].targets[0]


def test_catalog_has_at_least_eight_fault_types_with_contract_vocabularies() -> None:
    assert len(CATALOG) >= 8  # X-06 acceptance
    for fault in CATALOG.values():
        assert fault.fault_class in FAULT_CLASSES
        assert fault.indicator in INDICATORS
        assert fault.mode in MODES


@pytest.mark.parametrize("fault_id", sorted(CATALOG))
@pytest.mark.parametrize("severity", ["L1", "L2"])
def test_every_entry_builds_an_injection_and_a_valid_answer_key(fault_id: str, severity: str) -> None:
    fault = get_fault(fault_id, _target(fault_id), severity)
    inj = injection(
        fault,
        target=_target(fault_id),
        severity=severity,
        name="vl-1",
        namespace="ns",
        duration_s=600,
        cpu_limit="200m",
    )
    assert inj.revert_args, "every fault can be removed"
    assert bool(inj.manifests) != bool(inj.apply_args)
    key = answer_key.build(
        capture_id="ab" * 16,
        dataset="veyllab-ob",
        root_service=_target(fault_id),
        root_component=CONTAINER[_target(fault_id)],
        fault_id=fault_id,
        fault_class=fault.fault_class,
        indicator=fault.indicator,
        mode=fault.mode,
        t_inject_ns=1,
        t_end_ns=2,
        injection={"fault_id": fault_id},
    )
    AnswerKeyRow.model_validate(key)


def test_f01_stress_and_f02_memory() -> None:
    cpu = injection(
        get_fault("F01", "frontend", "L2"),
        target="frontend",
        severity="L2",
        name="n",
        namespace="ns",
        duration_s=600,
    ).manifests[0]
    assert cpu is not None and cpu["spec"]["stressors"] == {"cpu": {"workers": 2, "load": 100}}
    mem = injection(
        get_fault("F02", "frontend", "L1"),
        target="frontend",
        severity="L1",
        name="n",
        namespace="ns",
        duration_s=600,
    ).manifests[0]
    assert mem is not None and mem["spec"]["stressors"] == {"memory": {"workers": 1, "size": "256MB"}}
    assert mem["spec"]["duration"] == "600s"


def test_f04_delay_and_f05_loss() -> None:
    delay = injection(
        get_fault("F04", "cartservice", "L1"),
        target="cartservice",
        severity="L1",
        name="n",
        namespace="ns",
        duration_s=60,
    ).manifests[0]
    assert delay is not None and delay["spec"]["delay"] == {
        "latency": "200ms",
        "jitter": "20ms",
        "correlation": "0",
    }
    loss = injection(
        get_fault("F05", "cartservice", "L2"),
        target="cartservice",
        severity="L2",
        name="n",
        namespace="ns",
        duration_s=60,
    ).manifests[0]
    assert loss is not None and loss["spec"]["loss"] == {"loss": "50", "correlation": "0"}


def test_kills_are_one_shot_at_l1_and_scheduled_at_l2() -> None:
    one = injection(
        get_fault("F06", "frontend", "L1"),
        target="frontend",
        severity="L1",
        name="n",
        namespace="ns",
        duration_s=600,
    )
    (kill,) = one.manifests
    assert kill["kind"] == "PodChaos"
    assert "duration" not in kill["spec"]
    rep = injection(
        get_fault("F07", "frontend", "L2"),
        target="frontend",
        severity="L2",
        name="n",
        namespace="ns",
        duration_s=600,
    )
    # Regression (2026-11-09 live run): a Schedule fires one period late, so L2 also kills at once.
    first, repeat = rep.manifests
    assert (first["kind"], first["metadata"]["name"]) == ("PodChaos", "n")
    assert (repeat["kind"], repeat["metadata"]["name"]) == ("Schedule", "n-r")
    assert repeat["spec"]["schedule"] == "@every 120s"
    assert repeat["spec"]["podChaos"] == first["spec"]
    assert first["spec"]["containerNames"] == ["server"]
    assert rep.revert_args == (
        ("-n", "ns", "delete", "schedules.chaos-mesh.org", "n-r", "--ignore-not-found"),
        ("-n", "ns", "delete", "podchaos", "n", "--ignore-not-found"),
    )


def test_f08_pod_failure_is_capped_by_its_level() -> None:
    m = injection(
        get_fault("F08", "frontend", "L1"),
        target="frontend",
        severity="L1",
        name="n",
        namespace="ns",
        duration_s=600,
    ).manifests[0]
    assert m is not None and m["spec"]["duration"] == "200s"


def test_f11_cuts_and_restores_the_manifest_cpu_limit() -> None:
    inj = injection(
        get_fault("F11", "frontend", "L1"),
        target="frontend",
        severity="L1",
        name="n",
        namespace="ns",
        duration_s=600,
        cpu_limit="200m",
    )
    assert inj.manifests == ()
    assert inj.apply_args[0][-1] == "--limits=cpu=50m"
    assert inj.revert_args[0][-1] == "--limits=cpu=200m"
    with pytest.raises(ValueError):
        injection(
            get_fault("F11", "frontend", "L1"),
            target="frontend",
            severity="L1",
            name="n",
            namespace="ns",
            duration_s=600,
        )


@pytest.mark.parametrize(
    ("fault_id", "target", "severity"),
    [
        ("F99", "frontend", "L1"),
        ("F01", "loadgenerator", "L1"),
        ("F01", "redis-cart", "L1"),
        ("F13", "frontend", "L1"),
        ("F01", "frontend", "L3"),
    ],
)
def test_rejects_unknown_fault_target_or_level(fault_id: str, target: str, severity: str) -> None:
    with pytest.raises(ValueError):
        get_fault(fault_id, target, severity)


def test_loadgenerator_is_never_a_target() -> None:
    assert "loadgenerator" not in OB_SERVICES
    assert all("loadgenerator" not in f.targets for f in CATALOG.values())


def test_f11_lowers_the_request_when_the_cut_limit_falls_below_it() -> None:
    # Regression (live run 2026-11-09): Kubernetes rejected limit 50m below the frontend's 100m request.
    from vlab.cluster import cpu_limits, load_pins

    pins = load_pins()
    limit, request = cpu_limits(pins)["frontend"], cpu_limits(pins, "requests")["frontend"]
    assert (limit, request) == ("200m", "100m")
    inj = injection(get_fault("F11", "frontend", "L1"), target="frontend", severity="L1", name="n",
                    namespace="ns", duration_s=600, cpu_limit=limit, cpu_request=request)  # fmt: skip
    assert inj.apply_args[0][-2:] == ("--limits=cpu=50m", "--requests=cpu=50m")
    assert inj.revert_args[0][-2:] == ("--limits=cpu=200m", "--requests=cpu=100m")
