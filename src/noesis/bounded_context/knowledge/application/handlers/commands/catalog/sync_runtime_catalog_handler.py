"""Sync the catalog with what the runtimes of this host have installed (never deletes)."""

from collections.abc import Mapping, Sequence

from noesis.bounded_context.knowledge.application.dtos import (
    CatalogEntryDto,
    CatalogWriteResultDto,
    InstalledArtifactDto,
    NotInstalledDto,
    RuntimeEnum,
    RuntimeInventoryDto,
    SkippedArtifactDto,
    SyncedEntryDto,
    SyncReportDto,
    SyncRuntimeDto,
    UnreadableKindDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.catalog.register_catalog_entry_handler import (
    RegisterCatalogEntryCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.catalog.revise_catalog_entry_handler import (
    ReviseCatalogEntryCommand,
)
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    ICatalogEntryReadRepository,
    IRecordReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.runtime import IRuntimeInventoryProbe
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.catalog_discovery import (
    DISCOVERABLE_KINDS,
    NO_DESCRIPTION,
    declared_prerequisites,
)
from noesis.bounded_context.knowledge.application.services.catalog_lookup import (
    SpaceScopedQuery,
    resolve_query_space,
)
from noesis.bounded_context.knowledge.application.services.inputs import NewSourceInput
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CATALOG_STEP,
    CORE_STEP,
    require_steps,
)
from noesis.bounded_context.knowledge.application.services.secret_redactor import SecretRedactor
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    CatalogEntryKindEnum,
    CatalogEntryName,
    CatalogOriginEnum,
    CatalogRef,
    ContentHash,
    Key,
    SourceKindEnum,
    SpaceId,
)
from noesis.exceptions import (
    CatalogEntryAlreadyExistsError,
    IdempotencyKeyReusedError,
    InvalidCatalogNameError,
    RevisionConflictError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject

type _Key = tuple[CatalogEntryKindEnum, str]
type _Observation = tuple[RuntimeEnum, InstalledArtifactDto]

INVALID_NAME: str = "invalid_name"
MANIFEST_UNREADABLE: str = "manifest_unreadable"
WRITE_CONFLICT: str = "write_conflict"


class SyncRuntimeCatalogCommand(FrozenObject):
    """Register and revise entries for what the runtimes have installed.

    Attributes:
        space_key: Key of the space to sync into.
        runtimes: Runtimes to probe, resolved by the caller, in the order the blocks come back.
        actor: Who syncs.
        dry_run: Compute the report without writing.
    """

    space_key: Key
    runtimes: tuple[RuntimeEnum, ...]
    actor: Actor
    dry_run: bool = False


class SyncRuntimeCatalogHandler(IHandler[SyncRuntimeCatalogCommand, SyncReportDto]):
    """Reads the catalog, probes, then registers or revises through the catalog handlers.

    Idempotent: an artifact whose manifest digest, description, version and prerequisites match
    its entry's head writes nothing. It never deletes or retires an entry; an entry whose
    artifact is gone is only reported `not_installed`.
    """

    def __init__(
        self,
        *,
        read_repository: ICatalogEntryReadRepository,
        records: IRecordReadRepository,
        schema: IStoreSchema,
        runtime_probes: Mapping[RuntimeEnum, IRuntimeInventoryProbe],
        register: IHandler[RegisterCatalogEntryCommand, CatalogWriteResultDto],
        revise: IHandler[ReviseCatalogEntryCommand, CatalogWriteResultDto],
    ) -> None:
        self._read_repository: ICatalogEntryReadRepository = read_repository
        self._records: IRecordReadRepository = records
        self._schema: IStoreSchema = schema
        self._runtime_probes: Mapping[RuntimeEnum, IRuntimeInventoryProbe] = runtime_probes
        self._register: IHandler[RegisterCatalogEntryCommand, CatalogWriteResultDto] = register
        self._revise: IHandler[ReviseCatalogEntryCommand, CatalogWriteResultDto] = revise

    async def handle(self, action: SyncRuntimeCatalogCommand) -> SyncReportDto:
        """Sync every requested runtime.

        Raises:
            StoreNotInitialisedError: The `core` or `catalog` schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            GraphStoreUnavailableError: The store is down; nothing was probed.
        """
        await require_steps(self._schema, CORE_STEP, CATALOG_STEP)
        space_id: SpaceId = await resolve_query_space(
            self._records, SpaceScopedQuery(space_key=action.space_key)
        )
        entries: dict[_Key, CatalogEntryDto] = {
            (entry.kind, entry.name): entry for entry in await self._read_repository.find(space_id)
        }
        inventories: list[RuntimeInventoryDto] = [
            await self._runtime_probes[runtime].inventory() for runtime in action.runtimes
        ]
        observed: dict[_Key, list[_Observation]] = {}
        for inventory in inventories:
            for artifact in inventory.artifacts:
                if artifact.kind in DISCOVERABLE_KINDS:
                    observed.setdefault((artifact.kind, artifact.name), []).append(
                        (inventory.runtime, artifact)
                    )
        handled: set[_Key] = set()
        blocks: list[SyncRuntimeDto] = []
        for inventory in inventories:
            blocks.append(await self._sync_runtime(action, inventory, entries, observed, handled))
        return SyncReportDto(
            dry_run=action.dry_run, runtimes=tuple(blocks), next_steps=_next_steps(blocks, action)
        )

    async def _sync_runtime(
        self,
        action: SyncRuntimeCatalogCommand,
        inventory: RuntimeInventoryDto,
        entries: Mapping[_Key, CatalogEntryDto],
        observed: Mapping[_Key, Sequence[_Observation]],
        handled: set[_Key],
    ) -> SyncRuntimeDto:
        registered: list[SyncedEntryDto] = []
        revised: list[SyncedEntryDto] = []
        skipped: list[SkippedArtifactDto] = []
        unchanged: int = 0
        present: set[_Key] = set()
        for artifact in inventory.artifacts:
            if artifact.kind not in DISCOVERABLE_KINDS:
                continue
            key: _Key = (artifact.kind, artifact.name)
            present.add(key)
            if key in handled:
                unchanged += 1
                continue
            handled.add(key)
            reason: str | None = _unwritable(artifact)
            if reason is not None:
                skipped.append(
                    SkippedArtifactDto(kind=artifact.kind, name=artifact.name, reason=reason)
                )
                continue
            entry: CatalogEntryDto | None = entries.get(key)
            runtime, chosen = _choose(entry, (inventory.runtime, artifact), observed[key])
            try:
                if entry is None:
                    registered.append(await self._register_entry(action, runtime, chosen))
                elif _matches(entry, chosen):
                    unchanged += 1
                else:
                    revised.append(await self._revise_entry(action, runtime, chosen, entry))
            except (
                IdempotencyKeyReusedError,
                RevisionConflictError,
                CatalogEntryAlreadyExistsError,
            ):
                skipped.append(
                    SkippedArtifactDto(
                        kind=artifact.kind, name=artifact.name, reason=WRITE_CONFLICT
                    )
                )
        return SyncRuntimeDto(
            runtime=inventory.runtime,
            host=inventory.host,
            observed_at=inventory.observed_at,
            registered=tuple(registered),
            revised=tuple(revised),
            unchanged=unchanged,
            not_installed=_not_installed(entries, present, inventory.unreadable_kinds),
            skipped=tuple(skipped),
            unreadable_kinds=inventory.unreadable_kinds,
        )

    async def _register_entry(
        self,
        action: SyncRuntimeCatalogCommand,
        runtime: RuntimeEnum,
        artifact: InstalledArtifactDto,
    ) -> SyncedEntryDto:
        digest: str = _digest(artifact)
        synced = SyncedEntryDto(kind=artifact.kind, name=artifact.name, manifest_digest=digest)
        if action.dry_run:
            return synced
        result: CatalogWriteResultDto = await self._register.handle(
            RegisterCatalogEntryCommand(
                idempotency_key=_idempotency_key(runtime, artifact),
                space_key=action.space_key,
                kind=artifact.kind,
                name=artifact.name,
                purpose=artifact.description or NO_DESCRIPTION,
                version=artifact.observed_version,
                prerequisites=_requires(artifact),
                location=f"{runtime.value}:{artifact.name}",
                actor=action.actor,
                sources=(_source(runtime, artifact),),
                manifest_digest=ContentHash(value=digest),
                origin=CatalogOriginEnum.DISCOVERED,
            )
        )
        return synced.model_copy(update={"entry_id": result.id, "revision": result.revision})

    async def _revise_entry(
        self,
        action: SyncRuntimeCatalogCommand,
        runtime: RuntimeEnum,
        artifact: InstalledArtifactDto,
        entry: CatalogEntryDto,
    ) -> SyncedEntryDto:
        digest: str = _digest(artifact)
        synced = SyncedEntryDto(
            kind=artifact.kind, name=artifact.name, manifest_digest=digest, entry_id=entry.id
        )
        if action.dry_run:
            return synced
        result: CatalogWriteResultDto = await self._revise.handle(
            ReviseCatalogEntryCommand(
                idempotency_key=f"{_idempotency_key(runtime, artifact)}:r{entry.head_revision}",
                space_key=action.space_key,
                ref=entry.id,
                expected_revision=entry.head_revision,
                purpose=artifact.description,
                version=artifact.observed_version,
                prerequisites=_revised_requires(entry, artifact),
                actor=action.actor,
                sources=(_source(runtime, artifact),),
                manifest_digest=ContentHash(value=digest),
            )
        )
        return synced.model_copy(update={"revision": result.revision})


def _unwritable(artifact: InstalledArtifactDto) -> str | None:
    try:
        CatalogEntryName(value=artifact.name)
    except InvalidCatalogNameError:
        return INVALID_NAME
    if artifact.manifest_digest is None:
        return MANIFEST_UNREADABLE
    return None


def _digest(artifact: InstalledArtifactDto) -> str:
    if artifact.manifest_digest is None:  # pragma: no cover - `_unwritable` filtered it out
        raise ValueError("The artifact has no manifest digest.")
    return artifact.manifest_digest


def _choose(
    entry: CatalogEntryDto | None, own: _Observation, group: Sequence[_Observation]
) -> _Observation:
    """The observation that drives the write.

    An entry already at the digest of any runtime's copy stays as it is (so two runtimes with
    different copies do not revise each other forever); otherwise this runtime's copy decides.
    """
    if entry is None or entry.manifest_digest is None:
        return own
    return next((item for item in group if item[1].manifest_digest == entry.manifest_digest), own)


def _own_ref(artifact: InstalledArtifactDto) -> CatalogRef:
    return CatalogRef(kind=artifact.kind, name=CatalogEntryName(value=artifact.name))


def _requires(artifact: InstalledArtifactDto) -> tuple[str, ...]:
    return declared_prerequisites(artifact.declared_requires, own=_own_ref(artifact))


def _revised_requires(
    entry: CatalogEntryDto, artifact: InstalledArtifactDto
) -> tuple[str, ...] | None:
    """What to write as prerequisites: the manifest's, unless a hand-made entry has none to add."""
    requires: tuple[str, ...] = _requires(artifact)
    if requires or entry.origin is CatalogOriginEnum.DISCOVERED:
        return requires
    return None


def _matches(entry: CatalogEntryDto, artifact: InstalledArtifactDto) -> bool:
    """Whether the head already says what the manifest says."""
    if entry.manifest_digest != artifact.manifest_digest:
        return False
    if (
        artifact.description is not None
        and SecretRedactor.redact(artifact.description)[0].strip() != entry.purpose
    ):
        return False
    if (
        artifact.observed_version is not None
        and artifact.observed_version != entry.declared_version
    ):
        return False
    requires: tuple[str, ...] | None = _revised_requires(entry, artifact)
    return requires is None or requires == entry.prerequisites


def _source(runtime: RuntimeEnum, artifact: InstalledArtifactDto) -> NewSourceInput:
    return NewSourceInput(
        kind=SourceKindEnum.MANIFEST,
        locator=f"{runtime.value}:{artifact.name}",
        digest=ContentHash(value=_digest(artifact)),
    )


def _idempotency_key(runtime: RuntimeEnum, artifact: InstalledArtifactDto) -> str:
    """`catalog-sync:<runtime>:<kind>:<name>:<digest>`; a revise adds `:r<head revision>`.

    The suffix keeps a revision that changes only the version or description (same digest) from
    colliding with the register that first used the key.
    """
    return f"catalog-sync:{runtime.value}:{artifact.kind.value}:{artifact.name}:{_digest(artifact)}"


def _not_installed(
    entries: Mapping[_Key, CatalogEntryDto],
    present: set[_Key],
    unreadable: Sequence[UnreadableKindDto],
) -> tuple[NotInstalledDto, ...]:
    blind: set[CatalogEntryKindEnum] = {item.kind for item in unreadable}
    return tuple(
        NotInstalledDto(
            entry_id=entry.id, kind=entry.kind, name=entry.name, location=entry.location
        )
        for key, entry in entries.items()
        if entry.kind in DISCOVERABLE_KINDS and entry.kind not in blind and key not in present
    )


def _next_steps(
    blocks: Sequence[SyncRuntimeDto], action: SyncRuntimeCatalogCommand
) -> tuple[str, ...]:
    steps: list[str] = []
    if action.dry_run and any(block.registered or block.revised for block in blocks):
        steps.append("Run `noesis catalog sync` without --dry-run to write these changes.")
    for block in blocks:
        steps += [
            f"Install {item.kind.value} {item.name} from {item.location}, or ignore it: "
            "sync never removes entries."
            for item in block.not_installed
        ]
        steps += [
            f"Skipped {item.kind.value}:{item.name} ({item.reason}); register it by hand with "
            "`noesis catalog register` if it should be cataloged."
            for item in block.skipped
        ]
    return tuple(dict.fromkeys(steps))
