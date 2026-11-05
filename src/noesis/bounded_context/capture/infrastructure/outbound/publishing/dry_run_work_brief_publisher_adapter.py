"""Dry-run publisher: stores the brief for inspection and starts nothing."""

from pathlib import Path

from noesis.bounded_context.capture.application.dtos import PublicationDto
from noesis.bounded_context.capture.application.ports.publishing import IWorkBriefPublisher
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.contracts import WorkBriefContract

from .brief_files import BriefFiles


class DryRunWorkBriefPublisherAdapter(IWorkBriefPublisher):
    """Writes the brief file only; `noesis notes curate --brief-file` can replay it later."""

    def __init__(self, *, files: BriefFiles, clock: IClock) -> None:
        self._files: BriefFiles = files
        self._clock: IClock = clock

    async def publish(self, brief: WorkBriefContract) -> PublicationDto:
        """Store the brief."""
        try:
            brief_file: Path = self._files.write(brief, now=self._clock.now())
        except OSError as error:
            return PublicationDto(published=False, detail=f"could not store the brief: {error}")
        return PublicationDto(
            published=True, reference=str(brief_file), detail="dry run: brief stored, not curated"
        )
