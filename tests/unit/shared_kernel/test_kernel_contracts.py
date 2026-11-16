"""Kernel contracts published by C5a (AC-029, AC-030 static half)."""

from datetime import UTC, datetime
from typing import Literal, get_args, get_origin

import pytest
from pydantic import BaseModel, ValidationError

from noesis.shared_kernel.contracts.knowledge import (
    GraphNeighbourContract,
    IndexableRecordContract,
    RecordChangedContract,
    RecordHitContract,
    RecordStateContract,
)
from noesis.shared_kernel.contracts.retrieval import RecordSearchHitContract

pytestmark = pytest.mark.unit

C5A_CONTRACTS: list[type[BaseModel]] = [
    RecordChangedContract,
    RecordStateContract,
    IndexableRecordContract,
    RecordHitContract,
    GraphNeighbourContract,
    RecordSearchHitContract,
]


@pytest.mark.parametrize("contract", C5A_CONTRACTS, ids=lambda contract: contract.__name__)
def test_ac029_c5a_contracts(contract: type[BaseModel]) -> None:
    """Each contract carries `contract_version: Literal[1] = 1` and no other `*_version` field."""
    fields = contract.model_fields

    annotation = fields["contract_version"].annotation
    assert get_origin(annotation) is Literal
    assert get_args(annotation) == (1,)
    assert fields["contract_version"].default == 1
    assert [name for name in fields if name.endswith("_version")] == ["contract_version"]


def test_ac029_contracts_live_in_their_publisher_folder() -> None:
    for contract in (
        RecordChangedContract,
        RecordStateContract,
        IndexableRecordContract,
        RecordHitContract,
        GraphNeighbourContract,
    ):
        assert contract.__module__.startswith("noesis.shared_kernel.contracts.knowledge.")
    assert RecordSearchHitContract.__module__.startswith(
        "noesis.shared_kernel.contracts.retrieval."
    )


def test_ac030_indexable_record_body_is_a_required_str_without_file_fields() -> None:
    fields = IndexableRecordContract.model_fields

    assert fields["body"].annotation is str
    assert fields["body"].is_required()
    assert "content_hash" not in fields
    assert "file_locator" not in fields


def test_ac030_indexable_record_rejects_a_null_body() -> None:
    with pytest.raises(ValidationError):
        IndexableRecordContract(
            record_id="K",
            record_type="knowledge",
            subtype="decision",
            ownership="graph",
            revision=1,
            head_revision=1,
            status="proposed",
            project_id=None,
            tags=(),
            title="t",
            body=None,  # type: ignore[arg-type]
            revised_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def _change(change_kind: str) -> RecordChangedContract:
    return RecordChangedContract(
        event_id="e1",
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        sequence=1,
        space_id="S",
        record_id="K",
        record_type="knowledge",
        change_kind=change_kind,  # type: ignore[arg-type]
        revision=1,
        status="proposed",
    )


@pytest.mark.parametrize("change_kind", ["created", "revised", "status_changed"])
def test_record_changed_accepts_the_closed_change_kinds(change_kind: str) -> None:
    assert _change(change_kind).change_kind == change_kind


def test_record_changed_rejects_links_changed() -> None:
    """Wiki links are not data (D24): there is no link-set change kind."""
    with pytest.raises(ValidationError):
        _change("links_changed")
