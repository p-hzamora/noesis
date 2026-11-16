"""Shared helpers of the consolidation handlers: progress reader, scope authority, saga errors."""

from collections.abc import Sequence

import pytest
from tests.support.knowledge_support import (
    AGENT,
    NOW,
    FakeKnowledgeStore,
    FakeKnowledgeUnitOfWork,
)

from noesis.bounded_context.knowledge.application.dtos import (
    ConsolidationDto,
    ConsolidationMemberDto,
    ConsolidationStepDto,
    ReviewStateDto,
)
from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IReviewStateReadRepository,
)
from noesis.bounded_context.knowledge.application.services.consolidation_support import (
    PROGRESS_VERSION,
    ConsolidationProgressReader,
    ConsolidationSupport,
    may_decide_scope,
    partial_failure,
    progress_version_of,
    requires_for_scope,
    steps_metadata,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ActorKindEnum,
    ConsolidationProgressEnum,
    RecordId,
    ReviewRequirementEnum,
    SpaceId,
)
from noesis.exceptions import (
    ConsolidationPartiallyAppliedError,
    RecordNotFoundError,
    RevisionConflictError,
)

pytestmark = pytest.mark.unit

SPACE: SpaceId = SpaceId(value=f"{99:026d}")
USER: Actor = Actor(kind=ActorKindEnum.USER, name="pablo")
PROJECT: RecordId = RecordId(value=f"{900:026d}")


def rid(number: int) -> str:
    return f"{number:026d}"


class StubStates(IReviewStateReadRepository):
    """Review states by id; ids not given are unknown to the space."""

    def __init__(self, statuses: dict[str, tuple[str, str]]) -> None:
        self._statuses = statuses

    async def get_states(self, ids: Sequence[RecordId], space_id: SpaceId) -> list[ReviewStateDto]:
        return [
            ReviewStateDto(
                record_id=item.value,
                record_type="knowledge",
                status=self._statuses[item.value][0],
                effective_status=self._statuses[item.value][1],
                authority="x",
            )
            for item in ids
            if item.value in self._statuses
        ]

    async def list_pending_effects(self, space_id: SpaceId) -> list[object]:  # type: ignore[override]
        return []


def dto(
    successor: str | None = rid(100), assertions: tuple[str, ...] = (rid(201), rid(202))
) -> ConsolidationDto:
    return ConsolidationDto(
        id=rid(500),
        space_id=SPACE.value,
        kind="graph_merge",
        state="materialised",
        fingerprint="sha256:x",
        rationale="r",
        successor_id=successor,
        produced_assertion_ids=assertions,
        version=2,
        created_by_kind="agent",
        created_by_name="claude",
        created_at="2026-11-14T12:00:00+00:00",
        members=(
            ConsolidationMemberDto(record_id=rid(1), at_revision=1),
            ConsolidationMemberDto(record_id=rid(2), at_revision=1),
        ),
    )


async def test_progress_reader_applied_and_lists_produced_records() -> None:
    reader = ConsolidationProgressReader(
        StubStates(
            {
                rid(100): ("accepted", "accepted"),
                rid(201): ("accepted", "accepted"),
                rid(202): ("accepted", "accepted"),
                rid(1): ("accepted", "superseded"),
                rid(2): ("accepted", "superseded"),
            }
        )
    )

    progress, produced = await reader.of(dto(), SPACE)

    assert progress is ConsolidationProgressEnum.APPLIED
    assert [p.record_id for p in produced] == [rid(100), rid(201), rid(202)]
    assert all(p.effective_status == "accepted" for p in produced)


async def test_progress_reader_partial_when_members_not_yet_superseded() -> None:
    reader = ConsolidationProgressReader(
        StubStates(
            {
                rid(100): ("accepted", "accepted"),
                rid(201): ("accepted", "accepted"),
                rid(202): ("proposed", "proposed"),
                rid(1): ("accepted", "superseded"),
                rid(2): ("accepted", "accepted"),
            }
        )
    )

    progress, _ = await reader.of(dto(), SPACE)

    assert progress is ConsolidationProgressEnum.PARTIALLY_APPLIED


async def test_progress_reader_successor_retracted() -> None:
    reader = ConsolidationProgressReader(StubStates({rid(100): ("retracted", "retracted")}))

    progress, produced = await reader.of(dto(), SPACE)

    assert progress is ConsolidationProgressEnum.SUCCESSOR_RETRACTED
    assert [p.record_id for p in produced] == [rid(100)]  # unknown records are skipped


async def test_progress_reader_unmaterialised_is_pending_without_produced() -> None:
    reader = ConsolidationProgressReader(StubStates({rid(1): ("accepted", "accepted")}))

    progress, produced = await reader.of(dto(successor=None, assertions=()), SPACE)

    assert progress is ConsolidationProgressEnum.PENDING
    assert produced == ()


@pytest.mark.parametrize(
    ("project_scoped", "expected"),
    [
        (True, ReviewRequirementEnum.AGENT_OR_USER),
        (False, ReviewRequirementEnum.USER),
    ],
)
def test_requires_for_scope(project_scoped: bool, expected: ReviewRequirementEnum) -> None:
    assert requires_for_scope(project_scoped=project_scoped) is expected


@pytest.mark.parametrize(
    ("actor", "project_scoped", "expected"),
    [
        (USER, True, True),
        (USER, False, True),
        (AGENT, True, True),
        (AGENT, False, False),
    ],
)
def test_may_decide_scope(actor: Actor, project_scoped: bool, expected: bool) -> None:
    assert may_decide_scope(actor, project_scoped=project_scoped) is expected


@pytest.mark.parametrize(
    ("project_id", "expected"),
    [
        (PROJECT, ReviewRequirementEnum.AGENT_OR_USER),
        (None, ReviewRequirementEnum.USER),
    ],
)
def test_support_requires_follows_review_authority(
    project_id: RecordId | None, expected: ReviewRequirementEnum
) -> None:
    assert ConsolidationSupport.requires(project_id) is expected
    assert ConsolidationSupport.may_decide(AGENT, project_id) is (project_id is not None)
    assert ConsolidationSupport.may_decide(USER, project_id) is True


def step(target: str, outcome: str, code: str | None = None) -> ConsolidationStepDto:
    return ConsolidationStepDto(
        target=target, target_type="assertion", outcome=outcome, error_code=code
    )


def test_steps_metadata_is_json_in_order() -> None:
    assert steps_metadata([step("a", "accepted"), step("b", "failed", "E")]) == [
        {"target": "a", "target_type": "assertion", "outcome": "accepted", "error_code": None},
        {"target": "b", "target_type": "assertion", "outcome": "failed", "error_code": "E"},
    ]


def test_partial_failure_splits_steps_and_names_cause() -> None:
    cause = RecordNotFoundError("gone", {})

    error = partial_failure(
        consolidation_id="C1",
        steps=[
            step("a", "accepted"),
            step("b", "already_accepted"),
            step("c", "failed", "KNOWLEDGE_201_RECORD_NOT_FOUND"),
            step("d", "not_run"),
        ],
        progress="partially_applied",
        retry="noesis consolidation accept C1",
        cause=cause,
    )

    assert isinstance(error, ConsolidationPartiallyAppliedError)
    assert error.error_code == "KNOWLEDGE_295_CONSOLIDATION_PARTIALLY_APPLIED"
    assert error.metadata["completed"] == ["a", "b"]
    assert error.metadata["failed"] == ["c"]
    assert error.metadata["not_run"] == ["d"]
    assert error.metadata["consolidation_id"] == "C1"
    assert error.metadata["progress"] == "partially_applied"
    assert error.metadata["cause_code"] == cause.error_code
    assert error.metadata["cause"] == "gone"
    assert len(error.metadata["steps"]) == 4  # type: ignore[arg-type]
    assert "2 step(s) done, 1 failed, 1 not run" in error.message
    assert error.next_steps[0] == "noesis consolidation accept C1"
    assert "C1" in error.next_steps[1]


def test_partial_failure_without_cause_omits_cause_keys() -> None:
    error = partial_failure(
        consolidation_id="C1", steps=[step("a", "done")], progress="pending", retry="again"
    )

    assert "cause_code" not in error.metadata
    assert "cause" not in error.metadata


def entry(extra: dict[str, object]) -> LedgerEntry:
    return LedgerEntry(
        space_id=SPACE,
        key="k",
        command="consolidation.propose",
        fingerprint="f",
        extra=extra,
        recorded_at=NOW,
    )


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ({PROGRESS_VERSION: 4}, 4),
        ({}, 1),
        ({PROGRESS_VERSION: "3"}, 1),
        ({PROGRESS_VERSION: None}, 1),
    ],
)
def test_progress_version_of(extra: dict[str, object], expected: int) -> None:
    assert progress_version_of(entry(extra)) == expected


async def committed_pending(store: FakeKnowledgeStore) -> None:
    uow = FakeKnowledgeUnitOfWork(store)
    await uow.ledger.record(entry({PROGRESS_VERSION: 1, "stage": "opened"}))
    await uow.commit()


async def test_ledger_update_extra_compares_and_bumps_progress_version() -> None:
    store = FakeKnowledgeStore()
    await committed_pending(store)
    uow = FakeKnowledgeUnitOfWork(store)

    await uow.ledger.update_extra(
        SPACE, "k", expected_progress_version=1, extra={"stage": "materialised"}
    )
    await uow.commit()

    stored = store.ledger[(SPACE.value, "k")]
    assert stored.extra == {"stage": "materialised", PROGRESS_VERSION: 2}
    assert progress_version_of(stored) == 2


async def test_ledger_update_extra_rejects_stale_version() -> None:
    store = FakeKnowledgeStore()
    await committed_pending(store)
    first = FakeKnowledgeUnitOfWork(store)
    await first.ledger.update_extra(SPACE, "k", expected_progress_version=1, extra={"a": 1})
    await first.commit()

    with pytest.raises(RevisionConflictError):
        await FakeKnowledgeUnitOfWork(store).ledger.update_extra(
            SPACE, "k", expected_progress_version=1, extra={"b": 2}
        )

    assert store.ledger[(SPACE.value, "k")].extra == {"a": 1, PROGRESS_VERSION: 2}


async def test_ledger_update_extra_rejects_unknown_key() -> None:
    with pytest.raises(RevisionConflictError):
        await FakeKnowledgeUnitOfWork(FakeKnowledgeStore()).ledger.update_extra(
            SPACE, "missing", expected_progress_version=1, extra={}
        )


async def test_ledger_update_extra_is_dropped_on_rollback() -> None:
    store = FakeKnowledgeStore()
    await committed_pending(store)
    uow = FakeKnowledgeUnitOfWork(store)
    await uow.ledger.update_extra(SPACE, "k", expected_progress_version=1, extra={"x": 1})

    await uow.rollback()

    assert store.ledger[(SPACE.value, "k")].extra == {PROGRESS_VERSION: 1, "stage": "opened"}
