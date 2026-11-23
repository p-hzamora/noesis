"""Resources (skills, agents, CLI tools, MCP servers) that match a request."""

import abc

from noesis.shared_kernel.contracts.knowledge import (
    CatalogResourceHitContract,
    CatalogResourceLookupContract,
    CatalogResourceQueryContract,
)


class IResourceCatalogReader(abc.ABC):
    """Read-only search over the catalog and, on request, over what runtimes have installed."""

    @abc.abstractmethod
    async def search(self, query: CatalogResourceQueryContract) -> list[CatalogResourceHitContract]:
        """Up to `query.limit` hits of the space, best score first.

        Raises:
            GraphStoreUnavailableError: The store is down.
        """
        ...

    @abc.abstractmethod
    async def get_by_refs(
        self, lookup: CatalogResourceLookupContract
    ) -> list[CatalogResourceHitContract]:
        """The resources named by `lookup`; a name nothing answers is absent, never invented.

        Raises:
            GraphStoreUnavailableError: The store is down.
        """
        ...
