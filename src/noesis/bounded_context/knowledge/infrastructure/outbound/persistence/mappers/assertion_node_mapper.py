"""`Assertion` <-> `:Record:Assertion` node.

The node keeps the statement's ids as properties (for filtering) next to the `SUBJECT`,
`OBJECT` and `EVIDENCED_BY` edges that carry the graph shape; `live_key` is present only while
the assertion is `proposed` or `accepted`.
"""

from noesis.bounded_context.knowledge.domain.entities import Assertion
from noesis.bounded_context.knowledge.domain.value_objects import (
    Applicability,
    AssertionPredicateEnum,
    RecordId,
    RecordStatusEnum,
    SpaceId,
    StatementKey,
    Tag,
)

from .actor_properties import to_actor, to_actor_properties
from .node_keys import live_key
from .node_properties import NodeProperties, without_nulls

LIVE_STATUSES: frozenset[RecordStatusEnum] = frozenset(
    {RecordStatusEnum.PROPOSED, RecordStatusEnum.ACCEPTED}
)


def statement_key_of(assertion: Assertion) -> StatementKey:
    """The statement the assertion states."""
    return StatementKey(
        space_id=assertion.space_id,
        predicate=assertion.predicate,
        subject_id=assertion.subject_id,
        object_id=assertion.object_id,
        project_id=assertion.applicability.project_id,
    )


def is_live(assertion: Assertion) -> bool:
    """Whether the assertion still occupies its statement."""
    return assertion.status in LIVE_STATUSES


class AssertionNodeMapper:
    """Maps an assertion to node properties and back."""

    @staticmethod
    def to_properties(assertion: Assertion) -> NodeProperties:
        """Properties of the `:Record:Assertion` node."""
        project_id: RecordId | None = assertion.applicability.project_id
        return without_nulls(
            {
                "id": assertion.id.value,
                "space_id": assertion.space_id.value,
                "predicate": assertion.predicate.value,
                "subject_id": assertion.subject_id.value,
                "object_id": assertion.object_id.value,
                "evidence_ids": [item.value for item in assertion.evidence_ids],
                "source_ids": [item.value for item in assertion.source_ids],
                "rationale": assertion.rationale,
                "status": assertion.status.value,
                "decision_seq": assertion.decision_seq,
                "live_key": live_key(statement_key_of(assertion)) if is_live(assertion) else None,
                "superseded_by_assertion_id": (
                    assertion.superseded_by_assertion_id.value
                    if assertion.superseded_by_assertion_id
                    else None
                ),
                "project_id": project_id.value if project_id else None,
                "tags": [tag.value for tag in assertion.applicability.sorted_tags],
                **to_actor_properties(assertion.actor),
                "created_at": assertion.created_at,
                "updated_at": assertion.updated_at,
            }
        )

    @staticmethod
    def to_entity(
        node: NodeProperties, *, subject_at_revision: int | None, object_at_revision: int | None
    ) -> Assertion:
        """The assertion a node and its two edges store (no pending events)."""
        project_id: str | None = node.get("project_id")
        superseded_by: str | None = node.get("superseded_by_assertion_id")
        return Assertion(
            id=RecordId(value=node["id"]),
            space_id=SpaceId(value=node["space_id"]),
            predicate=AssertionPredicateEnum(node["predicate"]),
            subject_id=RecordId(value=node["subject_id"]),
            object_id=RecordId(value=node["object_id"]),
            evidence_ids=tuple(RecordId(value=item) for item in node.get("evidence_ids", [])),
            rationale=node["rationale"],
            actor=to_actor(node),
            applicability=Applicability(
                project_id=RecordId(value=project_id) if project_id else None,
                tags=frozenset(Tag(value=tag) for tag in node.get("tags", [])),
            ),
            status=RecordStatusEnum(node["status"]),
            source_ids=tuple(RecordId(value=item) for item in node["source_ids"]),
            subject_at_revision=subject_at_revision,
            object_at_revision=object_at_revision,
            decision_seq=node.get("decision_seq", 0),
            superseded_by_assertion_id=RecordId(value=superseded_by) if superseded_by else None,
            created_at=node["created_at"],
            updated_at=node["updated_at"],
        )
