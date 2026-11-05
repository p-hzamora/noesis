"""Questions that diagnostics asks Obsidian's MCP server."""

import abc


class IObsidianMcpProbe(abc.ABC):
    """Probes of Obsidian's MCP server: what vault it serves and whether it accepts a write."""

    @abc.abstractmethod
    async def list_root(self) -> tuple[str, ...]:
        """Names of the entries at the root of the served vault (folders without a slash).

        Raises:
            ObsidianMcpError: The MCP server does not answer.
        """
        ...

    @abc.abstractmethod
    async def write_probe(self) -> None:
        """Write the probe file `noesis-doctor-probe.md` at the vault root, then delete it.

        Raises:
            ObsidianMcpError: The server is unreachable or refuses the write or the delete.
        """
        ...
