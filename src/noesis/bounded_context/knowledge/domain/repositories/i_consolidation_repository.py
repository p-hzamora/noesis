"""Persistence of the Consolidation aggregate."""

import abc

from noesis.bounded_context.knowledge.domain.entities.consolidation import Consolidation
from noesis.bounded_context.knowledge.domain.value_objects import ConsolidationId, SpaceId


class IConsolidationRepository(abc.ABC):
    """All operations participate in the caller's unit of work."""

    @abc.abstractmethod
    async def add(self, consolidation: Consolidation) -> None:
        """Stage a new consolidation with its memberships.

        Raises:
            ConsolidationMembershipConflictError: A member already belongs to an open
                consolidation (the uniqueness backstop of the guard).
            EntryAlreadyExistsError: The id is taken.
        """
        ...

    @abc.abstractmethod
    async def get_by_id(
        self, consolidation_id: ConsolidationId, *, space_id: SpaceId
    ) -> Consolidation | None:
        """The consolidation in `space_id`, or None."""
        ...

    @abc.abstractmethod
    async def get_for_update(
        self, consolidation_id: ConsolidationId, *, space_id: SpaceId
    ) -> Consolidation | None:
        """Lock the consolidation until the unit of work ends, then read it."""
        ...

    @abc.abstractmethod
    async def save(self, consolidation: Consolidation, *, expected_version: int) -> None:
        """Stage the changed state, dismissal and produced records.

        Dismissal releases the memberships; every other state keeps them.

        Raises:
            RevisionConflictError: The stored version is not `expected_version`.
        """
        ...
