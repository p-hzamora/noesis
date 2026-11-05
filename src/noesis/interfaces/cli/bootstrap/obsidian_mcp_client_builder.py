"""Builds the Obsidian MCP client from the settings; the only place that unwraps the token."""

from noesis.core import Environment
from noesis.shared_kernel.infrastructure.outbound.mcp import ObsidianMcpClient


def build_obsidian_mcp_client(environment: Environment) -> ObsidianMcpClient:
    """The client for `NOESIS_OBSIDIAN_MCP_*`, shared by search, the writer and doctor."""
    settings = environment.notes
    token = settings.obsidian_mcp_token
    return ObsidianMcpClient(
        settings.obsidian_mcp_url,
        token=token.get_secret_value() if token else None,
        timeout_seconds=settings.obsidian_mcp_timeout_seconds,
    )
