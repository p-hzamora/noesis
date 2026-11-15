"""CatalogAvailability request and result contracts (FR-011; AC-015, Q-010 default)."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from noesis.shared_kernel.contracts.knowledge import (
    CatalogAvailabilityEntryContract,
    CatalogAvailabilityRequestContract,
    CatalogAvailabilityResultContract,
    CatalogAvailabilityRuntimeContract,
)

pytestmark = pytest.mark.unit

ID_ONE: str = f"{1:026d}"
ID_TWO: str = f"{2:026d}"
JSON_NATIVE: tuple[type, ...] = (str, int, bool, type(None), list, dict)


def entry(entry_id: str, status: str, reason: str, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "entry_id": entry_id,
        "kind": "skill",
        "name": f"demo-{status}",
        "purpose": "Demo",
        "declared_version": "1.0.0",
        "location": "plugin@market",
        "status": status,
        "reason": reason,
        "observed_version": None,
        "version_drift": None,
        "missing_prerequisites": [],
    }
    return {**values, **overrides}


def make_result() -> CatalogAvailabilityResultContract:
    entries = [
        entry(ID_ONE, "available", "none", observed_version="1.0.1", version_drift=True),
        entry(ID_TWO, "unavailable", "prerequisite_missing", missing_prerequisites=["cli_tool:x"]),
        entry("0" * 26, "unknown", "kind_not_probed"),
    ]
    return CatalogAvailabilityResultContract(
        outcome="checked",
        reason_code=None,
        runtimes=[
            {
                "runtime": "claude-code",
                "host": "box-1",
                "observed_at": "2026-11-14T12:00:00+00:00",
                "entries": entries,
            }
        ],
    )


def assert_json_native(value: object) -> None:
    assert isinstance(value, JSON_NATIVE), type(value)
    if isinstance(value, list):
        for item in value:
            assert_json_native(item)
    if isinstance(value, dict):
        for key, item in value.items():
            assert isinstance(key, str)
            assert_json_native(item)


def test_ac015_availability_contracts_round_trip() -> None:
    request = CatalogAvailabilityRequestContract(
        space_id="0" * 25 + "1", entry_ids=[ID_ONE, ID_TWO], runtimes=["claude-code", "codex"]
    )
    result = make_result()

    for model in (request, result):
        assert model.contract_version == 1
        assert type(model).model_validate_json(model.model_dump_json()) == model
        assert_json_native(model.model_dump(mode="json"))
        assert json.loads(model.model_dump_json()) == model.model_dump(mode="json")
    (block,) = result.runtimes
    assert isinstance(block, CatalogAvailabilityRuntimeContract)
    assert [type(e) for e in block.entries] == [CatalogAvailabilityEntryContract] * 3
    assert [e.status for e in block.entries] == ["available", "unavailable", "unknown"]
    assert block.entries[0].version_drift is True
    assert block.entries[0].observed_version == "1.0.1"
    assert list(block.entries[1].missing_prerequisites) == ["cli_tool:x"]


def test_result_exposes_exactly_the_published_entry_fields() -> None:
    (block,) = make_result().model_dump(mode="json")["runtimes"]

    assert set(block) == {"runtime", "host", "observed_at", "entries"}
    assert set(block["entries"][0]) == {
        "entry_id",
        "kind",
        "name",
        "purpose",
        "declared_version",
        "location",
        "status",
        "reason",
        "observed_version",
        "version_drift",
        "missing_prerequisites",
    }


def test_not_checked_result_carries_a_reason_code_and_no_runtimes() -> None:
    result = CatalogAvailabilityResultContract(
        outcome="not_checked", reason_code="runtime_unresolved", runtimes=[]
    )

    assert CatalogAvailabilityResultContract.model_validate_json(result.model_dump_json()) == result
    assert result.reason_code == "runtime_unresolved"
    assert list(result.runtimes) == []


def test_request_requires_the_space_id() -> None:
    """Q-010 default."""
    with pytest.raises(ValidationError):
        CatalogAvailabilityRequestContract(  # type: ignore[call-arg]
            entry_ids=[ID_ONE], runtimes=["claude-code"]
        )


def test_request_accepts_an_empty_runtimes_list() -> None:
    request = CatalogAvailabilityRequestContract(
        space_id="0" * 25 + "1", entry_ids=[ID_ONE], runtimes=[]
    )

    assert list(request.runtimes) == []


@pytest.mark.parametrize("model", ["request", "result"])
def test_contract_version_other_than_one_is_rejected(model: str) -> None:
    payload: dict[str, Any] = (
        {"space_id": "0" * 25 + "1", "entry_ids": [], "runtimes": []}
        if model == "request"
        else {"outcome": "not_checked", "reason_code": "runtime_unresolved", "runtimes": []}
    )
    contract = (
        CatalogAvailabilityRequestContract
        if model == "request"
        else CatalogAvailabilityResultContract
    )

    with pytest.raises(ValidationError):
        contract.model_validate({**payload, "contract_version": 2})


@pytest.mark.parametrize("entry_id", ["skill:demo", "gh", "", "0" * 25, f"{1:026d}x"])
def test_request_rejects_an_entry_id_that_is_not_a_ulid(entry_id: str) -> None:
    with pytest.raises(ValidationError):
        CatalogAvailabilityRequestContract(
            space_id="0" * 25 + "1", entry_ids=[entry_id], runtimes=["codex"]
        )
