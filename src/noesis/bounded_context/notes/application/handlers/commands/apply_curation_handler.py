"""Apply decisions: run the auto-curation policy and store the notes. No model, no brief."""

import copy
from collections.abc import Callable
from datetime import datetime
from pathlib import PurePosixPath

from noesis.bounded_context.notes.application.dtos import (
    ApplyFailureRecordDto,
    CurationResultDto,
    RejectedEntryDto,
    SkippedCandidateDto,
)
from noesis.bounded_context.notes.application.ports.failures import IApplyFailureLog
from noesis.bounded_context.notes.application.ports.ids import INoteIdGenerator
from noesis.bounded_context.notes.application.ports.manifest import IManifestProvider
from noesis.bounded_context.notes.application.ports.read_repositories import INoteReadRepository
from noesis.bounded_context.notes.application.ports.uow import INotesUnitOfWork
from noesis.bounded_context.notes.application.services.manifest import (
    KindCatalog,
    Manifest,
    NotePathResolver,
)
from noesis.bounded_context.notes.domain.entities import Note
from noesis.bounded_context.notes.domain.policies import (
    AutoCurationPolicy,
    CurationOutcome,
    CurationOutcomeEnum,
)
from noesis.bounded_context.notes.domain.value_objects import (
    CurationDecision,
    NoteDraft,
    NotePath,
    NotePlacement,
    NoteScope,
    NoteSourceRef,
)
from noesis.exceptions import ApplyFailedError, NoteStorageError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.domain import JsonValue
from noesis.utils import FrozenObject


class ApplyCurationCommand(FrozenObject):
    """Store `decisions` as auto notes of `scope`.

    Attributes:
        scope: Scope the notes belong to (`repo:<repo>`).
        decisions: What to store or skip.
        rejected: Entries the caller's parser could not turn into decisions; any makes the
            whole call fail before anything is written.
        raw_payload: The caller's input exactly as received, kept when the call fails.
        commits: Commit SHAs behind the knowledge; may be empty.
        session: Short session id; None when unknown.
        dry_run: Run the policy and report the outcome without writing.
    """

    scope: NoteScope
    decisions: tuple[CurationDecision, ...]
    rejected: tuple[RejectedEntryDto, ...] = ()
    raw_payload: str = ""
    commits: tuple[str, ...] = ()
    session: str | None = None
    dry_run: bool = False


class ApplyCurationHandler(IHandler[ApplyCurationCommand, CurationResultDto]):
    """Stores decisions through the auto-curation policy and the unit of work.

    A decision updates the auto note of the same scope, kind and slug in place (its id is
    kept) or creates a new note at the manifest layout's path, never overwriting a taken path.

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
        manifest: IManifestProvider,
        ids: INoteIdGenerator,
        read_repository: INoteReadRepository,
        failures: IApplyFailureLog | None = None,
    ) -> None:
        self._uow_factory: Callable[[], INotesUnitOfWork] = uow_factory
        self._clock: IClock = clock
        self._policy: AutoCurationPolicy = policy
        self._manifest: IManifestProvider = manifest
        self._ids: INoteIdGenerator = ids
        self._read_repository: INoteReadRepository = read_repository
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
            repository=action.scope.name,
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
        manifest: Manifest = await self._manifest.load()
        catalog: KindCatalog = manifest.catalog()
        resolver = NotePathResolver(manifest.layout, catalog)
        sources: tuple[NoteSourceRef, ...] = _sources(action)
        outcomes: list[CurationOutcome] = []
        batch: dict[tuple[str, str], Note] = {}  # notes created by earlier decisions of this call
        claimed: set[str] = set()
        async with self._uow_factory() as uow:
            for decision in action.decisions:
                draft: NoteDraft | None = decision.draft
                if draft is not None and catalog.find(draft.kind) is None:
                    outcomes.append(_unknown_kind(decision, draft, catalog))
                    continue
                existing_auto: Note | None = None
                manual_path: NotePath | None = None
                placement: NotePlacement | None = None
                if draft is not None:
                    key: tuple[str, str] = (draft.kind.value, draft.slug.value)
                    existing_auto = batch.get(key)
                    if existing_auto is None:
                        existing_auto, manual_path = await self._find_existing(
                            uow, resolver, action.scope, draft
                        )
                        if action.dry_run and existing_auto is not None:
                            existing_auto = copy.deepcopy(existing_auto)
                    placement = NotePlacement(
                        id=self._ids.new_id(),
                        path=await self._free_path(uow, resolver, action.scope, draft, claimed),
                        required_sections=catalog.require(draft.kind).sections,
                    )
                outcome: CurationOutcome = self._policy.apply(
                    decision,
                    scope=action.scope,
                    existing_auto=existing_auto,
                    manual_path=manual_path,
                    placement=placement,
                    sources=sources,
                    now=now,
                )
                if outcome.note is not None:
                    if outcome.outcome is CurationOutcomeEnum.CREATED and draft is not None:
                        batch[(draft.kind.value, draft.slug.value)] = outcome.note
                        claimed.add(outcome.note.path.value)
                    if not action.dry_run:
                        await uow.notes.save(outcome.note)
                outcomes.append(outcome)
            if not action.dry_run:
                await uow.commit()
        return outcomes

    async def _find_existing(
        self, uow: INotesUnitOfWork, resolver: NotePathResolver, scope: NoteScope, draft: NoteDraft
    ) -> tuple[Note | None, NotePath | None]:
        """The auto note (loaded) and the manual note's path with the draft's kind and slug.

        The read repository finds them wherever they are. When it knows nothing (it may read
        another source than the one written, or none at all), the layout's own path for the
        draft is checked through the write repository, so a note there is still not duplicated.
        """
        existing_auto: Note | None = None
        manual_path: NotePath | None = None
        for summary in await self._read_repository.find_active(scope, draft.kind):
            if PurePosixPath(summary.path).stem != draft.slug.value:
                continue
            path = NotePath(value=summary.path)
            if summary.origin == "auto" and existing_auto is None:
                existing_auto = await uow.notes.get(path)
            elif summary.origin != "auto" and manual_path is None:
                manual_path = path
        if existing_auto is None and manual_path is None:
            at_layout: Note | None = await uow.notes.get(
                next(iter(resolver.candidates(scope, draft.kind, draft.slug)))
            )
            if at_layout is not None and (at_layout.scope, at_layout.kind) == (scope, draft.kind):
                if at_layout.is_auto:
                    existing_auto = at_layout
                else:
                    manual_path = at_layout.path
        return existing_auto, manual_path

    @staticmethod
    async def _free_path(
        uow: INotesUnitOfWork,
        resolver: NotePathResolver,
        scope: NoteScope,
        draft: NoteDraft,
        claimed: set[str],
    ) -> NotePath:
        """The first layout path (`<slug>.md`, `<slug>-2.md`...) that nothing occupies."""
        for candidate in resolver.candidates(scope, draft.kind, draft.slug):
            if candidate.value not in claimed and not await uow.notes.exists(candidate):
                return candidate
        raise AssertionError("candidates never end")  # pragma: no cover

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
        context: dict[str, JsonValue] = {**metadata, "repository": action.scope.value}
        next_steps: list[str] = [*(cause.next_steps if cause else ())]
        if self._failures is not None and not action.dry_run:
            try:
                record: ApplyFailureRecordDto = await self._failures.record(
                    raw_payload=action.raw_payload,
                    scope=action.scope,
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
    return tuple(o.note.path.value for o in outcomes if o.outcome is kind and o.note is not None)


def _sources(action: ApplyCurationCommand) -> tuple[NoteSourceRef, ...]:
    """`commit:<sha>` for each commit and `session:<id>` for the session."""
    refs: list[str] = [f"commit:{sha}" for sha in action.commits]
    if action.session:
        refs.append(f"session:{action.session}")
    return tuple(NoteSourceRef(value=ref) for ref in refs)


def _unknown_kind(
    decision: CurationDecision, draft: NoteDraft, catalog: KindCatalog
) -> CurationOutcome:
    """A skip: the manifest does not list the draft's kind."""
    return CurationOutcome(
        outcome=CurationOutcomeEnum.SKIPPED,
        candidate=decision.candidate,
        reason=f"unknown note kind {draft.kind.value!r}; known: {', '.join(catalog.names())}",
    )
