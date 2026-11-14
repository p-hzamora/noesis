"""Read side: record, revision and source nodes -> DTOs."""

from collections.abc import Sequence
from typing import Final

from noesis.bounded_context.knowledge.application.dtos import (
    ActorDto,
    ApplicabilityDto,
    RecordDto,
    RevisionDto,
    SourceDto,
)
from noesis.bounded_context.knowledge.domain.value_objects import RecordTypeEnum

from .node_properties import NodeProperties

TYPE_BY_LABEL: Final[dict[str, RecordTypeEnum]] = {
    "Knowledge": RecordTypeEnum.KNOWLEDGE,
    "Experience": RecordTypeEnum.EXPERIENCE,
    "Assertion": RecordTypeEnum.ASSERTION,
    "Source": RecordTypeEnum.SOURCE,
    "Project": RecordTypeEnum.PROJECT,
    "CatalogEntry": RecordTypeEnum.CATALOG_ENTRY,
}


def record_type_of(labels: Sequence[str]) -> RecordTypeEnum | None:
    """The record type named by a `:Record` node's second label, if known."""
    return next((TYPE_BY_LABEL[label] for label in labels if label in TYPE_BY_LABEL), None)


class RecordDtoMapper:
    """Builds the DTOs `IRecordReadRepository` returns."""

    @staticmethod
    def to_source_dto(node: NodeProperties) -> SourceDto:
        """A cited source."""
        return SourceDto(
            id=node["id"], kind=node["kind"], locator=node["locator"], digest=node.get("digest")
        )

    @staticmethod
    def to_actor_dto(node: NodeProperties) -> ActorDto:
        """The actor stored in `actor_*` properties."""
        return ActorDto(
            kind=node["actor_kind"], name=node["actor_name"], session=node.get("actor_session")
        )

    @staticmethod
    def to_revision_dto(node: NodeProperties, sources: tuple[SourceDto, ...]) -> RevisionDto:
        """One revision with the sources it cites, in citation order."""
        return RevisionDto(
            number=node["number"],
            actor=RecordDtoMapper.to_actor_dto(node),
            created_at=node["created_at"],
            title=node["title"],
            body=node.get("body"),
            content_hash=node.get("content_hash"),
            file_version_source_id=node.get("file_version_source_id"),
            sources=sources,
        )

    @staticmethod
    def to_record_dto(
        node: NodeProperties,
        record_type: RecordTypeEnum,
        *,
        revision: RevisionDto | None,
        sources: tuple[SourceDto, ...],
    ) -> RecordDto:
        """Any record; fields that do not apply to its type stay None."""
        is_knowledge: bool = record_type is RecordTypeEnum.KNOWLEDGE
        is_experience: bool = record_type is RecordTypeEnum.EXPERIENCE
        is_source: bool = record_type is RecordTypeEnum.SOURCE
        is_project: bool = record_type is RecordTypeEnum.PROJECT
        return RecordDto(
            id=node["id"],
            type=record_type.value,
            space_id=node["space_id"],
            project_id=node.get("project_id"),
            subtype=node.get("subtype") if is_knowledge or is_experience else None,
            status=node.get("status") if is_knowledge else None,
            ownership=node.get("ownership") if is_knowledge else None,
            head_revision=node.get("head_revision") if is_knowledge else None,
            applicability=(
                ApplicabilityDto(
                    project_id=node.get("project_id"), tags=tuple(node.get("tags", []))
                )
                if is_knowledge
                else None
            ),
            actor=RecordDtoMapper.to_actor_dto(node) if is_experience else None,
            revision=revision,
            sources=sources,
            key=node.get("key") if is_project else None,
            name=node.get("name") if is_project else None,
            body=node.get("body") if is_experience else None,
            occurred_at=node.get("occurred_at") if is_experience else None,
            session=node.get("session") if is_experience else None,
            environment=node.get("environment") if is_experience else None,
            source_kind=node.get("kind") if is_source else None,
            locator=node.get("locator") if is_source else None,
            digest=node.get("digest") if is_source else None,
            created_at=node["created_at"],
            updated_at=node["updated_at"],
        )
