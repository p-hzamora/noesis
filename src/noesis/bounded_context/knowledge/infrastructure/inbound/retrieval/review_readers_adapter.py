"""Publish review and assertion read models through JSON-native contracts."""

from collections.abc import Sequence

from noesis.shared_kernel.contracts.knowledge import (
    AssertionSummaryContract,
    RecordReviewStateContract,
)
from noesis.shared_kernel.contracts.ports.retrieval import (
    IRecommendationReader,
    IResourceAssertionReader,
    IReviewReader,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jClient

from ....application.dtos import AssertionSummaryDto
from ....domain.value_objects import AssertionPredicateEnum, RecordId, RecordStatusEnum, SpaceId
from ...outbound.persistence.neo4j_assertion_read_adapter import Neo4jAssertionReadAdapter
from ...outbound.persistence.neo4j_review_state_read_adapter import Neo4jReviewStateReadAdapter


class ReviewReadersAdapter(IReviewReader, IRecommendationReader, IResourceAssertionReader):
    """Knowledge's read-only doors for Retrieval's review and recommendation ports."""

    def __init__(self, client: Neo4jClient) -> None:
        self._reviews = Neo4jReviewStateReadAdapter(client)
        self._assertions = Neo4jAssertionReadAdapter(client)

    async def get_states(
        self, ids: Sequence[str], *, space_id: str
    ) -> list[RecordReviewStateContract]:
        """Current effective review states, scoped by space."""
        states = await self._reviews.get_states(
            [RecordId(value=item) for item in ids], SpaceId(value=space_id)
        )
        return [
            RecordReviewStateContract.model_validate(state.model_dump(mode="json"))
            for state in states
        ]

    async def by_subjects(
        self, ids: Sequence[str], *, space_id: str
    ) -> list[AssertionSummaryContract]:
        """Live recommends assertions; project admission belongs to the consumer."""
        assertions = await self._assertions.list_by_subjects(
            [RecordId(value=item) for item in ids],
            space_id=SpaceId(value=space_id),
            predicates=[AssertionPredicateEnum.RECOMMENDS],
            statuses=[RecordStatusEnum.PROPOSED, RecordStatusEnum.ACCEPTED],
        )
        return await self._live(assertions, space_id)

    async def by_objects(
        self, ids: Sequence[str], *, space_id: str, predicates: Sequence[str]
    ) -> list[AssertionSummaryContract]:
        """Live assertions of the given predicates whose object is one of `ids`.

        Scope admission, staleness and the meaning of each predicate belong to the consumer.
        """
        known = {member.value for member in AssertionPredicateEnum}
        wanted = [AssertionPredicateEnum(item) for item in predicates if item in known]
        if not wanted:
            return []
        assertions = await self._assertions.list_by_objects(
            [RecordId(value=item) for item in ids],
            space_id=SpaceId(value=space_id),
            predicates=wanted,
            statuses=[RecordStatusEnum.PROPOSED, RecordStatusEnum.ACCEPTED],
        )
        return await self._live(assertions, space_id)

    async def _live(
        self, assertions: Sequence[AssertionSummaryDto], space_id: str
    ) -> list[AssertionSummaryContract]:
        states = {
            state.record_id: state
            for state in await self.get_states(
                [item.assertion_id for item in assertions], space_id=space_id
            )
        }
        return [
            AssertionSummaryContract.model_validate(item.model_dump(mode="json"))
            for item in assertions
            if item.assertion_id in states
            and states[item.assertion_id].effective_status in {"accepted", "proposed"}
        ]
