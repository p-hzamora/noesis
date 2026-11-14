"""Revise graph-owned Knowledge while it is still `proposed`."""

from pydantic import Field

from noesis.bounded_context.knowledge.application.dtos import ReviseResultDto
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
from noesis.bounded_context.knowledge.application.services.inputs import SourceInput
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
    GraphContent,
    Key,
    RecordId,
    RecordStatusEnum,
    Revision,
    SpaceId,
)
from noesis.exceptions import (
    EntryAlreadyExistsError,
    InvalidRecordError,
    RecordNotFoundError,
    RecordNotRevisableError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.utils import FrozenObject

REVISE_KNOWLEDGE_COMMAND: str = "revise_knowledge"


class ReviseKnowledgeCommand(FrozenObject):
    """Append a revision to proposed, graph-owned knowledge.

    Attributes:
        idempotency_key: Caller-chosen key; a repeat with the same request returns the first result.
        space_key: Key of the record's space.
        record_id: The knowledge to revise.
        expected_revision: The head number the change is based on.
        actor: Who revises.
        title: New title; the head's when None.
        body: New text; the head's when None.
        sources: Sources of the new revision; the head's when empty.
    """

    idempotency_key: str = Field(min_length=1)
    space_key: Key
    record_id: RecordId
    expected_revision: int = Field(ge=1)
    actor: Actor
    title: str | None = None
    body: str | None = None
    sources: tuple[SourceInput, ...] = ()


class ReviseKnowledgeHandler(IHandler[ReviseKnowledgeCommand, ReviseResultDto]):
    """Locks the record, checks its status then its head, appends n+1 and the ledger entry."""

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
        self._schema: IStoreSchema = schema
        self._references: RecordReferenceResolver = RecordReferenceResolver(
            uow_factory=uow_factory, clock=clock, ids=ids
        )

    async def handle(self, action: ReviseKnowledgeCommand) -> ReviseResultDto:
        """Revise, or replay the earlier identical revise.

        Raises:
            InvalidRecordError: Neither title nor body given, or the record is file-owned.
            StoreNotInitialisedError: The `core` schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            IdempotencyKeyReusedError: The key was used for a different request.
            ReferenceNotInSpaceError: An existing source id is not in the space.
            RecordNotFoundError: No such knowledge in the space.
            RecordNotRevisableError: The record is an experience.
            KnowledgeNotRevisableError: The knowledge is not `proposed`.
            RevisionConflictError: The expected revision is not the head.
        """
        if action.title is None and action.body is None:
            raise InvalidRecordError(
                "A revision needs a new title or a new body.",
                next_steps=["Pass --title and/or --body."],
            )
        await require_steps(self._schema, CORE_STEP)
        space_id: SpaceId = await self._references.resolve_space(action.space_key)
        fingerprint: str = fingerprint_request(
            REVISE_KNOWLEDGE_COMMAND, action, exclude={"idempotency_key"}
        )
        known: LedgerEntry | None = replay_of(
            await read_ledger(self._uow_factory, space_id, action.idempotency_key),
            command=REVISE_KNOWLEDGE_COMMAND,
            fingerprint=fingerprint,
        )
        if known is not None:
            return _result(known, replayed=True)
        new_source_ids: tuple[RecordId, ...] = await self._references.ensure_sources(
            space_id, action.sources
        )

        try:
            async with self._uow_factory() as uow:
                knowledge: Knowledge | None = await uow.knowledge.get_for_update(
                    action.record_id, space_id=space_id
                )
                if knowledge is None:
                    if await uow.experiences.get(action.record_id, space_id=space_id) is not None:
                        raise RecordNotRevisableError(
                            f"Record {action.record_id.value} is an experience; experiences are write-once.",
                            {"record_id": action.record_id.value, "type": "experience"},
                            next_steps=["Capture a new experience instead."],
                        )
                    raise RecordNotFoundError(
                        f"No knowledge {action.record_id.value} in this space.",
                        {"record_id": action.record_id.value, "space_id": space_id.value},
                        next_steps=["Check the id and the active space."],
                    )
                # A concurrent identical request may have committed while we waited for the lock.
                raced: LedgerEntry | None = replay_of(
                    await uow.ledger.get(space_id, action.idempotency_key),
                    command=REVISE_KNOWLEDGE_COMMAND,
                    fingerprint=fingerprint,
                )
                if raced is not None:
                    return _result(raced, replayed=True)
                current = knowledge.head.content
                if not isinstance(current, GraphContent):
                    raise InvalidRecordError(
                        "File-owned knowledge has no editable text; register a new file version instead.",
                        {"record_id": knowledge.id.value},
                    )
                now = self._clock.now()
                revision: Revision = knowledge.revise(
                    expected_revision=action.expected_revision,
                    actor=action.actor,
                    source_ids=new_source_ids or knowledge.head.source_ids,
                    content=GraphContent(
                        title=SecretRedactor.redact(action.title)[0]
                        if action.title is not None
                        else current.title,
                        body=SecretRedactor.redact(action.body)[0]
                        if action.body is not None
                        else current.body,
                    ),
                    now=now,
                )
                entry: LedgerEntry = LedgerEntry(
                    space_id=space_id,
                    key=action.idempotency_key,
                    command=REVISE_KNOWLEDGE_COMMAND,
                    fingerprint=fingerprint,
                    record_id=knowledge.id,
                    revision=revision.number,
                    recorded_at=now,
                )
                await uow.knowledge.append_revision(knowledge, revision)
                await uow.ledger.record(entry)
                await uow.commit()
        except EntryAlreadyExistsError:
            winner: LedgerEntry | None = replay_of(
                await read_ledger(self._uow_factory, space_id, action.idempotency_key),
                command=REVISE_KNOWLEDGE_COMMAND,
                fingerprint=fingerprint,
            )
            if winner is None:
                raise
            return _result(winner, replayed=True)
        return _result(entry, replayed=False)


def _result(entry: LedgerEntry, *, replayed: bool) -> ReviseResultDto:
    return ReviseResultDto(
        record_id=entry.record_id.value if entry.record_id is not None else "",
        revision=entry.revision or 0,
        status=RecordStatusEnum.PROPOSED.value,
        space_id=entry.space_id.value,
        replayed=replayed,
    )
