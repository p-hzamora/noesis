"""Catalog availability in the requested runtimes."""

import abc

from noesis.shared_kernel.contracts.knowledge import (
    CatalogAvailabilityRequestContract,
    CatalogAvailabilityResultContract,
)


class ICatalogAvailability(abc.ABC):
    """Observe catalog entries in the requested runtimes."""

    @abc.abstractmethod
    async def check(
        self, request: CatalogAvailabilityRequestContract
    ) -> CatalogAvailabilityResultContract:
        """Which catalog entries the requested runtimes have installed."""
        ...
