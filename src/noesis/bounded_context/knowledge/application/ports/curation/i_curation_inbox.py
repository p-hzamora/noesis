"""Curation inbox port: the local, process-level state of submissions that are being curated."""

import abc
from contextlib import AbstractAsyncContextManager

from noesis.bounded_context.knowledge.application.dtos import RelatedLookupDto
from noesis.bounded_context.knowledge.application.ports.curation.curation_ticket import (
    CurationTicket,
    StepOutcome,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    CurationPlan,
    CurationProgress,
    CurationSubmission,
)


class ICurationInbox(abc.ABC):
    """Keeps tickets across invocations: stage, plan, step outcomes, park, retry.

    The inbox is local to one machine; the graph ledger, not the inbox, says what was written.
    """

    @abc.abstractmethod
    async def stage(self, submission: CurationSubmission) -> CurationTicket:
        """Keep a submission; a second submission with the same key finds the same ticket.

        Raises:
            CurationInboxFailedError: The inbox cannot be written.
        """
        ...

    @abc.abstractmethod
    async def save_plan(
        self, ticket: str, plan: CurationPlan, *, related_lookup: RelatedLookupDto | None = None
    ) -> None:
        """Save the plan once, with how the related lookup went. The same plan again is a no-op.

        Raises:
            CurationInboxFailedError: A different plan was saved before, or the inbox cannot
                be written.
        """
        ...

    @abc.abstractmethod
    async def advance(
        self, ticket: str, expected: CurationProgress, to: CurationProgress
    ) -> CurationTicket:
        """Compare-and-advance: set the progress to `to` only if it is still `expected`.

        Raises:
            CurationInboxFailedError: The ticket is gone, its progress is not `expected`, or
                the inbox cannot be written.
        """
        ...

    @abc.abstractmethod
    async def record_step(self, ticket: str, outcome: StepOutcome) -> None:
        """Record how a step ended, replacing an earlier outcome of the same step.

        Raises:
            CurationInboxFailedError: The ticket is gone or the inbox cannot be written.
        """
        ...

    @abc.abstractmethod
    async def get(self, ticket: str) -> CurationTicket | None:
        """The ticket, or None.

        Raises:
            CurationInboxFailedError: The ticket exists and cannot be read.
        """
        ...

    @abc.abstractmethod
    async def list_parked(self) -> tuple[CurationTicket, ...]:
        """Every failed ticket, oldest failure first."""
        ...

    @abc.abstractmethod
    def locked(self, ticket: str) -> AbstractAsyncContextManager[None]:
        """Hold the ticket's lock; a second holder waits, up to a bound.

        Raises:
            CurationInboxFailedError: The lock cannot be taken within the bound.
        """
        ...

    @abc.abstractmethod
    async def keep_rejected(self, payload_text: str) -> str:
        """Keep a rejected, already redacted apply payload outside any ticket.

        Returns:
            The path of the kept file.
        """
        ...

    @abc.abstractmethod
    async def remove(self, ticket: str) -> None:
        """Delete the ticket and its files; an unknown ticket is a no-op."""
        ...
