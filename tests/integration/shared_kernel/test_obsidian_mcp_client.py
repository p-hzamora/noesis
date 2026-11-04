"""`ObsidianMcpClient`: decoded and raw answers, and tool refusals vs. transport failures."""

from pathlib import Path

import pytest
from tests.support.fake_obsidian_mcp import fake_obsidian_mcp, free_port

from noesis.exceptions import ObsidianMcpError, ObsidianMcpToolError
from noesis.shared_kernel.infrastructure.outbound.mcp import ObsidianMcpClient

pytestmark = pytest.mark.integration


def _client(url: str) -> ObsidianMcpClient:
    return ObsidianMcpClient(url, timeout_seconds=2)


async def test_call_text_returns_the_raw_answer_of_a_tool_that_does_not_speak_json(
    tmp_path: Path,
) -> None:
    with fake_obsidian_mcp(tmp_path) as server:
        async with _client(server.url).session() as session:
            answer: str = await session.call_text(
                "vault_write", {"path": "a/b.md", "content": "hello"}
            )

    assert answer == "Wrote a/b.md"
    assert (tmp_path / "a/b.md").read_text(encoding="utf-8") == "hello"


async def test_call_still_rejects_a_plain_text_answer(tmp_path: Path) -> None:
    with fake_obsidian_mcp(tmp_path) as server:
        async with _client(server.url).session() as session:
            with pytest.raises(ObsidianMcpError, match="not JSON") as raised:
                await session.call("vault_write", {"path": "a.md", "content": "x"})

    assert not isinstance(raised.value, ObsidianMcpToolError)


@pytest.mark.parametrize("decoded", [True, False], ids=["call", "call_text"])
async def test_a_tool_error_is_a_tool_error_subtype_of_the_mcp_error(
    tmp_path: Path, decoded: bool
) -> None:
    with fake_obsidian_mcp(tmp_path) as server:
        async with _client(server.url).session() as session:
            with pytest.raises(ObsidianMcpToolError) as raised:
                if decoded:
                    await session.call("vault_read", {"path": "missing.md"})
                else:
                    await session.call_text("vault_read", {"path": "missing.md"})

    assert isinstance(raised.value, ObsidianMcpError)
    assert raised.value.error_code == "INTEGRATION_102_OBSIDIAN_MCP_FAILED"
    assert "`vault_read` failed" in raised.value.message
    assert raised.value.metadata == {"tool": "vault_read"}


async def test_a_transport_failure_is_not_a_tool_error() -> None:
    client: ObsidianMcpClient = _client(f"http://127.0.0.1:{free_port()}/mcp/")

    with pytest.raises(ObsidianMcpError) as raised:
        async with client.session():
            pass  # pragma: no cover

    assert not isinstance(raised.value, ObsidianMcpToolError)
    assert "unreachable" in raised.value.message
