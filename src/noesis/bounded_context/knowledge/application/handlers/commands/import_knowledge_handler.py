"""Import one note or file as graph-owned Knowledge: create, revise or propose a successor."""

from noesis.bounded_context.knowledge.application.dtos import (
    ImportKnowledgeResultDto,
    PendingRecordChange,
)
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IImportCandidateReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.ports.supersession import (
    ISupersessionProposer,
)
from noesis.bounded_context.knowledge.application.services.idempotency import (
    fingerprint_request,
    read_ledger,
    replay_of,
)
from noesis.bounded_context.knowledge.application.services.import_keys import (
    FINGERPRINT_EXCLUDE,
    IMPORT_CREATE_COMMAND,
    IMPORT_REVISE_COMMAND,
    IMPORT_SUCCESSOR_COMMAND,
    content_hash,
    create_key,
    revise_key,
    successor_key,
    supersedes_key,
)
from noesis.bounded_context.knowledge.application.services.import_outcomes import (
    UNLINKED_SUCCESSOR_NOTE,
    ImportOutcomeEnum,
    result_of,
)
from noesis.bounded_context.knowledge.application.services.import_planner import ImportPlanner
from noesis.bounded_context.knowledge.application.services.import_request import (
    ImportRequest,
    PreparedImport,
)
from noesis.bounded_context.knowledge.application.services.inputs import (
    NewSourceInput,
    ProjectRef,
    SourceInput,
)
from noesis.bounded_context.knowledge.application.services.record_changes import (
    pending_changes_from,
)
from noesis.bounded_context.knowledge.application.services.record_reference_resolver import (
    RecordReferenceResolver,
)
from noesis.bounded_context.knowledge.domain.entities import Knowledge
from noesis.bounded_context.knowledge.domain.value_objects import (
    Applicability,
    ImportCandidate,
    ImportDecision,
    ImportDecisionKindEnum,
    OwnershipEnum,
    RecordId,
    RecordStatusEnum,
    Revision,
    SourceKindEnum,
)
from noesis.exceptions import EntryAlreadyExistsError, RecordNotFoundError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.domain import JsonValue

_CREATING: frozenset[ImportDecisionKindEnum] = frozenset(
    {
        ImportDecisionKindEnum.CREATE,
        ImportDecisionKindEnum.SUCCESSOR_LINKED,
        ImportDecisionKindEnum.SUCCESSOR_UNLINKED,
    }
)


class ImportKnowledgeCommand(ImportRequest):
    """Import one note or file; the fields are those of `ImportRequest`."""


class ImportKnowledgeHandler(IHandler[ImportKnowledgeCommand, ImportKnowledgeResultDto]):
    """Applies the decision table: rows that write nothing return at once; the others write.

    A known idempotency key with the same request returns the stored result; a create or revise
    that loses a race re-reads the ledger and returns the winner's result. Without a
    `proposer` an accepted target gets a plain successor (no `supersedes` proposal).
    """

    def __init__(
        self,
        *,
        uow_factory: KnowledgeUnitOfWorkFactory,
        clock: IClock,
        ids: IRecordIdGenerator,
        schema: IStoreSchema,
        candidates: IImportCandidateReadRepository,
        proposer: ISupersessionProposer | None = None,
    ) -> None:
        self._uow_factory: KnowledgeUnitOfWorkFactory = uow_factory
        self._clock: IClock = clock
        self._ids: IRecordIdGenerator = ids
        self._proposer: ISupersessionProposer | None = proposer
        self._references: RecordReferenceResolver = RecordReferenceResolver(
            uow_factory=uow_factory, clock=clock, ids=ids
        )
        self._planner: ImportPlanner = ImportPlanner(
            uow_factory=uow_factory, clock=clock, ids=ids, schema=schema, candidates=candidates
        )

    async def handle(self, action: ImportKnowledgeCommand) -> ImportKnowledgeResultDto:
        """Import the note, or return what an earlier identical import did.

        Raises:
            InvalidRecordError: A blank title or body.
            StoreNotInitialisedError: The `core` schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            IdempotencyKeyReusedError: The write's key holds a different request.
            EntryAlreadyExistsError: The create lost on the record id and no ledger entry won.
            RevisionConflictError: The target moved before the revision was appended.
            KnowledgeNotRevisableError: The target is no longer `proposed`.
        """
        prepared: PreparedImport = await self._planner.prepare(action)
        decision: ImportDecision = await self._planner.decide(
            prepared, can_link_successor=self._proposer is not None
        )
        target: ImportCandidate | None = decision.target
        if decision.kind is ImportDecisionKindEnum.REVISE and target is not None:
            return await self._revise(prepared, target)
        if decision.kind in _CREATING:
            return await self._create(prepared, decision)
        return result_of(decision, prepared)

    async def _create(
        self, prepared: PreparedImport, decision: ImportDecision
    ) -> ImportKnowledgeResultDto:
        request: ImportRequest = prepared.request
        target: ImportCandidate | None = decision.target
        hashed: str = content_hash(prepared.content, request.source_digest)
        command: str = IMPORT_CREATE_COMMAND
        key: str = create_key(request.record_id, request.source_locator, hashed)
        if target is not None:
            command = IMPORT_SUCCESSOR_COMMAND
            key = successor_key(target.id, target.head_revision, hashed)
        fingerprint: str = fingerprint_request(command, request, exclude=FINGERPRINT_EXCLUDE)
        known: LedgerEntry | None = replay_of(
            await read_ledger(self._uow_factory, prepared.space_id, key),
            command=command,
            fingerprint=fingerprint,
        )
        if known is not None:
            return self._replayed(known)

        project_id: RecordId | None = await self._references.ensure_project(
            prepared.space_id,
            ProjectRef(key=request.project_key) if request.project_key is not None else None,
        )
        source_ids: tuple[RecordId, ...] = await self._ensure_sources(prepared)
        now = self._clock.now()
        record_id: RecordId = (
            request.record_id
            if target is None and request.record_id is not None
            else self._ids.new_record_id()
        )
        knowledge: Knowledge = Knowledge.create(
            id=record_id,
            space_id=prepared.space_id,
            ownership=OwnershipEnum.GRAPH,
            subtype=request.subtype,
            applicability=Applicability(
                project_id=project_id, tags=frozenset((*request.tags, request.origin_tag))
            ),
            actor=request.actor,
            source_ids=source_ids,
            content=prepared.content,
            now=now,
        )
        changes: list[PendingRecordChange] = pending_changes_from(
            knowledge.collect_events(),
            record_type="knowledge",
            status=knowledge.status.value,
            occurred_at=now,
        )
        linked: bool = decision.kind is ImportDecisionKindEnum.SUCCESSOR_LINKED
        extra: dict[str, JsonValue] = (
            {"target_record_id": target.id.value, "linked": linked} if target is not None else {}
        )
        entry: LedgerEntry = LedgerEntry(
            space_id=prepared.space_id,
            key=key,
            command=command,
            fingerprint=fingerprint,
            record_id=record_id,
            revision=1,
            extra=extra,
            recorded_at=now,
        )
        try:
            async with self._uow_factory() as uow:
                await uow.knowledge.add(knowledge)
                await uow.ledger.record(entry)
                for change in changes:
                    await uow.changes.append(change)
                await uow.commit()
        except EntryAlreadyExistsError:
            winner: LedgerEntry | None = replay_of(
                await read_ledger(self._uow_factory, prepared.space_id, key),
                command=command,
                fingerprint=fingerprint,
            )
            if winner is None:
                raise
            return self._replayed(winner)
        if linked and target is not None and self._proposer is not None:
            assertion_id: RecordId = await self._link(
                self._proposer, prepared, record_id, target, source_ids
            )
            return self._from_entry(entry, replayed=False, assertion_id=assertion_id)
        return self._from_entry(entry, replayed=False)

    @staticmethod
    async def _link(
        proposer: ISupersessionProposer,
        prepared: PreparedImport,
        successor_id: RecordId,
        target: ImportCandidate,
        source_ids: tuple[RecordId, ...],
    ) -> RecordId:
        """Propose `successor supersedes target`; a failure leaves the successor unlinked (D-022)."""
        file_source_id: RecordId = source_ids[0]  # ensured first: the file_version Source
        return await proposer.propose(
            subject_id=successor_id,
            object_id=target.id,
            rationale=f"content of {prepared.request.source_locator} changed after acceptance",
            source_ids=(file_source_id,),
            actor=prepared.request.actor,
            idempotency_key=supersedes_key(successor_id, target.id),
            space_id=prepared.space_id,
        )

    async def _revise(
        self, prepared: PreparedImport, target: ImportCandidate
    ) -> ImportKnowledgeResultDto:
        request: ImportRequest = prepared.request
        key: str = revise_key(
            target.id, target.head_revision, content_hash(prepared.content, request.source_digest)
        )
        fingerprint: str = fingerprint_request(
            IMPORT_REVISE_COMMAND, request, exclude=FINGERPRINT_EXCLUDE
        )
        known: LedgerEntry | None = replay_of(
            await read_ledger(self._uow_factory, prepared.space_id, key),
            command=IMPORT_REVISE_COMMAND,
            fingerprint=fingerprint,
        )
        if known is not None:
            return self._replayed(known)

        source_ids: tuple[RecordId, ...] = await self._ensure_sources(prepared)
        try:
            async with self._uow_factory() as uow:
                knowledge: Knowledge | None = await uow.knowledge.get_for_update(
                    target.id, space_id=prepared.space_id
                )
                if knowledge is None:
                    raise RecordNotFoundError(
                        f"No knowledge {target.id.value} in this space.",
                        {"record_id": target.id.value, "space_id": prepared.space_id.value},
                    )
                # a concurrent identical request may have committed while we waited for the lock
                raced: LedgerEntry | None = replay_of(
                    await uow.ledger.get(prepared.space_id, key),
                    command=IMPORT_REVISE_COMMAND,
                    fingerprint=fingerprint,
                )
                if raced is not None:
                    return self._replayed(raced)
                now = self._clock.now()
                revision: Revision = knowledge.revise(
                    expected_revision=target.head_revision,
                    actor=request.actor,
                    source_ids=source_ids,
                    content=prepared.content,
                    now=now,
                )
                entry: LedgerEntry = LedgerEntry(
                    space_id=prepared.space_id,
                    key=key,
                    command=IMPORT_REVISE_COMMAND,
                    fingerprint=fingerprint,
                    record_id=knowledge.id,
                    revision=revision.number,
                    recorded_at=now,
                )
                revised: list[PendingRecordChange] = pending_changes_from(
                    knowledge.collect_events(),
                    record_type="knowledge",
                    status=knowledge.status.value,
                    occurred_at=now,
                )
                await uow.knowledge.append_revision(knowledge, revision)
                await uow.ledger.record(entry)
                for change in revised:
                    await uow.changes.append(change)
                await uow.commit()
        except EntryAlreadyExistsError:
            winner: LedgerEntry | None = replay_of(
                await read_ledger(self._uow_factory, prepared.space_id, key),
                command=IMPORT_REVISE_COMMAND,
                fingerprint=fingerprint,
            )
            if winner is None:
                raise
            return self._replayed(winner)
        return self._from_entry(entry, replayed=False)

    async def _ensure_sources(self, prepared: PreparedImport) -> tuple[RecordId, ...]:
        """The file's Source first, then one per header source (so the file is `[0]`)."""
        request: ImportRequest = prepared.request
        inputs: tuple[SourceInput, ...] = (
            NewSourceInput(
                kind=SourceKindEnum.FILE_VERSION,
                locator=request.source_locator,
                digest=request.source_digest,
            ),
            *(
                NewSourceInput(kind=source.kind, locator=source.locator)
                for source in request.header_sources
            ),
        )
        return await self._references.ensure_sources(prepared.space_id, inputs)

    def _replayed(self, entry: LedgerEntry) -> ImportKnowledgeResultDto:
        return self._from_entry(entry, replayed=True)

    @staticmethod
    def _from_entry(
        entry: LedgerEntry, *, replayed: bool, assertion_id: RecordId | None = None
    ) -> ImportKnowledgeResultDto:
        """The result a ledger entry stands for (the same on the first run and on a replay)."""
        record_id: str | None = entry.record_id.value if entry.record_id is not None else None
        proposed: str = RecordStatusEnum.PROPOSED.value
        if entry.command == IMPORT_REVISE_COMMAND:
            return ImportKnowledgeResultDto(
                outcome=ImportOutcomeEnum.REVISED,
                record_id=record_id,
                revision=entry.revision,
                status=proposed,
                replayed=replayed,
            )
        if entry.command == IMPORT_SUCCESSOR_COMMAND:
            target: JsonValue = entry.extra.get("target_record_id")
            linked: bool = entry.extra.get("linked") is True
            return ImportKnowledgeResultDto(
                outcome=ImportOutcomeEnum.SUCCESSOR_PROPOSED
                if linked
                else ImportOutcomeEnum.CREATED,
                record_id=record_id,
                revision=entry.revision,
                status=proposed,
                target_record_id=target if isinstance(target, str) else None,
                assertion_id=assertion_id.value if assertion_id is not None else None,
                reason=None if linked else UNLINKED_SUCCESSOR_NOTE,
                replayed=replayed,
            )
        return ImportKnowledgeResultDto(
            outcome=ImportOutcomeEnum.CREATED,
            record_id=record_id,
            revision=entry.revision,
            status=proposed,
            replayed=replayed,
        )
