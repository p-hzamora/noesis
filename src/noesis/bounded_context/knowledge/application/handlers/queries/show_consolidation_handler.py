"""Show one consolidation with its derived progress and current member labels."""

from noesis.bounded_context.knowledge.application.dtos import (
    CandidateSnapshotDto,
    ConsolidationDetailDto,
    ConsolidationDto,
    ConsolidationMemberDto,
    ConsolidationPageDto,
)
from noesis.bounded_context.knowledge.application.ports.consolidation import (
    IConsolidationReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IRecordReadRepository,
    IReviewStateReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.consolidation_support import (
    ConsolidationProgressReader,
    may_decide_scope,
    requires_for_scope,
)
from noesis.bounded_context.knowledge.application.services.review_support import require_space_id
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CONSOLIDATION_STEP,
    CORE_STEP,
    REVIEW_STEP,
    require_steps,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ConsolidationId,
    ConsolidationStateEnum,
    Key,
    RecordId,
    SpaceId,
)
from noesis.exceptions import ConsolidationNotFoundError, InvalidConsolidationError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject

ACCEPTANCE_NOTE: str = (
    "Acceptance started: the members stay reserved even if the successor is later retracted; "
    "review the produced records by hand if it must be undone."
)
OPENED_NOTE: str = (
    "The proposals are incomplete: run the propose command again with the same idempotency key."
)
DEFAULT_LIST_LIMIT: int = 20
MAX_LIST_LIMIT: int = 100


class ShowConsolidationQuery(FrozenObject):
    """One consolidation.

    Attributes:
        space_key: Key of the active space.
        actor: Who asks; decides `decidable_by_caller`.
        consolidation_id: The consolidation.
    """

    space_key: Key
    actor: Actor
    consolidation_id: ConsolidationId


class ShowConsolidationHandler(IHandler[ShowConsolidationQuery, ConsolidationDetailDto]):
    """Reads the aggregate, then derives progress from the current review state."""

    def __init__(
        self,
        *,
        read_repository: IConsolidationReadRepository,
        records: IRecordReadRepository,
        schema: IStoreSchema,
        states: IReviewStateReadRepository,
    ) -> None:
        self._read: IConsolidationReadRepository = read_repository
        self._records: IRecordReadRepository = records
        self._schema: IStoreSchema = schema
        self._progress: ConsolidationProgressReader = ConsolidationProgressReader(states)

    async def handle(self, action: ShowConsolidationQuery) -> ConsolidationDetailDto:
        """Show it.

        Raises:
            StoreNotInitialisedError: A required schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            ConsolidationNotFoundError: No such consolidation in the space.
        """
        await require_steps(self._schema, CORE_STEP, REVIEW_STEP, CONSOLIDATION_STEP)
        space_id: SpaceId = await require_space_id(self._records, action.space_key)
        stored: ConsolidationDto | None = await self._read.get(action.consolidation_id, space_id)
        if stored is None:
            raise ConsolidationNotFoundError(
                f"No consolidation {action.consolidation_id.value} in this space.",
                {"consolidation_id": action.consolidation_id.value},
                next_steps=["Run `noesis consolidation list`."],
            )
        labels: dict[str, CandidateSnapshotDto] = {
            s.record_id: s
            for s in await self._read.describe(
                [RecordId(value=m.record_id) for m in stored.members], space_id
            )
        }
        members: tuple[ConsolidationMemberDto, ...] = tuple(
            m.model_copy(
                update={
                    "title": labels[m.record_id].title if m.record_id in labels else None,
                    "effective_status": (
                        labels[m.record_id].effective_status if m.record_id in labels else None
                    ),
                }
            )
            for m in stored.members
        )
        detail: ConsolidationDto = stored.model_copy(update={"members": members})
        progress, produced = await self._progress.of(detail, space_id)
        scoped: bool = stored.project_key is not None
        return ConsolidationDetailDto(
            consolidation=detail,
            progress=progress.value,
            produced=produced,
            requires=requires_for_scope(project_scoped=scoped).value,
            decidable_by_caller=may_decide_scope(action.actor, project_scoped=scoped),
            membership_note=(
                ACCEPTANCE_NOTE
                if stored.state == ConsolidationStateEnum.ACCEPTANCE_STARTED.value
                else OPENED_NOTE
                if stored.state == ConsolidationStateEnum.OPENED.value
                else None
            ),
        )


class ListConsolidationsQuery(FrozenObject):
    """A page of consolidations.

    Attributes:
        space_key: Key of the active space.
        project: List this project's consolidations.
        space_wide: List the space-wide ones.
        state: Only this state.
        limit: Page size, 1..100.
        cursor: The previous page's `next_cursor`.
    """

    space_key: Key
    project: Key | None = None
    space_wide: bool = False
    state: ConsolidationStateEnum | None = None
    limit: int = DEFAULT_LIST_LIMIT
    cursor: str | None = None


class ListConsolidationsHandler(IHandler[ListConsolidationsQuery, ConsolidationPageDto]):
    """Lists consolidations of one project or of the space-wide records, ascending id."""

    def __init__(
        self,
        *,
        read_repository: IConsolidationReadRepository,
        records: IRecordReadRepository,
        schema: IStoreSchema,
    ) -> None:
        self._read: IConsolidationReadRepository = read_repository
        self._records: IRecordReadRepository = records
        self._schema: IStoreSchema = schema

    async def handle(self, action: ListConsolidationsQuery) -> ConsolidationPageDto:
        """List one page.

        Raises:
            InvalidConsolidationError: Not exactly one of a project and the space-wide scope,
                or a limit out of bounds.
            StoreNotInitialisedError: A required schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
        """
        if (action.project is not None) == action.space_wide:
            raise InvalidConsolidationError(
                "Choose exactly one of a project or the space-wide scope.",
                next_steps=["Pass one of --project or --global."],
            )
        if not 1 <= action.limit <= MAX_LIST_LIMIT:
            raise InvalidConsolidationError(
                f"The limit is 1..{MAX_LIST_LIMIT}.", {"limit": action.limit}
            )
        await require_steps(self._schema, CORE_STEP, REVIEW_STEP, CONSOLIDATION_STEP)
        space_id: SpaceId = await require_space_id(self._records, action.space_key)
        return await self._read.list_consolidations(
            space_id,
            project=action.project,
            state=action.state,
            limit=action.limit,
            cursor=action.cursor,
        )
