"""Explicit capture (`curate apply`) and the plan registration in the ledger."""

import pytest
from tests.support.curation_support import (
    AGENT,
    SECRET_GH,
    SHA1,
    USER,
    experience,
    knowledge,
    make_curation_env,
)

from noesis.bounded_context.knowledge.application.dtos import RejectedEntryDto
from noesis.bounded_context.knowledge.application.handlers.commands.register_curation_plan_handler import (
    CURATION_PLAN_COMMAND,
    RegisterCurationPlanCommand,
    RegisterCurationPlanHandler,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    DEFAULT_CURATION_SUBTYPES,
    Key,
    RecordId,
    SourceKindEnum,
)
from noesis.exceptions import CurationRejectedError, IdempotencyKeyReusedError

pytestmark = pytest.mark.unit

SESSION = "sess-c7-0002"


async def test_an_apply_without_a_commit_lands_with_the_session_and_the_work_brief_only() -> None:
    env = await make_curation_env()

    result = await env.apply.handle(env.apply_command([experience("e1", subtype="outcome")]))

    (item,) = result.items
    assert item.outcome == "recorded" and item.record_id is not None
    assert [(s.kind, s.locator) for s in result.sources] == [
        ("work_brief", result.submission_key),
        ("agent_session", SESSION),
    ]
    record = env.base.store.experiences[item.record_id]
    assert record.session == SESSION
    assert {env.base.store.sources[i.value].kind for i in record.source_ids} == {
        SourceKindEnum.WORK_BRIEF,
        SourceKindEnum.AGENT_SESSION,
    }
    assert env.curator.calls == [] and result.related_lookup.state == "disabled"


async def test_each_commit_of_an_apply_becomes_a_source() -> None:
    env = await make_curation_env()

    result = await env.apply.handle(env.apply_command([experience()], commits=(SHA1,)))

    assert [(s.kind, s.locator) for s in result.sources] == [
        ("work_brief", result.submission_key),
        ("commit", SHA1),
        ("agent_session", SESSION),
    ]


async def test_an_apply_runs_as_the_actor_the_cli_resolved() -> None:
    env = await make_curation_env()

    result = await env.apply.handle(env.apply_command([knowledge()], actor=USER))

    stored = env.base.store.knowledge[result.items[0].record_id or ""]
    assert stored.head.actor == USER


async def test_applying_the_same_payload_again_replays_it() -> None:
    env = await make_curation_env()
    first = await env.apply.handle(env.apply_command([experience()]))

    again = await env.apply.handle(env.apply_command([experience()]))

    assert again.replayed is True
    assert again.items[0].record_id == first.items[0].record_id
    assert len(env.base.store.experiences) == 1


async def test_another_session_is_another_submission() -> None:
    env = await make_curation_env()

    first = await env.apply.handle(env.apply_command([experience()]))
    second = await env.apply.handle(env.apply_command([experience()], session="sess-other"))

    assert first.submission_key != second.submission_key
    assert len(env.base.store.experiences) == 2


async def test_a_rejected_payload_is_kept_redacted_and_nothing_is_staged_or_written() -> None:
    env = await make_curation_env()
    rejected = (
        RejectedEntryDto(index=1, reason="missing body"),
        RejectedEntryDto(index=None, reason=f"odd {SECRET_GH}"),
    )

    with pytest.raises(CurationRejectedError) as raised:
        await env.apply.handle(
            env.apply_command([], rejected=rejected, raw_payload=f'{{"candidates": "{SECRET_GH}"}}')
        )

    assert raised.value.metadata["rejected"] == [
        {"index": 1, "reason": "missing body"},
        {"index": None, "reason": "odd [REDACTED]"},
    ]
    assert raised.value.metadata["kept_file"] == "/inbox/rejected/1.json"
    assert len(env.inbox.kept) == 1 and SECRET_GH not in env.inbox.kept[0]
    assert env.inbox.tickets == {} and env.base.store.ledger == {}
    assert env.base.store.experiences == {} and env.base.store.knowledge == {}


async def test_the_apply_curation_command_knows_no_curator_and_no_lookup() -> None:
    env = await make_curation_env()

    await env.apply.handle(env.apply_command([knowledge()]))

    assert env.curator.calls == [] and env.finder.calls == []


async def test_a_session_agent_actor_keeps_its_name() -> None:
    env = await make_curation_env()

    result = await env.apply.handle(env.apply_command([experience()], actor=AGENT))

    stored = env.base.store.experiences[result.items[0].record_id or ""]
    assert stored.actor == AGENT


# ----- RegisterCurationPlanHandler -----


async def test_registering_a_plan_ensures_the_work_brief_source_and_writes_the_ledger_entry() -> (
    None
):
    env = await make_curation_env()
    handler = RegisterCurationPlanHandler(
        uow_factory=env.base.uow, clock=env.base.clock, ids=env.base.ids, schema=env.base.schema
    )
    command = RegisterCurationPlanCommand(
        space_key=Key(value="default"), submission_key="abc", plan_hash="h1"
    )

    first = await handler.handle(command)
    again = await handler.handle(command)

    assert (first.replayed, again.replayed) == (False, True)
    assert first.source_id == again.source_id
    source = env.base.store.sources[first.source_id]
    assert (source.kind, source.locator) == (SourceKindEnum.WORK_BRIEF, "abc")
    entry = env.base.store.ledger[(env.base.space_id.value, "capture/abc/plan")]
    assert (entry.command, entry.fingerprint, entry.record_id) == (
        CURATION_PLAN_COMMAND,
        "h1",
        RecordId(value=first.source_id),
    )
    assert CURATION_PLAN_COMMAND == "curation.plan"
    assert env.base.store.changes == []  # a Source has no change-feed entry


async def test_another_plan_for_a_registered_submission_is_refused() -> None:
    env = await make_curation_env()
    handler = RegisterCurationPlanHandler(
        uow_factory=env.base.uow, clock=env.base.clock, ids=env.base.ids, schema=env.base.schema
    )
    await handler.handle(
        RegisterCurationPlanCommand(
            space_key=Key(value="default"), submission_key="abc", plan_hash="h1"
        )
    )

    with pytest.raises(IdempotencyKeyReusedError):
        await handler.handle(
            RegisterCurationPlanCommand(
                space_key=Key(value="default"), submission_key="abc", plan_hash="h2"
            )
        )


def test_the_default_subtypes_are_what_the_policy_is_built_with() -> None:
    assert DEFAULT_CURATION_SUBTYPES.experience == {"observation", "outcome", "failure"}
