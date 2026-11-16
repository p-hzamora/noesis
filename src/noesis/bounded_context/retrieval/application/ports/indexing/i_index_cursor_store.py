"""Where a projection's cursor and sync lock live."""

import abc


class IIndexCursorStore(abc.ABC):
    """Cursors (the last change sequence applied) and exclusive locks per projection and space."""

    @abc.abstractmethod
    async def get(self, projection: str, space_id: str) -> int | None:
        """The cursor; null when the projection was never initialised for the space."""
        ...

    @abc.abstractmethod
    async def advance(self, projection: str, space_id: str, sequence: int) -> None:
        """Set the cursor."""
        ...

    @abc.abstractmethod
    async def acquire(self, projection: str, space_id: str, owner: str, ttl_seconds: int) -> bool:
        """Compare-and-set the lock for `owner`; taken over once the holder's TTL expired.

        Returns:
            Whether `owner` now holds the lock.
        """
        ...

    @abc.abstractmethod
    async def release(self, projection: str, space_id: str, owner: str) -> None:
        """Drop the lock when `owner` holds it."""
        ...
