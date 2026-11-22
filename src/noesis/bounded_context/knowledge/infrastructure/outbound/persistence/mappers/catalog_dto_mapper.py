"""Read side: catalog entry and revision nodes -> DTOs."""

from noesis.bounded_context.knowledge.application.dtos import (
    CatalogEntryDetailDto,
    CatalogEntryDto,
)
from noesis.bounded_context.knowledge.domain.value_objects import CatalogOriginEnum

from .node_properties import NodeProperties


class CatalogDtoMapper:
    """Builds the DTOs `ICatalogEntryReadRepository` returns."""

    @staticmethod
    def to_entry_dto(entry: NodeProperties, revision: NodeProperties) -> CatalogEntryDto:
        """The entry with the content of `revision` (its head, for a listing)."""
        return CatalogEntryDto(
            id=entry["id"],
            space_id=entry["space_id"],
            kind=entry["entry_kind"],
            name=entry["name"],
            head_revision=entry["head_revision"],
            purpose=revision["purpose"],
            declared_version=revision.get("declared_version"),
            prerequisites=tuple(revision["prerequisites"]),
            location=revision["location"],
            capabilities=tuple(revision.get("capabilities") or ()),
            manifest_digest=revision.get("manifest_digest"),
            origin=revision.get("origin") or CatalogOriginEnum.REGISTERED,
        )

    @staticmethod
    def to_detail_dto(entry: NodeProperties, revision: NodeProperties) -> CatalogEntryDetailDto:
        """The entry with one revision's content and envelope."""
        return CatalogEntryDetailDto(
            **CatalogDtoMapper.to_entry_dto(entry, revision).model_dump(),
            number=revision["number"],
            actor_kind=revision["actor_kind"],
            actor_name=revision["actor_name"],
            actor_session=revision.get("actor_session"),
            created_at=revision["created_at"],
            source_ids=tuple(revision["source_ids"]),
        )
