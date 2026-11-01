"""Base interface for command and query handlers (the application's inbound actions)."""

import abc


class IHandler[TAction, TRes](abc.ABC):
    """Handles one command or query and returns its result."""

    @abc.abstractmethod
    async def handle(self, action: TAction) -> TRes:
        """Handle an application action and return its result."""
        ...
