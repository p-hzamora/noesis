"""Register a curation plan in the ledger, so the submission is never judged again (FR-004)."""

from noesis.bounded_context.knowledge.application.dtos import PlanRegistrationDto
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.idempotency import (
    read_ledger,
    replay_of,
)
from noesis.bounded_context.knowledge.application.services.record_reference_resolver import (
    RecordReferenceResolver,
)
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    require_initialised,
)
from noesis.bounded_context.knowledge.domain.entities import Source
from noesis.bounded_context.knowledge.domain.services import CaptureKeyPolicy
from noesis.bounded_context.knowledge.domain.value_objects import Key, SourceKindEnum, SpaceId
from noesis.exceptions import EntryAlreadyExistsError
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.utils import FrozenObject

CURATION_PLAN_COMMAND: str = "curation.plan"
"""The ledger command of a plan registration (C2's open command set, A-8)."""

MAX_RACE_RETRIES: int = 3


class RegisterCurationPlanCommand(FrozenObject):
    """Register the plan of a submission.

    Attributes:
        space_key: Key of the active space.
        submission_key: The submission's key; also the locator of its `work_brief` Source.
        plan_hash: The plan's hash, kept as the ledger fingerprint.
    """

    space_key: Key
    submission_key: str
    plan_hash: str


class RegisterCurationPlanHandler(IHandler[RegisterCurationPlanCommand, PlanRegistrationDto]):
    """One unit of work: ensure the `work_brief` Source and write the ledger entry.

    The entry has key `capture/<submission_key>/plan`, command `curation.plan`, the plan hash as
    fingerprint and the Source id as result. A Source records no change-feed entry (C5a), so
    nothing is appended to `uow.changes`.
    """

    def __init__(
        self,
        *,
        uow_factory: KnowledgeUnitOfWorkFactory,
        clock: IClock,
        ids: IRecordIdGenerator,
        schema: IStoreSchema,
    ) -> None:
        self._uow_factory: KnowledgeUnitOfWorkFactory = uow_factory
        self._clock: IClock = clock
        self._ids: IRecordIdGenerator = ids
        self._schema: IStoreSchema = schema
        self._references: RecordReferenceResolver = RecordReferenceResolver(
            uow_factory=uow_factory, clock=clock, ids=ids
        )

    async def handle(self, action: RegisterCurationPlanCommand) -> PlanRegistrationDto:
        """Register the plan, or replay the earlier identical registration.

        Raises:
            StoreNotInitialisedError: The `core` schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            IdempotencyKeyReusedError: Another plan was registered for this submission.
        """
        await require_initialised(self._schema)
        space_id: SpaceId = await self._references.resolve_space(action.space_key)
        key: str = CaptureKeyPolicy.plan_key(action.submission_key)
        for attempt in range(MAX_RACE_RETRIES):
            known: LedgerEntry | None = replay_of(
                await read_ledger(self._uow_factory, space_id, key),
                command=CURATION_PLAN_COMMAND,
                fingerprint=action.plan_hash,
            )
            if known is not None and known.record_id is not None:
                return PlanRegistrationDto(source_id=known.record_id.value, replayed=True)
            try:
                return await self._register(action, space_id, key)
            except EntryAlreadyExistsError:
                if attempt == MAX_RACE_RETRIES - 1:
                    raise
        raise AssertionError("unreachable")  # pragma: no cover

    async def _register(
        self, action: RegisterCurationPlanCommand, space_id: SpaceId, key: str
    ) -> PlanRegistrationDto:
        now = self._clock.now()
        async with self._uow_factory() as uow:
            source: Source | None = await uow.sources.get_by_natural_key(
                space_id=space_id,
                kind=SourceKindEnum.WORK_BRIEF,
                locator=action.submission_key,
                digest=None,
            )
            if source is None:
                source = Source.create(
                    id=self._ids.new_record_id(),
                    space_id=space_id,
                    kind=SourceKindEnum.WORK_BRIEF,
                    locator=action.submission_key,
                    now=now,
                )
                await uow.sources.add(source)
            await uow.ledger.record(
                LedgerEntry(
                    space_id=space_id,
                    key=key,
                    command=CURATION_PLAN_COMMAND,
                    fingerprint=action.plan_hash,
                    record_id=source.id,
                    recorded_at=now,
                )
            )
            await uow.commit()
        return PlanRegistrationDto(source_id=source.id.value)
