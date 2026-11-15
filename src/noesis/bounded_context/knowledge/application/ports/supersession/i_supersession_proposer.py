"""Port to propose that one record supersedes another (implemented over C4's assertions)."""

import abc

from noesis.bounded_context.knowledge.domain.value_objects import Actor, RecordId, SpaceId


class ISupersessionProposer(abc.ABC):
    """Proposes a `supersedes` assertion from a new record to the accepted one it replaces."""

    @abc.abstractmethod
    async def propose(
        self,
        *,
        subject_id: RecordId,
        object_id: RecordId,
        rationale: str,
        source_ids: tuple[RecordId, ...],
        actor: Actor,
        idempotency_key: str,
        space_id: SpaceId,
    ) -> RecordId:
        """Propose `subject_id` supersedes `object_id`.

        Args:
            subject_id: The successor.
            object_id: The accepted record it replaces.
            rationale: Why.
            source_ids: Sources the proposal rests on.
            actor: Who proposes.
            idempotency_key: Makes a repeat return the first proposal.
            space_id: Space of both records.

        Returns:
            The id of the proposed assertion.
        """
        ...
