"""Capture an Experience: something that happened, recorded once."""

from datetime import datetime

from pydantic import Field

from noesis.bounded_context.knowledge.application.dtos import CaptureResultDto
from noesis.bounded_context.knowledge.application.dtos.pending_record_change import (
    PendingRecordChange,
)
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.idempotency import (
    fingerprint_request,
    read_ledger,
    replay_of,
)
from noesis.bounded_context.knowledge.application.services.inputs import ProjectRef, SourceInput
from noesis.bounded_context.knowledge.application.services.record_changes import (
    pending_changes_from,
)
from noesis.bounded_context.knowledge.application.services.record_reference_resolver import (
    RecordReferenceResolver,
)
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    require_initialised,
)
from noesis.bounded_context.knowledge.application.services.secret_redactor import SecretRedactor
from noesis.bounded_context.knowledge.domain.entities import Experience
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ExperienceSubtypeEnum,
    Key,
    RecordId,
    RecordTypeEnum,
    SpaceId,
)
from noesis.exceptions import EntryAlreadyExistsError, ExperienceWithoutSourceError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.domain import JsonValue
from noesis.utils import FrozenObject

CAPTURE_EXPERIENCE_COMMAND: str = "capture_experience"


class CaptureExperienceCommand(FrozenObject):
    """Record an experience.

    Attributes:
        idempotency_key: Caller-chosen key; a repeat with the same request returns the first result.
        space_key: Key of the space to capture into.
        subtype: `observation`, `outcome` or `failure`.
        body: What happened.
        actor: Who records it.
        occurred_at: When it happened; the clock's now when None.
        project: Project to anchor it to (ensured); None for none.
        session: Harness session id.
        environment: Where it happened.
        sources: Existing source ids and/or new source descriptions; at least one.
    """

    idempotency_key: str = Field(min_length=1)
    space_key: Key
    subtype: ExperienceSubtypeEnum
    body: str
    actor: Actor
    occurred_at: datetime | None = None
    project: ProjectRef | None = None
    session: str | None = None
    environment: str | None = None
    sources: tuple[SourceInput, ...]


class CaptureExperienceHandler(IHandler[CaptureExperienceCommand, CaptureResultDto]):
    """Captures an experience with the same ledger-first flow as `CaptureKnowledgeHandler`."""

    def __init__(
        self,
        *,
        uow_factory: KnowledgeUnitOfWorkFactory,
        clock: IClock,
        ids: IRecordIdGenerator,
        schema: IStoreSchema,
    ) -> None:
        self._uow_factory: KnowledgeUnitOfWorkFactory = uow_factory
        self._clock: IClock = clock
        self._ids: IRecordIdGenerator = ids
        self._schema: IStoreSchema = schema
        self._references: RecordReferenceResolver = RecordReferenceResolver(
            uow_factory=uow_factory, clock=clock, ids=ids
        )

    async def handle(self, action: CaptureExperienceCommand) -> CaptureResultDto:
        """Capture, or replay the earlier identical capture.

        Raises:
            ExperienceWithoutSourceError: No source; nothing is written.
            StoreNotInitialisedError: The `core` schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            IdempotencyKeyReusedError: The key was used for a different request.
            ReferenceNotInSpaceError: An existing source id is not in the space.
        """
        if not action.sources:
            raise ExperienceWithoutSourceError(
                "An experience needs at least one source.",
                next_steps=["Cite at least one source."],
            )
        await require_initialised(self._schema)
        space_id: SpaceId = await self._references.resolve_space(action.space_key)
        fingerprint: str = fingerprint_request(
            CAPTURE_EXPERIENCE_COMMAND, action, exclude={"idempotency_key"}
        )
        known: LedgerEntry | None = replay_of(
            await read_ledger(self._uow_factory, space_id, action.idempotency_key),
            command=CAPTURE_EXPERIENCE_COMMAND,
            fingerprint=fingerprint,
        )
        if known is not None:
            return _result(known, replayed=True)

        # foreign source ids fail before the project ensure writes anything
        await self._references.check_existing_sources(space_id, action.sources)
        project_id: RecordId | None = await self._references.ensure_project(
            space_id, action.project
        )
        source_ids: tuple[RecordId, ...] = await self._references.ensure_sources(
            space_id, action.sources
        )
        now: datetime = self._clock.now()
        experience: Experience = Experience.create(
            id=self._ids.new_record_id(),
            space_id=space_id,
            project_id=project_id,
            subtype=action.subtype,
            body=SecretRedactor.redact(action.body)[0],
            occurred_at=action.occurred_at or now,
            session=(
                SecretRedactor.redact(action.session)[0] if action.session is not None else None
            ),
            environment=(
                SecretRedactor.redact(action.environment)[0]
                if action.environment is not None
                else None
            ),
            actor=action.actor,
            source_ids=source_ids,
            now=now,
        )
        changes: list[PendingRecordChange] = pending_changes_from(
            experience.collect_events(),
            record_type="experience",
            status=None,
            occurred_at=now,
        )
        project_value: JsonValue = project_id.value if project_id is not None else None
        entry: LedgerEntry = LedgerEntry(
            space_id=space_id,
            key=action.idempotency_key,
            command=CAPTURE_EXPERIENCE_COMMAND,
            fingerprint=fingerprint,
            record_id=experience.id,
            extra={"project_id": project_value},
            recorded_at=now,
        )
        try:
            async with self._uow_factory() as uow:
                await uow.experiences.add(experience)
                await uow.ledger.record(entry)
                for change in changes:
                    await uow.changes.append(change)
                await uow.commit()
        except EntryAlreadyExistsError:
            winner: LedgerEntry | None = replay_of(
                await read_ledger(self._uow_factory, space_id, action.idempotency_key),
                command=CAPTURE_EXPERIENCE_COMMAND,
                fingerprint=fingerprint,
            )
            if winner is None:
                raise
            return _result(winner, replayed=True)
        return _result(entry, replayed=False)


def _result(entry: LedgerEntry, *, replayed: bool) -> CaptureResultDto:
    project: JsonValue = entry.extra.get("project_id")
    return CaptureResultDto(
        record_id=entry.record_id.value if entry.record_id is not None else "",
        record_type=RecordTypeEnum.EXPERIENCE.value,
        space_id=entry.space_id.value,
        project_id=project if isinstance(project, str) else None,
        replayed=replayed,
    )
