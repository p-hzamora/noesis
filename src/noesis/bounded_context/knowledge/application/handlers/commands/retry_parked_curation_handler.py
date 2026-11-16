"""Retry a parked curation once, in the foreground."""

from noesis.bounded_context.knowledge.application.dtos import CurationResultDto
from noesis.bounded_context.knowledge.application.services.curation_runner import (
    CurationRunner,
    RelatedLookupModeEnum,
    RunOptions,
)
from noesis.bounded_context.knowledge.domain.value_objects import Key
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject


class RetryParkedCurationCommand(FrozenObject):
    """Retry the ticket.

    Attributes:
        ticket: The ticket from `curate parked`.
        space_key: Key of the active space.
        related_lookup: The current `NOESIS_CURATOR_RELATED_LOOKUP` setting; it applies only to a
            ticket that was not judged yet.
    """

    ticket: str
    space_key: Key
    related_lookup: RelatedLookupModeEnum = RelatedLookupModeEnum.REQUIRED


class RetryParkedCurationHandler(IHandler[RetryParkedCurationCommand, CurationResultDto]):
    """Re-enters a ticket at the stage it failed at.

    A saved plan is never judged again, so keys and fingerprints are identical and finished
    steps return their original ids from the ledger. A ticket still at `staged` is judged with
    one curator attempt. An applied ticket returns its result with `replayed: true`. On a new
    failure the ticket stays parked.
    """

    def __init__(self, *, runner: CurationRunner) -> None:
        self._runner: CurationRunner = runner

    async def handle(self, action: RetryParkedCurationCommand) -> CurationResultDto:
        """Retry the ticket.

        Raises:
            ParkedCurationTicketNotFoundError: No such ticket.
            GraphStoreUnavailableError: The store is still down; the ticket stays parked.
            CurationParkedError: The curator or a step failed again.
            RelatedLookupUnavailableError: The lookup is required and cannot answer.
            BriefAlreadyIngestedError: Registered in the store but no local plan matches.
            CurationInboxFailedError: The inbox cannot be used.
        """
        return await self._runner.retry(
            action.ticket,
            RunOptions(
                space_key=action.space_key,
                related_lookup=action.related_lookup,
                max_attempts=1,
                park_on_failure=True,
            ),
        )
