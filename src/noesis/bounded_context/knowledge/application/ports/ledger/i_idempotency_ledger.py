"""Idempotency ledger: what each key already produced."""

import abc

from noesis.bounded_context.knowledge.application.ports.ledger.ledger_entry import LedgerEntry
from noesis.bounded_context.knowledge.domain.value_objects import SpaceId
from noesis.shared_kernel.domain import JsonValue


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

    @abc.abstractmethod
    async def update_extra(
        self,
        space_id: SpaceId,
        key: str,
        *,
        expected_progress_version: int,
        extra: dict[str, JsonValue],
    ) -> None:
        """Replace `extra` of a pending entry; command, fingerprint and identity stay as recorded.

        Compare-and-set under the entry's lock: the stored `extra.progress_version` must be
        `expected_progress_version`; the stored value becomes one higher.

        Raises:
            RevisionConflictError: The entry is unknown or its progress version moved on.
        """
        ...
