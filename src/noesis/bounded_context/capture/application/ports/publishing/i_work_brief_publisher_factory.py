"""Chooses the publisher for a capture mode at runtime."""

import abc

from noesis.bounded_context.capture.application.ports.publishing.i_work_brief_publisher import (
    IWorkBriefPublisher,
)
from noesis.bounded_context.capture.domain.value_objects import CaptureModeEnum


class IWorkBriefPublisherFactory(abc.ABC):
    """Resolves the publisher of a mode."""

    @abc.abstractmethod
    def for_mode(self, mode: CaptureModeEnum) -> IWorkBriefPublisher:
        """The publisher used for `mode`."""
        ...
