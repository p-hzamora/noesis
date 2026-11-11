"""`ObsidianMcpNoteReadRepositoryAdapter` and its fallback, against a fake MCP server."""

from pathlib import Path

import pytest
from tests.support.fake_obsidian_mcp import fake_obsidian_mcp, free_port
from tests.support.notes_support import DefaultManifestProvider, FixedClock

from noesis.bounded_context.notes.application.dtos import NoteSummaryDto
from noesis.bounded_context.notes.application.handlers.queries import (
    RecallNotesHandler,
    RecallNotesQuery,
)
from noesis.bounded_context.notes.domain.value_objects import NoteScope
from noesis.bounded_context.notes.infrastructure.outbound.frontmatter import (
    YamlFrontmatterCodecAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.storage import (
    FallbackNoteReadRepositoryAdapter,
    FilesystemNoteReadRepositoryAdapter,
    ObsidianMcpNoteReadRepositoryAdapter,
)
from noesis.bounded_context.notes.infrastructure.outbound.storage.mappers import NoteMapper
from noesis.exceptions import NoteStorageError, ObsidianMcpError
from noesis.shared_kernel.enums import SearchEngineEnum
from noesis.shared_kernel.infrastructure.outbound.mcp import ObsidianMcpClient

pytestmark = pytest.mark.integration

TTL: str = """---
noesis:
  id: 01ARZ3NDEKTSV4RRFFQ69G5FAV
  scope: repo:demo
  kind: decision
  origin: auto
  sources: []
  updated: 2026-10-02
---

# Use a TTL cache

## Decision

Cache lookups for sixty seconds.
"""
OTHER_REPO: str = (
    TTL.replace("TTL cache", "TTL cache elsewhere")
    .replace("scope: repo:demo", "scope: repo:other")
    .replace("FAV", "FAW")
)
FOREIGN: str = "# Linux know-how\n\nA ttl trick that lives outside the noesis layout.\n"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    folder: Path = tmp_path / "vault"
    for relative, text in {
        "repos/demo/decisions/use-ttl-cache.md": TTL,
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
    mapper = NoteMapper(YamlFrontmatterCodecAdapter())
    files = FilesystemNoteReadRepositoryAdapter(vault, mapper)
    client = ObsidianMcpClient(url, token=token, timeout_seconds=5)
    return ObsidianMcpNoteReadRepositoryAdapter(client, mapper, listing=files), files


async def test_search_maps_hits_to_the_same_dto_as_the_filesystem_adapter(vault: Path) -> None:
    with fake_obsidian_mcp(vault) as server:
        mcp_repo, files = _adapters(vault, server.url)
        found: list[NoteSummaryDto] = (
            await mcp_repo.search("ttl cache", scope=NoteScope.for_repository("demo"), limit=5)
        ).notes

    expected: list[NoteSummaryDto] = (
        await files.search("ttl cache", scope=NoteScope.for_repository("demo"), limit=5)
    ).notes
    assert found == expected
    assert [note.path for note in found] == ["repos/demo/decisions/use-ttl-cache.md"]
    assert (found[0].kind, found[0].origin, found[0].updated) == ("decision", "auto", "2026-10-02")
    assert found[0].snippet == "Cache lookups for sixty seconds."


async def test_area_restricts_hits_to_that_folder(vault: Path) -> None:
    with fake_obsidian_mcp(vault) as server:
        mcp_repo, _ = _adapters(vault, server.url)
        everywhere: tuple[NoteSummaryDto, ...] = (
            await mcp_repo.search("ttl", scope=None, limit=10)
        ).notes
        only_other: list[NoteSummaryDto] = (
            await mcp_repo.search("ttl", scope=NoteScope.for_repository("other"), limit=10)
        ).notes

    assert {note.path for note in everywhere} >= {
        "repos/demo/decisions/use-ttl-cache.md",
        "repos/other/decisions/use-ttl-cache.md",
    }
    assert [note.path for note in only_other] == ["repos/other/decisions/use-ttl-cache.md"]


async def test_files_without_a_noesis_block_are_not_notes(vault: Path) -> None:
    with fake_obsidian_mcp(vault) as server:
        mcp_repo, _ = _adapters(vault, server.url)
        found: tuple[NoteSummaryDto, ...] = (
            await mcp_repo.search("trick", scope=None, limit=10)
        ).notes

    assert found == ()  # Obsidian finds os/linux/ttl-trick.md, but it carries no identity


async def test_the_lowest_score_is_the_best_hit_and_survives_the_limit(vault: Path) -> None:
    canned: list[tuple[str, float]] = [
        ("repos/other/decisions/use-ttl-cache.md", -1),
        (".obsidian/workspace.json", -99),
        ("repos/demo/decisions/use-ttl-cache.md", -7),
        ("os/linux/ttl-trick.md", -3),
    ]
    with fake_obsidian_mcp(vault, canned=canned) as server:
        mcp_repo, _ = _adapters(vault, server.url)
        found: tuple[NoteSummaryDto, ...] = (
            await mcp_repo.search("anything", scope=None, limit=2)
        ).notes

    assert [note.path for note in found] == [  # the plain file in between is dropped
        "repos/demo/decisions/use-ttl-cache.md",
        "repos/other/decisions/use-ttl-cache.md",
    ]


async def test_listing_stays_on_the_filesystem(vault: Path) -> None:
    with fake_obsidian_mcp(vault) as server:
        mcp_repo, files = _adapters(vault, server.url)
        listed: list[NoteSummaryDto] = await mcp_repo.list_notes(scope=None, origin=None)

    assert listed == await files.list_notes(scope=None, origin=None)
    assert server.calls == []


async def test_the_token_is_sent_and_a_wrong_one_is_rejected_without_leaking(vault: Path) -> None:
    with fake_obsidian_mcp(vault, token="s3cret") as server:
        good, _ = _adapters(vault, server.url, token="s3cret")
        assert (await good.search("ttl", scope=None, limit=1)).notes
        assert set(server.authorizations) == {"Bearer s3cret"}

        bad, _ = _adapters(vault, server.url, token="wrong-token")
        with pytest.raises(ObsidianMcpError) as raised:
            await bad.search("ttl", scope=None, limit=1)

    assert "wrong-token" not in str(raised.value)
    assert "wrong-token" not in repr(ObsidianMcpClient(server.url, token="wrong-token"))


async def test_an_unreachable_server_raises_obsidian_mcp_error(vault: Path) -> None:
    mcp_repo, _ = _adapters(vault, f"http://127.0.0.1:{free_port()}/mcp/")

    with pytest.raises(ObsidianMcpError, match="unreachable"):
        await mcp_repo.search("ttl", scope=None, limit=3)


async def test_fallback_searches_files_and_notifies_once(vault: Path) -> None:
    mcp_repo, files = _adapters(vault, f"http://127.0.0.1:{free_port()}/mcp/")
    notified: list[ObsidianMcpError] = []
    repo = FallbackNoteReadRepositoryAdapter(mcp_repo, files, on_fallback=notified.append)

    first: tuple[NoteSummaryDto, ...] = (await repo.search("ttl cache", scope=None, limit=5)).notes
    second: tuple[NoteSummaryDto, ...] = (await repo.search("ttl cache", scope=None, limit=5)).notes

    assert first == second == (await files.search("ttl cache", scope=None, limit=5)).notes
    assert first
    assert len(notified) == 1


async def test_a_second_text_block_with_a_truncation_note_is_ignored(vault: Path) -> None:
    with fake_obsidian_mcp(vault, truncation_note=True) as server:
        mcp_repo, _ = _adapters(vault, server.url)
        found: tuple[NoteSummaryDto, ...] = (
            await mcp_repo.search("ttl cache", scope=None, limit=5)
        ).notes

    assert found


async def test_an_unusable_answer_is_reported_as_such_not_as_unreachable(vault: Path) -> None:
    with fake_obsidian_mcp(vault, garbage=True) as server:
        mcp_repo, _ = _adapters(vault, server.url)
        with pytest.raises(ObsidianMcpError, match="not JSON"):
            await mcp_repo.search("ttl", scope=None, limit=1)


async def test_read_note_returns_the_whole_note_inside_the_area(vault: Path) -> None:
    with fake_obsidian_mcp(vault) as server:
        obsidian, _ = _adapters(vault, server.url)

        note = await obsidian.read_note(
            "repos/demo/decisions/use-ttl-cache.md", scope=NoteScope.for_repository("demo")
        )

    assert (note.title, note.kind, note.origin, note.updated) == (
        "Use a TTL cache", "decision", "auto", "2026-10-02",
    )  # fmt: skip
    assert note.content == TTL


@pytest.mark.parametrize(
    "path",
    [
        "repos/demo/../../secret.md",
        "../secret.md",
        "repos/demo/.obsidian/workspace.md",
        "repos/demo/decisions/use-ttl-cache.txt",
    ],
)
async def test_read_note_refuses_unsafe_paths_without_calling_obsidian(
    vault: Path, path: str
) -> None:
    with fake_obsidian_mcp(vault) as server:
        obsidian, _ = _adapters(vault, server.url)

        with pytest.raises(NoteStorageError):
            await obsidian.read_note(path, scope=NoteScope.for_repository("demo"))

    assert server.calls == []


async def test_read_note_refuses_another_scope(vault: Path) -> None:
    with fake_obsidian_mcp(vault) as server:
        obsidian, _ = _adapters(vault, server.url)

        with pytest.raises(NoteStorageError):
            await obsidian.read_note(
                "repos/other/decisions/use-ttl-cache.md", scope=NoteScope.for_repository("demo")
            )


async def test_read_note_falls_back_to_files_when_obsidian_is_down(vault: Path) -> None:
    obsidian, files = _adapters(vault, f"http://127.0.0.1:{free_port()}/mcp/")
    notices: list[ObsidianMcpError] = []
    repository = FallbackNoteReadRepositoryAdapter(obsidian, files, on_fallback=notices.append)

    note = await repository.read_note(
        "repos/demo/decisions/use-ttl-cache.md", scope=NoteScope.for_repository("demo")
    )

    assert note.content == TTL
    assert len(notices) == 1


async def test_a_search_for_a_whole_sentence_finds_nothing_but_keywords_do(vault: Path) -> None:
    """Obsidian's search wants every word: this is why recall searches keyword by keyword."""
    with fake_obsidian_mcp(vault, all_words=True) as server:
        obsidian, _ = _adapters(vault, server.url)
        scope = NoteScope.for_repository("demo")

        sentence = await obsidian.search(
            "use a ttl cache for lookups quickly", scope=scope, limit=5
        )
        keyword = await obsidian.search("ttl", scope=scope, limit=5)

    assert sentence.notes == ()
    assert [note.path for note in keyword.notes] == ["repos/demo/decisions/use-ttl-cache.md"]


async def test_recall_digest_finds_a_task_sentence_through_obsidian_within_the_area(
    vault: Path,
) -> None:
    """Recall searches keyword by keyword, so a task sentence still finds the area's notes."""
    with fake_obsidian_mcp(vault, all_words=True) as server:
        obsidian, _ = _adapters(vault, server.url)
        handler = RecallNotesHandler(
            read_repository=obsidian, manifest=DefaultManifestProvider(), clock=FixedClock()
        )

        digest = await handler.handle(
            RecallNotesQuery(
                task="summarize the ttl cache repo", scope="repo:demo", synthesize=False
            )
        )

    assert [entry.path for entry in digest.entries] == ["repos/demo/decisions/use-ttl-cache.md"]
    assert digest.considered == 1
    assert digest.backend is SearchEngineEnum.OBSIDIAN_MCP
