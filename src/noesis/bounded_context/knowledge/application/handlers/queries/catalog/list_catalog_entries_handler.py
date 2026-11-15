"""List the catalog entries of a space."""

from noesis.bounded_context.knowledge.application.dtos import CatalogEntryDto
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    ICatalogEntryReadRepository,
    IRecordReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.catalog_lookup import (
    SpaceScopedQuery,
    resolve_query_space,
)
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CORE_STEP,
    require_steps,
)
from noesis.bounded_context.knowledge.domain.value_objects import CatalogEntryKindEnum, SpaceId
from noesis.shared_kernel.application.handlers import IHandler


class ListCatalogEntriesQuery(SpaceScopedQuery):
    """List entries, optionally narrowed.

    Attributes:
        kind: Only entries of this kind.
        name_prefix: Only entries whose name starts with this (case-sensitive).
    """

    kind: CatalogEntryKindEnum | None = None
    name_prefix: str | None = None


class ListCatalogEntriesHandler(IHandler[ListCatalogEntriesQuery, tuple[CatalogEntryDto, ...]]):
    """Reads the entries of one space with their head content."""

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

    async def handle(self, action: ListCatalogEntriesQuery) -> tuple[CatalogEntryDto, ...]:
        """The entries; empty on a store without the `catalog` step.

        Raises:
            StoreNotInitialisedError: The `core` schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
        """
        await require_steps(self._schema, CORE_STEP)
        space_id: SpaceId = await resolve_query_space(self._records, action)
        return await self._read_repository.find(
            space_id, kind=action.kind, name_prefix=action.name_prefix
        )
