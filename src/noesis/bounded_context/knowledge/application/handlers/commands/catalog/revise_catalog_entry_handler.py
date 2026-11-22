"""Revise a catalog entry: a partial update that appends revision n+1."""

from pydantic import Field

from noesis.bounded_context.knowledge.application.dtos import (
    CatalogWriteResultDto,
    PendingRecordChange,
)
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.catalog_lookup import (
    catalog_entry_not_found,
    is_record_id,
)
from noesis.bounded_context.knowledge.application.services.idempotency import (
    fingerprint_request,
    read_ledger,
    replay_of,
)
from noesis.bounded_context.knowledge.application.services.inputs import SourceInput
from noesis.bounded_context.knowledge.application.services.record_changes import (
    pending_changes_from,
)
from noesis.bounded_context.knowledge.application.services.record_reference_resolver import (
    RecordReferenceResolver,
)
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CATALOG_STEP,
    CORE_STEP,
    require_steps,
)
from noesis.bounded_context.knowledge.application.services.secret_redactor import SecretRedactor
from noesis.bounded_context.knowledge.domain.entities import CatalogEntry
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    CatalogEntryKindEnum,
    CatalogRef,
    CatalogRevision,
    ContentHash,
    Key,
    RecordId,
    SpaceId,
    Tag,
)
from noesis.exceptions import (
    EntryAlreadyExistsError,
    InvalidCatalogPrerequisiteError,
    InvalidRecordError,
    RevisionConflictError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.utils import FrozenObject

REVISE_CATALOG_ENTRY_COMMAND: str = "revise_catalog_entry"


class ReviseCatalogEntryCommand(FrozenObject):
    """Append a revision; only the options given replace the head's values.

    Attributes:
        idempotency_key: Caller-chosen key; a repeat with the same request returns the first result.
        space_key: Key of the entry's space.
        ref: The entry id, or `kind:name` (split on the first colon).
        expected_revision: The head number the change is based on.
        purpose: New purpose; the head's when None.
        version: New declared version; the head's when None, cleared when blank.
        prerequisites: New prerequisites as `kind:name` text; the head's when None, cleared when
            empty, otherwise replacing the whole list.
        location: New location; the head's when None.
        actor: Who revises.
        sources: Sources of the new revision; at least one.
        capabilities: New capability tags; the head's when None, cleared when empty.
        manifest_digest: Manifest hash the values were read from; the head's when None.
    """

    idempotency_key: str = Field(min_length=1)
    space_key: Key
    ref: str = Field(min_length=1)
    expected_revision: int = Field(ge=1)
    purpose: str | None = None
    version: str | None = None
    prerequisites: tuple[str, ...] | None = None
    location: str | None = None
    actor: Actor
    sources: tuple[SourceInput, ...]
    capabilities: tuple[str, ...] | None = None
    manifest_digest: ContentHash | None = None


class ReviseCatalogEntryHandler(IHandler[ReviseCatalogEntryCommand, CatalogWriteResultDto]):
    """Locks the entry, checks its head, appends n+1 and the ledger entry; a no-op writes nothing."""

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

    async def handle(self, action: ReviseCatalogEntryCommand) -> CatalogWriteResultDto:
        """Revise, replay the earlier identical revise, or do nothing when nothing changes.

        Raises:
            InvalidRecordError: No source.
            InvalidCatalogPrerequisiteError: A prerequisite is malformed, or the entry requires
                itself.
            StoreNotInitialisedError: The `core` or `catalog` schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            IdempotencyKeyReusedError: The key was used for a different request.
            CatalogEntryNotFoundError: No such entry in the space, or the reference is neither
                an id nor `kind:name`.
            ReferenceNotInSpaceError: An existing source id is not in the space.
            RevisionConflictError: The expected revision is not the head (checked before the
                no-op decision).
        """
        if not action.sources:
            raise InvalidRecordError(
                "A catalog revision needs at least one source.",
                next_steps=["Cite at least one source."],
            )
        prerequisites: tuple[CatalogRef, ...] | None = (
            None
            if action.prerequisites is None
            else tuple(CatalogRef.parse(p) for p in action.prerequisites)
        )
        ref: CatalogRef | RecordId | None = _parse_ref(action.ref)
        await require_steps(self._schema, CORE_STEP, CATALOG_STEP)
        space_id: SpaceId = await self._references.resolve_space(action.space_key)
        fingerprint: str = fingerprint_request(
            REVISE_CATALOG_ENTRY_COMMAND, action, exclude={"idempotency_key"}
        )
        known: LedgerEntry | None = replay_of(
            await read_ledger(self._uow_factory, space_id, action.idempotency_key),
            command=REVISE_CATALOG_ENTRY_COMMAND,
            fingerprint=fingerprint,
        )
        if known is not None:
            return _result(known, replayed=True)
        async with self._uow_factory() as uow:
            found: CatalogEntry | None = None
            if isinstance(ref, RecordId):
                found = await uow.catalog_entries.get(ref, space_id=space_id)
            elif ref is not None:
                found = await uow.catalog_entries.get_by_key(space_id, ref.kind, ref.name.value)
        if found is None:
            raise catalog_entry_not_found(action.ref, space_id)
        new_source_ids: tuple[RecordId, ...] = await self._references.ensure_sources(
            space_id, action.sources
        )

        try:
            async with self._uow_factory() as uow:
                entry: CatalogEntry | None = await uow.catalog_entries.get_for_update(
                    found.id, space_id=space_id
                )
                if entry is None:
                    raise catalog_entry_not_found(action.ref, space_id)
                # A concurrent identical request may have committed while we waited for the lock.
                raced: LedgerEntry | None = replay_of(
                    await uow.ledger.get(space_id, action.idempotency_key),
                    command=REVISE_CATALOG_ENTRY_COMMAND,
                    fingerprint=fingerprint,
                )
                if raced is not None:
                    return _result(raced, replayed=True)
                previous: CatalogRevision = entry.head
                now = self._clock.now()
                merged_purpose: str = (
                    SecretRedactor.redact(action.purpose)[0]
                    if action.purpose is not None
                    else previous.purpose
                )
                merged_version: str | None = (
                    previous.version if action.version is None else (action.version.strip() or None)
                )
                merged_prerequisites: tuple[CatalogRef, ...] = (
                    previous.prerequisites if prerequisites is None else prerequisites
                )
                merged_location: str = (
                    previous.location if action.location is None else action.location
                )
                merged_capabilities: frozenset[Tag] = (
                    previous.capabilities
                    if action.capabilities is None
                    else frozenset(Tag(value=tag) for tag in action.capabilities)
                )
                merged_digest: ContentHash | None = (
                    action.manifest_digest or previous.manifest_digest
                )
                # A stale request still goes through `revise` so it raises the conflict.
                if action.expected_revision == entry.head_number and entry.head_has_content(
                    purpose=merged_purpose,
                    version=merged_version,
                    prerequisites=merged_prerequisites,
                    location=merged_location,
                    capabilities=merged_capabilities,
                    manifest_digest=merged_digest,
                    origin=previous.origin,
                ):
                    return _write_result(entry, previous.number, replayed=False)
                revision: CatalogRevision = entry.revise(
                    expected_revision=action.expected_revision,
                    purpose=merged_purpose,
                    version=merged_version,
                    prerequisites=merged_prerequisites,
                    location=merged_location,
                    actor=action.actor,
                    source_ids=new_source_ids,
                    now=now,
                    capabilities=merged_capabilities,
                    manifest_digest=merged_digest,
                    origin=previous.origin,
                )
                ledger_entry: LedgerEntry = LedgerEntry(
                    space_id=space_id,
                    key=action.idempotency_key,
                    command=REVISE_CATALOG_ENTRY_COMMAND,
                    fingerprint=fingerprint,
                    record_id=entry.id,
                    revision=revision.number,
                    extra={"kind": entry.kind.value, "name": entry.name.value},
                    recorded_at=now,
                )
                changes: list[PendingRecordChange] = pending_changes_from(
                    entry.collect_events(),
                    record_type="catalog_entry",
                    status=None,
                    occurred_at=now,
                )
                await uow.catalog_entries.append_revision(entry, revision)
                await uow.ledger.record(ledger_entry)
                for change in changes:
                    await uow.changes.append(change)
                await uow.commit()
        except EntryAlreadyExistsError, RevisionConflictError:
            winner: LedgerEntry | None = replay_of(
                await read_ledger(self._uow_factory, space_id, action.idempotency_key),
                command=REVISE_CATALOG_ENTRY_COMMAND,
                fingerprint=fingerprint,
            )
            if winner is None:
                raise
            return _result(winner, replayed=True)
        return _result(ledger_entry, replayed=False)


def _parse_ref(ref: str) -> CatalogRef | RecordId | None:
    """An id or `kind:name`; None when it is neither (it then matches nothing)."""
    if is_record_id(ref):
        return RecordId(value=ref)
    try:
        return CatalogRef.parse(ref)
    except InvalidCatalogPrerequisiteError:
        return None


def _write_result(entry: CatalogEntry, revision: int, *, replayed: bool) -> CatalogWriteResultDto:
    return CatalogWriteResultDto(
        id=entry.id.value,
        kind=entry.kind,
        name=entry.name.value,
        revision=revision,
        space_id=entry.space_id.value,
        replayed=replayed,
    )


def _result(entry: LedgerEntry, *, replayed: bool) -> CatalogWriteResultDto:
    return CatalogWriteResultDto(
        id=entry.record_id.value if entry.record_id is not None else "",
        kind=CatalogEntryKindEnum(str(entry.extra.get("kind"))),
        name=str(entry.extra.get("name")),
        revision=entry.revision or 0,
        space_id=entry.space_id.value,
        replayed=replayed,
    )
