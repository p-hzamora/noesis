"""Write-side guard reads of a consolidation, inside the unit of work's transaction."""

import abc
from collections.abc import Sequence

from noesis.bounded_context.knowledge.application.dtos import OpenMembershipDto
from noesis.bounded_context.knowledge.domain.value_objects import DismissedPair, RecordId, SpaceId


class IConsolidationGuardLookup(abc.ABC):
    """What must hold before a consolidation opens; exposed only on the unit of work."""

    @abc.abstractmethod
    async def conflicts(
        self, record_ids: Sequence[RecordId], space_id: SpaceId
    ) -> list[OpenMembershipDto]:
        """The records among `record_ids` that an open consolidation holds, ascending record id."""
        ...

    @abc.abstractmethod
    async def dismissed_pairs(
        self, record_ids: Sequence[RecordId], space_id: SpaceId
    ) -> list[DismissedPair]:
        """`distinct` dismissals that judged two records of `record_ids`, ascending consolidation id."""
        ...

    @abc.abstractmethod
    async def evidence_for(
        self, object_id: RecordId, exclude: Sequence[RecordId], space_id: SpaceId
    ) -> list[RecordId]:
        """Independent evidence about `object_id`, ascending id, without the `exclude` records.

        The Sources of its head revision and the subjects of live `supports` assertions about
        it. Structural links are never evidence.
        """
        ...
