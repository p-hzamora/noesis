"""Apply decisions: run the auto-curation policy and store the notes. No model, no brief."""

import copy
from collections.abc import Callable
from datetime import datetime

from noesis.bounded_context.notes.application.dtos import (
    ApplyFailureRecordDto,
    CurationResultDto,
    RejectedEntryDto,
    SkippedCandidateDto,
)
from noesis.bounded_context.notes.application.ports.failures import IApplyFailureLog
from noesis.bounded_context.notes.application.ports.uow import INotesUnitOfWork
from noesis.bounded_context.notes.domain.entities import Note
from noesis.bounded_context.notes.domain.policies import (
    AutoCurationPolicy,
    CurationOutcome,
    CurationOutcomeEnum,
)
from noesis.bounded_context.notes.domain.value_objects import (
    CurationDecision,
    NoteArea,
    NoteLocation,
    NoteOriginEnum,
)
from noesis.exceptions import ApplyFailedError, NoteStorageError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.domain import JsonValue
from noesis.utils import FrozenObject


class ApplyCurationCommand(FrozenObject):
    """Store `decisions` as auto notes of `area`.

    Attributes:
        area: Vault folder the notes belong to (`repos/<repo>`).
        decisions: What to store or skip.
        rejected: Entries the caller's parser could not turn into decisions; any makes the
            whole call fail before anything is written.
        raw_payload: The caller's input exactly as received, kept when the call fails.
        commits: Commit SHAs behind the knowledge; may be empty.
        session: Short session id; None when unknown.
        dry_run: Run the policy and report the outcome without writing.
    """

    area: NoteArea
    decisions: tuple[CurationDecision, ...]
    rejected: tuple[RejectedEntryDto, ...] = ()
    raw_payload: str = ""
    commits: tuple[str, ...] = ()
    session: str | None = None
    dry_run: bool = False


class ApplyCurationHandler(IHandler[ApplyCurationCommand, CurationResultDto]):
    """Stores decisions through the auto-curation policy and the unit of work.

    With a failure log, a rejected payload or a storage failure is kept there and reported as
    `ApplyFailedError`. Without one, a storage failure propagates as `NoteStorageError` so the
    caller (curate) can park its own input.
    """

    def __init__(
        self,
        *,
        uow_factory: Callable[[], INotesUnitOfWork],
        clock: IClock,
        policy: AutoCurationPolicy,
        failures: IApplyFailureLog | None = None,
    ) -> None:
        self._uow_factory: Callable[[], INotesUnitOfWork] = uow_factory
        self._clock: IClock = clock
        self._policy: AutoCurationPolicy = policy
        self._failures: IApplyFailureLog | None = failures

    async def handle(self, action: ApplyCurationCommand) -> CurationResultDto:
        """Store what the policy admits.

        Raises:
            ApplyFailedError: An entry was rejected, or storing failed and a failure log is set.
            NoteStorageError: Storing failed and there is no failure log.
        """
        if action.rejected:
            errors: list[str] = [
                f"{'payload' if entry.index is None else f'entry {entry.index}'}: {entry.reason}"
                for entry in action.rejected
            ]
            raise await self._failed(
                action,
                "The decisions were rejected: " + "; ".join(errors),
                errors,
                {"rejected": [entry.model_dump(mode="json") for entry in action.rejected]},
            )
        try:
            outcomes: list[CurationOutcome] = await self._store(action)
        except NoteStorageError as error:
            if self._failures is None:
                raise
            raise await self._failed(
                action,
                f"Storing the notes failed: {error.message}",
                [f"storage: {error.message}"],
                dict(error.metadata),
                cause=error,
            ) from error
        return CurationResultDto(
            repository=action.area.repository or action.area.value,
            created=_paths(outcomes, CurationOutcomeEnum.CREATED),
            updated=_paths(outcomes, CurationOutcomeEnum.UPDATED),
            skipped=tuple(
                SkippedCandidateDto(candidate=outcome.candidate, reason=outcome.reason)
                for outcome in outcomes
                if outcome.outcome is CurationOutcomeEnum.SKIPPED
            ),
        )

    async def _store(self, action: ApplyCurationCommand) -> list[CurationOutcome]:
        """Apply the policy to every decision and commit the resulting notes together."""
        now: datetime = self._clock.now()
        outcomes: list[CurationOutcome] = []
        async with self._uow_factory() as uow:
            for decision in action.decisions:
                existing_auto: Note | None = None
                existing_manual: Note | None = None
                if decision.draft is not None:
                    location = NoteLocation(
                        area=action.area,
                        origin=NoteOriginEnum.AUTO,
                        kind=decision.draft.kind,
                        slug=decision.draft.slug,
                    )
                    existing_auto = await uow.notes.get(location)
                    existing_manual = await uow.notes.get(
                        location.with_origin(NoteOriginEnum.MANUAL)
                    )
                    if action.dry_run and existing_auto is not None:
                        existing_auto = copy.deepcopy(existing_auto)
                outcome: CurationOutcome = self._policy.apply(
                    decision,
                    area=action.area,
                    existing_auto=existing_auto,
                    existing_manual=existing_manual,
                    commits=action.commits,
                    session=action.session,
                    now=now,
                )
                if outcome.note is not None and not action.dry_run:
                    await uow.notes.save(outcome.note)
                outcomes.append(outcome)
            if not action.dry_run:
                await uow.commit()
        return outcomes

    async def _failed(
        self,
        action: ApplyCurationCommand,
        message: str,
        errors: list[str],
        metadata: dict[str, JsonValue],
        *,
        cause: NoteStorageError | None = None,
    ) -> ApplyFailedError:
        """Keep the payload (unless dry-run) and build the error that tells where it went."""
        context: dict[str, JsonValue] = {**metadata, "repository": action.area.value}
        next_steps: list[str] = [*(cause.next_steps if cause else ())]
        if self._failures is not None and not action.dry_run:
            try:
                record: ApplyFailureRecordDto = await self._failures.record(
                    raw_payload=action.raw_payload,
                    area=action.area,
                    commits=action.commits,
                    session=action.session,
                    errors=errors,
                    now=self._clock.now(),
                )
            except NoteStorageError as record_error:
                context["raw_payload"] = action.raw_payload
                context["record_error"] = record_error.message
                next_steps.append(
                    "The payload could not be kept on disk: it is in `raw_payload`. "
                    "Fix the problem and run `noesis notes apply` with it again."
                )
            else:
                context |= {
                    "ticket": record.ticket,
                    "record_path": record.path,
                    "payload_path": record.payload_path,
                }
                next_steps.append(
                    f"Fix the cause, then run `noesis notes apply --decisions-file "
                    f"{record.payload_path}` again."
                )
        return ApplyFailedError(message, context, next_steps=next_steps)


def _paths(outcomes: list[CurationOutcome], kind: CurationOutcomeEnum) -> tuple[str, ...]:
    """Paths of the notes behind outcomes of one kind."""
    return tuple(
        o.note.location.relative_path for o in outcomes if o.outcome is kind and o.note is not None
    )
