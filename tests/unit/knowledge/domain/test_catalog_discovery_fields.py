"""Discovery fields of a catalog revision: defaults, equality of head content, old-node reads (WP-06)."""

import pytest
from tests.support.knowledge_support import AGENT, NOW

from noesis.bounded_context.knowledge.domain.entities import CatalogEntry
from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogEntryKindEnum,
    CatalogOriginEnum,
    ContentHash,
    RecordId,
    SourceKindEnum,
    SpaceId,
    Tag,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.persistence.mappers.catalog_entry_node_mapper import (
    CatalogEntryNodeMapper,
)

pytestmark = pytest.mark.unit

DIGEST: ContentHash = ContentHash.of(b"manifest")


def _entry(**extra: object) -> CatalogEntry:
    return CatalogEntry.create(
        id=RecordId(value=f"{1:026d}"),
        space_id=SpaceId(value=f"{9:026d}"),
        kind=CatalogEntryKindEnum.SKILL,
        name="plug:demo",
        purpose="Demo",
        location="claude-code:plug:demo",
        actor=AGENT,
        source_ids=(RecordId(value=f"{2:026d}"),),
        now=NOW,
        **extra,  # type: ignore[arg-type]
    )


def test_new_fields_default_to_empty_capabilities_no_digest_and_registered() -> None:
    head = _entry().head

    assert (head.capabilities, head.manifest_digest, head.origin) == (
        frozenset(),
        None,
        CatalogOriginEnum.REGISTERED,
    )


def test_manifest_is_a_source_kind() -> None:
    assert SourceKindEnum("manifest") is SourceKindEnum.MANIFEST


def test_head_has_content_compares_capabilities_digest_and_origin() -> None:
    entry = _entry(
        capabilities=frozenset({Tag(value="cli")}),
        manifest_digest=DIGEST,
        origin=CatalogOriginEnum.DISCOVERED,
    )
    head = entry.head
    base = {
        "purpose": head.purpose,
        "version": head.version,
        "prerequisites": head.prerequisites,
        "location": head.location,
        "capabilities": head.capabilities,
        "manifest_digest": head.manifest_digest,
        "origin": head.origin,
    }

    assert entry.head_has_content(**base)
    assert not entry.head_has_content(**{**base, "capabilities": frozenset()})
    assert not entry.head_has_content(**{**base, "manifest_digest": ContentHash.of(b"other")})
    assert not entry.head_has_content(**{**base, "origin": CatalogOriginEnum.REGISTERED})


def test_revise_carries_the_new_fields_on_the_new_head() -> None:
    entry = _entry()

    revision = entry.revise(
        expected_revision=1,
        purpose="Demo",
        version=None,
        prerequisites=(),
        location="claude-code:plug:demo",
        actor=AGENT,
        source_ids=(RecordId(value=f"{2:026d}"),),
        now=NOW,
        capabilities=frozenset({Tag(value="cli"), Tag(value="python")}),
        manifest_digest=DIGEST,
        origin=CatalogOriginEnum.DISCOVERED,
    )

    assert revision.manifest_digest == DIGEST
    assert {tag.value for tag in revision.capabilities} == {"cli", "python"}
    assert entry.head.origin is CatalogOriginEnum.DISCOVERED


def test_revision_round_trips_through_node_properties() -> None:
    entry = _entry(
        capabilities=frozenset({Tag(value="cli"), Tag(value="facet:name")}),
        manifest_digest=DIGEST,
        origin=CatalogOriginEnum.DISCOVERED,
    )

    props = CatalogEntryNodeMapper.to_revision_properties(entry.id, entry.name, entry.head)

    assert props["name"] == "plug:demo"
    assert props["capabilities_text"] == "cli facet:name"
    assert CatalogEntryNodeMapper.to_revision(props) == entry.head


def test_node_written_before_the_discovery_fields_reads_with_defaults() -> None:
    entry = _entry()
    legacy = dict(CatalogEntryNodeMapper.to_revision_properties(entry.id, entry.name, entry.head))
    for key in ("name", "capabilities", "capabilities_text", "manifest_digest", "origin"):
        legacy.pop(key, None)

    revision = CatalogEntryNodeMapper.to_revision(legacy)

    assert (revision.capabilities, revision.manifest_digest, revision.origin) == (
        frozenset(),
        None,
        CatalogOriginEnum.REGISTERED,
    )
