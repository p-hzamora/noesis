"""`ISupersessionProposer` over C4's `assertion propose` (predicate `supersedes`, C3 Q-015)."""

from noesis.bounded_context.knowledge.application.dtos import ProposeAssertionResultDto
from noesis.bounded_context.knowledge.application.handlers.commands.propose_assertion_handler import (
    ProposeAssertionCommand,
    ProposeAssertionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.supersession import (
    ISupersessionProposer,
)
from noesis.bounded_context.knowledge.application.services.inputs import (
    ExistingSourceInput,
    ProjectRef,
)
from noesis.bounded_context.knowledge.domain.entities import KnowledgeSpace, Project
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    AssertionPredicateEnum,
    RecordId,
    RecordReference,
    SpaceId,
)
from noesis.exceptions import SpaceNotFoundError


class AssertionSupersessionProposer(ISupersessionProposer):
    """Proposes `subject supersedes object` through C4's `ProposeAssertionHandler`.

    C4's command names the space by key and cites sources as inputs, so the ids C3 holds are
    translated: the space id to its key, each Source id to an `ExistingSourceInput` (the same
    Source node, no new one), and the assertion's project to the object's project (C4 requires a
    `supersedes` to share its object's project).
    """

    def __init__(
        self, *, uow_factory: KnowledgeUnitOfWorkFactory, propose: ProposeAssertionHandler
    ) -> None:
        self._uow_factory: KnowledgeUnitOfWorkFactory = uow_factory
        self._propose: ProposeAssertionHandler = propose

    async def propose(
        self,
        *,
        subject_id: RecordId,
        object_id: RecordId,
        rationale: str,
        source_ids: tuple[RecordId, ...],
        actor: Actor,
        idempotency_key: str,
        space_id: SpaceId,
    ) -> RecordId:
        """Propose `subject_id` supersedes `object_id`; a repeat with the same key replays.

        Raises:
            SpaceNotFoundError: No space has `space_id`.
            InvalidAssertionError, DuplicateAssertionError, StoreNotInitialisedError: From C4
                (an object outside the space is C4's `InvalidAssertionError`).
        """
        async with self._uow_factory() as uow:
            space: KnowledgeSpace | None = await uow.spaces.get(space_id)
            if space is None:
                raise SpaceNotFoundError(
                    f"No knowledge space has the id {space_id.value}.",
                    {"space_id": space_id.value},
                )
            found: list[RecordReference] = await uow.record_references.describe(
                [object_id], space_id
            )
            project: Project | None = None
            if found and found[0].project_id is not None:
                project = await uow.projects.get(found[0].project_id, space_id=space_id)
        result: ProposeAssertionResultDto = await self._propose.handle(
            ProposeAssertionCommand(
                space_key=space.key,
                actor=actor,
                apply=True,
                idempotency_key=idempotency_key,
                predicate=AssertionPredicateEnum.SUPERSEDES,
                subject_id=subject_id,
                object_id=object_id,
                rationale=rationale,
                project=ProjectRef(key=project.key) if project is not None else None,
                sources=tuple(ExistingSourceInput(source_id=source) for source in source_ids),
            )
        )
        return RecordId(value=result.id)
