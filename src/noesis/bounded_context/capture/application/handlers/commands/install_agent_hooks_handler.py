"""Register the noesis hooks in an agent's settings."""

from noesis.bounded_context.capture.application.assemblers import AgentHookChangeAssembler
from noesis.bounded_context.capture.application.dtos import AgentHookChangeDto, AgentHookPlanDto
from noesis.bounded_context.capture.application.ports.agent_hooks import IAgentHookRegistry
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject


class InstallAgentHooksCommand(FrozenObject):
    """Add the noesis hooks.

    Attributes:
        hook_command: The command the agent should run for every noesis hook.
        apply: Write the change; without it, only preview it.
    """

    hook_command: str
    apply: bool


class InstallAgentHooksHandler(IHandler[InstallAgentHooksCommand, AgentHookChangeDto]):
    """Plans the change and writes it only when asked and when something would change."""

    def __init__(self, *, registry: IAgentHookRegistry) -> None:
        self._registry: IAgentHookRegistry = registry

    async def handle(self, action: InstallAgentHooksCommand) -> AgentHookChangeDto:
        """Preview or apply the installation."""
        plan: AgentHookPlanDto = await self._registry.plan(action.hook_command)
        applied: bool = action.apply and plan.changed
        backup: str | None = await self._registry.apply(plan) if applied else None
        return AgentHookChangeAssembler.to_dto(plan, applied=applied, backup=backup)
