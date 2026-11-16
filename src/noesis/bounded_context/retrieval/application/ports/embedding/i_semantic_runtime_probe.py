"""Reports the semantic setup without loading a model or starting a process."""

import abc

from noesis.shared_kernel.domain import JsonValue


class ISemanticRuntimeProbe(abc.ABC):
    """Mode, optional dependency, prepared model and runtime reachability, for `index status`."""

    @abc.abstractmethod
    async def diagnostics(self) -> dict[str, JsonValue]:
        """Plain-JSON diagnostics; may contact a running runtime but never starts one."""
        ...
