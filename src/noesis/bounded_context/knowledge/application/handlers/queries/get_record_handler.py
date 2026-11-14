"""Read any record by id, optionally at a revision."""

from noesis.bounded_context.knowledge.application.dtos import RecordDto, RevisionDto
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IRecordReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CORE_STEP,
    require_steps,
)
from noesis.bounded_context.knowledge.domain.value_objects import Key, RecordId, SpaceId
from noesis.exceptions import RecordNotFoundError, SpaceNotFoundError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.utils import FrozenObject


class GetRecordQuery(FrozenObject):
    """Fetch a record of the active space.

    Attributes:
        space_key: Key of the active space.
        record_id: The record's id.
        revision: Revision to show; the head when None.
    """

    space_key: Key
    record_id: RecordId
    revision: int | None = None


class GetRecordHandler(IHandler[GetRecordQuery, RecordDto]):
    """Returns the record DTO; another space's id is "not found"."""

    def __init__(self, *, read_repository: IRecordReadRepository, schema: IStoreSchema) -> None:
        self._read_repository: IRecordReadRepository = read_repository
        self._schema: IStoreSchema = schema

    async def handle(self, action: GetRecordQuery) -> RecordDto:
        """Read the record.

        Raises:
            StoreNotInitialisedError: The `core` schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            RecordNotFoundError: Unknown id or revision, or the record is in another space.
        """
        await require_steps(self._schema, CORE_STEP)
        space_id: SpaceId | None = await self._read_repository.get_space_id(action.space_key)
        if space_id is None:
            raise SpaceNotFoundError(
                f"No knowledge space has the key {action.space_key.value!r}.",
                {"space_key": action.space_key.value},
                next_steps=["Run `noesis store init` or check the configured space key."],
            )
        record: RecordDto | None = await self._read_repository.get_by_id(
            action.record_id, space_id=space_id
        )
        if record is None:
            raise RecordNotFoundError(
                f"No record {action.record_id.value} in this space.",
                {"record_id": action.record_id.value, "space_id": space_id.value},
                next_steps=["Check the id and the active space."],
            )
        if action.revision is None:
            return record
        revision: RevisionDto | None = await self._read_repository.get_revision(
            action.record_id, action.revision, space_id=space_id
        )
        if revision is None:
            raise RecordNotFoundError(
                f"Record {action.record_id.value} has no revision {action.revision}.",
                {"record_id": action.record_id.value, "revision": action.revision},
                next_steps=["Run `noesis record get` without --revision to see the head."],
            )
        return record.model_copy(update={"revision": revision, "sources": revision.sources})
