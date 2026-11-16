"""A projection whose expensive work runs before, and outside, its fenced write."""

import abc

from .i_index_writer import IIndexWriter, ProjectionEntryDto


class IStagedIndexWriter[PreparedT](IIndexWriter):
    """`prepare` computes an entry with no transaction open; `commit` writes it, fenced.

    The synchroniser re-reads the record's head between the two, so a head that moved during
    the slow step is never written under the old revision. Every fenced write runs only while
    `owner` holds the projection's live lease, checked inside the write transaction.
    """

    @abc.abstractmethod
    async def prepare(self, entry: ProjectionEntryDto) -> PreparedT:
        """Compute what `commit` writes (embeddings); opens no write transaction."""
        ...

    @abc.abstractmethod
    async def commit(self, prepared: PreparedT, *, owner: str) -> None:
        """Atomically replace the record's entry with `prepared`.

        Raises:
            IndexSyncInProgressError: `owner` no longer holds the lease; nothing was written.
        """
        ...

    @abc.abstractmethod
    async def clear_fenced(self, space_id: str, *, owner: str) -> None:
        """Drop every entry of the space while `owner` holds the lease.

        Raises:
            IndexSyncInProgressError: `owner` no longer holds the lease; nothing was written.
        """
        ...

    @abc.abstractmethod
    def entry_of(self, prepared: PreparedT) -> ProjectionEntryDto:
        """The entry `prepared` was computed from."""
        ...
