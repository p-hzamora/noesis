"""The real Knowledge handlers over the real Neo4j adapters (AC-002, 004, 005, 006, 023)."""

import asyncio
from typing import Any

import pytest
from tests.support.knowledge_neo4j_support import (
    Neo4jKnowledgeEnv,
    make_neo4j_env,
    node_counts,
    query,
)
from tests.support.knowledge_support import AGENT, DEFAULT_SPACE_KEY

from noesis.bounded_context.knowledge.application.dtos import (
    CaptureResultDto,
    RecordDto,
    ReviseResultDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_experience_handler import (
    CaptureExperienceCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
    InitialiseStoreCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.revise_knowledge_handler import (
    ReviseKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.handlers.queries.get_record_handler import (
    GetRecordQuery,
)
from noesis.bounded_context.knowledge.application.services.inputs import (
    ExistingSourceInput,
    NewSourceInput,
    ProjectRef,
    SourceInput,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    ExperienceSubtypeEnum,
    Key,
    RecordId,
    Slug,
    SourceKindEnum,
    SpaceId,
    Tag,
)
from noesis.exceptions import (
    IdempotencyKeyReusedError,
    RecordNotFoundError,
    ReferenceNotInSpaceError,
    RevisionConflictError,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

WORK_SPACE: Key = Key(value="work")
COMMIT: NewSourceInput = NewSourceInput(kind=SourceKindEnum.COMMIT, locator="a" * 40)


def _capture(
    key: str = "k-1",
    *,
    body: str = "Records live in Neo4j.",
    space_key: Key = DEFAULT_SPACE_KEY,
    sources: tuple[SourceInput, ...] = (COMMIT,),
) -> CaptureKnowledgeCommand:
    return CaptureKnowledgeCommand(
        idempotency_key=key,
        space_key=space_key,
        title="Use Neo4j",
        body=body,
        subtype=Slug(value="decision"),
        actor=AGENT,
        project=ProjectRef(key=Key(value="noesis")),
        tags=(Tag(value="neo4j"),),
        sources=sources,
    )


def _revise(record_id: str, key: str, body: str) -> ReviseKnowledgeCommand:
    return ReviseKnowledgeCommand(
        idempotency_key=key,
        space_key=DEFAULT_SPACE_KEY,
        record_id=RecordId(value=record_id),
        expected_revision=1,
        actor=AGENT,
        body=body,
    )


async def _work_space(env: Neo4jKnowledgeEnv) -> None:
    await env.initialise_store.handle(InitialiseStoreCommand(default_space_key=WORK_SPACE))


async def test_capture_then_get_returns_the_record_with_its_head_and_sources(
    env: Neo4jKnowledgeEnv,
) -> None:
    captured: CaptureResultDto = await env.capture_knowledge.handle(_capture())

    record: RecordDto = await env.get_record.handle(
        GetRecordQuery(space_key=DEFAULT_SPACE_KEY, record_id=RecordId(value=captured.record_id))
    )

    assert record.type == "knowledge"
    assert (record.status, record.ownership, record.head_revision) == ("proposed", "graph", 1)
    assert record.project_id == captured.project_id
    assert record.applicability is not None
    assert record.applicability.tags == ("neo4j",)
    assert record.revision is not None
    assert (record.revision.title, record.revision.body) == ("Use Neo4j", "Records live in Neo4j.")
    assert [source.locator for source in record.sources] == ["a" * 40]


async def test_project_and_source_records_are_readable_by_id(env: Neo4jKnowledgeEnv) -> None:
    captured: CaptureResultDto = await env.capture_knowledge.handle(_capture())
    assert captured.project_id is not None
    knowledge: RecordDto = await env.get_record.handle(
        GetRecordQuery(space_key=DEFAULT_SPACE_KEY, record_id=RecordId(value=captured.record_id))
    )

    project: RecordDto = await env.get_record.handle(
        GetRecordQuery(space_key=DEFAULT_SPACE_KEY, record_id=RecordId(value=captured.project_id))
    )
    source: RecordDto = await env.get_record.handle(
        GetRecordQuery(
            space_key=DEFAULT_SPACE_KEY, record_id=RecordId(value=knowledge.sources[0].id)
        )
    )

    assert (project.type, project.key, project.name) == ("project", "noesis", "noesis")
    assert (source.type, source.source_kind, source.locator) == ("source", "commit", "a" * 40)


async def test_an_experience_is_captured_and_read_back(env: Neo4jKnowledgeEnv) -> None:
    captured: CaptureResultDto = await env.capture_experience.handle(
        CaptureExperienceCommand(
            idempotency_key="e-1",
            space_key=DEFAULT_SPACE_KEY,
            subtype=ExperienceSubtypeEnum.OUTCOME,
            body="The constraint caught the race.",
            actor=AGENT,
            session="s-1",
            sources=(COMMIT,),
        )
    )

    record: RecordDto = await env.get_record.handle(
        GetRecordQuery(space_key=DEFAULT_SPACE_KEY, record_id=RecordId(value=captured.record_id))
    )

    assert (record.type, record.subtype, record.body) == (
        "experience",
        "outcome",
        "The constraint caught the race.",
    )
    assert record.actor is not None
    assert record.actor.name == "claude"
    assert [source.locator for source in record.sources] == ["a" * 40]


async def test_a_record_of_another_space_is_not_found(env: Neo4jKnowledgeEnv) -> None:
    await _work_space(env)
    captured: CaptureResultDto = await env.capture_knowledge.handle(_capture())

    with pytest.raises(RecordNotFoundError) as raised:
        await env.get_record.handle(
            GetRecordQuery(space_key=WORK_SPACE, record_id=RecordId(value=captured.record_id))
        )

    assert raised.value.error_code == "KNOWLEDGE_201_RECORD_NOT_FOUND"


async def test_replaying_a_key_returns_the_original_and_a_different_request_is_rejected(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    first: CaptureResultDto = await env.capture_knowledge.handle(_capture())
    after_first: dict[str, int] = node_counts(neo4j_settings)

    replay: CaptureResultDto = await env.capture_knowledge.handle(_capture())
    with pytest.raises(IdempotencyKeyReusedError) as raised:
        await env.capture_knowledge.handle(_capture(body="Something else."))

    assert replay.record_id == first.record_id
    assert replay.replayed and not first.replayed
    assert raised.value.error_code == "KNOWLEDGE_203_IDEMPOTENCY_KEY_REUSED"
    assert node_counts(neo4j_settings) == after_first


async def test_two_racing_first_captures_with_one_key_store_one_record_and_agree_on_its_id(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    other: Neo4jKnowledgeEnv = make_neo4j_env(neo4j_settings)
    try:
        results: list[CaptureResultDto] = await asyncio.gather(
            env.capture_knowledge.handle(_capture()), other.capture_knowledge.handle(_capture())
        )
    finally:
        await other.client.close()

    assert results[0].record_id == results[1].record_id
    assert sorted(result.replayed for result in results) == [False, True]
    counts: dict[str, int] = node_counts(neo4j_settings)
    assert (counts["Knowledge"], counts["IdempotencyKey"], counts["Project"], counts["Source"]) == (
        1,
        1,
        1,
        1,
    )


async def test_two_concurrent_revises_of_one_head_let_exactly_one_win(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    captured: CaptureResultDto = await env.capture_knowledge.handle(_capture())
    other: Neo4jKnowledgeEnv = make_neo4j_env(neo4j_settings)
    try:
        outcomes: list[ReviseResultDto | BaseException] = await asyncio.gather(
            env.revise_knowledge.handle(_revise(captured.record_id, "r-a", "Version A.")),
            other.revise_knowledge.handle(_revise(captured.record_id, "r-b", "Version B.")),
            return_exceptions=True,
        )
    finally:
        await other.client.close()

    won: list[ReviseResultDto] = [o for o in outcomes if isinstance(o, ReviseResultDto)]
    lost: list[RevisionConflictError] = [
        o for o in outcomes if isinstance(o, RevisionConflictError)
    ]
    assert len(won) == 1 and len(lost) == 1, outcomes
    assert won[0].revision == 2
    assert lost[0].error_code == "KNOWLEDGE_202_REVISION_CONFLICT"
    assert (lost[0].metadata["expected_revision"], lost[0].metadata["actual_revision"]) == (1, 2)
    assert query(
        neo4j_settings,
        "MATCH (r:Revision {record_id: $id}) RETURN count(r) AS total",
        id=captured.record_id,
    ) == [{"total": 2}]


async def test_revise_then_get_shows_the_new_head_and_keeps_revision_one(
    env: Neo4jKnowledgeEnv,
) -> None:
    captured: CaptureResultDto = await env.capture_knowledge.handle(_capture())

    revised: ReviseResultDto = await env.revise_knowledge.handle(
        _revise(captured.record_id, "r-1", "Revised.")
    )
    head: RecordDto = await env.get_record.handle(
        GetRecordQuery(space_key=DEFAULT_SPACE_KEY, record_id=RecordId(value=captured.record_id))
    )
    first: RecordDto = await env.get_record.handle(
        GetRecordQuery(
            space_key=DEFAULT_SPACE_KEY, record_id=RecordId(value=captured.record_id), revision=1
        )
    )

    assert revised.revision == 2
    assert head.head_revision == 2
    assert head.revision is not None and head.revision.body == "Revised."
    assert first.revision is not None and first.revision.body == "Records live in Neo4j."


async def test_a_crash_between_capture_steps_leaves_orphans_that_the_retry_reuses(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id: SpaceId | None = await env.persistence.read_repository.get_space_id(DEFAULT_SPACE_KEY)
    assert space_id is not None
    orphan_project: RecordId | None = await env.references.ensure_project(
        space_id, ProjectRef(key=Key(value="noesis"))
    )
    orphan_sources: tuple[RecordId, ...] = await env.references.ensure_sources(space_id, (COMMIT,))
    # the process dies here: no record, no ledger entry

    retried: CaptureResultDto = await env.capture_knowledge.handle(_capture())
    record: RecordDto = await env.get_record.handle(
        GetRecordQuery(space_key=DEFAULT_SPACE_KEY, record_id=RecordId(value=retried.record_id))
    )

    assert orphan_project is not None
    assert retried.project_id == orphan_project.value
    assert [source.id for source in record.sources] == [orphan_sources[0].value]
    counts: dict[str, int] = node_counts(neo4j_settings)
    assert (counts["Project"], counts["Source"], counts["Knowledge"]) == (1, 1, 1)


async def test_a_new_source_locator_with_a_secret_is_stored_redacted(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    secret_url: NewSourceInput = NewSourceInput(
        kind=SourceKindEnum.URL, locator="https://example.test/doc?api_key=abcdefgh12345678"
    )

    await env.capture_knowledge.handle(_capture(sources=(secret_url,)))
    await env.capture_knowledge.handle(_capture("k-2", body="Again.", sources=(secret_url,)))

    rows: list[dict[str, Any]] = query(
        neo4j_settings, "MATCH (s:Source) RETURN s.locator AS locator"
    )
    assert rows == [{"locator": "https://example.test/doc?api_key=[REDACTED]"}]


async def test_citing_a_source_of_another_space_is_rejected_and_writes_nothing(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    await _work_space(env)
    elsewhere: CaptureResultDto = await env.capture_knowledge.handle(
        _capture("w-1", space_key=WORK_SPACE)
    )
    foreign: RecordDto = await env.get_record.handle(
        GetRecordQuery(space_key=WORK_SPACE, record_id=RecordId(value=elsewhere.record_id))
    )
    before: dict[str, int] = node_counts(neo4j_settings)

    with pytest.raises(ReferenceNotInSpaceError) as raised:
        await env.capture_knowledge.handle(
            _capture(
                "k-2",
                sources=(ExistingSourceInput(source_id=RecordId(value=foreign.sources[0].id)),),
            )
        )

    assert raised.value.error_code == "KNOWLEDGE_205_REFERENCE_NOT_IN_SPACE"
    assert node_counts(neo4j_settings) == before
