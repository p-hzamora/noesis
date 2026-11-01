"""Question that diagnostics asks Obsidian's MCP server."""

import abc


class IObsidianMcpProbe(abc.ABC):
    """Read-only view of the vault that Obsidian serves."""

    @abc.abstractmethod
    async def list_root(self) -> tuple[str, ...]:
        """Names of the entries at the root of the served vault (folders without a slash).

        Raises:
            ObsidianMcpError: The MCP server does not answer.
        """
        ...
