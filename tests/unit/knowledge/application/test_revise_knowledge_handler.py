"""ReviseKnowledgeHandler (FR-006, FR-011; AC-007, A-12, A-13)."""

import pytest
from tests.support.knowledge_commands import (
    experience_command,
    knowledge_command,
    racing_factory,
    revise_command,
)
from tests.support.knowledge_support import AGENT, NOW, KnowledgeEnv, make_env

from noesis.bounded_context.knowledge.application.dtos import ReviseResultDto
from noesis.bounded_context.knowledge.application.handlers.commands.revise_knowledge_handler import (
    ReviseKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.services.inputs import (
    ExistingSourceInput,
    NewSourceInput,
)
from noesis.bounded_context.knowledge.domain.entities import Knowledge, KnowledgeSpace, Source
from noesis.bounded_context.knowledge.domain.value_objects import (
    Applicability,
    ContentHash,
    FileContent,
    Key,
    OwnershipEnum,
    RecordId,
    RecordStatusEnum,
    Slug,
    SourceKindEnum,
)
from noesis.exceptions import (
    IdempotencyKeyReusedError,
    InvalidRecordError,
    KnowledgeNotRevisableError,
    RecordNotFoundError,
    RecordNotRevisableError,
    ReferenceNotInSpaceError,
    RevisionConflictError,
    SpaceNotFoundError,
    StoreNotInitialisedError,
)

pytestmark = pytest.mark.unit


async def captured(env: KnowledgeEnv) -> RecordId:
    result = await env.capture_knowledge.handle(knowledge_command())
    return RecordId(value=result.record_id)


async def test_revise_appends_revision_two_and_keeps_head_text_not_given() -> None:
    env: KnowledgeEnv = await make_env()
    record_id = await captured(env)
    env.clock.advance(60)

    result: ReviseResultDto = await env.revise_knowledge.handle(revise_command(record_id))

    assert isinstance(result, ReviseResultDto)
    assert (result.revision, result.status, result.replayed) == (2, "proposed", False)
    stored: Knowledge = env.store.knowledge[record_id.value]
    assert stored.head_number == 2
    assert stored.head.content.body == "Use retries with jitter."  # type: ignore[union-attr]
    assert stored.head.content.title == "Retry policy"  # type: ignore[union-attr]
    assert stored.head.created_at == env.clock.now()
    assert [r.number for r in env.store.revisions[record_id.value]] == [1, 2]
    original_sources = env.store.revisions[record_id.value][0].source_ids
    assert stored.head.source_ids == original_sources
    ledger = env.store.ledger[(stored.space_id.value, "r1")]
    assert (ledger.command, ledger.revision) == ("revise_knowledge", 2)


async def test_revise_with_new_title_and_sources_replaces_them() -> None:
    env: KnowledgeEnv = await make_env()
    record_id = await captured(env)

    await env.revise_knowledge.handle(
        revise_command(
            record_id,
            body=None,
            title="New title",
            sources=(NewSourceInput(kind=SourceKindEnum.URL, locator="https://y"),),
        )
    )

    head = env.store.knowledge[record_id.value].head
    assert head.content.title == "New title"  # type: ignore[union-attr]
    assert head.content.body == "Use retries."  # type: ignore[union-attr]
    assert len(head.source_ids) == 1
    assert env.store.sources[head.source_ids[0].value].locator == "https://y"


async def test_revise_requires_title_or_body() -> None:
    env: KnowledgeEnv = await make_env()
    record_id = await captured(env)

    with pytest.raises(InvalidRecordError, match="new title or a new body"):
        await env.revise_knowledge.handle(revise_command(record_id, body=None))

    assert env.store.knowledge[record_id.value].head_number == 1


async def test_revise_redacts_secrets() -> None:
    env: KnowledgeEnv = await make_env()
    record_id = await captured(env)

    await env.revise_knowledge.handle(
        revise_command(
            record_id, title="t sk-abcdefghijklmnopqrstuv", body="password = hunter2hunter2"
        )
    )

    content = env.store.knowledge[record_id.value].head.content
    assert "abcdefghijklmnopqrstuv" not in content.title  # type: ignore[union-attr]
    assert "hunter2hunter2" not in content.body  # type: ignore[union-attr]


async def test_revise_stale_expected_revision_conflicts_with_metadata_and_adds_nothing() -> None:
    env: KnowledgeEnv = await make_env()
    record_id = await captured(env)
    await env.revise_knowledge.handle(revise_command(record_id, "r1", expected=1))
    ledger_size = len(env.store.ledger)

    with pytest.raises(RevisionConflictError) as error:
        await env.revise_knowledge.handle(revise_command(record_id, "r2", expected=1))

    assert error.value.error_code == "KNOWLEDGE_202_REVISION_CONFLICT"
    assert error.value.metadata == {
        "record_id": record_id.value,
        "expected_revision": 1,
        "actual_revision": 2,
    }
    assert error.value.next_steps
    assert len(env.store.revisions[record_id.value]) == 2
    assert len(env.store.ledger) == ledger_size


@pytest.mark.parametrize(
    "status", [RecordStatusEnum.ACCEPTED, RecordStatusEnum.SUPERSEDED, RecordStatusEnum.RETRACTED]
)
async def test_revise_non_proposed_fails_typed_and_adds_no_revision(
    status: RecordStatusEnum,
) -> None:
    """AC-007, with a stale expected revision to prove status is checked first."""
    env: KnowledgeEnv = await make_env()
    record_id = await captured(env)
    env.store.knowledge[record_id.value].status = status

    with pytest.raises(KnowledgeNotRevisableError) as error:
        await env.revise_knowledge.handle(revise_command(record_id, expected=5))

    assert error.value.error_code == "KNOWLEDGE_005_KNOWLEDGE_NOT_REVISABLE"
    assert len(env.store.revisions[record_id.value]) == 1
    assert (env.store.knowledge[record_id.value].space_id.value, "r1") not in env.store.ledger


async def test_revise_unknown_id_is_not_found() -> None:
    env: KnowledgeEnv = await make_env()

    with pytest.raises(RecordNotFoundError) as error:
        await env.revise_knowledge.handle(revise_command(RecordId(value="1" * 26)))

    assert error.value.error_code == "KNOWLEDGE_201_RECORD_NOT_FOUND"


async def test_revise_experience_id_is_not_revisable() -> None:
    env: KnowledgeEnv = await make_env()
    experience = await env.capture_experience.handle(experience_command())

    with pytest.raises(RecordNotRevisableError) as error:
        await env.revise_knowledge.handle(revise_command(RecordId(value=experience.record_id)))

    assert error.value.error_code == "KNOWLEDGE_207_RECORD_NOT_REVISABLE"
    assert error.value.metadata["type"] == "experience"
    assert error.value.next_steps


async def test_revise_record_of_another_space_is_not_found() -> None:
    env: KnowledgeEnv = await make_env()
    record_id = await captured(env)
    other = KnowledgeSpace.create(
        id=env.ids.new_space_id(), key=Key(value="other"), name="other", now=NOW
    )
    env.store.spaces[other.id.value] = other

    with pytest.raises(RecordNotFoundError):
        await env.revise_knowledge.handle(revise_command(record_id, space_key=Key(value="other")))

    assert env.store.knowledge[record_id.value].head_number == 1


async def test_revise_unknown_space_fails() -> None:
    env: KnowledgeEnv = await make_env()
    record_id = await captured(env)

    with pytest.raises(SpaceNotFoundError):
        await env.revise_knowledge.handle(revise_command(record_id, space_key=Key(value="x")))


async def test_revise_file_owned_knowledge_is_rejected_and_adds_nothing() -> None:
    """A-12: file-owned text is revised by registering a new file version, not here."""
    env: KnowledgeEnv = await make_env()
    space_id = next(iter(env.store.spaces.values())).id
    version = Source.create(
        id=env.ids.new_record_id(),
        space_id=space_id,
        kind=SourceKindEnum.FILE_VERSION,
        locator="vault://v/a.md",
        digest=ContentHash.of(b"a"),
        now=NOW,
    )
    env.store.sources[version.id.value] = version
    file_knowledge = Knowledge.create(
        id=env.ids.new_record_id(),
        space_id=space_id,
        ownership=OwnershipEnum.FILE,
        subtype=Slug(value="decision"),
        applicability=Applicability(),
        actor=AGENT,
        source_ids=(version.id,),
        content=FileContent(
            content_hash=ContentHash.of(b"a"), file_version_source_id=version.id, title="A"
        ),
        now=NOW,
    )
    env.store.knowledge[file_knowledge.id.value] = file_knowledge
    env.store.revisions[file_knowledge.id.value] = [file_knowledge.head]

    with pytest.raises(InvalidRecordError, match="File-owned"):
        await env.revise_knowledge.handle(revise_command(file_knowledge.id))

    assert len(env.store.revisions[file_knowledge.id.value]) == 1
    assert env.store.ledger == {}


async def test_revise_replay_returns_same_result_and_writes_nothing() -> None:
    env: KnowledgeEnv = await make_env()
    record_id = await captured(env)
    first = await env.revise_knowledge.handle(revise_command(record_id))
    commits = env.store.commits

    again = await env.revise_knowledge.handle(revise_command(record_id))

    assert (again.record_id, again.revision, again.replayed) == (record_id.value, 2, True)
    assert first.replayed is False
    assert env.store.commits == commits
    assert len(env.store.revisions[record_id.value]) == 2


async def test_revise_same_key_different_request_is_rejected() -> None:
    env: KnowledgeEnv = await make_env()
    record_id = await captured(env)
    await env.revise_knowledge.handle(revise_command(record_id))

    with pytest.raises(IdempotencyKeyReusedError):
        await env.revise_knowledge.handle(revise_command(record_id, body="other body"))

    assert len(env.store.revisions[record_id.value]) == 2


async def test_revise_same_key_reused_by_capture_is_rejected_before_ensure() -> None:
    env: KnowledgeEnv = await make_env()
    record_id = await captured(env)
    sources = len(env.store.sources)

    with pytest.raises(IdempotencyKeyReusedError):
        await env.revise_knowledge.handle(
            revise_command(
                record_id,
                "k1",
                sources=(NewSourceInput(kind=SourceKindEnum.URL, locator="https://z"),),
            )
        )

    assert len(env.store.sources) == sources


async def test_racing_identical_revises_yield_one_revision_and_same_result() -> None:
    env: KnowledgeEnv = await make_env()
    record_id = await captured(env)
    command = revise_command(record_id)
    competitor: list[ReviseResultDto] = []

    async def compete() -> None:
        competitor.append(await env.revise_knowledge.handle(command))

    loser = ReviseKnowledgeHandler(
        uow_factory=racing_factory(env.store, compete),
        clock=env.clock,
        ids=env.ids,
        schema=env.schema,
    )

    result = await loser.handle(command)

    assert len(env.store.revisions[record_id.value]) == 2
    assert (result.revision, result.replayed) == (2, True)
    assert competitor[0].replayed is False


async def test_racing_different_revises_on_same_head_conflict() -> None:
    """A-13: the second writer to the same head loses with a revision conflict."""
    env: KnowledgeEnv = await make_env()
    record_id = await captured(env)

    async def compete() -> None:
        await env.revise_knowledge.handle(revise_command(record_id, "winner", body="winner text"))

    loser = ReviseKnowledgeHandler(
        uow_factory=racing_factory(env.store, compete),
        clock=env.clock,
        ids=env.ids,
        schema=env.schema,
    )

    with pytest.raises(RevisionConflictError) as error:
        await loser.handle(revise_command(record_id, "loser", body="loser text"))

    assert error.value.metadata["actual_revision"] == 2
    assert env.store.knowledge[record_id.value].head.content.body == "winner text"  # type: ignore[union-attr]
    assert len(env.store.revisions[record_id.value]) == 2


async def test_revise_citing_foreign_existing_source_is_rejected() -> None:
    env: KnowledgeEnv = await make_env()
    record_id = await captured(env)

    with pytest.raises(ReferenceNotInSpaceError):
        await env.revise_knowledge.handle(
            revise_command(
                record_id, sources=(ExistingSourceInput(source_id=RecordId(value="2" * 26)),)
            )
        )

    assert len(env.store.revisions[record_id.value]) == 1


async def test_revise_on_uninitialised_store_names_missing_step() -> None:
    env: KnowledgeEnv = await make_env(initialised=False)

    with pytest.raises(StoreNotInitialisedError) as error:
        await env.revise_knowledge.handle(revise_command(RecordId(value="1" * 26)))

    assert error.value.metadata == {"missing_steps": ["core"]}
    assert env.store.commits == 0
