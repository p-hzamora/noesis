"""Show which noesis hooks an agent's settings register."""

from noesis.bounded_context.capture.application.dtos import AgentHooksDto
from noesis.bounded_context.capture.application.ports.agent_hooks import IAgentHookRegistry
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject


class GetAgentHooksStatusQuery(FrozenObject):
    """Ask which noesis hooks are registered (no parameters)."""


class GetAgentHooksStatusHandler(IHandler[GetAgentHooksStatusQuery, AgentHooksDto]):
    """Reads the registry."""

    def __init__(self, *, registry: IAgentHookRegistry) -> None:
        self._registry: IAgentHookRegistry = registry

    async def handle(self, action: GetAgentHooksStatusQuery) -> AgentHooksDto:
        """The registered noesis hooks and the events still missing one."""
        return await self._registry.status()
