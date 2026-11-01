"""Maps capture modes to publishers, injected at composition time."""

from collections.abc import Mapping

from noesis.bounded_context.capture.application.ports.publishing import (
    IWorkBriefPublisher,
    IWorkBriefPublisherFactory,
)
from noesis.bounded_context.capture.domain.value_objects import CaptureModeEnum


class WorkBriefPublisherResolver(IWorkBriefPublisherFactory):
    """Live mode hands briefs to the curator; dry-run only records them. New modes = new entries."""

    def __init__(self, publishers: Mapping[CaptureModeEnum, IWorkBriefPublisher]) -> None:
        self._publishers: Mapping[CaptureModeEnum, IWorkBriefPublisher] = publishers

    def for_mode(self, mode: CaptureModeEnum) -> IWorkBriefPublisher:
        """The publisher registered for `mode`."""
        return self._publishers[mode]
