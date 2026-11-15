"""ProposeAssertionHandler (FR-001..FR-003, FR-015; AC-009, AC-010, AC-015, AC-022)."""

import pytest
from tests.support.knowledge_commands import revise_command
from tests.support.knowledge_support import AGENT, NOW, KnowledgeEnv, make_env
from tests.support.review_commands import propose_command, retract_assertion_command
from tests.support.review_fakes import (
    ReviewEnv,
    force_status,
    make_review_env,
    seed_catalog_entry,
    seed_experience,
    seed_knowledge,
)

from noesis.bounded_context.knowledge.application.dtos.review_dtos import (
    ProposeAssertionResultDto,
)
from noesis.bounded_context.knowledge.domain.entities import Assertion, KnowledgeSpace
from noesis.bounded_context.knowledge.domain.value_objects import (
    AssertionPredicateEnum,
    CatalogEntryKindEnum,
    Key,
    RecordId,
    RecordStatusEnum,
)
from noesis.exceptions import (
    DuplicateAssertionError,
    IdempotencyKeyReusedError,
    InvalidAssertionError,
    StoreNotInitialisedError,
)

pytestmark = pytest.mark.unit

SUPPORTS = AssertionPredicateEnum.SUPPORTS
SUPERSEDES = AssertionPredicateEnum.SUPERSEDES
RECOMMENDS = AssertionPredicateEnum.RECOMMENDS


def stored(env: ReviewEnv, result: ProposeAssertionResultDto) -> Assertion:
    return env.store.assertions[result.id]


async def test_propose_stores_a_proposed_assertion_with_the_judged_revisions_and_a_ledger_entry() -> (
    None
):
    env = await make_review_env()
    subject = await seed_experience(env)
    object_ = await seed_knowledge(env, "c1", project="acme")
    evidence = await seed_knowledge(env, "c2", project="acme")

    result = await env.propose_assertion().handle(
        propose_command(
            SUPPORTS,
            subject,
            object_,
            "p1",
            evidence=(evidence,),
            project="acme",
            tags=("area:retry",),
        )
    )

    assertion = stored(env, result)
    assert isinstance(result, ProposeAssertionResultDto)
    assert (result.status, result.replayed, result.predicate) == ("proposed", False, "supports")
    assert (result.subject_id, result.object_id) == (subject.value, object_.value)
    assert (result.subject_at_revision, result.object_at_revision) == (None, 1)
    assert result.evidence_ids == (evidence.value,)
    assert (result.project_key, result.tags) == ("acme", ("area:retry",))
    assert assertion.status is RecordStatusEnum.PROPOSED
    assert assertion.actor == AGENT
    assert assertion.created_at == NOW
    assert assertion.applicability.project_id is not None
    assert [t.value for t in assertion.applicability.sorted_tags] == ["area:retry"]
    assert len(assertion.source_ids) == 1
    ledger = env.store.ledger[(assertion.space_id.value, "p1")]
    assert (ledger.command, ledger.record_id) == ("assertion.propose", assertion.id)


async def test_propose_records_the_head_revision_at_proposal_time() -> None:
    env = await make_review_env()
    subject = await seed_knowledge(env, "c1")
    object_ = await seed_knowledge(env, "c2")
    await env.base.revise_knowledge.handle(revise_command(object_))

    result = await env.propose_assertion().handle(propose_command(SUPPORTS, subject, object_))

    assert (result.subject_at_revision, result.object_at_revision) == (1, 2)
    assert stored(env, result).object_at_revision == 2


async def test_propose_redacts_secrets_in_the_rationale() -> None:
    env = await make_review_env()
    subject = await seed_experience(env)
    object_ = await seed_knowledge(env, "c1")

    result = await env.propose_assertion().handle(
        propose_command(SUPPORTS, subject, object_, rationale="token is sk-abcdefghijklmnopqrstuv")
    )

    assert "abcdefghijklmnopqrstuv" not in stored(env, result).rationale
    assert stored(env, result).rationale.startswith("token is ")


async def test_propose_identical_live_statement_is_a_duplicate_naming_the_existing_id() -> None:
    env = await make_review_env()
    subject = await seed_experience(env)
    object_ = await seed_knowledge(env, "c1", project="acme")
    first = await env.propose_assertion().handle(
        propose_command(SUPPORTS, subject, object_, "k1", project="acme")
    )

    with pytest.raises(DuplicateAssertionError) as raised:
        await env.propose_assertion().handle(
            propose_command(SUPPORTS, subject, object_, "k2", project="acme")
        )

    assert raised.value.metadata["existing_id"] == first.id
    assert len(env.store.assertions) == 1
    assert (env.store.ledger.get((env.space_id.value, "k2"))) is None


async def test_an_accepted_statement_is_still_live() -> None:
    env = await make_review_env()
    subject = await seed_experience(env)
    object_ = await seed_knowledge(env, "c1")
    first = await env.propose_assertion().handle(propose_command(SUPPORTS, subject, object_, "k1"))
    force_status(env, RecordId(value=first.id), RecordStatusEnum.ACCEPTED)

    with pytest.raises(DuplicateAssertionError):
        await env.propose_assertion().handle(propose_command(SUPPORTS, subject, object_, "k2"))


async def test_the_project_is_part_of_the_statement_key() -> None:
    env = await make_review_env()
    subject = await seed_experience(env)
    object_ = await seed_knowledge(env, "c1")
    first = await env.propose_assertion().handle(
        propose_command(SUPPORTS, subject, object_, "k1", project="acme")
    )

    second = await env.propose_assertion().handle(
        propose_command(SUPPORTS, subject, object_, "k2", project="other")
    )

    assert second.id != first.id


async def test_retracting_the_live_assertion_frees_the_statement() -> None:
    env = await make_review_env()
    subject = await seed_experience(env)
    object_ = await seed_knowledge(env, "c1")
    first = await env.propose_assertion().handle(propose_command(SUPPORTS, subject, object_, "k1"))
    await env.retract_assertion().handle(retract_assertion_command(RecordId(value=first.id)))

    again = await env.propose_assertion().handle(propose_command(SUPPORTS, subject, object_, "k3"))

    assert again.id != first.id
    assert again.status == "proposed"
    assert env.store.assertions[first.id].status is RecordStatusEnum.RETRACTED


async def test_replay_with_the_same_key_returns_the_same_assertion_without_writing() -> None:
    env = await make_review_env()
    subject = await seed_experience(env)
    object_ = await seed_knowledge(env, "c1")
    first = await env.propose_assertion().handle(propose_command(SUPPORTS, subject, object_, "p1"))
    commits = env.store.commits

    replay = await env.propose_assertion().handle(propose_command(SUPPORTS, subject, object_, "p1"))

    assert replay.replayed is True
    assert replay.id == first.id
    assert env.store.commits == commits
    assert len(env.store.assertions) == 1


async def test_the_same_key_for_a_different_request_is_reused_key() -> None:
    env = await make_review_env()
    subject = await seed_experience(env)
    object_ = await seed_knowledge(env, "c1")
    await env.propose_assertion().handle(propose_command(SUPPORTS, subject, object_, "p1"))

    with pytest.raises(IdempotencyKeyReusedError):
        await env.propose_assertion().handle(
            propose_command(SUPPORTS, subject, object_, "p1", rationale="a different reason")
        )


async def test_an_invalid_request_writes_no_ledger_entry_so_the_key_works_afterwards() -> None:
    env = await make_review_env()
    subject = await seed_knowledge(env, "c1")
    object_ = await seed_knowledge(env, "c2")
    ledger_before = dict(env.store.ledger)

    with pytest.raises(InvalidAssertionError) as raised:
        await env.propose_assertion().handle(propose_command(SUPPORTS, subject, subject, "p1"))

    assert raised.value.metadata["field"] == "object"
    assert env.store.ledger == ledger_before
    assert env.store.assertions == {}
    ok = await env.propose_assertion().handle(propose_command(SUPPORTS, subject, object_, "p1"))
    assert ok.status == "proposed"


@pytest.mark.parametrize("wrong", ["subject", "object", "evidence"])
async def test_a_reference_unknown_in_the_active_space_is_invalid_and_named(wrong: str) -> None:
    env = await make_review_env()
    unknown = RecordId(value="7" + "Z" * 25)
    subject = await seed_experience(env)
    object_ = await seed_knowledge(env, "c1")
    known_evidence = await seed_knowledge(env, "c2")
    ids = {
        "subject": subject if wrong != "subject" else unknown,
        "object": object_ if wrong != "object" else unknown,
        "evidence": known_evidence if wrong != "evidence" else unknown,
    }

    with pytest.raises(InvalidAssertionError) as raised:
        await env.propose_assertion().handle(
            propose_command(SUPPORTS, ids["subject"], ids["object"], evidence=(ids["evidence"],))
        )

    assert raised.value.metadata["field"] == wrong
    assert env.store.assertions == {}


async def test_a_reference_in_another_space_is_invalid_like_an_unknown_one() -> None:
    env = await make_review_env()
    other_key = Key(value="elsewhere")
    async with env.uow() as uow:
        await uow.spaces.add(
            KnowledgeSpace.create(
                id=env.ids.new_space_id(), key=other_key, name="elsewhere", now=NOW
            )
        )
        await uow.commit()
    foreign = await seed_knowledge(env, "cf", space_key=other_key)
    object_ = await seed_knowledge(env, "c1")

    with pytest.raises(InvalidAssertionError) as raised:
        await env.propose_assertion().handle(propose_command(SUPPORTS, foreign, object_))

    assert raised.value.metadata["field"] == "subject"


async def test_supersedes_may_be_proposed_while_its_subject_is_still_proposed() -> None:
    env = await make_review_env()
    successor = await seed_knowledge(env, "n", status=RecordStatusEnum.PROPOSED)
    original = await seed_knowledge(env, "o", status=RecordStatusEnum.ACCEPTED)

    result = await env.propose_assertion().handle(propose_command(SUPERSEDES, successor, original))

    assert result.status == "proposed"
    assert result.subject_at_revision == 1


async def test_supersedes_with_a_project_on_a_space_wide_object_is_invalid() -> None:
    env = await make_review_env()
    successor = await seed_knowledge(env, "n", project="acme")
    original = await seed_knowledge(env, "o")

    with pytest.raises(InvalidAssertionError) as raised:
        await env.propose_assertion().handle(
            propose_command(SUPERSEDES, successor, original, project="acme")
        )

    assert raised.value.metadata["field"] == "project"


@pytest.mark.parametrize("kind", CatalogEntryKindEnum)
async def test_recommends_accepts_a_catalog_entry_of_every_kind_as_object(
    kind: CatalogEntryKindEnum,
) -> None:
    env = await make_review_env()
    subject = await seed_knowledge(env, "c1")
    entry = seed_catalog_entry(env, kind)

    result = await env.propose_assertion().handle(propose_command(RECOMMENDS, subject, entry))

    assert result.object_id == entry.value
    assert result.object_at_revision is None


async def test_propose_needs_the_review_schema_step() -> None:
    env: KnowledgeEnv = await make_env()
    review_env = ReviewEnv(env)
    subject = await seed_experience(review_env)
    object_ = await seed_knowledge(review_env, "c1")

    with pytest.raises(StoreNotInitialisedError) as raised:
        await review_env.propose_assertion().handle(propose_command(SUPPORTS, subject, object_))

    assert raised.value.metadata["missing_steps"] == ["review"]
