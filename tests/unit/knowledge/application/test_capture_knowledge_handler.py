"""CaptureKnowledgeHandler (flow 1: FR-003/004, FR-011, FR-012, FR-019; AC-004/005/006/010/021)."""

import pytest
from tests.support.knowledge_commands import (
    COMMIT,
    experience_command,
    knowledge_command,
    racing_factory,
)
from tests.support.knowledge_support import (
    DEFAULT_SPACE_KEY,
    NOW,
    KnowledgeEnv,
    make_env,
)

from noesis.bounded_context.knowledge.application.dtos import CaptureResultDto, RecordDto
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeCommand,
    CaptureKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.get_record_handler import (
    GetRecordQuery,
)
from noesis.bounded_context.knowledge.application.services.inputs import (
    ExistingSourceInput,
    NewSourceInput,
    ProjectRef,
)
from noesis.bounded_context.knowledge.domain.entities import Knowledge, KnowledgeSpace, Source
from noesis.bounded_context.knowledge.domain.value_objects import (
    Key,
    OwnershipEnum,
    RecordId,
    RecordStatusEnum,
    SourceKindEnum,
    SpaceId,
    Tag,
)
from noesis.exceptions import (
    IdempotencyKeyReusedError,
    InvalidRecordError,
    ReferenceNotInSpaceError,
    SpaceNotFoundError,
    StoreNotInitialisedError,
)

pytestmark = pytest.mark.unit


def store_snapshot(env: KnowledgeEnv) -> tuple[int, int, int, int, int, int]:
    s = env.store
    return (
        len(s.projects),
        len(s.sources),
        len(s.knowledge),
        len(s.experiences),
        len(s.ledger),
        s.commits,
    )


def add_source(env: KnowledgeEnv, space_key: Key = DEFAULT_SPACE_KEY) -> Source:
    space: SpaceId = next(s.id for s in env.store.spaces.values() if s.key == space_key)
    source: Source = Source.create(
        id=env.ids.new_record_id(),
        space_id=space,
        kind=SourceKindEnum.URL,
        locator="https://example.test/doc",
        now=NOW,
    )
    env.store.sources[source.id.value] = source
    return source


def add_space(env: KnowledgeEnv, key: str) -> KnowledgeSpace:
    space: KnowledgeSpace = KnowledgeSpace.create(
        id=env.ids.new_space_id(), key=Key(value=key), name=key, now=NOW
    )
    env.store.spaces[space.id.value] = space
    return space


async def test_capture_creates_proposed_graph_knowledge_with_project_sources_and_ledger() -> None:
    env: KnowledgeEnv = await make_env()

    result: CaptureResultDto = await env.capture_knowledge.handle(
        knowledge_command(project=ProjectRef(key=Key(value="noesis"), name="Noesis"))
    )

    assert isinstance(result, CaptureResultDto)
    assert (result.record_type, result.revision, result.status, result.replayed) == (
        "knowledge",
        1,
        "proposed",
        False,
    )
    stored: Knowledge = env.store.knowledge[result.record_id]
    assert stored.ownership is OwnershipEnum.GRAPH
    assert stored.status is RecordStatusEnum.PROPOSED
    assert stored.head.content.title == "Retry policy"  # type: ignore[union-attr]
    project = next(iter(env.store.projects.values()))
    assert (project.key.value, project.name) == ("noesis", "Noesis")
    assert result.project_id == project.id.value == stored.applicability.project_id.value  # type: ignore[union-attr]
    assert len(env.store.sources) == 1
    assert stored.head.source_ids == (next(iter(env.store.sources.values())).id,)
    ledger = env.store.ledger[(stored.space_id.value, "k1")]
    assert (ledger.command, ledger.record_id, ledger.revision) == (
        "capture_knowledge",
        stored.id,
        1,
    )


async def test_capture_without_project_is_space_wide_and_creates_no_project() -> None:
    env: KnowledgeEnv = await make_env()

    result = await env.capture_knowledge.handle(knowledge_command(project=None))

    assert result.project_id is None
    assert env.store.knowledge[result.record_id].applicability.project_id is None
    assert env.store.projects == {}


async def test_capture_reuses_existing_project_by_key() -> None:
    env: KnowledgeEnv = await make_env()

    first = await env.capture_knowledge.handle(knowledge_command("k1"))
    second = await env.capture_knowledge.handle(knowledge_command("k2", body="Other"))

    assert first.project_id == second.project_id
    assert len(env.store.projects) == 1
    assert len(env.store.sources) == 1  # same commit natural key


async def test_capture_sorts_and_dedupes_tags() -> None:
    env: KnowledgeEnv = await make_env()
    command = CaptureKnowledgeCommand(
        **{
            **knowledge_command().model_dump(),
            "tags": (Tag(value="b"), Tag(value="a"), Tag(value="b")),
        }
    )

    result = await env.capture_knowledge.handle(command)

    tags = env.store.knowledge[result.record_id].applicability.sorted_tags
    assert [t.value for t in tags] == ["a", "b"]


async def test_capture_accepts_existing_source_id_without_creating_sources() -> None:
    env: KnowledgeEnv = await make_env()
    source: Source = add_source(env)

    result = await env.capture_knowledge.handle(
        knowledge_command(sources=(ExistingSourceInput(source_id=source.id),))
    )

    assert env.store.knowledge[result.record_id].head.source_ids == (source.id,)
    assert len(env.store.sources) == 1


async def test_capture_dedupes_repeated_sources_in_order() -> None:
    env: KnowledgeEnv = await make_env()
    other = NewSourceInput(kind=SourceKindEnum.URL, locator="https://x")

    result = await env.capture_knowledge.handle(knowledge_command(sources=(COMMIT, other, COMMIT)))

    assert len(env.store.knowledge[result.record_id].head.source_ids) == 2


async def test_source_observed_time_comes_from_clock_not_caller() -> None:
    """A-9: Knowledge's clock sets `observed_at`; the caller cannot supply it."""
    env: KnowledgeEnv = await make_env()
    env.clock.advance(3600)

    await env.capture_knowledge.handle(knowledge_command())

    source = next(iter(env.store.sources.values()))
    assert source.observed_at == env.clock.now()
    assert "observed_at" not in NewSourceInput.model_fields
    assert "observed_at" not in ExistingSourceInput.model_fields
    knowledge = next(iter(env.store.knowledge.values()))
    assert knowledge.created_at == knowledge.head.created_at == env.clock.now()


async def test_replay_same_key_and_request_returns_same_id_and_writes_nothing() -> None:
    """AC-004."""
    env: KnowledgeEnv = await make_env()
    first = await env.capture_knowledge.handle(knowledge_command())
    before = store_snapshot(env)

    again = await env.capture_knowledge.handle(knowledge_command())

    assert again.record_id == first.record_id
    assert again.replayed is True
    assert first.replayed is False
    assert again.project_id == first.project_id
    assert store_snapshot(env) == before


async def test_same_key_different_request_is_rejected_before_any_ensure() -> None:
    """AC-004 / A-13: KNOWLEDGE_203 happens before a project or source is created."""
    env: KnowledgeEnv = await make_env()
    await env.capture_knowledge.handle(knowledge_command(project=None))
    before = store_snapshot(env)
    different = knowledge_command(
        body="Different",
        project=ProjectRef(key=Key(value="brand-new")),
        sources=(NewSourceInput(kind=SourceKindEnum.URL, locator="https://new"),),
    )

    with pytest.raises(IdempotencyKeyReusedError) as error:
        await env.capture_knowledge.handle(different)

    assert error.value.error_code == "KNOWLEDGE_203_IDEMPOTENCY_KEY_REUSED"
    assert error.value.next_steps
    assert store_snapshot(env) == before
    assert "brand-new" not in {p.key.value for p in env.store.projects.values()}


async def test_same_key_used_by_another_command_is_rejected() -> None:
    env: KnowledgeEnv = await make_env()
    await env.capture_knowledge.handle(knowledge_command("shared"))

    with pytest.raises(IdempotencyKeyReusedError):
        await env.capture_experience.handle(experience_command("shared"))


async def test_idempotency_keys_are_scoped_per_space() -> None:
    env: KnowledgeEnv = await make_env()
    add_space(env, "other")

    a = await env.capture_knowledge.handle(knowledge_command("k"))
    b = await env.capture_knowledge.handle(knowledge_command("k", space_key=Key(value="other")))

    assert a.record_id != b.record_id
    assert a.space_id != b.space_id
    assert not b.replayed


async def test_racing_first_captures_yield_one_record_and_same_id() -> None:
    """AC-005 at unit level: the competitor commits between our read and our write."""
    env: KnowledgeEnv = await make_env()
    source = add_source(env)
    command = knowledge_command(project=None, sources=(ExistingSourceInput(source_id=source.id),))
    competitor: list[CaptureResultDto] = []

    async def compete() -> None:
        competitor.append(await env.capture_knowledge.handle(command))

    loser = CaptureKnowledgeHandler(
        uow_factory=racing_factory(env.store, compete),
        clock=env.clock,
        ids=env.ids,
        schema=env.schema,
    )

    result: CaptureResultDto = await loser.handle(command)

    assert len(env.store.knowledge) == 1
    assert len(env.store.ledger) == 1
    assert result.record_id == competitor[0].record_id
    assert result.replayed is True
    assert competitor[0].replayed is False


async def test_racing_capture_with_different_request_same_key_is_rejected() -> None:
    env: KnowledgeEnv = await make_env()
    source = add_source(env)
    sources = (ExistingSourceInput(source_id=source.id),)
    winner_command = knowledge_command(project=None, sources=sources, body="winner")

    async def compete() -> None:
        await env.capture_knowledge.handle(winner_command)

    loser = CaptureKnowledgeHandler(
        uow_factory=racing_factory(env.store, compete),
        clock=env.clock,
        ids=env.ids,
        schema=env.schema,
    )

    with pytest.raises(IdempotencyKeyReusedError):
        await loser.handle(knowledge_command(project=None, sources=sources, body="loser"))
    assert len(env.store.knowledge) == 1


async def test_racing_project_creation_reuses_the_winner() -> None:
    env: KnowledgeEnv = await make_env()
    other = knowledge_command("k-other", body="other")

    async def compete() -> None:
        await env.capture_knowledge.handle(other)

    loser = CaptureKnowledgeHandler(
        uow_factory=racing_factory(env.store, compete),
        clock=env.clock,
        ids=env.ids,
        schema=env.schema,
    )

    result = await loser.handle(knowledge_command("k-mine"))

    assert len(env.store.projects) == 1
    assert len(env.store.knowledge) == 2
    assert result.project_id == next(iter(env.store.projects))


async def test_capture_without_sources_is_rejected_and_writes_nothing() -> None:
    env: KnowledgeEnv = await make_env()
    before = store_snapshot(env)

    with pytest.raises(InvalidRecordError, match="at least one source"):
        await env.capture_knowledge.handle(knowledge_command(sources=()))

    assert store_snapshot(env) == before


@pytest.mark.parametrize("field", ["title", "body"])
async def test_capture_blank_text_is_rejected(field: str) -> None:
    env: KnowledgeEnv = await make_env()

    with pytest.raises(InvalidRecordError):
        await env.capture_knowledge.handle(knowledge_command(**{field: "  "}))  # type: ignore[arg-type]

    assert env.store.knowledge == {}


async def test_capture_unknown_space_is_not_found() -> None:
    env: KnowledgeEnv = await make_env()

    with pytest.raises(SpaceNotFoundError) as error:
        await env.capture_knowledge.handle(knowledge_command(space_key=Key(value="nope")))

    assert error.value.error_code == "KNOWLEDGE_208_SPACE_NOT_FOUND"


async def test_capture_citing_source_of_another_space_is_rejected_and_writes_nothing() -> None:
    """D-006 / KNOWLEDGE_205."""
    env: KnowledgeEnv = await make_env()
    other = add_space(env, "other")
    foreign: Source = add_source(env)
    foreign_in_other = Source.create(
        id=env.ids.new_record_id(),
        space_id=other.id,
        kind=SourceKindEnum.URL,
        locator="https://other",
        now=NOW,
    )
    env.store.sources[foreign_in_other.id.value] = foreign_in_other
    before = store_snapshot(env)

    with pytest.raises(ReferenceNotInSpaceError) as error:
        await env.capture_knowledge.handle(
            knowledge_command(
                project=None, sources=(ExistingSourceInput(source_id=foreign_in_other.id),)
            )
        )

    assert error.value.error_code == "KNOWLEDGE_205_REFERENCE_NOT_IN_SPACE"
    assert error.value.metadata["source_id"] == foreign_in_other.id.value
    assert foreign.id != foreign_in_other.id
    assert store_snapshot(env) == before


async def test_capture_unknown_existing_source_id_is_rejected() -> None:
    env: KnowledgeEnv = await make_env()

    with pytest.raises(ReferenceNotInSpaceError):
        await env.capture_knowledge.handle(
            knowledge_command(sources=(ExistingSourceInput(source_id=RecordId(value="0" * 26)),))
        )

    assert env.store.knowledge == {}


async def test_same_project_key_in_two_spaces_yields_distinct_projects() -> None:
    env: KnowledgeEnv = await make_env()
    add_space(env, "other")

    a = await env.capture_knowledge.handle(knowledge_command("a"))
    b = await env.capture_knowledge.handle(knowledge_command("b", space_key=Key(value="other")))

    assert a.project_id != b.project_id
    assert len(env.store.projects) == 2


async def test_store_not_initialised_names_missing_steps_and_writes_nothing() -> None:
    """AC-021 at unit level, with two required steps unapplied."""
    env: KnowledgeEnv = await make_env(initialised=False)

    with pytest.raises(StoreNotInitialisedError) as error:
        await env.capture_knowledge.handle(knowledge_command())

    assert error.value.error_code == "KNOWLEDGE_204_STORE_NOT_INITIALISED"
    assert error.value.metadata == {"missing_steps": ["core"]}
    assert "core" in error.value.message
    assert any("store init" in step for step in error.value.next_steps)
    assert store_snapshot(env) == (0, 0, 0, 0, 0, 0)
    assert env.store.spaces == {}


@pytest.mark.parametrize(
    ("secret", "sensitive"),
    [
        ("sk-abcdefghijklmnopqrstuv", "abcdefghijklmnopqrstuv"),
        ("ghp_abcdefghijklmnopqrstuvwxyz", "abcdefghijklmnopqrstuvwxyz"),
        ("AKIAABCDEFGHIJKLMNOP", "AKIAABCDEFGHIJKLMNOP"),
        ("xoxb-1234567890-abcdef", "1234567890"),
        ("AIza" + "a" * 35, "a" * 35),
        ("Bearer abcdefghijklmnopqrstuvwxyz", "abcdefghijklmnopqrstuvwxyz"),
        ("password = hunter2hunter2", "hunter2hunter2"),
        ("api_key: abcdefgh12345678", "abcdefgh12345678"),
        ("-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----", "MIIabc"),
    ],
)
async def test_secrets_in_title_and_body_are_redacted_before_storage(
    secret: str, sensitive: str
) -> None:
    """AC-010."""
    env: KnowledgeEnv = await make_env()

    result = await env.capture_knowledge.handle(
        knowledge_command(title=f"Leak {secret} here", body=f"first\n{secret}\nlast")
    )

    content = env.store.knowledge[result.record_id].head.content
    for text in (content.title, content.body):  # type: ignore[union-attr]
        assert "[REDACTED]" in text
        assert sensitive not in text
    assert content.body.startswith("first")  # type: ignore[union-attr]
    assert content.body.endswith("last")  # type: ignore[union-attr]


async def test_capture_result_is_readable_through_get_record_as_dto() -> None:
    env: KnowledgeEnv = await make_env()
    result = await env.capture_knowledge.handle(knowledge_command())

    record = await env.get_record.handle(
        GetRecordQuery(space_key=DEFAULT_SPACE_KEY, record_id=RecordId(value=result.record_id))
    )

    assert isinstance(record, RecordDto)
    assert record.head_revision == 1


_SECRET_URL: NewSourceInput = NewSourceInput(
    kind=SourceKindEnum.URL, locator="https://example.test/doc?api_key=abcdefgh12345678&page=2"
)


async def test_new_source_locator_with_a_secret_query_param_is_stored_redacted() -> None:
    env: KnowledgeEnv = await make_env()

    await env.capture_knowledge.handle(knowledge_command(sources=(_SECRET_URL,)))

    locators: list[str] = [source.locator for source in env.store.sources.values()]
    assert locators == [
        "https://example.test/doc?api_key=[REDACTED]"
    ]  # the mask runs to the next separator
    assert "abcdefgh12345678" not in locators[0]


async def test_repeated_capture_with_a_secret_locator_reuses_the_redacted_source() -> None:
    env: KnowledgeEnv = await make_env()

    await env.capture_knowledge.handle(knowledge_command("k1", sources=(_SECRET_URL,)))
    await env.capture_knowledge.handle(
        knowledge_command("k2", title="Other", sources=(_SECRET_URL,))
    )

    assert len(env.store.sources) == 1
