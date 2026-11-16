"""Where a projection's cursor, build manifest and fenced sync lease live."""

import abc

from noesis.shared_kernel.domain import JsonValue
from noesis.utils import FrozenObject

from ....domain.enums import BuildStateEnum


class ProjectionManifestDto(FrozenObject):
    """What the last build of a projection in a space left behind.

    Attributes:
        state: `rebuilding` from the start of a rebuild until it completes.
        profile: The profile the completed build used; null for projections that record none.
    """

    state: BuildStateEnum
    profile: dict[str, JsonValue] | None = None


class IIndexCursorStore(abc.ABC):
    """Cursors (the last change sequence applied), build manifests and exclusive leases.

    A lease is fenced: every write that names an `owner` succeeds only while that owner holds an
    unexpired lease, checked in the write's own transaction.
    """

    @abc.abstractmethod
    async def get(self, projection: str, space_id: str) -> int | None:
        """The cursor; null when the projection was never initialised for the space."""
        ...

    @abc.abstractmethod
    async def advance(
        self, projection: str, space_id: str, sequence: int, *, owner: str | None = None
    ) -> None:
        """Set the cursor; with `owner`, only while that owner holds the live lease.

        Raises:
            IndexSyncInProgressError: `owner` no longer holds the lease; nothing was written.
        """
        ...

    @abc.abstractmethod
    async def acquire(self, projection: str, space_id: str, owner: str, ttl_seconds: int) -> bool:
        """Compare-and-set the lock for `owner`; taken over once the holder's TTL expired.

        Returns:
            Whether `owner` now holds the lock.
        """
        ...

    @abc.abstractmethod
    async def renew(self, projection: str, space_id: str, owner: str, ttl_seconds: int) -> bool:
        """Extend `owner`'s unexpired lease; an expired or lost lease is never re-taken.

        Returns:
            Whether the lease was extended.
        """
        ...

    @abc.abstractmethod
    async def release(self, projection: str, space_id: str, owner: str) -> None:
        """Drop the lock when `owner` holds it."""
        ...

    @abc.abstractmethod
    async def manifest(self, projection: str, space_id: str) -> ProjectionManifestDto | None:
        """The build manifest; null when the projection was never built for the space.

        A cursor written before manifests existed reads as `complete` with no profile.
        """
        ...

    @abc.abstractmethod
    async def begin_rebuild(self, projection: str, space_id: str, *, owner: str) -> None:
        """Mark the space `rebuilding` and drop its built profile, under `owner`'s lease.

        Raises:
            IndexSyncInProgressError: `owner` no longer holds the lease.
        """
        ...

    @abc.abstractmethod
    async def complete_rebuild(
        self,
        projection: str,
        space_id: str,
        *,
        owner: str,
        profile: dict[str, JsonValue],
    ) -> None:
        """Publish the built profile and mark the space `complete`, under `owner`'s lease.

        Raises:
            IndexSyncInProgressError: `owner` no longer holds the lease.
        """
        ...
