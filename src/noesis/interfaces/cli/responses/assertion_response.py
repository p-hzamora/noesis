"""`noesis assertion` output."""

from noesis.bounded_context.knowledge.application.dtos import (
    AssertionDto,
    ProposeAssertionResultDto,
)
from noesis.utils import FrozenObject

from .i_renderable_response import IRenderableResponse


class AssertionApplicabilityResponse(FrozenObject):
    """Where an assertion applies.

    Attributes:
        project_key: Project key; None means space-wide.
        tags: Tags, sorted.
    """

    project_key: str | None = None
    tags: tuple[str, ...] = ()


class AssertionEndpointResponse(FrozenObject):
    """One end of an assertion.

    Attributes:
        id: Record id.
        at_revision: Revision judged; None for types without revisions.
    """

    id: str
    at_revision: int | None = None


class AssertionListEndpointResponse(AssertionEndpointResponse):
    """One end of a listed assertion, with its derived status.

    Attributes:
        effective_status: Effective status of the record; None for types without status.
    """

    effective_status: str | None = None


class AssertionProposeResponse(IRenderableResponse):
    """`noesis assertion propose`: the assertion proposed, or the one an identical call created.

    Attributes:
        id: Assertion id.
        predicate: How subject relates to object.
        subject: Subject and the revision judged.
        object: Object and the revision judged.
        evidence: Evidence record ids.
        applicability: Project key and tags.
        status: `proposed`.
        replayed: True when the idempotency key was already used and nothing was written.
    """

    id: str
    predicate: str
    subject: AssertionEndpointResponse
    object: AssertionEndpointResponse
    evidence: tuple[str, ...] = ()
    applicability: AssertionApplicabilityResponse
    status: str
    replayed: bool = False

    @classmethod
    def from_dto(cls, dto: ProposeAssertionResultDto) -> AssertionProposeResponse:
        """The response for a handler result."""
        return cls(
            id=dto.id,
            predicate=dto.predicate,
            subject=AssertionEndpointResponse(
                id=dto.subject_id, at_revision=dto.subject_at_revision
            ),
            object=AssertionEndpointResponse(id=dto.object_id, at_revision=dto.object_at_revision),
            evidence=dto.evidence_ids,
            applicability=AssertionApplicabilityResponse(
                project_key=dto.project_key, tags=dto.tags
            ),
            status=dto.status,
            replayed=dto.replayed,
        )

    def render(self) -> str:
        note: str = " (replayed: nothing written)" if self.replayed else ""
        return (
            f"proposed assertion {self.id}: {self.subject.id} {self.predicate} "
            f"{self.object.id} ({self.status}){note}"
        )


class AssertionItemResponse(FrozenObject):
    """One assertion of `assertion list`.

    Attributes:
        id: Assertion id.
        predicate: How subject relates to object.
        subject: Subject, revision judged and effective status.
        object: Object, revision judged and effective status.
        evidence: Evidence record ids.
        applicability: Project key and tags.
        status: Stored status.
        effective_status: Derived status.
    """

    id: str
    predicate: str
    subject: AssertionListEndpointResponse
    object: AssertionListEndpointResponse
    evidence: tuple[str, ...] = ()
    applicability: AssertionApplicabilityResponse
    status: str
    effective_status: str

    @classmethod
    def from_dto(cls, dto: AssertionDto) -> AssertionItemResponse:
        """The response item for a read result."""
        return cls(
            id=dto.id,
            predicate=dto.predicate,
            subject=AssertionListEndpointResponse(
                id=dto.subject_id,
                at_revision=dto.subject_at_revision,
                effective_status=dto.subject_effective_status,
            ),
            object=AssertionListEndpointResponse(
                id=dto.object_id,
                at_revision=dto.object_at_revision,
                effective_status=dto.object_effective_status,
            ),
            evidence=dto.evidence_ids,
            applicability=AssertionApplicabilityResponse(
                project_key=dto.project_key, tags=dto.tags
            ),
            status=dto.status,
            effective_status=dto.effective_status,
        )


class AssertionListResponse(IRenderableResponse):
    """`noesis assertion list`: assertions about one record, ascending id.

    Attributes:
        assertions: The assertions.
    """

    assertions: tuple[AssertionItemResponse, ...] = ()

    @classmethod
    def from_dtos(cls, dtos: list[AssertionDto]) -> AssertionListResponse:
        """The response for a handler result."""
        return cls(assertions=tuple(AssertionItemResponse.from_dto(dto) for dto in dtos))

    def render(self) -> str:
        if not self.assertions:
            return "no assertions"
        return "\n".join(
            f"{item.id} {item.subject.id} {item.predicate} {item.object.id} "
            f"({item.status}, effective {item.effective_status})"
            for item in self.assertions
        )
