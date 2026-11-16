"""Propose an assertion about two records."""

from collections.abc import Sequence

from noesis.bounded_context.knowledge.application.dtos import ProposeAssertionResultDto
from noesis.bounded_context.knowledge.application.dtos.pending_record_change import (
    PendingRecordChange,
)
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.inputs import ProjectRef, SourceInput
from noesis.bounded_context.knowledge.application.services.record_changes import (
    pending_changes_from,
)
from noesis.bounded_context.knowledge.application.services.review_support import (
    Prelude,
    ReviewMutationCommand,
    ReviewSupport,
    result_extra,
    result_from,
)
from noesis.bounded_context.knowledge.application.services.secret_redactor import SecretRedactor
from noesis.bounded_context.knowledge.domain.entities import Assertion
from noesis.bounded_context.knowledge.domain.repositories.i_assertion_repository import (
    IAssertionRepository,
)
from noesis.bounded_context.knowledge.domain.services import AssertionStatementPolicy
from noesis.bounded_context.knowledge.domain.value_objects import (
    Applicability,
    AssertionPredicateEnum,
    RecordId,
    RecordReference,
    SpaceId,
    StatementKey,
    Tag,
)
from noesis.exceptions import (
    DuplicateAssertionError,
    EntryAlreadyExistsError,
    InvalidAssertionError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock

PROPOSE_ASSERTION_COMMAND: str = "assertion.propose"


class ProposeAssertionCommand(ReviewMutationCommand):
    """Propose an assertion.

    Attributes:
        predicate: How subject relates to object.
        subject_id: Subject record.
        object_id: Object record.
        evidence_ids: Records that evidence it.
        rationale: Why.
        project: The project it applies to; space-wide when None.
        tags: Tags narrowing the scope.
        sources: What it rests on; at least one.
    """

    predicate: AssertionPredicateEnum
    subject_id: RecordId
    object_id: RecordId
    evidence_ids: tuple[RecordId, ...] = ()
    rationale: str
    project: ProjectRef | None = None
    tags: tuple[Tag, ...] = ()
    sources: tuple[SourceInput, ...]


class ProposeAssertionHandler(IHandler[ProposeAssertionCommand, ProposeAssertionResultDto]):
    """Validates references, kinds and the live statement, then stores a `proposed` assertion."""

    def __init__(
        self,
        *,
        uow_factory: KnowledgeUnitOfWorkFactory,
        clock: IClock,
        ids: IRecordIdGenerator,
        schema: IStoreSchema,
    ) -> None:
        self._support: ReviewSupport = ReviewSupport(
            uow_factory=uow_factory, clock=clock, ids=ids, schema=schema
        )
        self._ids: IRecordIdGenerator = ids

    async def handle(self, action: ProposeAssertionCommand) -> ProposeAssertionResultDto:
        """Propose, or replay the earlier identical proposal.

        Raises:
            StoreNotInitialisedError: A required schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            IdempotencyKeyReusedError: The key was used for a different request.
            InvalidAssertionError: A reference is unknown in the space, or an invariant or the
                kind matrix is broken; the metadata names the field.
            DuplicateAssertionError: A live identical statement exists.
            ReferenceNotInSpaceError: An existing source id is not in the space.
        """
        support: ReviewSupport = self._support
        prelude: Prelude = await support.prelude(action, PROPOSE_ASSERTION_COMMAND)
        if prelude.replay is not None:
            return result_from(prelude.replay, ProposeAssertionResultDto)
        space_id: SpaceId = prelude.space_id
        known_project: RecordId | None = await self._find_project(space_id, action)
        # an unknown project has no id yet; a stand-in never equals another record's project
        project_id: RecordId | None = known_project or (
            self._ids.new_record_id() if action.project else None
        )
        references: dict[str, RecordReference] = await self._describe(action, space_id)
        subject: RecordReference = references[action.subject_id.value]
        object_: RecordReference = references[action.object_id.value]
        evidence: tuple[RecordReference, ...] = tuple(
            references[i.value] for i in dict.fromkeys(action.evidence_ids)
        )
        rationale: str = SecretRedactor.redact(action.rationale)[0]
        Assertion.check_creation(
            subject_id=action.subject_id,
            object_id=action.object_id,
            rationale=rationale,
            source_count=len(action.sources),
            evidence_ids=action.evidence_ids,
        )
        AssertionStatementPolicy.check(
            space_id=space_id,
            predicate=action.predicate,
            project_id=project_id,
            subject=subject,
            object=object_,
            evidence=evidence,
        )
        await support.references.check_existing_sources(space_id, action.sources)
        if known_project is not None or action.project is None:
            await self._reject_live_duplicate(action, space_id, project_id)
        project_id = await support.references.ensure_project(space_id, action.project)
        source_ids: tuple[RecordId, ...] = await support.references.ensure_sources(
            space_id, action.sources
        )
        assertion: Assertion = Assertion.propose(
            id=self._ids.new_record_id(),
            space_id=space_id,
            predicate=action.predicate,
            subject_id=action.subject_id,
            object_id=action.object_id,
            subject_at_revision=subject.head_revision,
            object_at_revision=object_.head_revision,
            evidence_ids=action.evidence_ids,
            rationale=rationale,
            actor=action.actor,
            applicability=Applicability(project_id=project_id, tags=frozenset(action.tags)),
            source_ids=source_ids,
            now=support.clock.now(),
        )
        result: ProposeAssertionResultDto = ProposeAssertionResultDto(
            id=assertion.id.value,
            predicate=assertion.predicate.value,
            subject_id=assertion.subject_id.value,
            subject_at_revision=assertion.subject_at_revision,
            object_id=assertion.object_id.value,
            object_at_revision=assertion.object_at_revision,
            evidence_ids=tuple(i.value for i in assertion.evidence_ids),
            project_key=action.project.key.value if action.project else None,
            tags=tuple(t.value for t in assertion.applicability.sorted_tags),
            status=assertion.status.value,
            space_id=space_id.value,
        )
        key: StatementKey = self._statement(action, space_id, project_id)
        try:
            async with support.uow_factory() as uow:
                raced: LedgerEntry | None = await support.raced(
                    uow, action, PROPOSE_ASSERTION_COMMAND, prelude
                )
                if raced is not None:
                    return result_from(raced, ProposeAssertionResultDto)
                repository: IAssertionRepository = uow.assertions
                live: Assertion | None = await repository.get_live_by_statement(key)
                if live is not None:
                    raise DuplicateAssertionError(
                        f"Assertion {live.id.value} already states the same.",
                        {"existing_id": live.id.value},
                        next_steps=["Use the existing assertion id."],
                    )
                if not action.apply:
                    return result
                changes: list[PendingRecordChange] = pending_changes_from(
                    assertion.collect_events(),
                    record_type="assertion",
                    status=assertion.status.value,
                    occurred_at=assertion.created_at,
                )
                await repository.add(assertion)
                await uow.ledger.record(
                    LedgerEntry(
                        space_id=space_id,
                        key=action.idempotency_key or "",
                        command=PROPOSE_ASSERTION_COMMAND,
                        fingerprint=prelude.fingerprint,
                        record_id=assertion.id,
                        extra=result_extra(result),
                        recorded_at=support.clock.now(),
                    )
                )
                for change in changes:
                    await uow.changes.append(change)
                await uow.commit()
        except EntryAlreadyExistsError as error:
            winner: LedgerEntry = await support.winner(
                error, action, PROPOSE_ASSERTION_COMMAND, prelude
            )
            return result_from(winner, ProposeAssertionResultDto)
        return result

    @staticmethod
    def _statement(
        action: ProposeAssertionCommand, space_id: SpaceId, project_id: RecordId | None
    ) -> StatementKey:
        return StatementKey(
            space_id=space_id,
            predicate=action.predicate,
            subject_id=action.subject_id,
            object_id=action.object_id,
            project_id=project_id,
        )

    async def _find_project(
        self, space_id: SpaceId, action: ProposeAssertionCommand
    ) -> RecordId | None:
        """The project's id when it exists; nothing is created."""
        if action.project is None:
            return None
        async with self._support.uow_factory() as uow:
            found = await uow.projects.get_by_key(action.project.key, space_id=space_id)
        return found.id if found else None

    async def _reject_live_duplicate(
        self, action: ProposeAssertionCommand, space_id: SpaceId, project_id: RecordId | None
    ) -> None:
        async with self._support.uow_factory() as uow:
            live: Assertion | None = await uow.assertions.get_live_by_statement(
                self._statement(action, space_id, project_id)
            )
        if live is not None:
            raise DuplicateAssertionError(
                f"Assertion {live.id.value} already states the same.",
                {"existing_id": live.id.value},
                next_steps=["Use the existing assertion id."],
            )

    async def _describe(
        self, action: ProposeAssertionCommand, space_id: SpaceId
    ) -> dict[str, RecordReference]:
        ids: Sequence[RecordId] = (action.subject_id, action.object_id, *action.evidence_ids)
        async with self._support.uow_factory() as uow:
            found: list[RecordReference] = await uow.record_references.describe(ids, space_id)
        by_id: dict[str, RecordReference] = {r.record_id.value: r for r in found}
        for field, record_id in (
            ("subject", action.subject_id),
            ("object", action.object_id),
            *(("evidence", i) for i in action.evidence_ids),
        ):
            if record_id.value not in by_id:
                raise InvalidAssertionError(
                    f"The {field} {record_id.value} does not exist in this space.",
                    {"field": field, "record_id": record_id.value},
                    next_steps=[f"Fix the {field}."],
                )
        return by_id
