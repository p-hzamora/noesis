"""Read side of consolidations and of the candidates a scan looks at."""

import abc
from collections.abc import Sequence

from noesis.bounded_context.knowledge.application.dtos import (
    CandidateSnapshotDto,
    CandidateSnapshotPageDto,
    ConsolidationDto,
    ConsolidationPageDto,
    OpenMembershipDto,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    ConsolidationId,
    ConsolidationStateEnum,
    DismissedPair,
    Key,
    RecordId,
    SpaceId,
)


class IConsolidationReadRepository(abc.ABC):
    """Consolidations and candidate snapshots as DTOs, scoped to one space."""

    @abc.abstractmethod
    async def get(
        self, consolidation_id: ConsolidationId, space_id: SpaceId
    ) -> ConsolidationDto | None:
        """The consolidation, or None; another space's reads as None."""
        ...

    @abc.abstractmethod
    async def list_consolidations(
        self,
        space_id: SpaceId,
        *,
        project: Key | None,
        state: ConsolidationStateEnum | None,
        limit: int,
        cursor: str | None,
    ) -> ConsolidationPageDto:
        """Consolidations of `project`, or of the space-wide records when None, ascending id."""
        ...

    @abc.abstractmethod
    async def describe(
        self, record_ids: Sequence[RecordId], space_id: SpaceId
    ) -> list[CandidateSnapshotDto]:
        """One snapshot per id that is a record of the space, in the order given."""
        ...

    @abc.abstractmethod
    async def recent_accepted(
        self, space_id: SpaceId, *, project: Key | None, limit: int, cursor: str | None
    ) -> CandidateSnapshotPageDto:
        """Accepted, not superseded Knowledge of `project` (space-wide when None).

        Ordered by latest accept time descending, then id; the cursor carries both.
        """
        ...

    @abc.abstractmethod
    async def count_unaccepted_migrated(self, space_id: SpaceId, *, project: Key | None) -> int:
        """Proposed Knowledge tagged `origin:migrated` in that scope, whatever the page."""
        ...

    @abc.abstractmethod
    async def conflicts(
        self, record_ids: Sequence[RecordId], space_id: SpaceId
    ) -> list[OpenMembershipDto]:
        """The records among `record_ids` that an open consolidation holds."""
        ...

    @abc.abstractmethod
    async def dismissed_pairs(
        self, record_ids: Sequence[RecordId], space_id: SpaceId
    ) -> list[DismissedPair]:
        """`distinct` dismissals that judged two records of `record_ids`."""
        ...
