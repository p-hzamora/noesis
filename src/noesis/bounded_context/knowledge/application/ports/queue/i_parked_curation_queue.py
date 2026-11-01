"""Where briefs wait after curation kept failing."""

import abc
from datetime import datetime

from noesis.bounded_context.knowledge.application.dtos import ParkedCurationDto
from noesis.shared_kernel.contracts import WorkBriefContract


class IParkedCurationQueue(abc.ABC):
    """Durable list of briefs waiting for a manual retry."""

    @abc.abstractmethod
    async def park(self, brief: WorkBriefContract, *, error: str, now: datetime) -> str:
        """Store `brief` and return its ticket."""
        ...

    @abc.abstractmethod
    async def list_parked(self) -> list[ParkedCurationDto]:
        """Every parked brief, oldest first."""
        ...

    @abc.abstractmethod
    async def get(self, ticket: str) -> WorkBriefContract | None:
        """The brief behind `ticket`, without removing it."""
        ...

    @abc.abstractmethod
    async def discard(self, ticket: str) -> None:
        """Remove `ticket` (after a successful retry)."""
        ...
