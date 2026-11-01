"""Chooses the publisher for a capture mode at runtime."""

import abc

from noesis.bounded_context.capture.domain.value_objects import CaptureModeEnum

from .i_work_brief_publisher import IWorkBriefPublisher


class IWorkBriefPublisherFactory(abc.ABC):
    """Resolves the publisher of a mode."""

    @abc.abstractmethod
    def for_mode(self, mode: CaptureModeEnum) -> IWorkBriefPublisher:
        """The publisher used for `mode`."""
        ...
