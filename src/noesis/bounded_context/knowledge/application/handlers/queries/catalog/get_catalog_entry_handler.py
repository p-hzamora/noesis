"""Show one catalog entry at its head or at a revision."""

from pydantic import Field

from noesis.bounded_context.knowledge.application.dtos import CatalogEntryDetailDto
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    ICatalogEntryReadRepository,
    IRecordReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
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
from noesis.bounded_context.knowledge.domain.value_objects import SpaceId
from noesis.shared_kernel.application.handlers import IHandler


class GetCatalogEntryQuery(SpaceScopedQuery):
    """Fetch an entry of the space.

    Attributes:
        ref: The entry id, or `kind:name` (split on the first colon).
        revision: Revision to show; the head when None.
    """

    ref: str = Field(min_length=1)
    revision: int | None = Field(default=None, ge=1)


class GetCatalogEntryHandler(IHandler[GetCatalogEntryQuery, CatalogEntryDetailDto]):
    """Returns the entry with one revision; another space's entry is "not found"."""

    def __init__(
        self,
        *,
        read_repository: ICatalogEntryReadRepository,
        records: IRecordReadRepository,
        schema: IStoreSchema,
    ) -> None:
        self._read_repository: ICatalogEntryReadRepository = read_repository
        self._records: IRecordReadRepository = records
        self._schema: IStoreSchema = schema

    async def handle(self, action: GetCatalogEntryQuery) -> CatalogEntryDetailDto:
        """Read the entry.

        Raises:
            StoreNotInitialisedError: The `core` schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            CatalogEntryNotFoundError: Unknown entry or revision, or the entry is in another space.
        """
        await require_steps(self._schema, CORE_STEP)
        space_id: SpaceId = await resolve_query_space(self._records, action)
        found: CatalogEntryDetailDto | None = await find_entry(
            self._read_repository, space_id, action.ref, revision=action.revision
        )
        if found is None:
            raise catalog_entry_not_found(action.ref, space_id, revision=action.revision)
        return found
