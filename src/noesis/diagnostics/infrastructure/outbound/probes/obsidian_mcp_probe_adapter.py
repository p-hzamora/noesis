"""`IObsidianMcpProbe` over Obsidian's MCP server."""

from noesis.diagnostics.application.ports.probes import IObsidianMcpProbe
from noesis.exceptions import ObsidianMcpError
from noesis.shared_kernel.domain import JsonValue
from noesis.shared_kernel.infrastructure.outbound.mcp import ObsidianMcpClient

PROBE_PATH: str = ".noesis/doctor-probe.md"
PROBE_CONTENT: str = "noesis doctor wrote this file to check that the vault accepts writes.\n"


class ObsidianMcpProbeAdapter(IObsidianMcpProbe):
    """Lists the vault root with `vault_list` and probes writes with `vault_write`."""

    def __init__(self, client: ObsidianMcpClient) -> None:
        self._client: ObsidianMcpClient = client

    async def list_root(self) -> tuple[str, ...]:
        """Root entry names; folders come back with a trailing slash, which is dropped.

        Raises:
            ObsidianMcpError: Unreachable server or an unexpected answer.
        """
        async with self._client.session() as session:
            answer: JsonValue = await session.call("vault_list", {"path": ""})
        files: JsonValue = answer.get("files") if isinstance(answer, dict) else None
        if not isinstance(files, list):
            raise ObsidianMcpError("Obsidian MCP `vault_list` answered an unexpected shape.")
        return tuple(sorted(item.rstrip("/") for item in files if isinstance(item, str)))

    async def write_probe(self) -> None:
        """Overwrite the hidden probe file; the same file every run, no timestamp.

        Raises:
            ObsidianMcpError: Unreachable server or a refused write.
        """
        async with self._client.session() as session:
            await session.call_text("vault_write", {"path": PROBE_PATH, "content": PROBE_CONTENT})
