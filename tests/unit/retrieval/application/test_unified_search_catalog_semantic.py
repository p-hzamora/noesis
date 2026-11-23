"""Catalog entries found by meaning join the lexical candidates; absence changes nothing."""

import pytest
from tests.support.retrieval.fake_semantic_source import FakeSemanticSource
from tests.support.retrieval.retrieval_fakes import SPACE
from tests.unit.retrieval.application.test_unified_search_handler import (
    FixedClock,
    Harness,
    entry_id,
    resource,
)

from noesis.bounded_context.retrieval.application.dtos.search_dtos import UnifiedSearchResultDto
from noesis.bounded_context.retrieval.application.handlers.queries.unified_search_handler import (
    UnifiedSearchHandler,
)
from noesis.bounded_context.retrieval.application.services.resource_facts_service import (
    ResourceFactsService,
)
from noesis.bounded_context.retrieval.domain.value_objects.projection_key import ProjectionKey
from noesis.shared_kernel.contracts.knowledge import CatalogResourceHitContract

pytestmark = pytest.mark.unit

HEAD: int = 3


def semantic_harness(
    found: list[CatalogResourceHitContract],
    known: list[CatalogResourceHitContract],
    catalog_hits: list[int],
    *,
    ready: bool = True,
) -> tuple[Harness, FakeSemanticSource]:
    """A harness whose record search has semantic `ready` (or no registered source)."""
    harness = Harness(found, known=known)
    for _ in range(HEAD):
        harness.world.feed.add(SPACE, "K")
    harness.world.cursors.set("semantic", SPACE, HEAD)
    source = FakeSemanticSource()
    source.set_hits(SPACE, [ProjectionKey(record_id=entry_id(n), revision=1) for n in catalog_hits])
    harness.handler = UnifiedSearchHandler(
        harness.world.searcher(with_semantic=ready),
        resources=harness.resources,
        facts=ResourceFactsService(
            reviews=harness.reviews,
            recommendations=harness.recommendations,
            assertions=harness.assertions,
            availability=harness.availability,
        ),
        briefing=harness.briefing,
        clock=FixedClock(),
        catalog_semantic=source,
    )
    return harness, source


def channels(result: UnifiedSearchResultDto) -> dict[str, tuple[str, ...]]:
    return {item.name: item.why.channels for item in result.resources}


async def test_an_entry_only_semantic_search_finds_joins_the_resources() -> None:
    cli = resource("cli-skill", "cli delivery", number=1)
    meaning = resource("vault-curator", "tidy the notes", number=2)
    harness, source = semantic_harness([cli], [meaning], [2])

    result = await harness.run(needs=("cli",))

    assert channels(result) == {
        "cli-skill": ("catalog_text",),
        "vault-curator": ("catalog_semantic",),
    }
    assert [call.text for call in source.calls] == ["create a cli project"]


async def test_an_entry_found_by_both_channels_appears_once_with_both() -> None:
    cli = resource("cli-skill", "cli delivery", number=1)
    other = resource("cli-other", "another cli", number=2)
    harness, _ = semantic_harness([cli, other], [], [2, 1])

    result = await harness.run(needs=("cli",))

    assert [item.name for item in result.resources].count("cli-skill") == 1
    assert channels(result)["cli-skill"] == ("catalog_text", "catalog_semantic")


async def test_the_semantic_rank_lifts_an_entry_the_lexical_search_put_last() -> None:
    first = resource("alpha", "one", number=1)
    last = resource("omega", "two", number=2)
    harness, _ = semantic_harness([first, last], [], [2])

    result = await harness.run(needs=())

    assert next(item.name for item in result.resources) == "omega"


async def test_without_a_usable_semantic_index_the_source_is_never_asked() -> None:
    cli = resource("cli-skill", "cli delivery", number=1)
    meaning = resource("vault-curator", "tidy the notes", number=2)
    harness, source = semantic_harness([cli], [meaning], [2], ready=False)

    result = await harness.run(needs=("cli",))

    assert source.calls == []
    assert channels(result) == {"cli-skill": ("catalog_text",)}


async def test_a_failing_catalog_source_keeps_the_lexical_answer_and_warns() -> None:
    cli = resource("cli-skill", "cli delivery", number=1)
    harness, source = semantic_harness([cli], [], [])
    source.go_down()

    result = await harness.run(needs=("cli",))

    assert channels(result) == {"cli-skill": ("catalog_text",)}
    assert any("semantic search is unavailable" in warning for warning in result.warnings)
