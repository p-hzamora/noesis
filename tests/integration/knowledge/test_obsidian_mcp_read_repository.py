"""`ObsidianMcpNoteReadRepositoryAdapter` and its fallback, against a fake MCP server."""

from pathlib import Path

import pytest
from tests.support.fake_obsidian_mcp import fake_obsidian_mcp, free_port

from noesis.bounded_context.knowledge.application.dtos import NoteSummaryDto
from noesis.bounded_context.knowledge.domain.value_objects import NoteArea
from noesis.bounded_context.knowledge.infrastructure.outbound.storage import (
    FallbackNoteReadRepositoryAdapter,
    FilesystemNoteReadRepositoryAdapter,
    ObsidianMcpNoteReadRepositoryAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.outbound.storage.mappers import NoteMapper
from noesis.exceptions import ObsidianMcpError
from noesis.shared_kernel.infrastructure.outbound.mcp import ObsidianMcpClient

pytestmark = pytest.mark.integration

TTL: str = """---
type: decision
id: auto-decision-use-ttl-cache
title: Use a TTL cache
date: 2026-10-01
updated: 2026-10-02
---

# Use a TTL cache

## Decision

Cache lookups for sixty seconds.
"""
OTHER_REPO: str = TTL.replace("TTL cache", "TTL cache elsewhere")
FOREIGN: str = "# Linux know-how\n\nA ttl trick that lives outside the noesis layout.\n"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    folder: Path = tmp_path / "vault"
    for relative, text in {
        "repos/demo/auto/decisions/use-ttl-cache.md": TTL,
        "repos/other/decisions/use-ttl-cache.md": OTHER_REPO,
        "os/linux/ttl-trick.md": FOREIGN,
        "repos/demo/index.md": "# Index\n\nTable of contents.\n",
    }.items():
        (folder / relative).parent.mkdir(parents=True, exist_ok=True)
        (folder / relative).write_text(text, encoding="utf-8")
    return folder


def _adapters(
    vault: Path, url: str, token: str | None = None
) -> tuple[ObsidianMcpNoteReadRepositoryAdapter, FilesystemNoteReadRepositoryAdapter]:
    mapper = NoteMapper()
    files = FilesystemNoteReadRepositoryAdapter(vault, mapper)
    client = ObsidianMcpClient(url, token=token, timeout_seconds=5)
    return ObsidianMcpNoteReadRepositoryAdapter(client, mapper, listing=files), files


async def test_search_maps_hits_to_the_same_dto_as_the_filesystem_adapter(vault: Path) -> None:
    with fake_obsidian_mcp(vault) as server:
        mcp_repo, files = _adapters(vault, server.url)
        found: list[NoteSummaryDto] = (
            await mcp_repo.search("ttl cache", area=NoteArea(value="repos/demo"), limit=5)
        ).notes

    expected: list[NoteSummaryDto] = (
        await files.search("ttl cache", area=NoteArea(value="repos/demo"), limit=5)
    ).notes
    assert found == expected
    assert [note.path for note in found] == ["repos/demo/auto/decisions/use-ttl-cache.md"]
    assert (found[0].kind, found[0].origin, found[0].updated) == ("decision", "auto", "2026-10-02")
    assert found[0].snippet == "Cache lookups for sixty seconds."


async def test_area_restricts_hits_to_that_folder(vault: Path) -> None:
    with fake_obsidian_mcp(vault) as server:
        mcp_repo, _ = _adapters(vault, server.url)
        everywhere: tuple[NoteSummaryDto, ...] = (
            await mcp_repo.search("ttl", area=None, limit=10)
        ).notes
        only_other: list[NoteSummaryDto] = (
            await mcp_repo.search("ttl", area=NoteArea(value="repos/other"), limit=10)
        ).notes

    assert {note.path for note in everywhere} >= {
        "repos/demo/auto/decisions/use-ttl-cache.md",
        "repos/other/decisions/use-ttl-cache.md",
    }
    assert [note.path for note in only_other] == ["repos/other/decisions/use-ttl-cache.md"]


async def test_notes_outside_the_noesis_layout_are_found_without_a_kind(vault: Path) -> None:
    with fake_obsidian_mcp(vault) as server:
        mcp_repo, _ = _adapters(vault, server.url)
        found: tuple[NoteSummaryDto, ...] = (
            await mcp_repo.search("trick", area=None, limit=10)
        ).notes

    assert [(note.path, note.kind, note.origin, note.title) for note in found] == [
        ("os/linux/ttl-trick.md", None, "manual", "Linux know-how")
    ]


async def test_hits_are_ranked_by_score_and_cut_at_the_limit(vault: Path) -> None:
    canned: list[tuple[str, float]] = [
        ("repos/other/decisions/use-ttl-cache.md", 1),
        (".obsidian/workspace.json", 99),
        ("repos/demo/auto/decisions/use-ttl-cache.md", 7),
        ("os/linux/ttl-trick.md", 3),
    ]
    with fake_obsidian_mcp(vault, canned=canned) as server:
        mcp_repo, _ = _adapters(vault, server.url)
        found: tuple[NoteSummaryDto, ...] = (
            await mcp_repo.search("anything", area=None, limit=2)
        ).notes

    assert [note.path for note in found] == [
        "repos/demo/auto/decisions/use-ttl-cache.md",
        "os/linux/ttl-trick.md",
    ]


async def test_listing_stays_on_the_filesystem(vault: Path) -> None:
    with fake_obsidian_mcp(vault) as server:
        mcp_repo, files = _adapters(vault, server.url)
        listed: list[NoteSummaryDto] = await mcp_repo.list_notes(area=None, origin=None)

    assert listed == await files.list_notes(area=None, origin=None)
    assert server.calls == []


async def test_the_token_is_sent_and_a_wrong_one_is_rejected_without_leaking(vault: Path) -> None:
    with fake_obsidian_mcp(vault, token="s3cret") as server:
        good, _ = _adapters(vault, server.url, token="s3cret")
        assert (await good.search("ttl", area=None, limit=1)).notes
        assert set(server.authorizations) == {"Bearer s3cret"}

        bad, _ = _adapters(vault, server.url, token="wrong-token")
        with pytest.raises(ObsidianMcpError) as raised:
            await bad.search("ttl", area=None, limit=1)

    assert "wrong-token" not in str(raised.value)
    assert "wrong-token" not in repr(ObsidianMcpClient(server.url, token="wrong-token"))


async def test_an_unreachable_server_raises_obsidian_mcp_error(vault: Path) -> None:
    mcp_repo, _ = _adapters(vault, f"http://127.0.0.1:{free_port()}/mcp/")

    with pytest.raises(ObsidianMcpError, match="unreachable"):
        await mcp_repo.search("ttl", area=None, limit=3)


async def test_fallback_searches_files_and_notifies_once(vault: Path) -> None:
    mcp_repo, files = _adapters(vault, f"http://127.0.0.1:{free_port()}/mcp/")
    notified: list[ObsidianMcpError] = []
    repo = FallbackNoteReadRepositoryAdapter(mcp_repo, files, on_fallback=notified.append)

    first: tuple[NoteSummaryDto, ...] = (await repo.search("ttl cache", area=None, limit=5)).notes
    second: tuple[NoteSummaryDto, ...] = (await repo.search("ttl cache", area=None, limit=5)).notes

    assert first == second == (await files.search("ttl cache", area=None, limit=5)).notes
    assert first
    assert len(notified) == 1


async def test_a_second_text_block_with_a_truncation_note_is_ignored(vault: Path) -> None:
    with fake_obsidian_mcp(vault, truncation_note=True) as server:
        mcp_repo, _ = _adapters(vault, server.url)
        found: tuple[NoteSummaryDto, ...] = (
            await mcp_repo.search("ttl cache", area=None, limit=5)
        ).notes

    assert found


async def test_an_unusable_answer_is_reported_as_such_not_as_unreachable(vault: Path) -> None:
    with fake_obsidian_mcp(vault, garbage=True) as server:
        mcp_repo, _ = _adapters(vault, server.url)
        with pytest.raises(ObsidianMcpError, match="not JSON"):
            await mcp_repo.search("ttl", area=None, limit=1)
