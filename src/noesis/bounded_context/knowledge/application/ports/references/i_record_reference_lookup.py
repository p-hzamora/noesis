"""Write-side guard read: what a referenced record is, on the generic record label."""

import abc
from collections.abc import Sequence

from noesis.bounded_context.knowledge.domain.value_objects import RecordId, RecordReference, SpaceId


class IRecordReferenceLookup(abc.ABC):
    """Describes records of any type by id; exposed only on the unit of work."""

    @abc.abstractmethod
    async def describe(self, ids: Sequence[RecordId], space_id: SpaceId) -> list[RecordReference]:
        """One reference per id that exists in `space_id`.

        Unknown ids and ids of another space are left out; the caller decides what a missing
        reference means.
        """
        ...
