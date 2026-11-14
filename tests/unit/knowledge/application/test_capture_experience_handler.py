"""CaptureExperienceHandler (FR-007, FR-011, FR-012; AC-004/008/010)."""

import pytest
from tests.support.knowledge_commands import experience_command, racing_factory
from tests.support.knowledge_support import AGENT, NOW, KnowledgeEnv, make_env

from noesis.bounded_context.knowledge.application.dtos import CaptureResultDto
from noesis.bounded_context.knowledge.application.handlers.commands.capture_experience_handler import (
    CaptureExperienceHandler,
)
from noesis.bounded_context.knowledge.application.services.inputs import (
    ExistingSourceInput,
    ProjectRef,
)
from noesis.bounded_context.knowledge.domain.entities import Source
from noesis.bounded_context.knowledge.domain.value_objects import (
    ExperienceSubtypeEnum,
    Key,
    SourceKindEnum,
)
from noesis.exceptions import (
    ExperienceWithoutSourceError,
    IdempotencyKeyReusedError,
    InvalidRecordError,
    StoreNotInitialisedError,
)

pytestmark = pytest.mark.unit


async def test_capture_experience_records_write_once_entry_with_clock_defaults() -> None:
    env: KnowledgeEnv = await make_env()

    result: CaptureResultDto = await env.capture_experience.handle(
        experience_command(
            session="s-9",
            environment="ci",
            project=ProjectRef(key=Key(value="noesis")),
            subtype=ExperienceSubtypeEnum.OUTCOME,
        )
    )

    assert (result.record_type, result.revision, result.status, result.replayed) == (
        "experience",
        None,
        None,
        False,
    )
    stored = env.store.experiences[result.record_id]
    assert stored.subtype is ExperienceSubtypeEnum.OUTCOME
    assert stored.occurred_at == NOW
    assert (stored.session, stored.environment, stored.actor) == ("s-9", "ci", AGENT)
    assert result.project_id == stored.project_id.value  # type: ignore[union-attr]
    assert len(env.store.sources) == 1
    assert env.store.knowledge == {}


async def test_capture_experience_keeps_caller_occurred_at() -> None:
    env: KnowledgeEnv = await make_env()
    earlier = NOW.replace(year=2025)

    result = await env.capture_experience.handle(experience_command(occurred_at=earlier))

    assert env.store.experiences[result.record_id].occurred_at == earlier


async def test_capture_experience_without_source_fails_and_writes_nothing() -> None:
    env: KnowledgeEnv = await make_env()
    commits: int = env.store.commits

    with pytest.raises(ExperienceWithoutSourceError):
        await env.capture_experience.handle(experience_command(sources=()))

    assert env.store.experiences == {}
    assert env.store.ledger == {}
    assert env.store.commits == commits


async def test_capture_experience_blank_body_is_rejected() -> None:
    env: KnowledgeEnv = await make_env()

    with pytest.raises(InvalidRecordError):
        await env.capture_experience.handle(experience_command(body="  "))

    assert env.store.experiences == {}


async def test_experience_replay_returns_same_id_and_writes_nothing() -> None:
    env: KnowledgeEnv = await make_env()
    first = await env.capture_experience.handle(experience_command())
    commits: int = env.store.commits

    again = await env.capture_experience.handle(experience_command())

    assert again.record_id == first.record_id
    assert again.replayed is True
    assert len(env.store.experiences) == 1
    assert env.store.commits == commits


async def test_experience_same_key_different_request_is_rejected_before_ensure() -> None:
    env: KnowledgeEnv = await make_env()
    await env.capture_experience.handle(experience_command())
    sources = len(env.store.sources)

    with pytest.raises(IdempotencyKeyReusedError):
        await env.capture_experience.handle(
            experience_command(body="different", project=ProjectRef(key=Key(value="new")))
        )

    assert len(env.store.sources) == sources
    assert env.store.projects == {}


async def test_experience_on_uninitialised_store_fails_naming_step() -> None:
    env: KnowledgeEnv = await make_env(initialised=False)

    with pytest.raises(StoreNotInitialisedError) as error:
        await env.capture_experience.handle(experience_command())

    assert error.value.metadata == {"missing_steps": ["core"]}
    assert env.store.commits == 0


@pytest.mark.parametrize(
    ("secret", "sensitive"),
    [
        ("sk-abcdefghijklmnopqrstuv", "abcdefghijklmnopqrstuv"),
        ("ghp_abcdefghijklmnopqrstuvwxyz", "abcdefghijklmnopqrstuvwxyz"),
        ("token=abcdefgh12345678", "abcdefgh12345678"),
        ("Bearer abcdefghijklmnopqrstuvwxyz", "abcdefghijklmnopqrstuvwxyz"),
    ],
)
async def test_secrets_in_body_and_environment_are_redacted(secret: str, sensitive: str) -> None:
    """AC-010 for experiences: body and environment."""
    env: KnowledgeEnv = await make_env()

    result = await env.capture_experience.handle(
        experience_command(body=f"ran with {secret} ok", environment=f"env {secret}")
    )

    stored = env.store.experiences[result.record_id]
    assert stored.body.startswith("ran with ")
    assert stored.body.endswith(" ok")
    assert sensitive not in stored.body
    assert stored.environment is not None
    assert sensitive not in stored.environment
    assert "[REDACTED]" in stored.body
    assert "[REDACTED]" in stored.environment


async def test_racing_identical_experience_captures_yield_one_record() -> None:
    env: KnowledgeEnv = await make_env()
    source = Source.create(
        id=env.ids.new_record_id(),
        space_id=next(iter(env.store.spaces.values())).id,
        kind=SourceKindEnum.URL,
        locator="https://x",
        now=NOW,
    )
    env.store.sources[source.id.value] = source
    command = experience_command(sources=(ExistingSourceInput(source_id=source.id),))
    competitor: list[CaptureResultDto] = []

    async def compete() -> None:
        competitor.append(await env.capture_experience.handle(command))

    loser = CaptureExperienceHandler(
        uow_factory=racing_factory(env.store, compete),
        clock=env.clock,
        ids=env.ids,
        schema=env.schema,
    )

    result = await loser.handle(command)

    assert len(env.store.experiences) == 1
    assert result.record_id == competitor[0].record_id
    assert result.replayed is True


async def test_racing_source_creation_reuses_the_winning_source() -> None:
    """Two captures citing the same new source: one source row, both records cite it."""
    env: KnowledgeEnv = await make_env()

    async def compete() -> None:
        await env.capture_experience.handle(experience_command("other"))

    loser = CaptureExperienceHandler(
        uow_factory=racing_factory(env.store, compete),
        clock=env.clock,
        ids=env.ids,
        schema=env.schema,
    )

    result = await loser.handle(experience_command("mine"))

    assert len(env.store.sources) == 1
    assert len(env.store.experiences) == 2
    only = next(iter(env.store.sources.values()))
    assert env.store.experiences[result.record_id].source_ids == (only.id,)


async def test_capture_experience_redacts_a_secret_in_the_session() -> None:
    env: KnowledgeEnv = await make_env()

    result: CaptureResultDto = await env.capture_experience.handle(
        experience_command(session="token=abcdefgh12345678")
    )

    assert env.store.experiences[result.record_id].session == "token=[REDACTED]"
