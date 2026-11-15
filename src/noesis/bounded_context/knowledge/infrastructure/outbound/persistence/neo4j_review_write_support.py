"""What the review writes share: staging a `:Decision` and reading a constraint clash.

`Decision.decision_key` makes a transition against a transition a uniqueness race; the loser
gets `StatusConflictError`. `Assertion.live_key` is the backstop of "one live statement".
"""

from typing import Final, LiteralString

from noesis.bounded_context.knowledge.domain.entities.review_decision import ReviewDecision
from noesis.bounded_context.knowledge.domain.value_objects import RecordId, SpaceId
from noesis.exceptions import GraphStoreConstraintViolatedError, StatusConflictError
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jTransaction

from .mappers import DecisionNodeMapper

DECISION_KEY_PROPERTY: Final[str] = "decision_key"
LIVE_KEY_PROPERTY: Final[str] = "live_key"

_STAGE_DECISION: LiteralString = """
MATCH (record:Record {id: $id, space_id: $space_id})
CREATE (decision:Decision $decision)-[:DECIDES]->(record)
RETURN record.id AS id
"""


def status_conflict(
    error: GraphStoreConstraintViolatedError, record_id: RecordId | None = None
) -> StatusConflictError | None:
    """The conflict error when `error` is a clash on the decision key, else None."""
    if error.metadata.get("property") != DECISION_KEY_PROPERTY:
        return None
    metadata: dict[str, str] = {"record_id": record_id.value} if record_id else {}
    return StatusConflictError(
        "Another decision on this record committed first.",
        {**metadata},
        next_steps=["Run `noesis review log` and re-evaluate."],
    )


async def stage_decision(
    transaction: Neo4jTransaction,
    *,
    space_id: SpaceId,
    record_id: RecordId,
    decision: ReviewDecision,
) -> None:
    """Create the decision node and its `DECIDES` edge.

    Raises:
        StatusConflictError: A decision with the same key exists.
    """
    try:
        await transaction.run(
            _STAGE_DECISION,
            {
                "id": record_id.value,
                "space_id": space_id.value,
                "decision": DecisionNodeMapper.to_properties(record_id, decision),
            },
        )
    except GraphStoreConstraintViolatedError as error:
        conflict: StatusConflictError | None = status_conflict(error, record_id)
        if conflict is None:
            raise
        raise conflict from error
