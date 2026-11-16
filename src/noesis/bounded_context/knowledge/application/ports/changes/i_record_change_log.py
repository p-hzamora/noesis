"""Outbound port: append record changes to the change feed inside a unit of work."""

import abc

from noesis.bounded_context.knowledge.application.dtos.pending_record_change import (
    PendingRecordChange,
)
from noesis.shared_kernel.contracts.knowledge import RecordChangedContract


class IRecordChangeLog(abc.ABC):
    """Stages changes in the transaction of the aggregate write they describe."""

    @abc.abstractmethod
    async def append(self, change: PendingRecordChange) -> RecordChangedContract:
        """Stage `change` with the next sequence of its space.

        The sequence is assigned inside the transaction, so it is commit-ordered and gap-free;
        a rollback consumes none.

        Returns:
            The change as the feed will serve it.
        """
        ...
