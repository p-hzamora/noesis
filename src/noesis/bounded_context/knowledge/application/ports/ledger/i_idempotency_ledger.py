"""Idempotency ledger: what each key already produced."""

import abc

from noesis.bounded_context.knowledge.application.ports.ledger.ledger_entry import LedgerEntry
from noesis.bounded_context.knowledge.domain.value_objects import SpaceId


class IIdempotencyLedger(abc.ABC):
    """Looks up and records command outcomes inside a unit of work."""

    @abc.abstractmethod
    async def get(self, space_id: SpaceId, key: str) -> LedgerEntry | None:
        """The entry for (space, key), or None."""
        ...

    @abc.abstractmethod
    async def record(self, entry: LedgerEntry) -> None:
        """Stage `entry`; it commits with the unit of work.

        Raises:
            EntryAlreadyExistsError: (space, key) is already recorded.
        """
        ...
