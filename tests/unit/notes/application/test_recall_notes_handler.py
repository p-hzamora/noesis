"""Recall: keywords, over-fetch, re-ranking, and a digest bounded by limit and budget."""

import pytest
from pydantic import ValidationError
from tests.support.notes_support import (
    DefaultManifestProvider,
    FixedClock,
    InMemoryNoteReadRepository,
    a_summary,
)

from noesis.bounded_context.notes.application.dtos import NoteSummaryDto, RecallDigestDto
from noesis.bounded_context.notes.application.handlers.queries import (
    RecallNotesHandler,
    RecallNotesQuery,
)
from noesis.bounded_context.notes.application.services.recall import CHARS_PER_TOKEN
from noesis.exceptions import NoRecallTermsError
from noesis.shared_kernel.enums import SearchEngineEnum

pytestmark = pytest.mark.unit


def _note(
    name: str,
    *,
    kind: str | None = "decision",
    origin: str = "manual",
    updated: str | None = "2026-10-01",
    snippet: str = "",
) -> NoteSummaryDto:
    return a_summary(
        f"repos/demo/{name}.md",
        title=f"Title {name}",
        kind=kind or "decision",
        origin=origin,
        updated=updated,
        snippet=snippet,
    )


def _handler(*notes: NoteSummaryDto) -> tuple[RecallNotesHandler, InMemoryNoteReadRepository]:
    repository = InMemoryNoteReadRepository(notes)
    return RecallNotesHandler(
        read_repository=repository, manifest=DefaultManifestProvider(), clock=FixedClock()
    ), repository


def _size(digest: RecallDigestDto) -> int:
    return sum(
        len(entry.kind or "")
        + len(entry.title)
        + len(entry.path)
        + len(entry.date or "")
        + len(entry.snippet)
        for entry in digest.entries
    )


def test_query_defaults_and_bounds() -> None:
    query = RecallNotesQuery(task="fix the login cache")

    assert (query.limit, query.budget_tokens, query.scope) == (5, 1000, None)
    for bad in (
        {"task": ""},
        {"task": "x", "limit": 0},
        {"task": "x", "limit": 21},
        {"task": "x", "budget_tokens": -1},
    ):
        with pytest.raises(ValidationError):
            RecallNotesQuery(**bad)  # type: ignore[arg-type]
    assert RecallNotesQuery(task="x", limit=20, budget_tokens=0).budget_tokens == 0


async def test_searches_each_keyword_on_its_own_not_the_sentence() -> None:
    handler, repository = _handler(_note("a"))

    await handler.handle(RecallNotesQuery(synthesize=False, task="How to fix the login cache?"))

    assert repository.queries == ["fix", "login", "cache"]


@pytest.mark.parametrize(("limit", "fetched"), [(1, 3), (3, 9), (5, 10), (20, 10)])
async def test_each_query_over_fetches_three_times_the_limit_capped_at_ten(
    limit: int, fetched: int
) -> None:
    handler, repository = _handler(_note("a"))

    await handler.handle(RecallNotesQuery(synthesize=False, task="login cache", limit=limit))

    assert repository.limits == [fetched, fetched]


async def test_ranking_can_promote_a_gotcha_over_the_engines_first_hit() -> None:
    handler, _ = _handler(
        _note("run", kind="run", origin="auto", updated="2025-01-01"),
        _note("gotcha", kind="gotcha"),
    )

    digest = await handler.handle(RecallNotesQuery(synthesize=False, task="login cache"))

    assert [entry.path for entry in digest.entries] == [
        "repos/demo/gotcha.md",
        "repos/demo/run.md",
    ]


async def test_an_old_run_is_still_returned() -> None:
    handler, _ = _handler(_note("run", kind="run", updated="2019-01-01"))

    digest = await handler.handle(RecallNotesQuery(synthesize=False, task="login cache"))

    assert [entry.path for entry in digest.entries] == ["repos/demo/run.md"]


async def test_unknown_values_do_not_break_ranking() -> None:
    handler, _ = _handler(_note("odd", kind="weird", origin="alien", updated="soon"))

    digest = await handler.handle(RecallNotesQuery(synthesize=False, task="login cache"))

    assert [(e.kind, e.date) for e in digest.entries] == [("weird", "soon")]


async def test_takes_the_limit_and_reports_considered_and_omitted() -> None:
    handler, _ = _handler(*(_note(str(i)) for i in range(8)))

    digest = await handler.handle(RecallNotesQuery(synthesize=False, task="login cache", limit=3))

    assert len(digest.entries) == 3
    assert (digest.considered, digest.omitted) == (8, 5)
    assert digest.backend is SearchEngineEnum.FILESYSTEM


async def test_no_matches_is_an_empty_digest() -> None:
    handler, _ = _handler()

    digest = await handler.handle(RecallNotesQuery(synthesize=False, task="login cache"))

    assert (digest.entries, digest.considered, digest.omitted) == ((), 0, 0)


async def test_a_preferred_scope_ranks_first_without_hiding_the_rest() -> None:
    mine = _note("a").model_copy(update={"path": "repos/mine/a.md", "scope": "repo:mine"})
    handler, _ = _handler(_note("b"), mine)

    digest = await handler.handle(
        RecallNotesQuery(synthesize=False, task="login cache", prefer_scope="repo:mine")
    )

    assert [entry.path for entry in digest.entries] == ["repos/mine/a.md", "repos/demo/b.md"]


async def test_entries_carry_kind_title_path_date_and_snippet() -> None:
    handler, _ = _handler(_note("a", snippet="Keep tokens in memory."))

    entry = (await handler.handle(RecallNotesQuery(synthesize=False, task="login cache"))).entries[
        0
    ]

    assert (entry.kind, entry.title, entry.path, entry.date, entry.snippet) == (
        "decision",
        "Title a",
        "repos/demo/a.md",
        "2026-10-01",
        "Keep tokens in memory.",
    )


async def test_budget_drops_the_lowest_ranked_entries_first() -> None:
    notes = [_note(str(i), snippet="") for i in range(4)]
    handler, _ = _handler(*notes)
    one_entry = _size(
        await handler.handle(RecallNotesQuery(synthesize=False, task="login cache", limit=1))
    )
    budget_tokens = (2 * one_entry) // CHARS_PER_TOKEN + 1

    digest = await handler.handle(
        RecallNotesQuery(synthesize=False, task="login cache", budget_tokens=budget_tokens)
    )

    assert [entry.path for entry in digest.entries] == ["repos/demo/0.md", "repos/demo/1.md"]
    assert (digest.considered, digest.omitted) == (4, 2)
    assert _size(digest) <= budget_tokens * CHARS_PER_TOKEN


async def test_budget_then_shortens_snippets_from_the_lowest_ranked() -> None:
    long = "x" * 400
    handler, _ = _handler(_note("0", snippet=long), _note("1", snippet=long))
    bare = _size(
        await RecallNotesHandler(
            read_repository=InMemoryNoteReadRepository([_note("0"), _note("1")]),
            manifest=DefaultManifestProvider(),
            clock=FixedClock(),
        ).handle(RecallNotesQuery(synthesize=False, task="login cache"))
    )
    budget_tokens = (bare + 300) // CHARS_PER_TOKEN

    digest = await handler.handle(
        RecallNotesQuery(synthesize=False, task="login cache", budget_tokens=budget_tokens)
    )

    assert len(digest.entries) == 2
    assert digest.omitted == 0
    first, second = digest.entries
    assert len(first.snippet) > len(second.snippet)
    assert first.snippet != long
    assert _size(digest) <= budget_tokens * CHARS_PER_TOKEN


async def test_zero_budget_means_unlimited() -> None:
    long = "x" * 5000
    handler, _ = _handler(*(_note(str(i), snippet=long) for i in range(5)))

    digest = await handler.handle(
        RecallNotesQuery(synthesize=False, task="login cache", budget_tokens=0)
    )

    assert len(digest.entries) == 5
    assert all(entry.snippet == long for entry in digest.entries)


async def test_a_budget_smaller_than_one_entry_returns_nothing_and_omits_everything() -> None:
    handler, _ = _handler(_note("0"), _note("1"))

    digest = await handler.handle(
        RecallNotesQuery(synthesize=False, task="login cache", budget_tokens=1)
    )

    assert digest.entries == ()
    assert (digest.considered, digest.omitted) == (2, 2)


async def test_a_task_without_keywords_is_a_typed_error() -> None:
    handler, repository = _handler(_note("a"))

    with pytest.raises(NoRecallTermsError):
        await handler.handle(RecallNotesQuery(synthesize=False, task="the and of"))

    assert repository.queries == []
