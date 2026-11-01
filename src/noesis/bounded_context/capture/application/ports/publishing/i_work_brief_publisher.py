"""Hands a work brief to whatever turns it into knowledge."""

import abc

from noesis.bounded_context.capture.application.dtos import PublicationDto
from noesis.shared_kernel.contracts import WorkBriefContract


class IWorkBriefPublisher(abc.ABC):
    """Publishes a brief without waiting for it to be curated."""

    @abc.abstractmethod
    async def publish(self, brief: WorkBriefContract) -> PublicationDto:
        """Start the hand-over; `published` is False when it could not start."""
        ...
