"""Read side: record, revision and source nodes -> DTOs."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from noesis.bounded_context.knowledge.application.dtos import (
    ActorDto,
    ApplicabilityDto,
    AssertionEndpointDto,
    RecordDto,
    RevisionDto,
    SourceDto,
    SupersededByDto,
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


@dataclass(frozen=True, slots=True)
class ReviewView:
    """What `record get` adds from the review module.

    Attributes:
        effective_status: Derived status; None for types without status.
        superseded_by: The accepted `supersedes` assertion and its subject, or None.
        subject_at_revision: Assertion subject revision judged.
        object_at_revision: Assertion object revision judged.
    """

    effective_status: str | None = None
    superseded_by: tuple[str, str] | None = None
    subject_at_revision: int | None = None
    object_at_revision: int | None = None


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
        review: ReviewView | None = None,
    ) -> RecordDto:
        """Any record; fields that do not apply to its type stay None."""
        is_knowledge: bool = record_type is RecordTypeEnum.KNOWLEDGE
        is_experience: bool = record_type is RecordTypeEnum.EXPERIENCE
        is_source: bool = record_type is RecordTypeEnum.SOURCE
        is_project: bool = record_type is RecordTypeEnum.PROJECT
        is_assertion: bool = record_type is RecordTypeEnum.ASSERTION
        view: ReviewView = review or ReviewView()
        return RecordDto(
            id=node["id"],
            type=record_type.value,
            space_id=node["space_id"],
            project_id=node.get("project_id"),
            subtype=node.get("subtype") if is_knowledge or is_experience else None,
            status=node.get("status") if is_knowledge or is_assertion else None,
            ownership=node.get("ownership") if is_knowledge else None,
            head_revision=node.get("head_revision") if is_knowledge else None,
            applicability=(
                ApplicabilityDto(
                    project_id=node.get("project_id"), tags=tuple(node.get("tags", []))
                )
                if is_knowledge or is_assertion
                else None
            ),
            actor=RecordDtoMapper.to_actor_dto(node) if is_experience or is_assertion else None,
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
            effective_status=view.effective_status if is_knowledge or is_assertion else None,
            superseded_by=(
                SupersededByDto(assertion_id=view.superseded_by[0], record_id=view.superseded_by[1])
                if view.superseded_by
                else None
            ),
            predicate=node.get("predicate") if is_assertion else None,
            subject=(
                AssertionEndpointDto(id=node["subject_id"], at_revision=view.subject_at_revision)
                if is_assertion
                else None
            ),
            object=(
                AssertionEndpointDto(id=node["object_id"], at_revision=view.object_at_revision)
                if is_assertion
                else None
            ),
            evidence_ids=tuple(node.get("evidence_ids", [])) if is_assertion else (),
            rationale=node.get("rationale") if is_assertion else None,
            created_at=node["created_at"],
            updated_at=node["updated_at"],
        )
