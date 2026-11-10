import hashlib
import json
from pathlib import Path

import pytest
from vlab import answer_key

CAPTURE_ID = "0123456789abcdef0123456789abcdef"


def _key() -> dict[str, object]:
    injection = {
        "fault_id": "F01",
        "tool": "chaos-mesh/StressChaos",
        "tool_version": "2.8.7",
        "params": {"workers": 2, "load": 80},
        "severity": "L1",
        "seed": 7,
    }
    return answer_key.build(
        capture_id=CAPTURE_ID,
        dataset="veyllab-ob",
        root_service="productcatalogservice",
        root_component="server",
        fault_id="F01",
        fault_class="cpu",
        indicator="cpu",
        mode="resource",
        t_inject_ns=2_000,
        t_end_ns=3_000,
        injection=injection,
    )


def test_case_id_is_sha256_prefix_of_capture_id() -> None:
    assert answer_key.case_id(CAPTURE_ID) == hashlib.sha256(CAPTURE_ID.encode()).hexdigest()[:12]


def test_key_has_only_contract_columns_and_canonical_injection() -> None:
    key = _key()
    assert set(key) == answer_key.COLUMNS  # the contract model requires every column
    assert key["is_no_fault"] is False
    assert key["validated"] is None
    injection = str(key["injection_json"])
    assert injection == answer_key.canonical_json(json.loads(injection))
    assert set(json.loads(injection)) == {"fault_id", "tool", "tool_version", "params", "severity", "seed"}


def test_written_only_under_answer_keys(tmp_path: Path) -> None:
    path = answer_key.write(_key(), capture_id=CAPTURE_ID, captures_dir=tmp_path)
    assert path == tmp_path / "answer_keys" / f"{CAPTURE_ID}.json"
    assert not (tmp_path / CAPTURE_ID).exists()
    assert json.loads(path.read_text(encoding="utf-8"))["case_id"] == answer_key.case_id(CAPTURE_ID)


def test_refuses_a_path_outside_answer_keys(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        answer_key.write(_key(), capture_id=f"../{CAPTURE_ID}/x", captures_dir=tmp_path)


def test_key_validates_against_the_contract_model() -> None:
    # Regression: keys without `mode` failed AnswerKeyRow when packaging (every column is required).
    from veyltrace_contracts.models import AnswerKeyRow

    assert AnswerKeyRow.model_validate(_key()).mode == "resource"


def test_no_fault_key_has_null_roots_and_validates() -> None:
    from veyltrace_contracts.models import AnswerKeyRow

    key = answer_key.build_no_fault(
        capture_id=CAPTURE_ID,
        dataset="veyllab-ob",
        t_ref_ns=5,
        t_end_ns=6,
        injection={"fault_id": "F14", "seed": 1},
    )
    assert set(key) == answer_key.COLUMNS
    assert key["is_no_fault"] is True and key["root_service"] is None and key["fault_class"] is None
    assert AnswerKeyRow.model_validate(key).t_inject_ns == 5
