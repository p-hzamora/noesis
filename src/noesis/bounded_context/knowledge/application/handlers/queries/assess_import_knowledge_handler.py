"""Predict what importing one note would do, without writing anything."""

from noesis.bounded_context.knowledge.application.dtos import ImportKnowledgeResultDto
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IImportCandidateReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.import_outcomes import result_of
from noesis.bounded_context.knowledge.application.services.import_planner import ImportPlanner
from noesis.bounded_context.knowledge.application.services.import_request import (
    ImportRequest,
    PreparedImport,
)
from noesis.bounded_context.knowledge.domain.value_objects import ImportDecision
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock


class AssessImportKnowledgeQuery(ImportRequest):
    """Assess one note or file; the fields are those of `ImportRequest`."""


class AssessImportKnowledgeHandler(IHandler[AssessImportKnowledgeQuery, ImportKnowledgeResultDto]):
    """Validates, redacts, reads the candidates and decides; no ledger read, no write."""

    def __init__(
        self,
        *,
        uow_factory: KnowledgeUnitOfWorkFactory,
        clock: IClock,
        ids: IRecordIdGenerator,
        schema: IStoreSchema,
        candidates: IImportCandidateReadRepository,
        can_link_successor: bool,
    ) -> None:
        self._can_link_successor: bool = can_link_successor
        self._planner: ImportPlanner = ImportPlanner(
            uow_factory=uow_factory, clock=clock, ids=ids, schema=schema, candidates=candidates
        )

    async def handle(self, action: AssessImportKnowledgeQuery) -> ImportKnowledgeResultDto:
        """The outcome an apply of the same request would produce, from the current state.

        Raises:
            InvalidRecordError: A blank title or body.
            StoreNotInitialisedError: The `core` schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
        """
        prepared: PreparedImport = await self._planner.prepare(action)
        decision: ImportDecision = await self._planner.decide(
            prepared, can_link_successor=self._can_link_successor
        )
        return result_of(decision, prepared)
