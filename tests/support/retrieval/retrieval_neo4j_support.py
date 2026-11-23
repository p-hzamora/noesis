"""Seeding and wiring for Retrieval tests over the real Neo4j container.

Records are created through C2's capture and revise handlers (so every `:Change` is the one
production writes); the searcher is wired from the real Knowledge inbound adapters and the Neo4j
cursor store. `MutableClock` fixes the times the scenarios name (T1, T2, T3).
"""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Final

from tests.support.knowledge_commands import (
    COMMIT,
    experience_command,
    knowledge_command,
    revise_command,
)
from tests.support.knowledge_neo4j_support import Neo4jKnowledgeEnv, make_neo4j_env
from tests.support.knowledge_support import DEFAULT_SPACE_KEY, NOW

from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
    InitialiseStoreCommand,
)
from noesis.bounded_context.knowledge.application.services.inputs import (
    NewSourceInput,
    ProjectRef,
    SourceInput,
)
from noesis.bounded_context.knowledge.domain.entities import KnowledgeSpace
from noesis.bounded_context.knowledge.domain.value_objects import (
    Key,
    RecordId,
    SourceKindEnum,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_indexable_record_reader_adapter import (
    Neo4jIndexableRecordReaderAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_change_feed_adapter import (
    Neo4jRecordChangeFeedAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_neighbour_reader_adapter import (
    Neo4jRecordNeighbourReaderAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_state_reader_adapter import (
    Neo4jRecordStateReaderAdapter,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.retrieval.neo4j_record_text_search_adapter import (
    Neo4jRecordTextSearchAdapter,
)
from noesis.bounded_context.retrieval.application.dtos.record_search_dtos import (
    RecordSearchRequestDto,
    RecordSearchResultDto,
)
from noesis.bounded_context.retrieval.application.ports.candidates.i_candidate_source import (
    ICandidateSource,
)
from noesis.bounded_context.retrieval.application.services.record_searcher import RecordSearcher
from noesis.bounded_context.retrieval.infrastructure.outbound.persistence.neo4j_index_cursor_store_adapter import (
    Neo4jIndexCursorStoreAdapter,
)
from noesis.interfaces.cli.bootstrap.knowledge_handlers_builder import EXTRA_SCHEMA_STEPS
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

T1: Final[datetime] = datetime(2026, 1, 1, tzinfo=UTC)
T2: Final[datetime] = datetime(2026, 1, 2, tzinfo=UTC)
T3: Final[datetime] = datetime(2026, 1, 3, tzinfo=UTC)
OTHER_SPACE_KEY: Final[Key] = Key(value="other-space")


def commit_source(fill: str = "a") -> NewSourceInput:
    """A commit Source; two records citing the same fill share one Source node in a space."""
    return NewSourceInput(kind=SourceKindEnum.COMMIT, locator=fill * 40)


SHARED_SOURCE: Final[NewSourceInput] = COMMIT


async def initialised_env(
    settings: Neo4jConnectionSettings, *, with_retrieval_steps: bool = True
) -> AsyncIterator[Neo4jKnowledgeEnv]:
    """Handlers over a wiped database after `store init` (space `default`).

    With `with_retrieval_steps` false only C2's `core` step is registered (AC-028's setup).
    """
    env: Neo4jKnowledgeEnv = make_neo4j_env(
        settings, extra_steps=EXTRA_SCHEMA_STEPS if with_retrieval_steps else ()
    )
    await env.initialise_store.handle(InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY))
    try:
        yield env
    finally:
        await env.client.close()


async def space_id_of(env: Neo4jKnowledgeEnv, key: Key = DEFAULT_SPACE_KEY) -> str:
    """The id of an existing space."""
    space_id = await env.persistence.read_repository.get_space_id(key)
    assert space_id is not None, key
    return space_id.value


async def add_space(env: Neo4jKnowledgeEnv, key: Key = OTHER_SPACE_KEY) -> str:
    """Create a second space and return its id."""
    space = KnowledgeSpace.create(
        id=env.persistence.ids.new_space_id(), key=key, name=key.value, now=NOW
    )
    async with env.uow() as uow:
        await uow.spaces.add(space)
        await uow.commit()
    return space.id.value


def _project(project: str | None) -> ProjectRef | None:
    return ProjectRef(key=Key(value=project)) if project else None


async def capture_knowledge(
    env: Neo4jKnowledgeEnv,
    key: str,
    title: str,
    *,
    body: str = "A body about records.",
    project: str | None = None,
    sources: Sequence[SourceInput] = (SHARED_SOURCE,),
    space_key: Key = DEFAULT_SPACE_KEY,
) -> str:
    """Capture graph-owned knowledge (space-wide unless `project`); returns its id."""
    result = await env.capture_knowledge.handle(
        knowledge_command(
            key,
            title=title,
            body=body,
            project=_project(project),
            sources=tuple(sources),
            space_key=space_key,
        )
    )
    return result.record_id


async def capture_experience(
    env: Neo4jKnowledgeEnv,
    key: str,
    body: str,
    *,
    project: str | None = None,
    sources: Sequence[SourceInput] = (SHARED_SOURCE,),
    space_key: Key = DEFAULT_SPACE_KEY,
) -> str:
    """Capture an experience (space-wide unless `project`); returns its id."""
    result = await env.capture_experience.handle(
        experience_command(
            key,
            body=body,
            sources=tuple(sources),
            project=_project(project),
            space_key=space_key,
        )
    )
    return result.record_id


async def revise_knowledge(
    env: Neo4jKnowledgeEnv,
    record_id: str,
    key: str,
    *,
    expected: int,
    body: str | None = None,
    title: str | None = None,
    space_key: Key = DEFAULT_SPACE_KEY,
) -> int:
    """Append a revision; returns the new head revision."""
    overrides: dict[str, object] = {"space_key": space_key}
    if body is not None:
        overrides["body"] = body
    if title is not None:
        overrides["title"] = title
    result = await env.revise_knowledge.handle(
        revise_command(RecordId(value=record_id), key, expected=expected, **overrides)
    )
    return result.revision


def build_searcher(
    env: Neo4jKnowledgeEnv, *, candidate_sources: Sequence[ICandidateSource] = ()
) -> RecordSearcher:
    """`RecordSearcher` over the real Knowledge inbound adapters and the Neo4j cursor store."""
    client = env.client
    return RecordSearcher(
        Neo4jRecordTextSearchAdapter(client),
        Neo4jRecordStateReaderAdapter(client),
        Neo4jRecordNeighbourReaderAdapter(client),
        Neo4jIndexableRecordReaderAdapter(client),
        tuple(candidate_sources),
        Neo4jIndexCursorStoreAdapter(client, env.clock),
        Neo4jRecordChangeFeedAdapter(client),
    )


def search_request(
    text: str,
    space_id: str,
    *,
    project_key: str | None = None,
    all_projects: bool = False,
    statuses: tuple[str, ...] = (),
    limit: int = 10,
) -> RecordSearchRequestDto:
    """A search request with every field explicit (no tag, type or stale options)."""
    return RecordSearchRequestDto(
        text=text,
        space_id=space_id,
        project_key=project_key,
        all_projects=all_projects,
        tags=(),
        record_types=(),
        statuses=statuses,
        limit=limit,
        include_stale=False,
        require_semantic=False,
    )


def hit_ids(result: RecordSearchResultDto) -> list[str]:
    """The record ids of a result, in returned order."""
    return [hit.record_id for hit in result.hits]
