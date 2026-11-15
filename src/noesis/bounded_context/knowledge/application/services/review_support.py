"""What the review command handlers share: the common prelude, ledger replay and space lookup."""

from dataclasses import dataclass
from typing import Any

from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IRecordReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.ports.uow import IKnowledgeUnitOfWork
from noesis.bounded_context.knowledge.application.services.idempotency import (
    fingerprint_request,
    read_ledger,
    replay_of,
)
from noesis.bounded_context.knowledge.application.services.record_reference_resolver import (
    RecordReferenceResolver,
)
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CORE_STEP,
    REVIEW_STEP,
    require_steps,
)
from noesis.bounded_context.knowledge.domain.value_objects import Actor, Key, SpaceId
from noesis.exceptions import EntryAlreadyExistsError, InvalidRecordError, SpaceNotFoundError
from noesis.shared_kernel.application.dtos import BaseDto
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.domain import JsonValue
from noesis.utils import FrozenObject


class ReviewMutationCommand(FrozenObject):
    """The fields every mutating review command has.

    Attributes:
        space_key: Key of the active space.
        actor: Who acts.
        apply: False for a preview: every check runs, nothing is written.
        idempotency_key: Caller-chosen key; required to apply.
    """

    space_key: Key
    actor: Actor
    apply: bool = True
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class Prelude:
    """What a handler knows before it opens its writing unit of work.

    Attributes:
        space_id: The command's space.
        fingerprint: Request fingerprint; empty for a preview.
        replay: The ledger entry to replay, or None.
    """

    space_id: SpaceId
    fingerprint: str
    replay: LedgerEntry | None


async def require_space_id(records: IRecordReadRepository, key: Key) -> SpaceId:
    """Id of the space with `key`, for the query handlers.

    Raises:
        SpaceNotFoundError: No such space.
    """
    space_id: SpaceId | None = await records.get_space_id(key)
    if space_id is None:
        raise SpaceNotFoundError(
            f"No knowledge space has the key {key.value!r}.",
            {"space_key": key.value},
            next_steps=["Run `noesis store init` or check the configured space key."],
        )
    return space_id


def result_extra(result: BaseDto) -> dict[str, JsonValue]:
    """The ledger `extra` that lets a replay rebuild `result`."""
    dumped: Any = result.model_dump(mode="json", exclude={"replayed"})
    return {"result": dumped}


def result_from[TDto: BaseDto](entry: LedgerEntry, dto_type: type[TDto]) -> TDto:
    """Rebuild a stored result and mark it replayed."""
    return dto_type.model_validate({**entry.extra["result"], "replayed": True})  # type: ignore[dict-item]


class ReviewSupport:
    """Dependencies and steps common to every review command handler."""

    def __init__(
        self,
        *,
        uow_factory: KnowledgeUnitOfWorkFactory,
        clock: IClock,
        ids: IRecordIdGenerator,
        schema: IStoreSchema,
    ) -> None:
        self.uow_factory: KnowledgeUnitOfWorkFactory = uow_factory
        self.clock: IClock = clock
        self.schema: IStoreSchema = schema
        self.references: RecordReferenceResolver = RecordReferenceResolver(
            uow_factory=uow_factory, clock=clock, ids=ids
        )

    async def require_schema(self) -> None:
        """Fail unless the `core` and `review` steps are applied."""
        await require_steps(self.schema, CORE_STEP, REVIEW_STEP)

    async def prelude(self, command: ReviewMutationCommand, ledger_command: str) -> Prelude:
        """Schema, space, then (when applying) the key and the ledger replay.

        Raises:
            StoreNotInitialisedError: A required step is missing.
            SpaceNotFoundError: The space key is unknown.
            InvalidRecordError: Applying without an idempotency key.
            IdempotencyKeyReusedError: The key served a different request.
        """
        await self.require_schema()
        space_id: SpaceId = await self.references.resolve_space(command.space_key)
        if not command.apply:
            return Prelude(space_id=space_id, fingerprint="", replay=None)
        key: str | None = command.idempotency_key
        if not key:
            raise InvalidRecordError(
                "Applying this command needs an idempotency key.",
                next_steps=["Pass --idempotency-key."],
            )
        fingerprint: str = fingerprint_request(ledger_command, command, exclude={"idempotency_key"})
        replay: LedgerEntry | None = replay_of(
            await read_ledger(self.uow_factory, space_id, key),
            command=ledger_command,
            fingerprint=fingerprint,
        )
        return Prelude(space_id=space_id, fingerprint=fingerprint, replay=replay)

    async def raced(
        self,
        uow: IKnowledgeUnitOfWork,
        command: ReviewMutationCommand,
        ledger_command: str,
        prelude: Prelude,
    ) -> LedgerEntry | None:
        """An identical request that committed while this one waited for the record lock."""
        if not command.apply or command.idempotency_key is None:
            return None
        return replay_of(
            await uow.ledger.get(prelude.space_id, command.idempotency_key),
            command=ledger_command,
            fingerprint=prelude.fingerprint,
        )

    async def winner(
        self,
        error: EntryAlreadyExistsError,
        command: ReviewMutationCommand,
        ledger_command: str,
        prelude: Prelude,
    ) -> LedgerEntry:
        """The entry an identical concurrent request wrote; re-raises `error` when none."""
        key: str = command.idempotency_key or ""
        found: LedgerEntry | None = replay_of(
            await read_ledger(self.uow_factory, prelude.space_id, key),
            command=ledger_command,
            fingerprint=prelude.fingerprint,
        )
        if found is None:
            raise error
        return found
