"""What the consolidation handlers share: schema, member snapshots, progress and step results."""

from collections.abc import Sequence
from dataclasses import dataclass

from noesis.bounded_context.knowledge.application.dtos import (
    ConsolidationDto,
    ConsolidationStepDto,
    ProducedRecordDto,
    ReviewStateDto,
)
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IReviewStateReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.ports.uow import IKnowledgeUnitOfWork
from noesis.bounded_context.knowledge.application.services.review_support import (
    Prelude,
    ReviewMutationCommand,
    ReviewSupport,
)
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CONSOLIDATION_STEP,
    CORE_STEP,
    REVIEW_STEP,
    require_steps,
)
from noesis.bounded_context.knowledge.domain.entities import Knowledge
from noesis.bounded_context.knowledge.domain.services import (
    ConsolidationProgressPolicy,
    ReviewAuthorityPolicy,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ActorKindEnum,
    Applicability,
    ConsolidationProgressEnum,
    MemberCandidate,
    RecordId,
    RecordTypeEnum,
    ReviewRequirementEnum,
    SpaceId,
)
from noesis.exceptions import (
    AppException,
    ConsolidationPartiallyAppliedError,
    InfrastructureException,
)
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.domain import JsonValue

PROGRESS_VERSION: str = "progress_version"
"""`LedgerEntry.extra` key of the compare-and-set token of a pending outer command."""


@dataclass(frozen=True, slots=True)
class MemberSnapshot:
    """What a locking read of the members found.

    Attributes:
        candidates: One per requested id, in the order given.
        source_ids: Sources of each existing member's head revision.
        knowledge: Each existing Knowledge member.
    """

    candidates: tuple[MemberCandidate, ...]
    source_ids: dict[str, tuple[RecordId, ...]]
    knowledge: dict[str, Knowledge]


class ConsolidationProgressReader:
    """Derives a consolidation's progress and the produced records' states from review state."""

    def __init__(self, states: IReviewStateReadRepository) -> None:
        self._states: IReviewStateReadRepository = states

    async def of(
        self, consolidation: ConsolidationDto, space_id: SpaceId
    ) -> tuple[ConsolidationProgressEnum, tuple[ProducedRecordDto, ...]]:
        """Derived progress and the produced records' current states."""
        produced_ids: list[RecordId] = [
            RecordId(value=item)
            for item in (
                *([consolidation.successor_id] if consolidation.successor_id else []),
                *consolidation.produced_assertion_ids,
            )
        ]
        member_ids: list[RecordId] = [RecordId(value=m.record_id) for m in consolidation.members]
        states: dict[str, ReviewStateDto] = {
            state.record_id: state
            for state in await self._states.get_states([*produced_ids, *member_ids], space_id)
        }

        def effective(record_id: str) -> str | None:
            state: ReviewStateDto | None = states.get(record_id)
            return state.effective_status if state else None

        progress: ConsolidationProgressEnum = ConsolidationProgressPolicy.derive(
            materialised=consolidation.successor_id is not None,
            successor_status=effective(consolidation.successor_id or ""),
            assertion_statuses=[effective(item) for item in consolidation.produced_assertion_ids],
            member_statuses=[effective(m.record_id) for m in consolidation.members],
        )
        produced: tuple[ProducedRecordDto, ...] = tuple(
            ProducedRecordDto(
                record_id=item.value,
                record_type=states[item.value].record_type,
                status=states[item.value].status,
                effective_status=states[item.value].effective_status,
            )
            for item in produced_ids
            if item.value in states
        )
        return progress, produced


def requires_for_scope(*, project_scoped: bool) -> ReviewRequirementEnum:
    """`agent_or_user` for members of one named project, else `user`."""
    return ReviewRequirementEnum.AGENT_OR_USER if project_scoped else ReviewRequirementEnum.USER


def may_decide_scope(actor: Actor, *, project_scoped: bool) -> bool:
    """A user decides every scope; an agent only a named project's."""
    return actor.kind is ActorKindEnum.USER or project_scoped


class ConsolidationSupport:
    """Dependencies and steps common to every consolidation command handler."""

    def __init__(
        self,
        *,
        uow_factory: KnowledgeUnitOfWorkFactory,
        clock: IClock,
        ids: IRecordIdGenerator,
        schema: IStoreSchema,
        states: IReviewStateReadRepository,
    ) -> None:
        self.uow_factory: KnowledgeUnitOfWorkFactory = uow_factory
        self.clock: IClock = clock
        self.ids: IRecordIdGenerator = ids
        self.schema: IStoreSchema = schema
        self.states: IReviewStateReadRepository = states
        self.review: ReviewSupport = ReviewSupport(
            uow_factory=uow_factory, clock=clock, ids=ids, schema=schema
        )
        self.progress: ConsolidationProgressReader = ConsolidationProgressReader(states)

    async def progress_of(
        self, consolidation: ConsolidationDto, space_id: SpaceId
    ) -> tuple[ConsolidationProgressEnum, tuple[ProducedRecordDto, ...]]:
        """Derived progress and the produced records' current states."""
        return await self.progress.of(consolidation, space_id)

    async def require_schema(self) -> None:
        """Fail before any write unless the `core`, `review` and `consolidation` steps apply."""
        await require_steps(self.schema, CORE_STEP, REVIEW_STEP, CONSOLIDATION_STEP)

    async def prelude(self, command: ReviewMutationCommand, ledger_command: str) -> Prelude:
        """Schema, space, then (when applying) the key and the ledger replay."""
        await self.require_schema()
        return await self.review.prelude(command, ledger_command)

    async def snapshot_members(
        self, uow: IKnowledgeUnitOfWork, ids: Sequence[RecordId], space_id: SpaceId, *, lock: bool
    ) -> MemberSnapshot:
        """Read the members; with `lock` each is locked in ascending id, the order that avoids deadlock."""
        knowledge: dict[str, Knowledge] = {}
        for record_id in sorted(set(ids), key=lambda item: item.value):
            found: Knowledge | None = await (
                uow.knowledge.get_for_update(record_id, space_id=space_id)
                if lock
                else uow.knowledge.get(record_id, space_id=space_id)
            )
            if found is not None:
                knowledge[record_id.value] = found
        references = {
            reference.record_id.value: reference
            for reference in await uow.record_references.describe(list(ids), space_id)
        }
        candidates: list[MemberCandidate] = []
        for record_id in ids:
            reference = references.get(record_id.value)
            record: Knowledge | None = knowledge.get(record_id.value)
            if reference is None:
                candidates.append(MemberCandidate(record_id=record_id, found=False))
            elif reference.record_type is not RecordTypeEnum.KNOWLEDGE or record is None:
                candidates.append(MemberCandidate(record_id=record_id, is_knowledge=False))
            else:
                candidates.append(
                    MemberCandidate(
                        record_id=record_id,
                        effective_status=reference.effective_status,
                        subtype=record.subtype,
                        project_id=record.applicability.project_id,
                        head_revision=record.head_number,
                        tags=tuple(tag.value for tag in record.applicability.sorted_tags),
                    )
                )
        return MemberSnapshot(
            candidates=tuple(candidates),
            source_ids={key: item.head.source_ids for key, item in knowledge.items()},
            knowledge=knowledge,
        )

    @staticmethod
    def requires(project_id: RecordId | None) -> ReviewRequirementEnum:
        """`agent_or_user` for one named project, else `user`."""
        return ReviewAuthorityPolicy.requires([Applicability(project_id=project_id)])

    @staticmethod
    def may_decide(actor: Actor, project_id: RecordId | None) -> bool:
        """Whether `actor` may decide a consolidation of that project."""
        return ReviewAuthorityPolicy.may_decide(actor, [Applicability(project_id=project_id)])


def steps_metadata(steps: Sequence[ConsolidationStepDto]) -> list[JsonValue]:
    """The steps as JSON values, split by outcome in the order they ran."""
    return [step.model_dump(mode="json") for step in steps]


def partial_failure(
    *,
    consolidation_id: str,
    steps: Sequence[ConsolidationStepDto],
    progress: str,
    retry: str,
    cause: AppException | None = None,
) -> ConsolidationPartiallyAppliedError:
    """The error for a saga that stopped after some of its steps committed.

    Args:
        consolidation_id: The consolidation the steps belong to.
        steps: Every step, completed, failed or not run.
        progress: The derived progress after the failure.
        retry: The command that resumes it.
        cause: The first failure, when there is one.
    """
    completed: list[str] = [s.target for s in steps if s.outcome not in ("failed", "not_run")]
    failed: list[str] = [s.target for s in steps if s.outcome == "failed"]
    not_run: list[str] = [s.target for s in steps if s.outcome == "not_run"]
    metadata: dict[str, JsonValue] = {
        "consolidation_id": consolidation_id,
        "progress": progress,
        "steps": steps_metadata(steps),
        "completed": [*completed],
        "failed": [*failed],
        "not_run": [*not_run],
    }
    if cause is not None:
        metadata["cause_code"] = cause.error_code
        metadata["cause"] = cause.message
    return ConsolidationPartiallyAppliedError(
        f"Consolidation {consolidation_id} stopped part-way: {len(completed)} step(s) done, "
        f"{len(failed)} failed, {len(not_run)} not run. Earlier steps stay committed.",
        metadata,
        next_steps=[
            retry,
            f"Run `noesis consolidation show {consolidation_id}` to see where it stands.",
        ],
    )


def is_store_failure(error: AppException) -> bool:
    """Whether a step failed because the store (or another integration) is unreachable.

    Such a failure interrupts a saga: later steps would only fail the same way.
    """
    return isinstance(error, InfrastructureException) or error.error_code.startswith("INTEGRATION")


def progress_version_of(entry: LedgerEntry) -> int:
    """The compare-and-set token stored in a pending entry's `extra`."""
    value: JsonValue = entry.extra.get(PROGRESS_VERSION)
    return value if isinstance(value, int) else 1
