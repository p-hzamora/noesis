"""Lists what one agent runtime has installed."""

import abc

from noesis.bounded_context.knowledge.application.dtos import (
    RuntimeEnum,
    RuntimeInventoryDto,
)


class IRuntimeInventoryProbe(abc.ABC):
    """A read-only probe of one runtime.

    It executes nothing and reads names only. A kind it cannot read (broken configuration) or
    does not probe is reported in `unreadable_kinds`, never raised.
    """

    @property
    @abc.abstractmethod
    def runtime(self) -> RuntimeEnum:
        """The runtime this probe describes."""
        ...

    @abc.abstractmethod
    async def inventory(self) -> RuntimeInventoryDto:
        """What is installed now, with host and observation time."""
        ...
