"""Capture a graph-owned Knowledge proposal (flow 1 of the record store, D-005)."""

from pydantic import Field, field_validator

from noesis.bounded_context.knowledge.application.dtos import CaptureResultDto
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
from noesis.bounded_context.knowledge.application.services.record_reference_resolver import (
    RecordReferenceResolver,
)
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CORE_STEP,
    require_steps,
)
from noesis.bounded_context.knowledge.application.services.secret_redactor import SecretRedactor
from noesis.bounded_context.knowledge.domain.entities import Knowledge
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    Applicability,
    GraphContent,
    Key,
    OwnershipEnum,
    RecordId,
    RecordStatusEnum,
    RecordTypeEnum,
    Slug,
    SpaceId,
    Tag,
)
from noesis.exceptions import EntryAlreadyExistsError, InvalidRecordError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.domain import JsonValue
from noesis.utils import FrozenObject

CAPTURE_KNOWLEDGE_COMMAND: str = "capture_knowledge"


class CaptureKnowledgeCommand(FrozenObject):
    """Propose graph-owned knowledge.

    Attributes:
        idempotency_key: Caller-chosen key; a repeat with the same request returns the first result.
        space_key: Key of the space to capture into.
        title: Short title.
        body: Full text.
        subtype: Open validated slug.
        actor: Who captures.
        project: Project to anchor it to (ensured); None for space-wide.
        tags: Labels; sorted and de-duplicated.
        sources: Existing source ids and/or new source descriptions; at least one.
    """

    idempotency_key: str = Field(min_length=1)
    space_key: Key
    title: str
    body: str
    subtype: Slug
    actor: Actor
    project: ProjectRef | None = None
    tags: tuple[Tag, ...] = ()
    sources: tuple[SourceInput, ...]

    @field_validator("tags")
    @classmethod
    def _normalised(cls, value: tuple[Tag, ...]) -> tuple[Tag, ...]:
        return tuple(sorted(set(value), key=lambda tag: tag.value))


class CaptureKnowledgeHandler(IHandler[CaptureKnowledgeCommand, CaptureResultDto]):
    """Captures knowledge: ledger read, ensure project and sources, then record and ledger entry.

    A known key with the same request returns the stored result without writing; with a
    different request it fails before any ensure. A record or ledger insert that loses a race
    re-reads the ledger and returns the winner's result.
    """

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

    async def handle(self, action: CaptureKnowledgeCommand) -> CaptureResultDto:
        """Capture, or replay the earlier identical capture.

        Raises:
            InvalidRecordError: No source, or a blank title or body.
            StoreNotInitialisedError: The `core` schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            IdempotencyKeyReusedError: The key was used for a different request.
            ReferenceNotInSpaceError: An existing source id is not in the space.
        """
        if not action.sources:
            raise InvalidRecordError(
                "Knowledge needs at least one source.", next_steps=["Cite at least one source."]
            )
        await require_steps(self._schema, CORE_STEP)
        space_id: SpaceId = await self._references.resolve_space(action.space_key)
        fingerprint: str = fingerprint_request(
            CAPTURE_KNOWLEDGE_COMMAND, action, exclude={"idempotency_key"}
        )
        known: LedgerEntry | None = replay_of(
            await read_ledger(self._uow_factory, space_id, action.idempotency_key),
            command=CAPTURE_KNOWLEDGE_COMMAND,
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
        now = self._clock.now()
        knowledge: Knowledge = Knowledge.create(
            id=self._ids.new_record_id(),
            space_id=space_id,
            ownership=OwnershipEnum.GRAPH,
            subtype=action.subtype,
            applicability=Applicability(project_id=project_id, tags=frozenset(action.tags)),
            actor=action.actor,
            source_ids=source_ids,
            content=GraphContent(
                title=SecretRedactor.redact(action.title)[0],
                body=SecretRedactor.redact(action.body)[0],
            ),
            now=now,
        )
        project_value: JsonValue = project_id.value if project_id is not None else None
        entry: LedgerEntry = LedgerEntry(
            space_id=space_id,
            key=action.idempotency_key,
            command=CAPTURE_KNOWLEDGE_COMMAND,
            fingerprint=fingerprint,
            record_id=knowledge.id,
            revision=knowledge.head_number,
            extra={"project_id": project_value},
            recorded_at=now,
        )
        try:
            async with self._uow_factory() as uow:
                await uow.knowledge.add(knowledge)
                await uow.ledger.record(entry)
                await uow.commit()
        except EntryAlreadyExistsError:
            winner: LedgerEntry | None = replay_of(
                await read_ledger(self._uow_factory, space_id, action.idempotency_key),
                command=CAPTURE_KNOWLEDGE_COMMAND,
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
        record_type=RecordTypeEnum.KNOWLEDGE.value,
        revision=entry.revision,
        status=RecordStatusEnum.PROPOSED.value,
        space_id=entry.space_id.value,
        project_id=project if isinstance(project, str) else None,
        replayed=replayed,
    )
