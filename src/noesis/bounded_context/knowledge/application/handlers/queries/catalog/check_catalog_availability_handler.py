"""Check whether cataloged entries are available in the runtimes of this host, right now."""

from collections.abc import Mapping

from noesis.bounded_context.knowledge.application.dtos import (
    AvailabilityObservationDto,
    AvailabilityReportDto,
    AvailabilityStatusEnum,
    AvailabilitySummaryDto,
    CatalogEntryDto,
    RuntimeAvailabilityDto,
    RuntimeEnum,
    RuntimeInventoryDto,
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
    catalog_entry_not_found,
    find_entry,
    resolve_query_space,
)
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CORE_STEP,
    require_steps,
)
from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum, SpaceId
from noesis.shared_kernel.application.handlers import IHandler


class CheckCatalogAvailabilityQuery(SpaceScopedQuery):
    """Assess entries against the given runtimes.

    Attributes:
        refs: Entry ids or `kind:name` references; empty means every entry of the space.
        kind: Narrows the selection to one kind.
        runtimes: Runtimes to probe, resolved by the caller, in the order the blocks come back.
    """

    refs: tuple[str, ...] = ()
    kind: CatalogEntryKindEnum | None = None
    runtimes: tuple[RuntimeEnum, ...]


class CheckCatalogAvailabilityHandler(
    IHandler[CheckCatalogAvailabilityQuery, AvailabilityReportDto]
):
    """Reads the selected entries first, then probes; stores nothing."""

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

    async def handle(self, action: CheckCatalogAvailabilityQuery) -> AvailabilityReportDto:
        """Assess every selected entry in every requested runtime.

        Raises:
            StoreNotInitialisedError: The `core` schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            CatalogEntryNotFoundError: A reference is unknown or in another space.
            GraphStoreUnavailableError: The store is down; nothing was probed.
        """
        await require_steps(self._schema, CORE_STEP)
        space_id: SpaceId = await resolve_query_space(self._records, action)
        entries: tuple[CatalogEntryDto, ...] = await self._select(space_id, action)
        inventories: tuple[RuntimeInventoryDto, ...] = await build_inventories(
            self._runtime_probes, self._host_tools, action.runtimes, entries
        )
        blocks: tuple[RuntimeAvailabilityDto, ...] = tuple(
            _block(entries, inventory) for inventory in inventories
        )
        return AvailabilityReportDto(
            runtimes=blocks, entries=entries, next_steps=_next_steps(entries, blocks)
        )

    async def _select(
        self, space_id: SpaceId, action: CheckCatalogAvailabilityQuery
    ) -> tuple[CatalogEntryDto, ...]:
        if not action.refs:
            return await self._read_repository.find(space_id, kind=action.kind)
        selected: dict[str, CatalogEntryDto] = {}
        for ref in action.refs:
            found: CatalogEntryDto | None = await find_entry(self._read_repository, space_id, ref)
            if found is None:
                raise catalog_entry_not_found(ref, space_id)
            if action.kind is None or found.kind is action.kind:
                selected.setdefault(found.id, found)
        return tuple(selected.values())


def _block(
    entries: tuple[CatalogEntryDto, ...], inventory: RuntimeInventoryDto
) -> RuntimeAvailabilityDto:
    observations: tuple[AvailabilityObservationDto, ...] = tuple(
        assess_availability(entry, inventory) for entry in entries
    )

    def count(status: AvailabilityStatusEnum) -> int:
        return sum(1 for observation in observations if observation.status is status)

    return RuntimeAvailabilityDto(
        runtime=inventory.runtime,
        host=inventory.host,
        observed_at=inventory.observed_at,
        observations=observations,
        summary=AvailabilitySummaryDto(
            available=count(AvailabilityStatusEnum.AVAILABLE),
            unavailable=count(AvailabilityStatusEnum.UNAVAILABLE),
            unknown=count(AvailabilityStatusEnum.UNKNOWN),
        ),
        unreadable_kinds=inventory.unreadable_kinds,
    )


def _next_steps(
    entries: tuple[CatalogEntryDto, ...], blocks: tuple[RuntimeAvailabilityDto, ...]
) -> tuple[str, ...]:
    by_id: dict[str, CatalogEntryDto] = {entry.id: entry for entry in entries}
    steps: list[str] = []
    for block in blocks:
        for observation in block.observations:
            entry: CatalogEntryDto = by_id[observation.entry_id]
            if observation.status is AvailabilityStatusEnum.UNAVAILABLE:
                steps.append(f"Install {entry.kind.value} {entry.name} from {entry.location}.")
            if observation.version_drift:
                steps.append(
                    f"Run `noesis catalog revise {entry.kind.value}:{entry.name} "
                    f"--expected-revision {entry.head_revision} "
                    f"--declared-version {observation.observed_version} "
                    "--source <kind>:<locator> --idempotency-key <key>` "
                    "to record the installed version."
                )
    return tuple(dict.fromkeys(steps))
