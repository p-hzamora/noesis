"""Resources (skills, agents, CLI tools, MCP servers) that match a request."""

from typing import Protocol

from noesis.shared_kernel.contracts.knowledge import (
    CatalogResourceHitContract,
    CatalogResourceQueryContract,
)


class IResourceCatalogReader(Protocol):
    """Read-only search over the catalog and, on request, over what runtimes have installed."""

    async def search(self, query: CatalogResourceQueryContract) -> list[CatalogResourceHitContract]:
        """Up to `query.limit` hits of the space, best score first.

        Raises:
            GraphStoreUnavailableError: The store is down.
        """
        ...
