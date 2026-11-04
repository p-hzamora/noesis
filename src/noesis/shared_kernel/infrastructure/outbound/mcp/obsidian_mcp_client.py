"""Thin client for Obsidian's MCP server over streamable HTTP.

Wraps the official `mcp` SDK so the rest of noesis sees plain JSON in and out, and one
exception type (`ObsidianMcpError`) for everything that can go wrong: Obsidian closed, a
timeout, a rejected token, a tool error, an unreadable answer. Swapping the SDK for the
Local REST API would only touch this module.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent

from noesis.exceptions import ObsidianMcpError, ObsidianMcpToolError
from noesis.shared_kernel.domain import JsonValue

DEFAULT_TIMEOUT_SECONDS: float = 5.0


def _first_of(group: BaseExceptionGroup[BaseException]) -> ObsidianMcpError | None:
    """The first `ObsidianMcpError` inside a (possibly nested) exception group."""
    for member in group.exceptions:
        if isinstance(member, ObsidianMcpError):
            return member
        if isinstance(member, BaseExceptionGroup) and (found := _first_of(member)):
            return found
    return None


class ObsidianMcpSession:
    """One initialised MCP session; `call` returns a tool's decoded JSON, `call_text` its raw text."""

    def __init__(self, session: ClientSession, timeout_seconds: float) -> None:
        self._session: ClientSession = session
        self._timeout_seconds: float = timeout_seconds

    async def _run(self, tool: str, arguments: dict[str, Any] | None) -> str:
        """Call `tool` and return the text of its first content block.

        Raises:
            ObsidianMcpToolError: The tool answered with an error.
            ObsidianMcpError: The call timed out.
        """
        try:
            async with asyncio.timeout(self._timeout_seconds):
                result: CallToolResult = await self._session.call_tool(tool, arguments or {})
        except TimeoutError as error:
            raise ObsidianMcpError(
                f"Obsidian MCP tool `{tool}` timed out after {self._timeout_seconds:g}s.",
                {"tool": tool},
            ) from error
        blocks: list[str] = [
            block.text for block in result.content if isinstance(block, TextContent)
        ]
        text: str = (
            blocks[0] if blocks else ""
        )  # later blocks are notes such as "N results left out"
        if result.isError:
            raise ObsidianMcpToolError(
                f"Obsidian MCP tool `{tool}` failed: {text[:200] or 'no detail'}", {"tool": tool}
            )
        return text

    async def call(self, tool: str, arguments: dict[str, Any] | None = None) -> JsonValue:
        """Call `tool` and decode the JSON text it answers with.

        Args:
            tool: MCP tool name, e.g. `search_simple`.
            arguments: Tool arguments.

        Returns:
            The decoded JSON value (the tool's text content).

        Raises:
            ObsidianMcpToolError: The tool answered with an error.
            ObsidianMcpError: The call timed out, or answered something that is not JSON.
        """
        text: str = await self._run(tool, arguments)
        try:
            decoded: JsonValue = json.loads(text)
        except json.JSONDecodeError as error:
            raise ObsidianMcpError(
                f"Obsidian MCP tool `{tool}` answered something that is not JSON.", {"tool": tool}
            ) from error
        return decoded

    async def call_text(self, tool: str, arguments: dict[str, Any] | None = None) -> str:
        """Call `tool` and return its text answer undecoded (e.g. `vault_write` answers text).

        Args:
            tool: MCP tool name, e.g. `vault_write`.
            arguments: Tool arguments.

        Returns:
            The tool's first text content block.

        Raises:
            ObsidianMcpToolError: The tool answered with an error.
            ObsidianMcpError: The call timed out.
        """
        return await self._run(tool, arguments)


class ObsidianMcpClient:
    """Opens sessions against one Obsidian MCP endpoint.

    The token is sent as the `Authorization` header and is never part of an error message,
    a log line or a repr.
    """

    def __init__(
        self,
        url: str,
        *,
        token: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._url: str = url
        self._token: str | None = token
        self._timeout_seconds: float = timeout_seconds

    def __repr__(self) -> str:
        return f"ObsidianMcpClient(url={self._url!r})"

    def _headers(self) -> dict[str, str]:
        if not self._token:
            return {}
        bearer: str = self._token if " " in self._token else f"Bearer {self._token}"
        return {"Authorization": bearer}

    @asynccontextmanager
    async def session(self) -> AsyncIterator[ObsidianMcpSession]:
        """Connect and initialise one session.

        Raises:
            ObsidianMcpError: The server cannot be reached or does not speak MCP. Errors
                raised inside the `async with` body are not wrapped.
        """
        try:
            async with (
                httpx.AsyncClient(
                    headers=self._headers(),
                    timeout=httpx.Timeout(self._timeout_seconds),
                    follow_redirects=True,
                ) as http_client,
                streamable_http_client(self._url, http_client=http_client) as (read, write, _),
                ClientSession(read, write) as session,
            ):
                async with asyncio.timeout(self._timeout_seconds):
                    await session.initialize()
                body = ObsidianMcpSession(session, self._timeout_seconds)
                yield body
        except ObsidianMcpError:
            raise
        except BaseExceptionGroup as group:
            ours: ObsidianMcpError | None = _first_of(group)
            if ours is not None:  # raised by the body, wrapped by the SDK's task group
                raise ours from None
            raise self._unavailable(group) from group
        except (OSError, TimeoutError, httpx.HTTPError, RuntimeError) as error:
            raise self._unavailable(error) from error

    def _unavailable(self, error: BaseException) -> ObsidianMcpError:
        leaf: BaseException = error
        while isinstance(leaf, BaseExceptionGroup) and leaf.exceptions:
            leaf = leaf.exceptions[0]
        reason: str = f"{type(leaf).__name__}: {leaf}"[:200]
        return ObsidianMcpError(
            f"Obsidian MCP at {self._url} is unreachable ({reason}).", {"url": self._url}
        )
