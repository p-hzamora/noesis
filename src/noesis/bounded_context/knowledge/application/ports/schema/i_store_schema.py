"""Named, idempotent schema steps of the store."""

import abc


class IStoreSchema(abc.ABC):
    """The store's schema steps: registered by modules and contexts, applied by `store init`.

    A step has a stable name (`core`, ...) and is applied at most once. There is no numeric
    schema version (D-027).
    """

    @abc.abstractmethod
    def registered_steps(self) -> tuple[str, ...]:
        """Names of every registered step, in the order they apply."""
        ...

    @abc.abstractmethod
    async def applied_steps(self) -> frozenset[str]:
        """Names of the steps recorded as applied; empty on an uninitialised store."""
        ...

    @abc.abstractmethod
    async def apply_step(self, name: str) -> bool:
        """Apply a registered step unless it was applied before.

        Returns:
            True when this call applied it, False when it was already applied.
        """
        ...
