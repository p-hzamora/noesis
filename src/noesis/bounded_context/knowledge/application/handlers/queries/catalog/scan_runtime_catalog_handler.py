"""Scan what the runtimes of this host have installed against the catalog; registers nothing."""

from collections.abc import Mapping

from noesis.bounded_context.knowledge.application.dtos import (
    AvailabilityObservationDto,
    AvailabilityReasonEnum,
    AvailabilityStatusEnum,
    CatalogEntryDto,
    NotInstalledDto,
    RuntimeEnum,
    RuntimeInventoryDto,
    ScanReportDto,
    ScanRuntimeDto,
    UncatalogedArtifactDto,
    VersionDriftDto,
)
from noesis.bounded_context.knowledge.application.policies.catalog import assess_availability
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    ICatalogEntryReadRepository,
    IRecordReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.runtime import (
    IHostToolProbe,
    IRuntimeInventoryProbe,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.availability_inventory import (
    build_inventories,
)
from noesis.bounded_context.knowledge.application.services.catalog_lookup import (
    SpaceScopedQuery,
    resolve_query_space,
)
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CORE_STEP,
    require_steps,
)
from noesis.bounded_context.knowledge.domain.value_objects import SpaceId
from noesis.shared_kernel.application.handlers import IHandler


class ScanRuntimeCatalogQuery(SpaceScopedQuery):
    """Compare the runtimes' installed artifacts with the space's catalog.

    Attributes:
        runtimes: Runtimes to probe, resolved by the caller, in the order the blocks come back.
    """

    runtimes: tuple[RuntimeEnum, ...]


class ScanRuntimeCatalogHandler(IHandler[ScanRuntimeCatalogQuery, ScanReportDto]):
    """Reads every entry of the space first, then probes; stores nothing."""

    def __init__(
        self,
        *,
        read_repository: ICatalogEntryReadRepository,
        records: IRecordReadRepository,
        schema: IStoreSchema,
        runtime_probes: Mapping[RuntimeEnum, IRuntimeInventoryProbe],
        host_tools: IHostToolProbe,
    ) -> None:
        self._read_repository: ICatalogEntryReadRepository = read_repository
        self._records: IRecordReadRepository = records
        self._schema: IStoreSchema = schema
        self._runtime_probes: Mapping[RuntimeEnum, IRuntimeInventoryProbe] = runtime_probes
        self._host_tools: IHostToolProbe = host_tools

    async def handle(self, action: ScanRuntimeCatalogQuery) -> ScanReportDto:
        """List uncataloged artifacts, version drift and not-installed entries per runtime.

        Only cataloged CLI tools are looked up on the host, so uncataloged CLI tools are never
        reported.

        Raises:
            StoreNotInitialisedError: The `core` schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            GraphStoreUnavailableError: The store is down; nothing was probed.
        """
        await require_steps(self._schema, CORE_STEP)
        space_id: SpaceId = await resolve_query_space(self._records, action)
        entries: tuple[CatalogEntryDto, ...] = await self._read_repository.find(space_id)
        inventories: tuple[RuntimeInventoryDto, ...] = await build_inventories(
            self._runtime_probes, self._host_tools, action.runtimes, entries
        )
        blocks: tuple[ScanRuntimeDto, ...] = tuple(
            _scan(entries, inventory) for inventory in inventories
        )
        return ScanReportDto(runtimes=blocks, next_steps=_next_steps(blocks, entries))


def _scan(entries: tuple[CatalogEntryDto, ...], inventory: RuntimeInventoryDto) -> ScanRuntimeDto:
    cataloged: set[tuple[str, str]] = {(entry.kind.value, entry.name) for entry in entries}
    drift: list[VersionDriftDto] = []
    not_installed: list[NotInstalledDto] = []
    for entry in entries:
        observation: AvailabilityObservationDto = assess_availability(entry, inventory)
        if observation.reason is AvailabilityReasonEnum.NOT_INSTALLED:
            not_installed.append(
                NotInstalledDto(
                    entry_id=entry.id, kind=entry.kind, name=entry.name, location=entry.location
                )
            )
        elif (
            observation.status is AvailabilityStatusEnum.AVAILABLE
            and observation.version_drift
            and entry.declared_version is not None
            and observation.observed_version is not None
        ):
            drift.append(
                VersionDriftDto(
                    entry_id=entry.id,
                    kind=entry.kind,
                    name=entry.name,
                    declared_version=entry.declared_version,
                    observed_version=observation.observed_version,
                )
            )
    return ScanRuntimeDto(
        runtime=inventory.runtime,
        host=inventory.host,
        observed_at=inventory.observed_at,
        uncataloged=tuple(
            UncatalogedArtifactDto(
                kind=artifact.kind, name=artifact.name, observed_version=artifact.observed_version
            )
            for artifact in inventory.artifacts
            if (artifact.kind.value, artifact.name) not in cataloged
        ),
        version_drift=tuple(drift),
        not_installed=tuple(not_installed),
        unreadable_kinds=inventory.unreadable_kinds,
    )


def _next_steps(
    blocks: tuple[ScanRuntimeDto, ...], entries: tuple[CatalogEntryDto, ...]
) -> tuple[str, ...]:
    by_id: dict[str, CatalogEntryDto] = {entry.id: entry for entry in entries}
    steps: list[str] = []
    for block in blocks:
        steps += [
            f"Install {item.kind.value} {item.name} from {item.location}."
            for item in block.not_installed
        ]
        for item in block.version_drift:
            steps.append(
                f"Run `noesis catalog revise {item.kind.value}:{item.name} "
                f"--expected-revision {by_id[item.entry_id].head_revision} "
                f"--declared-version {item.observed_version} "
                "--source <kind>:<locator> --idempotency-key <key>` "
                "to record the installed version."
            )
    return tuple(dict.fromkeys(steps))
