"""RememberHandler (FR-011..FR-014; AC-012, AC-013): reconciliation, check mode, keys, assertions."""

import pytest
from tests.support.knowledge_commands import COMMIT
from tests.support.knowledge_support import AGENT, DEFAULT_SPACE_KEY
from tests.support.remember_support import FakeFinder, FlakyPropose
from tests.support.review_fakes import ReviewEnv, make_review_env, seed_knowledge

from noesis.bounded_context.knowledge.application.dtos import (
    CatalogEntryDetailDto,
    CatalogEntryDto,
    RememberKindEnum,
    RememberResultDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.propose_assertion_handler import (
    ProposeAssertionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.remember_handler import (
    KEY_PREFIX,
    RememberCommand,
    RememberHandler,
)
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    ICatalogEntryReadRepository,
)
from noesis.bounded_context.knowledge.application.services.inputs import ProjectRef
from noesis.bounded_context.knowledge.domain.value_objects import (
    CatalogEntryKindEnum,
    Key,
    RecordId,
    RecordStatusEnum,
    Slug,
    SpaceId,
)
from noesis.exceptions import (
    CatalogEntryNotFoundError,
    IdempotencyKeyReusedError,
    InvalidAssertionError,
    InvalidRecordError,
    RecordNotFoundError,
    RememberPartiallyAppliedError,
)

pytestmark = pytest.mark.unit

TITLE = "Retry policy"
BODY = "Use retries."


class NoCatalog(ICatalogEntryReadRepository):
    """A space with an empty catalog."""

    async def get_by_id(
        self, record_id: RecordId, *, space_id: SpaceId, revision: int | None = None
    ) -> CatalogEntryDetailDto | None:
        return None

    async def get_by_key(
        self,
        space_id: SpaceId,
        kind: CatalogEntryKindEnum,
        name: str,
        *,
        revision: int | None = None,
    ) -> CatalogEntryDetailDto | None:
        return None

    async def find(
        self,
        space_id: SpaceId,
        *,
        kind: CatalogEntryKindEnum | None = None,
        name_prefix: str | None = None,
    ) -> tuple[CatalogEntryDto, ...]:
        return ()


def remember_handler(
    env: ReviewEnv, finder: FakeFinder, *, propose: ProposeAssertionHandler | None = None
) -> RememberHandler:
    return RememberHandler(
        uow_factory=env.uow,
        clock=env.clock,
        ids=env.ids,
        schema=env.schema,
        capture_knowledge=env.base.capture_knowledge,
        capture_experience=env.base.capture_experience,
        propose_assertion=propose or env.propose_assertion(),
        records=env.records,
        catalog=NoCatalog(),
        finder=finder,
    )


def knowledge(**overrides: object) -> RememberCommand:
    values: dict[str, object] = {
        "kind": RememberKindEnum.KNOWLEDGE,
        "space_key": DEFAULT_SPACE_KEY,
        "actor": AGENT,
        "sources": (COMMIT,),
        "title": TITLE,
        "body": BODY,
        "knowledge_subtype": Slug(value="decision"),
    }
    return RememberCommand(**{**values, **overrides})  # type: ignore[arg-type]


def snapshot(env: ReviewEnv) -> tuple[int, ...]:
    s = env.store
    return (
        len(s.projects),
        len(s.sources),
        len(s.knowledge),
        len(s.experiences),
        len(s.ledger),
        len(s.assertions),
        s.commits,
    )


async def test_remember_writes_proposed_knowledge_with_a_derived_key() -> None:
    env = await make_review_env()

    result: RememberResultDto = await remember_handler(env, FakeFinder()).handle(knowledge())

    assert result.written is True
    assert (result.record_type, result.status, result.revision) == ("knowledge", "proposed", 1)
    assert result.idempotency_key.startswith(KEY_PREFIX)
    assert result.replayed is False
    assert len(env.store.knowledge) == 1


async def test_identical_requests_replay_without_a_second_record() -> None:
    env = await make_review_env()
    handler = remember_handler(env, FakeFinder())

    first = await handler.handle(knowledge())
    second = await handler.handle(knowledge())

    assert second.replayed is True
    assert second.record_id == first.record_id
    assert second.idempotency_key == first.idempotency_key
    assert len(env.store.knowledge) == 1


async def test_default_key_ignores_surrounding_whitespace_but_not_content() -> None:
    env = await make_review_env()
    handler = remember_handler(env, FakeFinder())

    first = await handler.handle(knowledge(body=BODY))
    padded = await handler.handle(knowledge(body=f"  {BODY}\n"))
    other = await handler.handle(knowledge(body="Retry with backoff."))

    assert padded.idempotency_key == first.idempotency_key
    assert other.idempotency_key != first.idempotency_key


async def test_same_explicit_key_with_another_body_is_refused() -> None:
    env = await make_review_env()
    handler = remember_handler(env, FakeFinder())
    await handler.handle(knowledge(idempotency_key="k-1"))
    before = snapshot(env)

    with pytest.raises(IdempotencyKeyReusedError):
        await handler.handle(knowledge(idempotency_key="k-1", body="Something else."))

    assert snapshot(env) == before


async def test_same_explicit_key_with_other_refines_is_refused_once_completed() -> None:
    env = await make_review_env()
    target = await seed_knowledge(env, "t1", title="Other")
    handler = remember_handler(env, FakeFinder())
    await handler.handle(knowledge(idempotency_key="k-1", refines=(target.value,)))

    with pytest.raises(IdempotencyKeyReusedError):
        await handler.handle(knowledge(idempotency_key="k-1"))


async def test_check_writes_nothing_and_reports_reconciliation() -> None:
    env = await make_review_env()
    existing = await seed_knowledge(env, "k0", title=TITLE)
    before = snapshot(env)

    result = await remember_handler(env, FakeFinder([existing.value])).handle(knowledge(check=True))

    assert snapshot(env) == before
    assert result.written is False
    assert result.record_id is None
    assert [d.id for d in result.reconciliation.duplicates] == [existing.value]


async def test_duplicate_is_reported_written_proposed_and_the_original_untouched() -> None:
    env = await make_review_env()
    existing = await seed_knowledge(env, "k0", title=TITLE, status=RecordStatusEnum.ACCEPTED)

    result = await remember_handler(env, FakeFinder([existing.value])).handle(knowledge())

    assert [(d.id, d.score, d.authority) for d in result.reconciliation.duplicates] == [
        (existing.value, 1.0, "authoritative")
    ]
    assert result.reconciliation.related == ()
    assert any("consolidation propose" in step for step in result.next_steps)
    assert result.status == "proposed"
    assert env.store.knowledge[existing.value].status is RecordStatusEnum.ACCEPTED
    assert len(env.store.knowledge) == 2
    assert env.store.assertions == {}


async def test_a_partly_alike_record_is_related_not_duplicate() -> None:
    env = await make_review_env()
    existing = await seed_knowledge(env, "k0", title="Retry policy for payments and refunds")

    result = await remember_handler(env, FakeFinder([existing.value])).handle(
        knowledge(body="Use retries with exponential backoff.")
    )

    assert result.reconciliation.duplicates == ()
    assert [r.id for r in result.reconciliation.related] == [existing.value]
    assert result.next_steps == ()


async def test_a_replay_is_not_its_own_duplicate() -> None:
    env = await make_review_env()
    first = await remember_handler(env, FakeFinder()).handle(knowledge())

    replay = await remember_handler(env, FakeFinder([first.record_id or ""])).handle(knowledge())

    assert replay.replayed is True
    assert replay.reconciliation.duplicates == ()


async def test_an_unavailable_lookup_warns_and_still_writes() -> None:
    env = await make_review_env()

    result = await remember_handler(env, FakeFinder(fail=True)).handle(knowledge())

    assert result.written is True
    assert result.reconciliation.duplicates == ()
    assert result.reconciliation.warnings


async def test_refines_proposes_an_assertion_from_the_new_record_with_its_sources_as_evidence() -> (
    None
):
    env = await make_review_env()
    target = await seed_knowledge(env, "t1", title="Skill guide")

    result = await remember_handler(env, FakeFinder()).handle(
        knowledge(refines=(target.value,), title="Skill guide gotcha", body="Mind the cache.")
    )

    (assertion,) = result.assertions
    stored = env.store.assertions[assertion.id or ""]
    assert (assertion.predicate, assertion.status) == ("refines", "proposed")
    assert stored.subject_id.value == result.record_id
    assert stored.object_id == target
    assert stored.status is RecordStatusEnum.PROPOSED
    assert len(stored.evidence_ids) == 1
    assert env.store.knowledge[target.value].status is RecordStatusEnum.PROPOSED


async def test_supersedes_proposes_a_supersedes_assertion_and_leaves_the_old_record() -> None:
    env = await make_review_env()
    old = await seed_knowledge(env, "t1", project="noesis", status=RecordStatusEnum.ACCEPTED)

    result = await remember_handler(env, FakeFinder()).handle(
        knowledge(
            supersedes=old,
            body="Use retries with jitter.",
            project=ProjectRef(key=Key(value="noesis")),
        )
    )

    (assertion,) = result.assertions
    assert (assertion.predicate, assertion.status) == ("supersedes", "proposed")
    assert env.store.knowledge[old.value].status is RecordStatusEnum.ACCEPTED


async def test_unknown_refines_target_fails_before_any_write() -> None:
    env = await make_review_env()
    before = snapshot(env)

    with pytest.raises(RecordNotFoundError):
        await remember_handler(env, FakeFinder()).handle(knowledge(refines=("0" * 25 + "9",)))
    with pytest.raises(CatalogEntryNotFoundError):
        await remember_handler(env, FakeFinder()).handle(
            knowledge(refines=("catalog:skill:missing",))
        )

    assert snapshot(env) == before


async def test_refines_target_of_the_wrong_kind_fails_before_any_write() -> None:
    env = await make_review_env()
    from tests.support.review_fakes import seed_experience

    experience = await seed_experience(env)
    before = snapshot(env)

    with pytest.raises(InvalidAssertionError):
        await remember_handler(env, FakeFinder()).handle(knowledge(refines=(experience.value,)))

    assert snapshot(env) == before


async def test_failed_assertion_keeps_the_record_and_a_rerun_completes_it() -> None:
    env = await make_review_env()
    target = await seed_knowledge(env, "t1", title="Skill guide")
    flaky = FlakyPropose(uow_factory=env.uow, clock=env.clock, ids=env.ids, schema=env.schema)
    handler = remember_handler(env, FakeFinder(), propose=flaky)
    command = knowledge(refines=(target.value,), idempotency_key="k-1")

    with pytest.raises(RememberPartiallyAppliedError) as raised:
        await handler.handle(command)

    assert raised.value.metadata["idempotency_key"] == "k-1"
    assert len(env.store.knowledge) == 2  # the target and the kept record
    assert env.store.assertions == {}

    completed = await handler.handle(command)

    assert completed.replayed is True
    assert len(env.store.knowledge) == 2
    assert len(env.store.assertions) == 1
    assert [a.status for a in completed.assertions] == ["proposed"]


async def test_experience_cannot_supersede() -> None:
    env = await make_review_env()
    old = await seed_knowledge(env, "t1")

    with pytest.raises(InvalidRecordError):
        await remember_handler(env, FakeFinder()).handle(
            RememberCommand(
                kind=RememberKindEnum.EXPERIENCE,
                space_key=DEFAULT_SPACE_KEY,
                actor=AGENT,
                sources=(COMMIT,),
                body="It failed.",
                supersedes=old,
            )
        )


async def test_remember_requires_a_source_and_for_knowledge_a_title_and_subtype() -> None:
    env = await make_review_env()
    handler = remember_handler(env, FakeFinder())

    with pytest.raises(InvalidRecordError):
        await handler.handle(knowledge(sources=()))
    with pytest.raises(InvalidRecordError):
        await handler.handle(knowledge(title=None))
    with pytest.raises(InvalidRecordError):
        await handler.handle(knowledge(knowledge_subtype=None))
