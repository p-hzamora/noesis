"""Curated ingestion: the flow of a work brief from the inbox to the store (fakes, no I/O)."""

import pytest
from tests.support.curation_support import (
    ANSWER_3K,
    ANSWER_EK,
    PROJECT,
    SECRET_AWS,
    SECRET_GH,
    SECRET_PW,
    SESSION,
    SHA1,
    SHA2,
    CurationEnv,
    FakeCurator,
    FakeRelatedFinder,
    brief_contract,
    experience,
    knowledge,
    make_curation_env,
)
from tests.support.review_fakes import seed_knowledge

from noesis.bounded_context.knowledge.application.dtos import CurationResultDto, RecordDto
from noesis.bounded_context.knowledge.application.handlers.commands.retry_parked_curation_handler import (
    RetryParkedCurationCommand,
)
from noesis.bounded_context.knowledge.domain.services import CaptureKeyPolicy
from noesis.bounded_context.knowledge.domain.value_objects import (
    CurationProgress,
    CurationStageEnum,
    RecordId,
    RecordStatusEnum,
)
from noesis.exceptions import (
    BriefAlreadyIngestedError,
    CurationParkedError,
    CuratorRunFailedError,
    GraphStoreUnavailableError,
    InvalidRecordError,
    ParkedCurationTicketNotFoundError,
    RelatedLookupUnavailableError,
    RevisionConflictError,
)

pytestmark = pytest.mark.unit

SPACE_KEY = "default"


async def read(env: CurationEnv, record_id: str) -> RecordDto:
    found = await env.base.records.get_by_id(RecordId(value=record_id), space_id=env.base.space_id)
    assert found is not None
    return found


def submission_key(**overrides: object) -> str:
    from noesis.bounded_context.knowledge.application.mappers import WorkBriefMapper

    return WorkBriefMapper.to_domain(brief_contract(**overrides)).submission_key()  # type: ignore[arg-type]


def ledger_keys(env: CurationEnv) -> set[str]:
    return {key for (_, key) in env.base.store.ledger}


def ticket_of(env: CurationEnv):  # type: ignore[no-untyped-def]
    return env.inbox.tickets[CaptureKeyPolicy.ticket_of(submission_key())]


# ----- AC-001 -----


async def test_a_brief_lands_an_experience_and_a_proposal_with_the_three_source_kinds() -> None:
    env = await make_curation_env()

    result = await env.ingest.handle(env.ingest_command())

    sk = submission_key()
    e1, k1 = result.items
    assert (e1.outcome, e1.type, e1.revision, e1.status) == ("recorded", "experience", None, None)
    assert (k1.outcome, k1.type, k1.revision, k1.status) == ("proposed", "knowledge", 1, "proposed")
    assert (result.replayed, result.dry_run, result.submission_key) == (False, False, sk)
    assert (
        result.related_lookup.state == "disabled" and result.related_lookup.pending_changes is None
    )
    assert [(s.kind, s.locator) for s in result.sources] == [
        ("work_brief", sk),
        ("commit", SHA1),
        ("commit", SHA2),
        ("agent_session", SESSION),
    ]
    assert all(s.id for s in result.sources)
    for item in (e1, k1):
        record = await read(env, item.record_id or "")
        assert {(s.kind, s.locator) for s in record.sources} == {
            ("work_brief", sk),
            ("commit", SHA1),
            ("commit", SHA2),
            ("agent_session", SESSION),
        }
    knowledge_record = await read(env, k1.record_id or "")
    assert knowledge_record.applicability is not None and knowledge_record.applicability.tags == ()
    project = await read(env, knowledge_record.project_id or "")
    assert project.key == PROJECT
    assert knowledge_record.revision is not None
    assert knowledge_record.revision.actor.name == "noesis-curator"
    assert knowledge_record.revision.actor.session == SESSION
    experience_record = await read(env, e1.record_id or "")
    assert experience_record.session == SESSION


async def test_every_write_uses_its_capture_key_and_the_ticket_ends_applied() -> None:
    env = await make_curation_env()

    await env.ingest.handle(env.ingest_command())

    sk = submission_key()
    assert env.experience.keys == [f"capture/{sk}/1/experience"]
    assert env.knowledge.keys == [f"capture/{sk}/2/knowledge"]
    assert f"capture/{sk}/plan" in ledger_keys(env)
    ticket = ticket_of(env)
    assert ticket.progress.stage is CurationStageEnum.APPLIED
    assert ticket.plan is not None
    assert {(s.ordinal, s.step, s.outcome.value) for s in ticket.steps} == {
        (1, "experience", "written"),
        (2, "knowledge", "written"),
    }


async def test_capture_never_accepts_and_the_manager_holds_no_accept_handler() -> None:
    env = await make_curation_env()

    await env.ingest.handle(env.ingest_command())

    assert {k.status for k in env.base.store.knowledge.values()} == {RecordStatusEnum.PROPOSED}
    manager_fields = {name.lower() for name in vars(env.runner._manager)}
    assert not any("accept" in name for name in manager_fields)


# ----- AC-003, AC-004 -----


async def test_the_same_brief_replays_without_judging_or_writing_again() -> None:
    env = await make_curation_env()
    first = await env.ingest.handle(env.ingest_command())
    before = len(env.base.store.knowledge) + len(env.base.store.experiences)

    again = await env.ingest.handle(env.ingest_command())
    excerpt = await env.ingest.handle(
        env.ingest_command(brief=brief_contract(excerpt="a different excerpt"))
    )

    assert len(env.curator.calls) == 1
    assert (again.replayed, excerpt.replayed) == (True, True)
    assert [i.record_id for i in again.items] == [i.record_id for i in first.items]
    assert [i.record_id for i in excerpt.items] == [i.record_id for i in first.items]
    assert len(env.base.store.knowledge) + len(env.base.store.experiences) == before


async def test_a_registered_brief_without_its_local_plan_fails_and_names_the_source() -> None:
    env = await make_curation_env()
    first = await env.ingest.handle(env.ingest_command())
    env.inbox.tickets.clear()

    with pytest.raises(BriefAlreadyIngestedError) as raised:
        await env.ingest.handle(env.ingest_command())

    work_brief = next(s for s in first.sources if s.kind == "work_brief")
    assert raised.value.metadata["work_brief_source_id"] == work_brief.id
    assert raised.value.metadata["submission_key"] == submission_key()
    assert len(env.curator.calls) == 1
    assert env.inbox.tickets == {}  # Q-015: the ticket is removed


async def test_a_local_plan_of_another_hash_is_also_refused() -> None:
    env = await make_curation_env()
    await env.ingest.handle(env.ingest_command())
    ticket = ticket_of(env)
    env.inbox.tickets[ticket.ticket] = ticket.model_copy(
        update={"plan": ticket.plan.model_copy(update={"entries": ()}) if ticket.plan else None}
    )

    with pytest.raises(BriefAlreadyIngestedError):
        await env.ingest.handle(env.ingest_command())


async def test_a_plan_saved_before_the_ledger_entry_is_registered_without_judging_again() -> None:
    env = await make_curation_env()
    await env.ingest.handle(env.ingest_command())
    ticket = ticket_of(env)
    sk = submission_key()
    del env.base.store.ledger[(env.base.space_id.value, f"capture/{sk}/plan")]  # a crash window
    env.inbox.tickets[ticket.ticket] = ticket.model_copy(
        update={"progress": CurationProgress(stage=CurationStageEnum.PLANNED), "steps": ()}
    )

    again = await env.ingest.handle(env.ingest_command())

    assert len(env.curator.calls) == 1
    assert again.replayed is False
    assert f"capture/{sk}/plan" in ledger_keys(env)


# ----- AC-005, AC-006 -----


async def test_a_down_store_parks_the_brief_without_judging_and_the_retry_lands_it() -> None:
    down = GraphStoreUnavailableError("down", {"phase": "connect"})
    env = await make_curation_env(finder=FakeRelatedFinder(error=down))

    with pytest.raises(GraphStoreUnavailableError) as raised:
        await env.ingest.handle(env.ingest_command(related_lookup="required"))

    ticket_id = CaptureKeyPolicy.ticket_of(submission_key())
    assert raised.value.metadata["ticket"] == ticket_id
    assert any(f"noesis curate retry {ticket_id}" in step for step in raised.value.next_steps)
    assert env.curator.calls == []
    (parked,) = await env.list_parked.handle(_query())
    assert (parked.ticket, parked.stage, parked.reason, parked.repository) == (
        ticket_id,
        "staged",
        "store_unavailable",
        PROJECT,
    )
    env.runner._finder = FakeRelatedFinder()  # the store is back

    result = await env.retry.handle(
        RetryParkedCurationCommand(ticket=ticket_id, space_key=_space(), related_lookup="required")
    )

    assert [i.outcome for i in result.items] == ["recorded", "proposed"]
    assert len(env.curator.calls) == 1
    assert await env.list_parked.handle(_query()) == ()


async def test_a_store_down_mid_apply_is_reported_as_the_store_error_and_retried_in_place() -> None:
    env = await make_curation_env(answer=ANSWER_3K)
    sk = submission_key()
    env.knowledge.fail_once[f"capture/{sk}/2/knowledge"] = GraphStoreUnavailableError("down")

    with pytest.raises(GraphStoreUnavailableError) as raised:
        await env.ingest.handle(env.ingest_command())

    ticket = ticket_of(env)
    assert raised.value.metadata["ticket"] == ticket.ticket
    assert ticket.progress.failed_at is CurationStageEnum.APPLYING
    assert (
        ticket.progress.reason is not None and ticket.progress.reason.value == "store_unavailable"
    )

    result = await env.retry.handle(
        RetryParkedCurationCommand(ticket=ticket.ticket, space_key=_space())
    )

    assert [i.outcome for i in result.items] == ["proposed"] * 3
    assert env.knowledge.keys.count(f"capture/{sk}/1/knowledge") == 2  # replayed from the ledger
    assert env.knowledge.keys.count(f"capture/{sk}/3/knowledge") == 1
    assert len(env.base.store.knowledge) == 3


async def test_a_failure_after_the_first_of_three_writes_keeps_its_id_on_retry() -> None:
    env = await make_curation_env(answer=ANSWER_3K)
    sk = submission_key()
    env.knowledge.fail_once[f"capture/{sk}/2/knowledge"] = InvalidRecordError("boom")

    with pytest.raises(CurationParkedError) as raised:
        await env.ingest.handle(env.ingest_command())

    ticket = ticket_of(env)
    assert raised.value.metadata["cause"] == "KNOWLEDGE_007_INVALID_RECORD"
    assert raised.value.metadata["ticket"] == ticket.ticket
    assert ticket.progress.failed_at is CurationStageEnum.APPLYING
    assert ticket.progress.reason is not None and ticket.progress.reason.value == "step_failed"
    assert ticket.progress.error_code == "KNOWLEDGE_007_INVALID_RECORD"
    first_id = next(iter(env.base.store.knowledge))

    result = await env.retry.handle(
        RetryParkedCurationCommand(ticket=ticket.ticket, space_key=_space())
    )

    ids = [i.record_id for i in result.items]
    assert ids[0] == first_id
    assert len(set(ids)) == 3 and len(env.base.store.knowledge) == 3
    assert env.knowledge.keys.count(f"capture/{sk}/1/knowledge") == 2
    assert env.knowledge.keys.count(f"capture/{sk}/3/knowledge") == 1
    assert result.replayed is True
    assert len(env.curator.calls) == 1


# ----- AC-007, AC-008, AC-012 -----


async def test_an_accepted_target_gets_a_successor_and_a_proposed_supersedes() -> None:
    env = await make_curation_env()
    target = await seed_knowledge(
        env.base, "seed", project=PROJECT, status=RecordStatusEnum.ACCEPTED
    )

    result = await env.apply.handle(
        env.apply_command([knowledge("k1", target=target.value, reason="replaces the target")])
    )

    (item,) = result.items
    assert item.outcome == "successor_proposed" and item.target_record_id == target.value
    assert item.record_id != target.value and len(item.assertion_ids) == 1
    assertion = env.base.store.assertions[item.assertion_ids[0]]
    assert (assertion.predicate.value, assertion.status) == (
        "supersedes",
        RecordStatusEnum.PROPOSED,
    )
    assert (assertion.subject_id.value, assertion.object_id.value) == (item.record_id, target.value)
    unchanged = env.base.store.knowledge[target.value]
    assert (unchanged.status, unchanged.head_number) == (RecordStatusEnum.ACCEPTED, 1)
    sk = result.submission_key
    assert env.knowledge.keys == [f"capture/{sk}/1/knowledge"]
    assert env.assertion is not None and env.assertion.keys == [f"capture/{sk}/1/supersedes"]


async def test_a_crash_between_the_proposal_and_the_link_writes_the_link_once_on_retry() -> None:
    env = await make_curation_env()
    target = await seed_knowledge(
        env.base, "seed", project=PROJECT, status=RecordStatusEnum.ACCEPTED
    )
    candidates = [knowledge("k1", target=target.value, reason="replaces")]
    sk = None
    assert env.assertion is not None
    from noesis.bounded_context.knowledge.application.handlers.commands.apply_curation_handler import (
        payload_key,
    )

    sk = payload_key("sess-c7-0002", tuple(candidates))
    env.assertion.fail_once[f"capture/{sk}/1/supersedes"] = InvalidRecordError("crash")

    with pytest.raises(CurationParkedError):
        await env.apply.handle(env.apply_command(candidates))
    successor_id = next(k for k in env.base.store.knowledge if k != target.value)

    result = await env.retry.handle(
        RetryParkedCurationCommand(ticket=CaptureKeyPolicy.ticket_of(sk), space_key=_space())
    )

    (item,) = result.items
    assert item.record_id == successor_id
    assert len(env.base.store.knowledge) == 2 and len(env.base.store.assertions) == 1
    assert env.knowledge.keys.count(f"capture/{sk}/1/knowledge") == 2
    assert env.assertion.keys.count(f"capture/{sk}/1/supersedes") == 2


async def test_a_proposed_target_is_revised_at_its_head() -> None:
    env = await make_curation_env()
    target = await seed_knowledge(env.base, "seed", project=PROJECT)

    result = await env.apply.handle(
        env.apply_command(
            [
                knowledge(
                    "k1", target=target.value, title="New title", body="New body", reason="refines"
                )
            ]
        )
    )

    (item,) = result.items
    assert (item.outcome, item.record_id, item.revision, item.status) == (
        "revised",
        target.value,
        2,
        "proposed",
    )
    record = await read(env, target.value)
    assert record.revision is not None
    assert (record.revision.title, record.revision.body) == ("New title", "New body")
    assert len(env.base.store.knowledge) == 1


async def test_a_migrated_proposed_target_is_kept_and_a_proposal_made_with_no_assertion() -> None:
    env = await make_curation_env()
    target = await seed_knowledge(
        env.base, "seed", project=PROJECT, tags=("origin:migrated",), title="Parser offset handling"
    )

    result = await env.apply.handle(
        env.apply_command([knowledge("k1", target=target.value, reason="refines")])
    )

    (item,) = result.items
    assert (item.outcome, item.reason, item.target_record_id) == (
        "proposed",
        "migrated_target_kept",
        target.value,
    )
    assert item.record_id != target.value and item.assertion_ids == ()
    assert env.base.store.knowledge[target.value].head_number == 1  # not revised
    assert env.base.store.assertions == {}


async def test_evidence_becomes_a_proposed_supports_from_the_experience_to_the_knowledge() -> None:
    answer = (
        experience("e1"),
        knowledge("k1", evidence=("e1",), reason="observed in this session"),
    )
    env = await make_curation_env(answer=answer)

    result = await env.ingest.handle(env.ingest_command())

    e1, k1 = result.items
    assert len(k1.assertion_ids) == 1
    assertion = env.base.store.assertions[k1.assertion_ids[0]]
    assert assertion.predicate.value == "supports" and assertion.status is RecordStatusEnum.PROPOSED
    assert (assertion.subject_id.value, assertion.object_id.value) == (e1.record_id, k1.record_id)
    assert [i.value for i in assertion.evidence_ids] == [e1.record_id]
    assert assertion.rationale == "observed in this session"
    assert f"capture/{submission_key()}/2/supports-1" in ledger_keys(env)


async def test_evidence_to_a_later_experience_is_linked_after_both_records_exist() -> None:
    answer = (knowledge("k1", evidence=("e1",), reason="seen"), experience("e1"))
    env = await make_curation_env(answer=answer)

    result = await env.ingest.handle(env.ingest_command())

    k1, e1 = result.items
    assert len(k1.assertion_ids) == 1 and e1.record_id is not None


async def test_without_assertions_a_successor_target_is_proposed_and_evidence_is_not_linked() -> (
    None
):
    env = await make_curation_env(assertions=False)
    target = await seed_knowledge(
        env.base, "seed", project=PROJECT, status=RecordStatusEnum.ACCEPTED
    )
    candidates = [
        experience("e1"),
        knowledge("k1", target=target.value, evidence=("e1",), reason="replaces"),
    ]

    result = await env.apply.handle(env.apply_command(candidates))

    _, k1 = result.items
    assert k1.outcome == "proposed" and k1.target_record_id == target.value
    assert k1.assertion_ids == ()
    assert k1.reason == "assertions unavailable: target not linked"
    assert env.assertion is None and env.base.store.assertions == {}


# ----- revise conflict -----


async def test_a_revise_conflict_skips_that_step_and_the_ticket_completes() -> None:
    env = await make_curation_env()
    target = await seed_knowledge(env.base, "seed", project=PROJECT)
    candidates = [knowledge("k1", target=target.value, reason="refines")]
    from noesis.bounded_context.knowledge.application.handlers.commands.apply_curation_handler import (
        payload_key,
    )

    sk = payload_key("sess-c7-0002", tuple(candidates))
    env.revise.fail_once[f"capture/{sk}/1/revise"] = RevisionConflictError("moved on")

    result = await env.apply.handle(env.apply_command(candidates))

    (item,) = result.items
    assert (item.outcome, item.reason, item.record_id) == ("skipped", "target_changed", None)
    ticket = env.inbox.tickets[CaptureKeyPolicy.ticket_of(sk)]
    assert ticket.progress.stage is CurationStageEnum.APPLIED
    step = ticket.step(1, "revise")
    assert step is not None and (step.outcome.value, step.reason) == ("skipped", "target_changed")

    again = await env.retry.handle(
        RetryParkedCurationCommand(ticket=ticket.ticket, space_key=_space())
    )

    assert again.items[0].outcome == "skipped"
    assert env.revise.keys == [f"capture/{sk}/1/revise"]  # revise is not called again


# ----- AC-009 -----


async def test_a_required_lookup_that_cannot_answer_parks_the_brief_and_skips_the_curator() -> None:
    env = await make_curation_env(finder=FakeRelatedFinder(error=RuntimeError("index missing")))

    with pytest.raises(RelatedLookupUnavailableError) as raised:
        await env.ingest.handle(env.ingest_command(related_lookup="required"))

    ticket = ticket_of(env)
    assert raised.value.metadata["ticket"] == ticket.ticket
    assert env.curator.calls == []
    assert ticket.progress.failed_at is CurationStageEnum.STAGED
    assert ticket.progress.reason is not None
    assert ticket.progress.reason.value == "related_lookup_unavailable"

    result = await env.ingest.handle(env.ingest_command(related_lookup="off"))

    assert result.related_lookup.state == "disabled"
    assert [i.outcome for i in result.items] == ["recorded", "proposed"]
    assert await env.list_parked.handle(_query()) == ()


async def test_a_lookup_that_answers_hands_the_related_records_to_the_curator() -> None:
    env = await make_curation_env(finder=FakeRelatedFinder(pending=4))
    seeded = await seed_knowledge(env.base, "seed", project=PROJECT, title="Parser offset handling")
    env.runner._finder = FakeRelatedFinder([seeded.value], pending=4)

    result = await env.ingest.handle(env.ingest_command(related_lookup="required"))

    assert (result.related_lookup.state, result.related_lookup.pending_changes) == ("used", 4)
    ((brief, related),) = env.curator.calls
    assert env.runner._finder.calls[0] == (brief.search_text(), PROJECT, 8)  # type: ignore[attr-defined]
    (found,) = related
    assert (found.record_id, found.title, found.status, found.project_key, found.revision) == (
        seeded.value,
        "Parser offset handling",
        "proposed",
        PROJECT,
        1,
    )
    assert not hasattr(found, "ownership")


async def test_the_lookup_state_of_a_replay_is_the_one_the_judgment_used() -> None:
    env = await make_curation_env(finder=FakeRelatedFinder(pending=2))
    await env.ingest.handle(env.ingest_command(related_lookup="required"))

    again = await env.ingest.handle(env.ingest_command(related_lookup="off"))

    assert (again.replayed, again.related_lookup.state, again.related_lookup.pending_changes) == (
        True,
        "used",
        2,
    )


# ----- curator failures -----


async def test_a_curator_that_fails_every_attempt_parks_the_brief_and_a_retry_lands_it() -> None:
    boom = CuratorRunFailedError("did not print JSON")
    curator = FakeCurator(ANSWER_EK, failures=[boom, boom])
    env = await make_curation_env(curator=curator)

    with pytest.raises(CurationParkedError) as raised:
        await env.ingest.handle(env.ingest_command(max_attempts=2))

    ticket = ticket_of(env)
    assert raised.value.metadata["cause"] == "KNOWLEDGE_141_CURATOR_FAILED"
    assert raised.value.metadata["ticket"] == ticket.ticket
    assert len(curator.calls) == 2 and env.sleeps == [0.5]
    assert ticket.progress.failed_at is CurationStageEnum.STAGED
    assert ticket.progress.reason is not None and ticket.progress.reason.value == "curator_failed"
    assert env.base.store.knowledge == {}

    result = await env.retry.handle(
        RetryParkedCurationCommand(ticket=ticket.ticket, space_key=_space())
    )

    assert [i.outcome for i in result.items] == ["recorded", "proposed"]
    assert len(curator.calls) == 3


async def test_no_park_reports_the_curator_error_and_removes_the_ticket() -> None:
    curator = FakeCurator(failures=[CuratorRunFailedError("missing")])
    env = await make_curation_env(curator=curator)

    with pytest.raises(CuratorRunFailedError):
        await env.ingest.handle(env.ingest_command(max_attempts=1, park_on_failure=False))

    assert env.inbox.tickets == {}


async def test_an_unusable_curator_answer_is_the_same_failure_as_a_missing_binary() -> None:
    curator = FakeCurator(failures=[CuratorRunFailedError("no candidates list")] * 2)
    env = await make_curation_env(curator=curator)

    with pytest.raises(CurationParkedError):
        await env.ingest.handle(env.ingest_command())

    assert len(curator.calls) == 2


async def test_a_flawed_curator_entry_becomes_a_skip_and_keeps_the_ordinals() -> None:
    from noesis.bounded_context.knowledge.domain.value_objects import CurationCandidate

    answer = (CurationCandidate(flaw="unknown kind 'poem'"), experience("e1"))
    env = await make_curation_env(answer=answer)

    result = await env.ingest.handle(env.ingest_command())

    first, second = result.items
    assert (first.ordinal, first.outcome, first.reason) == (
        1,
        "skipped",
        "malformed: unknown kind 'poem'",
    )
    assert (second.ordinal, second.outcome) == (2, "recorded")
    assert env.experience.keys == [f"capture/{submission_key()}/2/experience"]


# ----- AC-010 -----


async def test_secrets_never_reach_the_curator_the_inbox_or_the_store() -> None:
    answer = (experience("e1"), knowledge("k1", body=f"key {SECRET_AWS} in the body"))
    env = await make_curation_env(answer=answer)
    contract = brief_contract(goal=f"fix {SECRET_GH}", excerpt=f"we set {SECRET_PW}")

    result = await env.ingest.handle(env.ingest_command(brief=contract))

    secrets = (SECRET_GH, SECRET_AWS, "hunter2hunter2")
    (brief, _) = env.curator.calls[0]
    assert not any(s in brief.model_dump_json() for s in secrets)
    assert "[REDACTED]" in brief.model_dump_json()
    for ticket in env.inbox.tickets.values():
        assert not any(s in ticket.model_dump_json() for s in secrets)
    stored = await read(env, result.items[1].record_id or "")
    assert stored.revision is not None and SECRET_AWS not in (stored.revision.body or "")
    assert not any(s in repr(env.base.store.knowledge) for s in secrets)


async def test_a_secret_in_an_apply_payload_does_not_change_which_submission_it_is() -> None:
    env = await make_curation_env()
    redacted = [experience("e1", body="token [REDACTED] seen")]
    leaky = [experience("e1", body=f"token {SECRET_GH} seen")]

    first = await env.apply.handle(env.apply_command(leaky))
    second = await env.apply.handle(env.apply_command(redacted))

    assert first.submission_key == second.submission_key and second.replayed is True
    assert SECRET_GH not in repr(env.base.store.experiences)


# ----- dry runs -----


async def test_a_dry_run_judges_and_reports_but_writes_nothing() -> None:
    env = await make_curation_env()

    result = await env.ingest.handle(env.ingest_command(dry_run=True))

    assert (result.ticket, result.dry_run, result.replayed) == (None, True, False)
    assert [(i.outcome, i.record_id) for i in result.items] == [
        ("recorded", None),
        ("proposed", None),
    ]
    assert all(s.id is None for s in result.sources)
    assert len(env.curator.calls) == 1
    assert env.inbox.tickets == {} and env.base.store.ledger == {}
    assert env.base.store.knowledge == {} and env.base.store.experiences == {}


async def test_a_dry_run_of_an_apply_keeps_nothing_even_a_rejected_payload() -> None:
    from noesis.bounded_context.knowledge.application.dtos import RejectedEntryDto
    from noesis.exceptions import CurationRejectedError

    env = await make_curation_env()

    dry = await env.apply.handle(env.apply_command([experience()], dry_run=True))
    with pytest.raises(CurationRejectedError):
        await env.apply.handle(
            env.apply_command(
                [],
                rejected=(RejectedEntryDto(index=1, reason="missing body"),),
                raw_payload="{}",
                dry_run=True,
            )
        )

    assert dry.dry_run is True and env.curator.calls == []
    assert env.inbox.tickets == {} and env.inbox.kept == [] and env.base.store.ledger == {}


# ----- retry and listing -----


async def test_an_unknown_ticket_is_reported_with_the_listing_as_the_next_step() -> None:
    env = await make_curation_env()

    with pytest.raises(ParkedCurationTicketNotFoundError) as raised:
        await env.retry.handle(
            RetryParkedCurationCommand(ticket="no-such-ticket", space_key=_space())
        )

    assert raised.value.next_steps == ("Run `noesis curate parked` to list the tickets.",)


async def test_parked_tickets_are_listed_oldest_failure_first_with_stage_reason_and_age() -> None:
    env = await make_curation_env(finder=FakeRelatedFinder(error=RuntimeError("down")))
    with pytest.raises(RelatedLookupUnavailableError):
        await env.ingest.handle(env.ingest_command(related_lookup="required"))
    env.base.clock.advance(60)
    with pytest.raises(RelatedLookupUnavailableError):
        await env.ingest.handle(
            env.ingest_command(brief=brief_contract(session="sess-2"), related_lookup="required")
        )
    env.base.clock.advance(30)

    listed = await env.list_parked.handle(_query())

    assert [item.age_seconds for item in listed] == [90, 30]
    assert {(i.stage, i.reason, i.repository) for i in listed} == {
        ("staged", "related_lookup_unavailable", PROJECT)
    }
    assert listed[0].parked_at < listed[1].parked_at


async def test_a_second_run_on_a_held_ticket_waits_for_the_first() -> None:
    import asyncio

    env = await make_curation_env()

    first, second = await asyncio.gather(
        env.ingest.handle(env.ingest_command()), env.ingest.handle(env.ingest_command())
    )

    assert sorted([first.replayed, second.replayed]) == [False, True]
    assert len(env.curator.calls) == 1
    assert len(env.base.store.knowledge) == 1 and len(env.base.store.experiences) == 1


def _query():  # type: ignore[no-untyped-def]
    from noesis.bounded_context.knowledge.application.handlers.queries.list_parked_curations_handler import (
        ListParkedCurationsQuery,
    )

    return ListParkedCurationsQuery()


def _space():  # type: ignore[no-untyped-def]
    from noesis.bounded_context.knowledge.domain.value_objects import Key

    return Key(value=SPACE_KEY)


def test_the_result_dto_has_no_ownership_field() -> None:
    assert "ownership" not in CurationResultDto.model_fields
