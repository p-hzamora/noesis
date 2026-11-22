"""CatalogResourceQuery and CatalogResourceHit contracts (WP-08)."""

import json

import pytest
from pydantic import ValidationError

from noesis.shared_kernel.contracts.knowledge import (
    CatalogResourceHitContract,
    CatalogResourceQueryContract,
)

pytestmark = pytest.mark.unit

ID: str = f"{1:026d}"


def test_query_defaults_are_text_search_without_overlay() -> None:
    query = CatalogResourceQueryContract(space_id="s")

    assert (query.terms, query.kinds, query.runtimes, query.include_unsynced) == ((), (), (), False)
    assert query.contract_version == 1


def test_query_rejects_unknown_kind_runtime_and_out_of_range_limit() -> None:
    for bad in ({"kinds": ("tool",)}, {"runtimes": ("vim",)}, {"limit": 0}, {"limit": 101}):
        with pytest.raises(ValidationError):
            CatalogResourceQueryContract(space_id="s", **bad)  # type: ignore[arg-type]


def test_hit_without_an_entry_is_valid_and_json_native() -> None:
    hit = CatalogResourceHitContract(
        kind="skill", name="plug:x", purpose="p", cataloged=False, score=0.5
    )

    dumped = json.loads(hit.model_dump_json())

    assert (dumped["catalog_id"], dumped["revision"], dumped["cataloged"]) == (None, None, False)
    assert dumped["origin"] == "registered"


@pytest.mark.parametrize("overrides", [{"catalog_id": "nope"}, {"score": 1.5}, {"kind": "tool"}])
def test_hit_rejects_malformed_values(overrides: dict[str, object]) -> None:
    values: dict[str, object] = {
        "catalog_id": ID,
        "kind": "skill",
        "name": "x",
        "purpose": "p",
        "cataloged": True,
        "score": 0.5,
    }

    with pytest.raises(ValidationError):
        CatalogResourceHitContract(**{**values, **overrides})  # type: ignore[arg-type]
