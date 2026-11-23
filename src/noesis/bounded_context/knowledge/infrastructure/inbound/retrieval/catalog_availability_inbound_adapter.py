"""Answers Retrieval's availability requests by running the check handler.

Store failures and every other Knowledge error reach the caller unchanged: only an empty
runtime list, the one case where nothing can be checked, becomes `not_checked`.
"""

from noesis.bounded_context.knowledge.application.dtos import (
    AvailabilityObservationDto,
    AvailabilityReportDto,
    CatalogEntryDto,
    RuntimeAvailabilityDto,
    RuntimeEnum,
)
from noesis.bounded_context.knowledge.application.handlers.queries.catalog import (
    CheckCatalogAvailabilityHandler,
    CheckCatalogAvailabilityQuery,
)
from noesis.bounded_context.knowledge.domain.value_objects import SpaceId
from noesis.shared_kernel.contracts.knowledge import (
    CatalogAvailabilityRequestContract,
    CatalogAvailabilityResultContract,
    CatalogAvailabilityRuntimeContract,
)
from noesis.shared_kernel.contracts.ports.retrieval import ICatalogAvailability

RUNTIME_UNRESOLVED: str = "runtime_unresolved"


class CatalogAvailabilityInboundAdapter(ICatalogAvailability):
    """Retrieval's door to catalog availability.

    Args:
        check: The handler that reads the store before any probe.
    """

    def __init__(self, *, check: CheckCatalogAvailabilityHandler) -> None:
        self._check: CheckCatalogAvailabilityHandler = check

    async def check(
        self, request: CatalogAvailabilityRequestContract
    ) -> CatalogAvailabilityResultContract:
        """Check the requested entries in the requested runtimes.

        Raises:
            GraphStoreUnavailableError: The store is down; nothing was probed.
            CatalogEntryNotFoundError: An id is unknown or in another space.
        """
        if not request.runtimes:
            return CatalogAvailabilityResultContract(
                outcome="not_checked", reason_code=RUNTIME_UNRESOLVED
            )
        report: AvailabilityReportDto = await self._check.handle(
            CheckCatalogAvailabilityQuery(
                space_id=SpaceId(value=request.space_id),
                refs=request.entry_ids,
                runtimes=tuple(RuntimeEnum(runtime) for runtime in request.runtimes),
            )
        )
        entries: dict[str, CatalogEntryDto] = {entry.id: entry for entry in report.entries}
        return CatalogAvailabilityResultContract(
            outcome="checked",
            runtimes=tuple(_runtime(block, entries) for block in report.runtimes),
        )


def _runtime(
    block: RuntimeAvailabilityDto, entries: dict[str, CatalogEntryDto]
) -> CatalogAvailabilityRuntimeContract:
    return CatalogAvailabilityRuntimeContract.model_validate(
        {
            "runtime": block.runtime.value,
            "host": block.host,
            "observed_at": block.observed_at,
            "entries": [_entry(item, entries[item.entry_id]) for item in block.observations],
        }
    )


def _entry(observation: AvailabilityObservationDto, entry: CatalogEntryDto) -> dict[str, object]:
    return {
        "entry_id": observation.entry_id,
        "kind": observation.kind.value,
        "name": observation.name,
        "purpose": entry.purpose,
        "declared_version": entry.declared_version,
        "location": entry.location,
        "status": observation.status.value,
        "reason": observation.reason.value,
        "observed_version": observation.observed_version,
        "version_drift": observation.version_drift,
        "missing_prerequisites": list(observation.missing_prerequisites),
    }
