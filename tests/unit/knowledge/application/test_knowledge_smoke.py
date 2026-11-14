"""Smoke tests of the Knowledge handlers over the in-memory fakes."""

import pytest
from tests.support.knowledge_support import AGENT, DEFAULT_SPACE_KEY, KnowledgeEnv, make_env

from noesis.bounded_context.knowledge.application.dtos import CaptureResultDto, RecordDto
from noesis.bounded_context.knowledge.application.handlers.commands.capture_experience_handler import (
    CaptureExperienceCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.revise_knowledge_handler import (
    ReviseKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.handlers.queries.get_record_handler import (
    GetRecordQuery,
)
from noesis.bounded_context.knowledge.application.services.inputs import (
    NewSourceInput,
    ProjectRef,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    ExperienceSubtypeEnum,
    Key,
    RecordId,
    Slug,
    SourceKindEnum,
)
from noesis.exceptions import (
    IdempotencyKeyReusedError,
    RevisionConflictError,
    StoreNotInitialisedError,
)

pytestmark = pytest.mark.unit

COMMIT: NewSourceInput = NewSourceInput(kind=SourceKindEnum.COMMIT, locator="a" * 40)


def capture_command(key: str = "k1", body: str = "Use retries.") -> CaptureKnowledgeCommand:
    return CaptureKnowledgeCommand(
        idempotency_key=key,
        space_key=DEFAULT_SPACE_KEY,
        title="Retry policy",
        body=body,
        subtype=Slug(value="decision"),
        actor=AGENT,
        project=ProjectRef(key=Key(value="noesis")),
        sources=(COMMIT,),
    )


async def test_capture_then_get_returns_revision_one_proposed() -> None:
    env: KnowledgeEnv = await make_env()

    result: CaptureResultDto = await env.capture_knowledge.handle(capture_command())
    record: RecordDto = await env.get_record.handle(
        GetRecordQuery(space_key=DEFAULT_SPACE_KEY, record_id=RecordId(value=result.record_id))
    )

    assert (result.revision, result.status, result.replayed) == (1, "proposed", False)
    assert record.status == "proposed"
    assert record.revision is not None
    assert record.revision.body == "Use retries."
    assert record.project_id is not None


async def test_repeat_capture_replays_and_different_request_is_rejected() -> None:
    env: KnowledgeEnv = await make_env()
    first: CaptureResultDto = await env.capture_knowledge.handle(capture_command())

    again: CaptureResultDto = await env.capture_knowledge.handle(capture_command())

    assert again.record_id == first.record_id
    assert again.replayed
    assert len(env.store.knowledge) == 1
    with pytest.raises(IdempotencyKeyReusedError):
        await env.capture_knowledge.handle(capture_command(body="Something else."))


async def test_revise_appends_and_stale_expected_revision_conflicts() -> None:
    env: KnowledgeEnv = await make_env()
    captured: CaptureResultDto = await env.capture_knowledge.handle(capture_command())
    record_id: RecordId = RecordId(value=captured.record_id)

    def revise(key: str, expected: int) -> ReviseKnowledgeCommand:
        return ReviseKnowledgeCommand(
            idempotency_key=key,
            space_key=DEFAULT_SPACE_KEY,
            record_id=record_id,
            expected_revision=expected,
            actor=AGENT,
            body="Use retries with jitter.",
        )

    revised = await env.revise_knowledge.handle(revise("r1", 1))

    assert revised.revision == 2
    with pytest.raises(RevisionConflictError) as conflict:
        await env.revise_knowledge.handle(revise("r2", 1))
    assert conflict.value.metadata == {
        "record_id": captured.record_id,
        "expected_revision": 1,
        "actual_revision": 2,
    }


async def test_experience_secret_is_redacted_before_storage() -> None:
    env: KnowledgeEnv = await make_env()

    result: CaptureResultDto = await env.capture_experience.handle(
        CaptureExperienceCommand(
            idempotency_key="e1",
            space_key=DEFAULT_SPACE_KEY,
            subtype=ExperienceSubtypeEnum.FAILURE,
            body="deploy failed, api_key = abcdefgh12345678",
            actor=AGENT,
            sources=(COMMIT,),
        )
    )

    stored = env.store.experiences[result.record_id]
    assert "abcdefgh12345678" not in stored.body
    assert "[REDACTED]" in stored.body


async def test_command_on_uninitialised_store_names_the_missing_step() -> None:
    env: KnowledgeEnv = await make_env(initialised=False)

    with pytest.raises(StoreNotInitialisedError) as error:
        await env.capture_knowledge.handle(capture_command())

    assert error.value.metadata == {"missing_steps": ["core"]}
    assert env.store.commits == 0
