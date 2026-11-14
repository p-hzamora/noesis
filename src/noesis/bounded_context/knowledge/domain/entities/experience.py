"""The Experience aggregate: something that happened. Write-once."""

from dataclasses import dataclass
from datetime import datetime
from typing import Self

from noesis.bounded_context.knowledge.domain.events import ExperienceRecorded
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ExperienceSubtypeEnum,
    RecordId,
    SpaceId,
)
from noesis.exceptions import ExperienceWithoutSourceError, InvalidRecordError
from noesis.shared_kernel.domain.entities import AggregateRoot


@dataclass(slots=True, kw_only=True)
class Experience(AggregateRoot["Experience"]):
    """An observation, outcome or failure. No status, no revision, no mutating method.

    Attributes:
        id: Record id.
        space_id: Owning space, fixed.
        project_id: Project it happened in, when any.
        subtype: `observation`, `outcome` or `failure`.
        body: What happened (after redaction).
        occurred_at: When it happened.
        session: Harness session id, when known.
        environment: Where it happened, when known.
        actor: Who recorded it.
        source_ids: What it rests on; at least one.
    """

    id: RecordId
    space_id: SpaceId
    project_id: RecordId | None = None
    subtype: ExperienceSubtypeEnum
    body: str
    occurred_at: datetime
    session: str | None = None
    environment: str | None = None
    actor: Actor
    source_ids: tuple[RecordId, ...]

    @classmethod
    def create(
        cls,
        *,
        id: RecordId,
        space_id: SpaceId,
        project_id: RecordId | None = None,
        subtype: ExperienceSubtypeEnum,
        body: str,
        occurred_at: datetime,
        session: str | None = None,
        environment: str | None = None,
        actor: Actor,
        source_ids: tuple[RecordId, ...],
        now: datetime,
    ) -> Self:
        """Record an experience once.

        Raises:
            ExperienceWithoutSourceError: `source_ids` is empty.
            InvalidRecordError: The body is blank.

        Returns:
            The experience with `ExperienceRecorded` pending.
        """
        if not source_ids:
            raise ExperienceWithoutSourceError(
                "An experience needs at least one source.",
                next_steps=["Cite at least one source."],
            )
        if not body.strip():
            raise InvalidRecordError("An experience needs a body.")
        experience: Self = cls(
            id=id,
            space_id=space_id,
            project_id=project_id,
            subtype=subtype,
            body=body,
            occurred_at=occurred_at,
            session=session,
            environment=environment,
            actor=actor,
            source_ids=tuple(dict.fromkeys(source_ids)),
            created_at=now,
            updated_at=now,
        )
        experience._record(
            ExperienceRecorded(aggregate_id=id.value, space_id=space_id.value, subtype=subtype)
        )
        return experience
