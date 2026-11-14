"""GetRecordHandler (FR-003, FR-010; AC-006, AC-021)."""

import pytest
from tests.support.knowledge_commands import experience_command, knowledge_command, revise_command
from tests.support.knowledge_support import DEFAULT_SPACE_KEY, NOW, KnowledgeEnv, make_env

from noesis.bounded_context.knowledge.application.dtos import RecordDto
from noesis.bounded_context.knowledge.application.handlers.queries.get_record_handler import (
    GetRecordQuery,
)
from noesis.bounded_context.knowledge.domain.entities import KnowledgeSpace
from noesis.bounded_context.knowledge.domain.value_objects import Key, RecordId
from noesis.exceptions import RecordNotFoundError, SpaceNotFoundError, StoreNotInitialisedError

pytestmark = pytest.mark.unit


def query(record_id: str, revision: int | None = None, space: Key = DEFAULT_SPACE_KEY):
    return GetRecordQuery(space_key=space, record_id=RecordId(value=record_id), revision=revision)


async def test_get_returns_head_as_dto_by_default() -> None:
    env: KnowledgeEnv = await make_env()
    captured = await env.capture_knowledge.handle(knowledge_command())
    await env.revise_knowledge.handle(revise_command(RecordId(value=captured.record_id)))

    record: RecordDto = await env.get_record.handle(query(captured.record_id))

    assert isinstance(record, RecordDto)
    assert (record.type, record.status, record.head_revision) == ("knowledge", "proposed", 2)
    assert record.revision is not None
    assert record.revision.number == 2
    assert record.revision.body == "Use retries with jitter."


async def test_get_at_revision_returns_that_revisions_content_and_sources() -> None:
    env: KnowledgeEnv = await make_env()
    captured = await env.capture_knowledge.handle(knowledge_command())
    await env.revise_knowledge.handle(revise_command(RecordId(value=captured.record_id)))

    record = await env.get_record.handle(query(captured.record_id, revision=1))

    assert record.revision is not None
    assert (record.revision.number, record.revision.body) == (1, "Use retries.")
    assert record.head_revision == 2
    assert record.sources == record.revision.sources
    assert len(record.sources) == 1


async def test_get_unknown_revision_is_not_found() -> None:
    env: KnowledgeEnv = await make_env()
    captured = await env.capture_knowledge.handle(knowledge_command())

    for number in (0, 2, 99):
        with pytest.raises(RecordNotFoundError) as error:
            await env.get_record.handle(query(captured.record_id, revision=number))
        assert error.value.metadata["revision"] == number


async def test_get_unknown_id_is_not_found() -> None:
    env: KnowledgeEnv = await make_env()

    with pytest.raises(RecordNotFoundError) as error:
        await env.get_record.handle(query("1" * 26))

    assert error.value.error_code == "KNOWLEDGE_201_RECORD_NOT_FOUND"
    assert error.value.next_steps


async def test_get_record_of_another_space_is_not_found() -> None:
    """AC-006."""
    env: KnowledgeEnv = await make_env()
    captured = await env.capture_knowledge.handle(knowledge_command())
    other = KnowledgeSpace.create(
        id=env.ids.new_space_id(), key=Key(value="other"), name="other", now=NOW
    )
    env.store.spaces[other.id.value] = other

    with pytest.raises(RecordNotFoundError):
        await env.get_record.handle(query(captured.record_id, space=Key(value="other")))
    with pytest.raises(RecordNotFoundError):
        await env.get_record.handle(query(captured.record_id, revision=1, space=Key(value="other")))
    assert (await env.get_record.handle(query(captured.record_id))).id == captured.record_id


async def test_get_unknown_space_is_space_not_found() -> None:
    env: KnowledgeEnv = await make_env()
    captured = await env.capture_knowledge.handle(knowledge_command())

    with pytest.raises(SpaceNotFoundError):
        await env.get_record.handle(query(captured.record_id, space=Key(value="ghost")))


async def test_get_reads_experience_project_and_source_records() -> None:
    env: KnowledgeEnv = await make_env()
    knowledge = await env.capture_knowledge.handle(knowledge_command())
    experience = await env.capture_experience.handle(experience_command())

    exp_record = await env.get_record.handle(query(experience.record_id))
    project_record = await env.get_record.handle(query(knowledge.project_id or ""))
    source_id = next(iter(env.store.sources))
    source_record = await env.get_record.handle(query(source_id))

    assert (exp_record.type, exp_record.body) == ("experience", "deploy failed")
    assert exp_record.status is None
    assert (project_record.type, project_record.key) == ("project", "noesis")
    assert (source_record.type, source_record.source_kind) == ("source", "commit")


async def test_get_on_uninitialised_store_names_missing_step() -> None:
    """AC-011/AC-021 at unit level."""
    env: KnowledgeEnv = await make_env(initialised=False)

    with pytest.raises(StoreNotInitialisedError) as error:
        await env.get_record.handle(query("1" * 26))

    assert error.value.error_code == "KNOWLEDGE_204_STORE_NOT_INITIALISED"
    assert error.value.metadata == {"missing_steps": ["core"]}
    assert error.value.next_steps
