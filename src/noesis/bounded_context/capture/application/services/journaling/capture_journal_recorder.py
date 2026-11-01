"""Writes capture outcomes to the session journal, skipping the quiet ones unless tracing."""

from noesis.bounded_context.capture.application.dtos import CaptureOutcomeDto, CaptureRunDto
from noesis.bounded_context.capture.application.ports.journal import ICaptureJournal
from noesis.bounded_context.capture.domain.value_objects import SessionId
from noesis.shared_kernel.application.ports.clock import IClock


class CaptureJournalRecorder:
    """Decides what is worth journaling; the journal adapter decides how it is stored."""

    def __init__(self, *, journal: ICaptureJournal, clock: IClock, trace: bool) -> None:
        self._journal: ICaptureJournal = journal
        self._clock: IClock = clock
        self._trace: bool = trace

    async def record(
        self, outcome: CaptureOutcomeDto, *, reference: str | None = None
    ) -> CaptureOutcomeDto:
        """Journal `outcome` (quiet outcomes only in trace mode) and return it unchanged."""
        if self._trace or not outcome.outcome.is_quiet:
            await self._journal.append(
                SessionId(value=outcome.session_id),
                CaptureRunDto(
                    at=self._clock.now().isoformat(timespec="seconds"),
                    outcome=outcome.outcome.value,
                    detail=outcome.detail,
                    reference=reference,
                ),
            )
        return outcome
