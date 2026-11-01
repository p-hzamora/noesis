"""Base Unit of Work port: one consistent change, committed or rolled back as a whole."""

import abc
from types import TracebackType


class IUnitOfWork[T](abc.ABC):
    """Coordinates the transactional work of one command."""

    @abc.abstractmethod
    async def __aenter__(self) -> T:
        """Start the unit of work and return it."""
        ...

    @abc.abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Finish the unit of work, rolling back if an exception escaped."""
        ...

    @abc.abstractmethod
    async def commit(self) -> None:
        """Make every pending change durable."""
        ...

    @abc.abstractmethod
    async def rollback(self) -> None:
        """Discard every pending change."""
        ...
