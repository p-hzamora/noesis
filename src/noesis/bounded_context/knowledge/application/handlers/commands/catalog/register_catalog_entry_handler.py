"""Register a capability in the catalog (revision 1)."""

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
from noesis.bounded_context.knowledge.domain.entities.catalog_entry import (
    ensure_no_self_prerequisite,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    CatalogEntryKindEnum,
    CatalogEntryName,
    CatalogRef,
    Key,
    RecordId,
    SpaceId,
)
from noesis.exceptions import (
    CatalogEntryAlreadyExistsError,
    EntryAlreadyExistsError,
    InvalidRecordError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.utils import FrozenObject

REGISTER_CATALOG_ENTRY_COMMAND: str = "register_catalog_entry"


class RegisterCatalogEntryCommand(FrozenObject):
    """Register a capability with explicit values.

    Attributes:
        idempotency_key: Caller-chosen key; a repeat with the same request returns the first result.
        space_key: Key of the space to register into.
        kind: What it is.
        name: Its name (the catalog name grammar).
        purpose: What it is for; secrets are masked before storage.
        version: Declared version; None or blank for none.
        prerequisites: What must be present, as `kind:name` text.
        location: Where its definition is version-controlled; never an install path.
        actor: Who registers.
        sources: Existing source ids and/or new source descriptions; at least one.
    """

    idempotency_key: str = Field(min_length=1)
    space_key: Key
    kind: CatalogEntryKindEnum
    name: str
    purpose: str
    version: str | None = None
    prerequisites: tuple[str, ...] = ()
    location: str
    actor: Actor
    sources: tuple[SourceInput, ...]


class RegisterCatalogEntryHandler(IHandler[RegisterCatalogEntryCommand, CatalogWriteResultDto]):
    """Registers an entry: ledger read, duplicate check, ensure sources, then entry and ledger.

    A known key with the same request returns the stored result without writing; with a
    different request it fails before any ensure. An entry or ledger insert that loses a race
    re-reads the ledger and returns the winner's result, or reports the duplicate.
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

    async def handle(self, action: RegisterCatalogEntryCommand) -> CatalogWriteResultDto:
        """Register, or replay the earlier identical registration.

        Raises:
            InvalidCatalogNameError: The name breaks the grammar.
            InvalidCatalogPrerequisiteError: A prerequisite is malformed or the entry itself.
            InvalidRecordError: No source, or a blank purpose or location.
            StoreNotInitialisedError: The `core` or `catalog` schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            IdempotencyKeyReusedError: The key was used for a different request.
            CatalogEntryAlreadyExistsError: The kind and name already exist in the space.
            ReferenceNotInSpaceError: An existing source id is not in the space.
        """
        if not action.sources:
            raise InvalidRecordError(
                "A catalog entry needs at least one source.",
                next_steps=["Cite at least one source."],
            )
        name: CatalogEntryName = CatalogEntryName(value=action.name)
        prerequisites: tuple[CatalogRef, ...] = tuple(
            CatalogRef.parse(p) for p in action.prerequisites
        )
        ensure_no_self_prerequisite(action.kind, name, prerequisites)
        await require_steps(self._schema, CORE_STEP, CATALOG_STEP)
        space_id: SpaceId = await self._references.resolve_space(action.space_key)
        fingerprint: str = fingerprint_request(
            REGISTER_CATALOG_ENTRY_COMMAND, action, exclude={"idempotency_key"}
        )
        known: LedgerEntry | None = replay_of(
            await read_ledger(self._uow_factory, space_id, action.idempotency_key),
            command=REGISTER_CATALOG_ENTRY_COMMAND,
            fingerprint=fingerprint,
        )
        if known is not None:
            return _result(known, replayed=True)
        async with self._uow_factory() as uow:
            existing: CatalogEntry | None = await uow.catalog_entries.get_by_key(
                space_id, action.kind, name.value
            )
        if existing is not None:
            raise _already_exists(action.kind, name)

        source_ids: tuple[RecordId, ...] = await self._references.ensure_sources(
            space_id, action.sources
        )
        now = self._clock.now()
        entry: CatalogEntry = CatalogEntry.create(
            id=self._ids.new_record_id(),
            space_id=space_id,
            kind=action.kind,
            name=name.value,
            purpose=SecretRedactor.redact(action.purpose)[0],
            version=(action.version or "").strip() or None,
            prerequisites=prerequisites,
            location=action.location,
            actor=action.actor,
            source_ids=source_ids,
            now=now,
        )
        changes: list[PendingRecordChange] = pending_changes_from(
            entry.collect_events(), record_type="catalog_entry", status=None, occurred_at=now
        )
        ledger_entry: LedgerEntry = LedgerEntry(
            space_id=space_id,
            key=action.idempotency_key,
            command=REGISTER_CATALOG_ENTRY_COMMAND,
            fingerprint=fingerprint,
            record_id=entry.id,
            revision=entry.head_number,
            extra={"kind": action.kind.value, "name": name.value},
            recorded_at=now,
        )
        try:
            async with self._uow_factory() as uow:
                await uow.catalog_entries.add(entry)
                await uow.ledger.record(ledger_entry)
                for change in changes:
                    await uow.changes.append(change)
                await uow.commit()
        except (EntryAlreadyExistsError, CatalogEntryAlreadyExistsError) as error:
            winner: LedgerEntry | None = replay_of(
                await read_ledger(self._uow_factory, space_id, action.idempotency_key),
                command=REGISTER_CATALOG_ENTRY_COMMAND,
                fingerprint=fingerprint,
            )
            if winner is None:
                raise _already_exists(action.kind, name) from error
            return _result(winner, replayed=True)
        return _result(ledger_entry, replayed=False)


def _already_exists(
    kind: CatalogEntryKindEnum, name: CatalogEntryName
) -> CatalogEntryAlreadyExistsError:
    return CatalogEntryAlreadyExistsError(
        f"A catalog entry {kind.value}:{name.value} already exists in this space.",
        {"kind": kind.value, "name": name.value},
        next_steps=[
            f"Run `noesis catalog revise {kind.value}:{name.value}` to change the existing entry."
        ],
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
