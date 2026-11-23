"""Catalog entries in the semantic projection, over the pinned Neo4j container.

A synonym-aware fake embedder maps different words of one idea to one concept, so a paraphrase with
no word in common with an entry still lands next to it. No model is downloaded or run.
"""

from typing import Any

import pytest
from tests.integration.retrieval.test_semantic_projection_neo4j import Semantic
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv
from tests.support.knowledge_support import AGENT, DEFAULT_SPACE_KEY
from tests.support.retrieval.fake_embedding import FakeEngine, FakeTextEmbedder, bag_of_words
from tests.support.retrieval.retrieval_neo4j_support import (
    build_searcher,
    capture_knowledge,
    search_request,
    space_id_of,
)

from noesis.bounded_context.knowledge.application.handlers.commands.catalog.register_catalog_entry_handler import (
    RegisterCatalogEntryCommand,
    RegisterCatalogEntryHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.catalog.revise_catalog_entry_handler import (
    ReviseCatalogEntryCommand,
    ReviseCatalogEntryHandler,
)
from noesis.bounded_context.knowledge.application.services.inputs import NewSourceInput
from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogEntryKindEnum,
    SourceKindEnum,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_resource_catalog_reader_adapter import (
    Neo4jResourceCatalogReaderAdapter,
)
from noesis.bounded_context.retrieval.application.dtos.search_dtos import UnifiedSearchRequestDto
from noesis.bounded_context.retrieval.application.handlers.queries.unified_search_handler import (
    UnifiedSearchHandler,
)
from noesis.bounded_context.retrieval.application.services.resource_facts_service import (
    ResourceFactsService,
)
from noesis.bounded_context.retrieval.domain.enums import SemanticStateEnum
from noesis.bounded_context.retrieval.infrastructure.outbound.semantic import (
    Neo4jSemanticCandidateSource,
)
from noesis.shared_kernel.infrastructure.outbound.clock import SystemClockAdapter

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

CONCEPTS: dict[str, str] = {
    "rotate": "renewal",
    "renew": "renewal",
    "refresh": "renewal",
    "credentials": "secret",
    "passwords": "secret",
    "secrets": "secret",
    "expiring": "stale",
    "outdated": "stale",
    "old": "stale",
}


def concepts(text: str) -> list[str]:
    """The words of `text` with each synonym replaced by its concept."""
    return [CONCEPTS.get(word.lower(), word.lower()) for word in text.replace("-", " ").split()]


class ConceptEngine(FakeEngine):
    """`FakeEngine` whose vectors are bags of concepts instead of bags of words."""

    def embed_query(self, text: str) -> tuple[float, ...]:
        """The query's concepts as a vector."""
        return bag_of_words(concepts(text))

    def embed_passage(self, text: str):  # type: ignore[no-untyped-def]
        """The passage's concepts, windowed like words."""
        return super().embed_passage(" ".join(concepts(text)))


def register_command(key: str, name: str, purpose: str) -> RegisterCatalogEntryCommand:
    return RegisterCatalogEntryCommand(
        idempotency_key=key,
        space_key=DEFAULT_SPACE_KEY,
        kind=CatalogEntryKindEnum.SKILL,
        name=name,
        purpose=purpose,
        location="skills/" + name,
        actor=AGENT,
        sources=(
            NewSourceInput(kind=SourceKindEnum.URL, locator="https://example.invalid/" + name),
        ),
    )


def handlers(env: Neo4jKnowledgeEnv) -> dict[str, Any]:
    return {
        "uow_factory": env.persistence.uow_factory,
        "clock": env.clock,
        "ids": env.persistence.ids,
        "schema": env.persistence.schema,
    }


async def seed(env: Neo4jKnowledgeEnv) -> dict[str, str]:
    """Two entries, one record whose text matches the catalog query's concepts; ids by name."""
    register = RegisterCatalogEntryHandler(**handlers(env))
    ids: dict[str, str] = {}
    for key, name, purpose in (
        ("c1", "rotate-credentials", "Renew the access secrets of a service"),
        ("c2", "tidy-notes", "Sort and file markdown notes"),
    ):
        ids[name] = (await register.handle(register_command(key, name, purpose))).id
    return ids


def catalog_source(semantic: Semantic) -> Neo4jSemanticCandidateSource:
    return Neo4jSemanticCandidateSource(
        semantic.env.client, semantic.embedder, semantic.inspector, catalog_entries=True
    )


def concept_semantic(env: Neo4jKnowledgeEnv) -> Semantic:
    return Semantic(env, FakeTextEmbedder(ConceptEngine()))


PARAPHRASE: str = "refresh outdated passwords"


async def test_a_paraphrase_finds_the_catalog_entry_and_never_a_record(
    env: Neo4jKnowledgeEnv,
) -> None:
    space_id = await space_id_of(env)
    ids = await seed(env)
    record = await capture_knowledge(env, "k1", "Secrets", body="renewal of secret stale values")
    semantic = concept_semantic(env)
    await semantic.rebuild(space_id)

    found = await catalog_source(semantic).find(PARAPHRASE, space_id=space_id, limit=5)
    records = await semantic.source.find(PARAPHRASE, space_id=space_id, limit=5)

    assert {"rotate-credentials", "tidy-notes"}.isdisjoint(PARAPHRASE.split())
    assert next(key.record_id for key in found.hits) == ids["rotate-credentials"]
    assert {key.record_id for key in found.hits} == set(ids.values())
    assert [key.record_id for key in records.hits] == [record]


async def test_rebuild_covers_catalog_entries_and_sync_follows_a_revision(
    env: Neo4jKnowledgeEnv,
) -> None:
    space_id = await space_id_of(env)
    ids = await seed(env)
    semantic = concept_semantic(env)

    await semantic.rebuild(space_id)

    assert await semantic.writer.entries(space_id) == {
        ids["rotate-credentials"]: 1,
        ids["tidy-notes"]: 1,
    }
    revise = ReviseCatalogEntryHandler(**handlers(env))
    await revise.handle(
        ReviseCatalogEntryCommand(
            idempotency_key="r1",
            space_key=DEFAULT_SPACE_KEY,
            ref="skill:tidy-notes",
            expected_revision=1,
            purpose="Sort and file markdown notes",
            version=None,
            prerequisites=None,
            location=None,
            actor=AGENT,
            sources=(NewSourceInput(kind=SourceKindEnum.URL, locator="https://example.invalid/t"),),
            capabilities=("renew-secrets",),
        )
    )
    await semantic.sync(space_id)

    entries = await semantic.writer.entries(space_id)
    assert entries[ids["tidy-notes"]] == 2


async def test_unified_search_returns_the_resource_by_meaning_only_with_semantic(
    env: Neo4jKnowledgeEnv,
) -> None:
    space_id = await space_id_of(env)
    ids = await seed(env)
    semantic = concept_semantic(env)
    await semantic.rebuild(space_id)
    results = {}
    for with_semantic in (False, True):
        searcher = build_searcher(
            env, candidate_sources=(semantic.source,) if with_semantic else ()
        )
        handler = UnifiedSearchHandler(
            searcher,
            resources=Neo4jResourceCatalogReaderAdapter(env.client, env.persistence.schema, {}),
            facts=ResourceFactsService(
                reviews=None, recommendations=None, assertions=None, availability=None
            ),
            briefing=None,
            clock=SystemClockAdapter(),
            catalog_semantic=catalog_source(semantic) if with_semantic else None,
        )
        results[with_semantic] = await handler.handle(
            UnifiedSearchRequestDto(records=search_request(PARAPHRASE, space_id))
        )

    assert results[False].records.semantic_state is SemanticStateEnum.ABSENT
    assert results[False].resources == ()
    assert results[True].records.semantic_state is SemanticStateEnum.READY
    found = results[True].resources[0]
    assert (found.name, found.catalog_id) == ("rotate-credentials", ids["rotate-credentials"])
    assert found.why.channels == ("catalog_semantic",)
