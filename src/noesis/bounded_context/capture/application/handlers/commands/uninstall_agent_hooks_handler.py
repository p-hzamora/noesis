"""Remove the noesis hooks from an agent's settings."""

from noesis.bounded_context.capture.application.assemblers import AgentHookChangeAssembler
from noesis.bounded_context.capture.application.dtos import AgentHookChangeDto, AgentHookPlanDto
from noesis.bounded_context.capture.application.ports.agent_hooks import IAgentHookRegistry
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject


class UninstallAgentHooksCommand(FrozenObject):
    """Remove the noesis hooks.

    Attributes:
        apply: Write the change; without it, only preview it.
    """

    apply: bool


class UninstallAgentHooksHandler(IHandler[UninstallAgentHooksCommand, AgentHookChangeDto]):
    """Plans the removal and writes it only when asked and when something would change."""

    def __init__(self, *, registry: IAgentHookRegistry) -> None:
        self._registry: IAgentHookRegistry = registry

    async def handle(self, action: UninstallAgentHooksCommand) -> AgentHookChangeDto:
        """Preview or apply the removal."""
        plan: AgentHookPlanDto = await self._registry.plan(None)
        applied: bool = action.apply and plan.changed
        backup: str | None = await self._registry.apply(plan) if applied else None
        return AgentHookChangeAssembler.to_dto(plan, applied=applied, backup=backup)
