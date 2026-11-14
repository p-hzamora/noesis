"""Knowledge Neo4j repositories: round trips, mapping, lock and conflicts (D-016)."""

import asyncio
from typing import Any

import pytest
from tests.support.knowledge_neo4j_support import (
    Neo4jKnowledgeEnv,
    make_neo4j_env,
    node_counts,
    query,
)
from tests.support.knowledge_support import AGENT, DEFAULT_SPACE_KEY, NOW

from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.domain.entities import (
    Experience,
    Knowledge,
    KnowledgeSpace,
    Project,
    Source,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Applicability,
    ContentHash,
    ExperienceSubtypeEnum,
    FileContent,
    GraphContent,
    Key,
    OwnershipEnum,
    RecordId,
    Revision,
    Slug,
    SourceKindEnum,
    SpaceId,
    Tag,
)
from noesis.exceptions import (
    EntryAlreadyExistsError,
    ReferenceNotInSpaceError,
    RevisionConflictError,
)
from noesis.shared_kernel.infrastructure.outbound.neo4j import Neo4jConnectionSettings

pytestmark = [pytest.mark.integration, pytest.mark.neo4j]

BLOCKED_PROBE_SECONDS: float = 0.5


async def _default_space(env: Neo4jKnowledgeEnv) -> SpaceId:
    async with env.uow() as uow:
        space: KnowledgeSpace | None = await uow.spaces.get_by_key(DEFAULT_SPACE_KEY)
    assert space is not None
    return space.id


async def _add_space(env: Neo4jKnowledgeEnv, key: str) -> SpaceId:
    space = KnowledgeSpace.create(
        id=env.persistence.ids.new_space_id(), key=Key(value=key), name=key, now=NOW
    )
    async with env.uow() as uow:
        await uow.spaces.add(space)
        await uow.commit()
    return space.id


async def _add_source(
    env: Neo4jKnowledgeEnv,
    space_id: SpaceId,
    *,
    kind: SourceKindEnum = SourceKindEnum.COMMIT,
    locator: str = "a" * 40,
    digest: ContentHash | None = None,
) -> Source:
    source = Source.create(
        id=env.persistence.ids.new_record_id(),
        space_id=space_id,
        kind=kind,
        locator=locator,
        digest=digest,
        now=NOW,
    )
    async with env.uow() as uow:
        await uow.sources.add(source)
        await uow.commit()
    source.collect_events()
    return source


async def _add_project(env: Neo4jKnowledgeEnv, space_id: SpaceId, key: str = "noesis") -> Project:
    project = Project.create(
        id=env.persistence.ids.new_record_id(),
        space_id=space_id,
        key=Key(value=key),
        name=key,
        now=NOW,
    )
    async with env.uow() as uow:
        await uow.projects.add(project)
        await uow.commit()
    project.collect_events()
    return project


def _graph_knowledge(
    env: Neo4jKnowledgeEnv, space_id: SpaceId, source: Source, project: Project | None = None
) -> Knowledge:
    knowledge = Knowledge.create(
        id=env.persistence.ids.new_record_id(),
        space_id=space_id,
        ownership=OwnershipEnum.GRAPH,
        subtype=Slug(value="decision"),
        applicability=Applicability(
            project_id=project.id if project else None,
            tags=frozenset({Tag(value="area:store"), Tag(value="neo4j")}),
        ),
        actor=AGENT,
        source_ids=(source.id,),
        content=GraphContent(title="Use Neo4j", body="Records live in Neo4j."),
        now=NOW,
    )
    knowledge.collect_events()
    return knowledge


async def _add(env: Neo4jKnowledgeEnv, knowledge: Knowledge) -> None:
    async with env.uow() as uow:
        await uow.knowledge.add(knowledge)
        await uow.commit()


def _next_revision(knowledge: Knowledge, number: int, body: str) -> Revision:
    return Revision(
        number=number,
        actor=AGENT,
        source_ids=knowledge.head.source_ids,
        created_at=NOW,
        content=GraphContent(title="Use Neo4j", body=body),
    )


async def test_spaces_round_trip_and_are_unique_by_key(env: Neo4jKnowledgeEnv) -> None:
    space_id: SpaceId = await _add_space(env, "work")

    async with env.uow() as uow:
        by_id: KnowledgeSpace | None = await uow.spaces.get(space_id)
        by_key: KnowledgeSpace | None = await uow.spaces.get_by_key(Key(value="work"))
        with pytest.raises(EntryAlreadyExistsError):
            await uow.spaces.add(
                KnowledgeSpace.create(
                    id=env.persistence.ids.new_space_id(), key=Key(value="work"), name="x", now=NOW
                )
            )

    assert by_id == by_key
    assert by_id is not None
    assert (by_id.key.value, by_id.name, by_id.created_at) == ("work", "work", NOW)


async def test_projects_round_trip_and_are_unique_by_key_within_a_space(
    env: Neo4jKnowledgeEnv,
) -> None:
    space_id: SpaceId = await _default_space(env)
    other: SpaceId = await _add_space(env, "work")
    project: Project = await _add_project(env, space_id)
    same_key_elsewhere: Project = await _add_project(env, other)

    async with env.uow() as uow:
        assert await uow.projects.get(project.id, space_id=space_id) == project
        assert await uow.projects.get_by_key(Key(value="noesis"), space_id=space_id) == project
        assert await uow.projects.get(project.id, space_id=other) is None
        assert await uow.projects.get_by_key(Key(value="noesis"), space_id=other) == (
            same_key_elsewhere
        )
    with pytest.raises(EntryAlreadyExistsError):
        await _add_project(env, space_id)


@pytest.mark.parametrize(
    "digest", [None, ContentHash(value="sha256:" + "b" * 64)], ids=["no-digest", "digest"]
)
async def test_sources_round_trip_and_are_unique_by_natural_key(
    env: Neo4jKnowledgeEnv, digest: ContentHash | None
) -> None:
    space_id: SpaceId = await _default_space(env)
    source: Source = await _add_source(
        env,
        space_id,
        kind=SourceKindEnum.URL,
        locator="https://example.com/" + "x" * 5000,
        digest=digest,
    )

    async with env.uow() as uow:
        assert await uow.sources.get(source.id, space_id=space_id) == source
        assert (
            await uow.sources.get_by_natural_key(
                space_id=space_id, kind=source.kind, locator=source.locator, digest=digest
            )
            == source
        )
    with pytest.raises(EntryAlreadyExistsError):
        await _add_source(
            env, space_id, kind=SourceKindEnum.URL, locator=source.locator, digest=digest
        )


async def test_graph_owned_knowledge_round_trips_with_its_edges(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id: SpaceId = await _default_space(env)
    source: Source = await _add_source(env, space_id)
    project: Project = await _add_project(env, space_id)
    knowledge: Knowledge = _graph_knowledge(env, space_id, source, project)

    await _add(env, knowledge)
    async with env.uow() as uow:
        loaded: Knowledge | None = await uow.knowledge.get(knowledge.id, space_id=space_id)

    assert loaded == knowledge
    edges: list[dict[str, Any]] = query(
        neo4j_settings,
        "MATCH (k:Record:Knowledge {id: $id})-[e]->(t) RETURN type(e) AS edge, labels(t) AS target "
        "UNION MATCH (r:Revision)-[e]->(t) WHERE r.record_id = $id "
        "RETURN type(e) AS edge, labels(t) AS target",
        id=knowledge.id.value,
    )
    assert {(row["edge"], tuple(sorted(row["target"]))) for row in edges} == {
        ("IN_SPACE", ("Space",)),
        ("BELONGS_TO_PROJECT", ("Project", "Record")),
        ("REVISION_OF", ("Knowledge", "Record")),
        ("FROM_SOURCE", ("Record", "Source")),
    }
    node: dict[str, Any] = query(
        neo4j_settings,
        "MATCH (k:Knowledge {id: $id}) RETURN properties(k) AS k",
        id=knowledge.id.value,
    )[0]["k"]
    assert node["space_id"] == space_id.value
    assert node["head_revision"] == 1
    assert node["tags"] == ["area:store", "neo4j"]


async def test_a_file_owned_revision_stores_hash_source_and_title_and_no_text(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id: SpaceId = await _default_space(env)
    version: Source = await _add_source(
        env, space_id, kind=SourceKindEnum.FILE_VERSION, locator="vault://main/decisions/neo4j.md"
    )
    knowledge = Knowledge.create(
        id=env.persistence.ids.new_record_id(),
        space_id=space_id,
        ownership=OwnershipEnum.FILE,
        subtype=Slug(value="decision"),
        applicability=Applicability(),
        actor=AGENT,
        source_ids=(version.id,),
        content=FileContent(
            content_hash=ContentHash(value="sha256:" + "c" * 64),
            file_version_source_id=version.id,
            title="Use Neo4j",
        ),
        now=NOW,
    )
    knowledge.collect_events()

    await _add(env, knowledge)
    async with env.uow() as uow:
        loaded: Knowledge | None = await uow.knowledge.get(knowledge.id, space_id=space_id)

    assert loaded == knowledge
    revision: dict[str, Any] = query(
        neo4j_settings,
        "MATCH (r:Revision {record_id: $id}) RETURN properties(r) AS r",
        id=knowledge.id.value,
    )[0]["r"]
    assert revision["content_hash"] == "sha256:" + "c" * 64
    assert revision["file_version_source_id"] == version.id.value
    assert revision["title"] == "Use Neo4j"
    assert "body" not in revision
    assert "text" not in revision


async def test_experiences_round_trip_with_their_sources_and_project(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id: SpaceId = await _default_space(env)
    first: Source = await _add_source(env, space_id)
    second: Source = await _add_source(
        env, space_id, kind=SourceKindEnum.AGENT_SESSION, locator="s-1"
    )
    project: Project = await _add_project(env, space_id)
    experience = Experience.create(
        id=env.persistence.ids.new_record_id(),
        space_id=space_id,
        project_id=project.id,
        subtype=ExperienceSubtypeEnum.FAILURE,
        body="The migration timed out.",
        occurred_at=NOW,
        session="s-1",
        environment="ci",
        actor=AGENT,
        source_ids=(second.id, first.id),
        now=NOW,
    )
    experience.collect_events()

    async with env.uow() as uow:
        await uow.experiences.add(experience)
        await uow.commit()
    async with env.uow() as uow:
        loaded: Experience | None = await uow.experiences.get(experience.id, space_id=space_id)

    assert loaded == experience
    assert query(
        neo4j_settings,
        "MATCH (:Experience {id: $id})-[:FROM_SOURCE]->(s) RETURN count(s) AS total",
        id=experience.id.value,
    ) == [{"total": 2}]


async def test_ledger_entries_round_trip_per_space_and_a_key_is_recorded_once(
    env: Neo4jKnowledgeEnv,
) -> None:
    space_id: SpaceId = await _default_space(env)
    other: SpaceId = await _add_space(env, "work")
    entry = LedgerEntry(
        space_id=space_id,
        key="k-1",
        command="capture_knowledge",
        fingerprint="sha256:" + "d" * 64,
        record_id=RecordId(value="01JD0000000000000000000000"),
        revision=1,
        extra={"project_id": None, "nested": {"a": [1, 2]}},
        recorded_at=NOW,
    )

    async with env.uow() as uow:
        await uow.ledger.record(entry)
        await uow.ledger.record(entry.model_copy(update={"space_id": other}))
        await uow.commit()
    async with env.uow() as uow:
        assert await uow.ledger.get(space_id, "k-1") == entry
        assert await uow.ledger.get(space_id, "unknown") is None
        with pytest.raises(EntryAlreadyExistsError):
            await uow.ledger.record(entry)


async def test_leaving_a_unit_of_work_without_commit_writes_nothing(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    before: dict[str, int] = node_counts(neo4j_settings)

    async with env.uow() as uow:
        await uow.spaces.add(
            KnowledgeSpace.create(
                id=env.persistence.ids.new_space_id(), key=Key(value="tmp"), name="t", now=NOW
            )
        )

    assert node_counts(neo4j_settings) == before


async def test_a_reference_to_another_space_is_rejected_by_the_adapter_and_nothing_is_written(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id: SpaceId = await _default_space(env)
    other: SpaceId = await _add_space(env, "work")
    foreign_source: Source = await _add_source(env, other)
    foreign_project: Project = await _add_project(env, other)
    knowledge: Knowledge = _graph_knowledge(env, space_id, foreign_source, foreign_project)
    before: dict[str, int] = node_counts(neo4j_settings)

    with pytest.raises(ReferenceNotInSpaceError) as raised:
        await _add(env, knowledge)

    assert raised.value.metadata["project_id"] == foreign_project.id.value
    assert raised.value.metadata["source_ids"] == [foreign_source.id.value]
    assert node_counts(neo4j_settings) == before


async def test_get_for_update_makes_a_second_locker_wait_and_then_read_the_new_head(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id: SpaceId = await _default_space(env)
    knowledge: Knowledge = _graph_knowledge(env, space_id, await _add_source(env, space_id))
    await _add(env, knowledge)
    other: Neo4jKnowledgeEnv = make_neo4j_env(neo4j_settings)
    try:
        async with env.uow() as holder:
            held: Knowledge | None = await holder.knowledge.get_for_update(
                knowledge.id, space_id=space_id
            )
            assert held is not None

            async def wait_and_read() -> Knowledge | None:
                async with other.uow() as waiter:
                    return await waiter.knowledge.get_for_update(knowledge.id, space_id=space_id)

            waiting: asyncio.Task[Knowledge | None] = asyncio.create_task(wait_and_read())
            await asyncio.sleep(BLOCKED_PROBE_SECONDS)
            assert not waiting.done()
            await holder.knowledge.append_revision(held, _next_revision(held, 2, "Second."))
            await holder.commit()

        seen: Knowledge | None = await asyncio.wait_for(waiting, timeout=10)
    finally:
        await other.client.close()

    assert seen is not None
    assert seen.head_number == 2
    assert (
        "_lock"
        not in query(neo4j_settings, "MATCH (k:Knowledge) RETURN keys(k) AS keys")[0]["keys"]
    )


async def test_appending_onto_a_stale_head_is_a_revision_conflict_with_the_actual_head(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id: SpaceId = await _default_space(env)
    knowledge: Knowledge = _graph_knowledge(env, space_id, await _add_source(env, space_id))
    await _add(env, knowledge)

    async with env.uow() as first:
        await first.knowledge.append_revision(knowledge, _next_revision(knowledge, 2, "First."))
        await first.commit()
    with pytest.raises(RevisionConflictError) as raised:
        async with env.uow() as second:
            await second.knowledge.append_revision(knowledge, _next_revision(knowledge, 2, "Late."))
            await second.commit()

    assert raised.value.error_code == "KNOWLEDGE_202_REVISION_CONFLICT"
    assert raised.value.metadata["expected_revision"] == 1
    assert raised.value.metadata["actual_revision"] == 2
    assert query(
        neo4j_settings,
        "MATCH (r:Revision {record_id: $id}) RETURN count(r) AS total",
        id=knowledge.id.value,
    ) == [{"total": 2}]


async def test_racing_appends_of_one_revision_number_collide_on_the_revision_key(
    env: Neo4jKnowledgeEnv, neo4j_settings: Neo4jConnectionSettings
) -> None:
    space_id: SpaceId = await _default_space(env)
    knowledge: Knowledge = _graph_knowledge(env, space_id, await _add_source(env, space_id))
    await _add(env, knowledge)
    other: Neo4jKnowledgeEnv = make_neo4j_env(neo4j_settings)
    try:
        async with env.uow() as winner:
            await winner.knowledge.append_revision(knowledge, _next_revision(knowledge, 2, "Win."))

            async def lose() -> None:
                async with other.uow() as loser:
                    await loser.knowledge.append_revision(
                        knowledge, _next_revision(knowledge, 2, "Lose.")
                    )
                    await loser.commit()

            losing: asyncio.Task[None] = asyncio.create_task(lose())
            await asyncio.sleep(BLOCKED_PROBE_SECONDS)
            assert not losing.done()
            await winner.commit()

        with pytest.raises(RevisionConflictError) as raised:
            await asyncio.wait_for(losing, timeout=10)
    finally:
        await other.client.close()

    assert raised.value.metadata["actual_revision"] == 2
