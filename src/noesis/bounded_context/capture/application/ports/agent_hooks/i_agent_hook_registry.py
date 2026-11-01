"""Where an agent keeps its hook configuration."""

import abc

from noesis.bounded_context.capture.application.dtos import (
    AgentHookPlanDto,
    AgentHooksDto,
)


class IAgentHookRegistry(abc.ABC):
    """Reads and edits the noesis hooks in one agent's settings; foreign hooks are never touched."""

    @abc.abstractmethod
    async def status(self) -> AgentHooksDto:
        """Which noesis hooks are registered right now.

        Raises:
            AgentSettingsInvalidError: The settings file exists but is not a JSON object.
        """
        ...

    @abc.abstractmethod
    async def plan(self, command: str | None) -> AgentHookPlanDto:
        """Compute the change without writing it.

        Args:
            command: Hook command to register for every noesis hook; None removes them.

        Raises:
            AgentSettingsInvalidError: The settings file exists but is not a JSON object.
        """
        ...

    @abc.abstractmethod
    async def apply(self, plan: AgentHookPlanDto) -> str | None:
        """Write a plan after a timestamped backup of the existing file.

        Args:
            plan: A plan produced by `plan`.

        Returns:
            The backup file path, or None when there was no file to back up.
        """
        ...
