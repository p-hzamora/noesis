"""CatalogEntryNodeMapper: the stored key is the aggregate's own `catalog_key`."""

import pytest
from tests.support.knowledge_support import AGENT, NOW

from noesis.bounded_context.knowledge.domain.entities import CatalogEntry
from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogEntryKindEnum,
    RecordId,
    SpaceId,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence.mappers.catalog_entry_node_mapper import (
    CatalogEntryNodeMapper,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence.mappers.node_keys import (
    catalog_key,
)

pytestmark = pytest.mark.unit


def test_entity_key_node_key_helper_and_stored_property_are_the_same_string() -> None:
    space: SpaceId = SpaceId(value=f"{99:026d}")
    entry: CatalogEntry = CatalogEntry.create(
        id=RecordId(value=f"{1:026d}"),
        space_id=space,
        kind=CatalogEntryKindEnum.CLI_TOOL,
        name="gh",
        purpose="GitHub CLI",
        location="https://github.com/cli/cli",
        actor=AGENT,
        source_ids=(RecordId(value=f"{2:026d}"),),
        now=NOW,
    )

    stored: object = CatalogEntryNodeMapper.to_properties(entry)["catalog_key"]

    assert stored == entry.catalog_key == catalog_key(space, entry.kind, entry.name.value)
