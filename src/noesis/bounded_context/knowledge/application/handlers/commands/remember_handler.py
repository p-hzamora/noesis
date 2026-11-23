"""Remember: capture knowledge or an experience on purpose, reconciled against what exists.

Orchestrates the capture and assertion handlers; it holds no validation, redaction, source,
actor or scope logic of its own (FR-011).
"""

from datetime import datetime

from noesis.bounded_context.knowledge.application.dtos import (
    CaptureResultDto,
    CatalogEntryDetailDto,
    ProposeAssertionResultDto,
    ReconciledRecordDto,
    ReconciliationDto,
    RecordDto,
    RememberedAssertionDto,
    RememberKindEnum,
    RememberResultDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_experience_handler import (
    CaptureExperienceCommand,
    CaptureExperienceHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeCommand,
    CaptureKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.propose_assertion_handler import (
    ProposeAssertionCommand,
    ProposeAssertionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.ledger import LedgerEntry
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    ICatalogEntryReadRepository,
    IRecordReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.catalog_lookup import (
    catalog_entry_not_found,
    find_entry,
    is_record_id,
)
from noesis.bounded_context.knowledge.application.services.idempotency import (
    fingerprint_request,
    read_ledger,
    replay_of,
)
from noesis.bounded_context.knowledge.application.services.inputs import ProjectRef, SourceInput
from noesis.bounded_context.knowledge.application.services.record_reference_resolver import (
    RecordReferenceResolver,
)
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    require_initialised,
)
from noesis.bounded_context.knowledge.application.services.secret_redactor import SecretRedactor
from noesis.bounded_context.knowledge.domain.services import TextOverlapPolicy
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    AssertionPredicateEnum,
    ExperienceSubtypeEnum,
    Key,
    RecordId,
    RecordTypeEnum,
    Slug,
    SpaceId,
    Tag,
)
from noesis.exceptions import (
    AppException,
    EntryAlreadyExistsError,
    InvalidAssertionError,
    InvalidRecordError,
    RecordNotFoundError,
    RememberPartiallyAppliedError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.contracts.ports.knowledge import IRelatedRecordFinder
from noesis.shared_kernel.contracts.retrieval import RecordSearchHitContract
from noesis.shared_kernel.domain import JsonValue
from noesis.utils import FrozenObject

REMEMBER_COMMAND: str = "remember"
MARKER_SUFFIX: str = "#remember"
KEY_PREFIX: str = "remember:"
DUPLICATE_THRESHOLD: float = 0.8
RELATED_THRESHOLD: float = 0.3
LOOKUP_HITS: int = 10
QUERY_BODY_CHARACTERS: int = 200
CONSOLIDATE_NEXT_STEP: str = (
    "Once both are accepted, `noesis consolidation propose --member {existing} --member {new} "
    "--title ... --body ... --rationale ...` can merge them; nothing is merged automatically."
)


class RememberCommand(FrozenObject):
    """Remember knowledge or an experience.

    Attributes:
        kind: `knowledge` (written `proposed`) or `experience`.
        space_key: Key of the space to write into.
        actor: Who remembers.
        project: Project to anchor it to; None for space-wide.
        sources: Existing source ids and/or new source descriptions; at least one.
        body: Full text.
        title: Knowledge: short title.
        knowledge_subtype: Knowledge: open validated slug.
        tags: Knowledge: labels.
        experience_subtype: Experience: `observation`, `outcome` or `failure`.
        occurred_at: Experience: when it happened.
        session: Experience: harness session id.
        environment: Experience: where it happened.
        refines: Targets (record id, `record:<id>`, `catalog:<kind>:<name>`) the new record refines.
        supersedes: Knowledge the new record is proposed to supersede.
        idempotency_key: Caller-chosen key; `remember:<sha256 of the normalised request>` when None.
        check: Report the reconciliation and write nothing.
    """

    kind: RememberKindEnum
    space_key: Key
    actor: Actor
    project: ProjectRef | None = None
    sources: tuple[SourceInput, ...]
    body: str
    title: str | None = None
    knowledge_subtype: Slug | None = None
    tags: tuple[Tag, ...] = ()
    experience_subtype: ExperienceSubtypeEnum = ExperienceSubtypeEnum.OBSERVATION
    occurred_at: datetime | None = None
    session: str | None = None
    environment: str | None = None
    refines: tuple[str, ...] = ()
    supersedes: RecordId | None = None
    idempotency_key: str | None = None
    check: bool = False


class _Target(FrozenObject):
    predicate: AssertionPredicateEnum
    ref: str
    object_id: RecordId


class RememberHandler(IHandler[RememberCommand, RememberResultDto]):
    """Checks references, reconciles, captures through the capture handlers, then proposes.

    Never merges, retracts, accepts or supersedes anything. The same key and request replay the
    first result; a rerun after a failed assertion completes it. The record is written by the
    capture handlers under the request's key; a marker entry under `<key>#remember` seals the
    whole request so that the same key with another request is refused.
    """

    def __init__(
        self,
        *,
        uow_factory: KnowledgeUnitOfWorkFactory,
        clock: IClock,
        ids: IRecordIdGenerator,
        schema: IStoreSchema,
        capture_knowledge: CaptureKnowledgeHandler,
        capture_experience: CaptureExperienceHandler,
        propose_assertion: ProposeAssertionHandler,
        records: IRecordReadRepository,
        catalog: ICatalogEntryReadRepository,
        finder: IRelatedRecordFinder,
        duplicate_threshold: float = DUPLICATE_THRESHOLD,
        related_threshold: float = RELATED_THRESHOLD,
    ) -> None:
        self._uow_factory: KnowledgeUnitOfWorkFactory = uow_factory
        self._clock: IClock = clock
        self._schema: IStoreSchema = schema
        self._capture_knowledge: CaptureKnowledgeHandler = capture_knowledge
        self._capture_experience: CaptureExperienceHandler = capture_experience
        self._propose: ProposeAssertionHandler = propose_assertion
        self._records: IRecordReadRepository = records
        self._catalog: ICatalogEntryReadRepository = catalog
        self._finder: IRelatedRecordFinder = finder
        self._duplicate: float = duplicate_threshold
        self._related: float = related_threshold
        self._references: RecordReferenceResolver = RecordReferenceResolver(
            uow_factory=uow_factory, clock=clock, ids=ids
        )

    async def handle(self, action: RememberCommand) -> RememberResultDto:
        """Remember, or preview with `check`.

        Raises:
            InvalidRecordError: No source, a missing title or subtype, or `supersedes` on an
                experience.
            StoreNotInitialisedError: The `core` schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
            IdempotencyKeyReusedError: The key was used for a different request.
            RecordNotFoundError: A `refines` or `supersedes` record is not in the space.
            CatalogEntryNotFoundError: A `refines` catalog entry is not in the space.
            InvalidAssertionError: A target has a kind the predicate does not allow.
            RememberPartiallyAppliedError: The record is written but an assertion failed; rerun
                with the same key to complete it.
            Also whatever the capture handlers raise (blank text, foreign source ids).
        """
        self._check_shape(action)
        normalised: RememberCommand = _normalised(action)
        fingerprint: str = fingerprint_request(
            REMEMBER_COMMAND, normalised, exclude={"idempotency_key", "check"}
        )
        key: str = action.idempotency_key or f"{KEY_PREFIX}{fingerprint.removeprefix('sha256:')}"
        await require_initialised(self._schema)
        space_id: SpaceId = await self._references.resolve_space(action.space_key)
        marker: LedgerEntry | None = replay_of(
            await read_ledger(self._uow_factory, space_id, key + MARKER_SUFFIX),
            command=REMEMBER_COMMAND,
            fingerprint=fingerprint,
        )
        targets: list[_Target] = await self._targets(action, space_id)
        reconciliation: ReconciliationDto = await self._reconcile(normalised, space_id)
        if action.check:
            return _preview(action, space_id, key, reconciliation, targets)
        written: RememberCommand = action if action.idempotency_key else _trimmed(action)
        captured: CaptureResultDto = await self._capture(written, key)
        reconciliation = _without(reconciliation, captured.record_id)
        assertions: list[RememberedAssertionDto] = await self._assert(
            action, captured, key, targets
        )
        failed: list[RememberedAssertionDto] = [a for a in assertions if a.status == "failed"]
        if failed:
            raise _partial(captured, key, assertions)
        if marker is None and targets:
            await self._seal(space_id, key, fingerprint, captured)
        return RememberResultDto(
            written=True,
            record_id=captured.record_id,
            record_type=captured.record_type,
            revision=captured.revision,
            status=captured.status,
            space_id=captured.space_id,
            project_id=captured.project_id,
            replayed=captured.replayed,
            idempotency_key=key,
            reconciliation=reconciliation,
            assertions=tuple(assertions),
            next_steps=_next_steps(reconciliation, captured.record_id),
        )

    @staticmethod
    def _check_shape(action: RememberCommand) -> None:
        if not action.sources:
            raise InvalidRecordError(
                "A remembered record needs at least one source.",
                next_steps=["Cite at least one source."],
            )
        if action.kind is RememberKindEnum.KNOWLEDGE:
            if not (action.title and action.title.strip()) or action.knowledge_subtype is None:
                raise InvalidRecordError(
                    "Knowledge needs a title and a subtype.",
                    next_steps=["Give --title and --subtype."],
                )
        elif action.supersedes is not None:
            raise InvalidRecordError(
                "Only knowledge can supersede a record.",
                next_steps=["Remember it as knowledge, or drop --supersedes."],
            )

    async def _targets(self, action: RememberCommand, space_id: SpaceId) -> list[_Target]:
        """Resolve every `--refines` and `--supersedes` target before anything is written."""
        targets: list[_Target] = []
        for ref in dict.fromkeys(action.refines):
            object_id, kind = await self._resolve(ref, space_id)
            if kind not in (RecordTypeEnum.KNOWLEDGE.value, RecordTypeEnum.CATALOG_ENTRY.value):
                raise _wrong_kind(ref, kind, AssertionPredicateEnum.REFINES)
            targets.append(
                _Target(predicate=AssertionPredicateEnum.REFINES, ref=ref, object_id=object_id)
            )
        if action.supersedes is not None:
            object_id, kind = await self._resolve(action.supersedes.value, space_id)
            if kind != RecordTypeEnum.KNOWLEDGE.value:
                raise _wrong_kind(action.supersedes.value, kind, AssertionPredicateEnum.SUPERSEDES)
            targets.append(
                _Target(
                    predicate=AssertionPredicateEnum.SUPERSEDES,
                    ref=action.supersedes.value,
                    object_id=object_id,
                )
            )
        return targets

    async def _resolve(self, ref: str, space_id: SpaceId) -> tuple[RecordId, str]:
        """Id and record type of a reference; another space's id is "not found"."""
        text: str = ref.strip().removeprefix("record:")
        if is_record_id(text):
            record: RecordDto | None = await self._records.get_by_id(
                RecordId(value=text), space_id=space_id
            )
            if record is not None:
                return RecordId(value=record.id), record.type
        entry: CatalogEntryDetailDto | None = await find_entry(
            self._catalog, space_id, text.removeprefix("catalog:")
        )
        if entry is not None:
            return RecordId(value=entry.id), RecordTypeEnum.CATALOG_ENTRY.value
        if is_record_id(text):
            raise RecordNotFoundError(
                f"No record {text} in this space.",
                {"record_id": text},
                next_steps=["Check the id and the active space."],
            )
        raise catalog_entry_not_found(ref, space_id)

    async def _reconcile(self, action: RememberCommand, space_id: SpaceId) -> ReconciliationDto:
        """Duplicates and related records; a lookup that cannot answer is a warning."""
        text: str = _text_of(action)
        try:
            found: RecordSearchHitContract = await self._finder.find(
                _query_of(action),
                space_id=space_id.value,
                project_key=action.project.key.value if action.project else None,
                limit=LOOKUP_HITS,
            )
        except AppException as error:
            return ReconciliationDto(
                warnings=(
                    f"Similar-record lookup unavailable ({error.error_code}); "
                    "nothing was checked for duplicates.",
                )
            )
        duplicates: list[ReconciledRecordDto] = []
        related: list[ReconciledRecordDto] = []
        for hit in found.hits:
            record: RecordDto | None = await self._records.get_by_id(
                RecordId(value=hit.record_id), space_id=space_id
            )
            if record is None:
                continue
            score: float = round(TextOverlapPolicy.score(text, _record_text(record)), 3)
            item = ReconciledRecordDto(
                id=hit.record_id, score=score, authority=hit.authority, title=hit.title
            )
            if score >= self._duplicate and hit.record_type == action.kind.value:
                duplicates.append(item)
            elif score >= self._related:
                related.append(item)
        warnings: tuple[str, ...] = (
            ("The semantic index is not queryable; only lexical matches were checked.",)
            if found.semantic_state in ("absent", "unavailable")
            else ()
        )
        return ReconciliationDto(
            duplicates=tuple(sorted(duplicates, key=_best_first)),
            related=tuple(sorted(related, key=_best_first)),
            warnings=warnings,
        )

    async def _capture(self, action: RememberCommand, key: str) -> CaptureResultDto:
        if action.kind is RememberKindEnum.KNOWLEDGE:
            return await self._capture_knowledge.handle(
                CaptureKnowledgeCommand(
                    idempotency_key=key,
                    space_key=action.space_key,
                    title=_present(action.title),
                    body=action.body,
                    subtype=_present(action.knowledge_subtype),
                    actor=action.actor,
                    project=action.project,
                    tags=action.tags,
                    sources=action.sources,
                )
            )
        return await self._capture_experience.handle(
            CaptureExperienceCommand(
                idempotency_key=key,
                space_key=action.space_key,
                subtype=action.experience_subtype,
                body=action.body,
                actor=action.actor,
                occurred_at=action.occurred_at,
                project=action.project,
                session=action.session,
                environment=action.environment,
                sources=action.sources,
            )
        )

    async def _assert(
        self,
        action: RememberCommand,
        captured: CaptureResultDto,
        key: str,
        targets: list[_Target],
    ) -> list[RememberedAssertionDto]:
        """Propose one assertion per target; a failure is recorded and the rest still run."""
        if not targets:
            return []
        subject: RecordId = RecordId(value=captured.record_id)
        record: RecordDto | None = await self._records.get_by_id(
            subject, space_id=SpaceId(value=captured.space_id)
        )
        evidence: tuple[RecordId, ...] = tuple(
            RecordId(value=source.id) for source in (record.sources if record else ())
        )
        outcomes: list[RememberedAssertionDto] = []
        for target in targets:
            command = ProposeAssertionCommand(
                space_key=action.space_key,
                actor=action.actor,
                idempotency_key=f"{key}:{target.predicate.value}:{target.object_id.value}",
                predicate=target.predicate,
                subject_id=subject,
                object_id=target.object_id,
                evidence_ids=evidence,
                rationale=(
                    f"Proposed by `noesis remember`: this record {target.predicate.value} "
                    f"{target.ref}."
                ),
                project=action.project,
                sources=action.sources,
            )
            try:
                proposed: ProposeAssertionResultDto = await self._propose.handle(command)
            except AppException as error:
                outcomes.append(
                    RememberedAssertionDto(
                        predicate=target.predicate.value,
                        object_ref=target.ref,
                        status="failed",
                        error=f"{error.error_code}: {error.message}",
                    )
                )
                continue
            outcomes.append(
                RememberedAssertionDto(
                    id=proposed.id,
                    predicate=target.predicate.value,
                    object_ref=target.ref,
                    status=proposed.status,
                )
            )
        return outcomes

    async def _seal(
        self, space_id: SpaceId, key: str, fingerprint: str, captured: CaptureResultDto
    ) -> None:
        """Record that the whole request completed; losing a race to an identical call is fine."""
        entry = LedgerEntry(
            space_id=space_id,
            key=key + MARKER_SUFFIX,
            command=REMEMBER_COMMAND,
            fingerprint=fingerprint,
            record_id=RecordId(value=captured.record_id),
            recorded_at=self._clock.now(),
        )
        try:
            async with self._uow_factory() as uow:
                await uow.ledger.record(entry)
                await uow.commit()
        except EntryAlreadyExistsError:
            return


def _normalised(action: RememberCommand) -> RememberCommand:
    """Trimmed, redacted text and sorted, unique tags and targets: the request that is hashed."""
    return action.model_copy(
        update={
            "body": SecretRedactor.redact(action.body.strip())[0],
            "title": (
                SecretRedactor.redact(action.title.strip())[0] if action.title is not None else None
            ),
            "tags": tuple(sorted(set(action.tags), key=lambda tag: tag.value)),
            "refines": tuple(sorted({ref.strip() for ref in action.refines})),
        }
    )


def _trimmed(action: RememberCommand) -> RememberCommand:
    """Without a given key the request is identified by its trimmed text, so it is also written trimmed."""
    return action.model_copy(
        update={
            "body": action.body.strip(),
            "title": action.title.strip() if action.title is not None else None,
        }
    )


def _best_first(item: ReconciledRecordDto) -> float:
    return -item.score


def _present[T](value: T | None) -> T:
    if value is None:  # pragma: no cover - _check_shape guarantees it
        raise InvalidRecordError("Knowledge needs a title and a subtype.")
    return value


def _text_of(action: RememberCommand) -> str:
    return f"{action.title or ''} {action.body}".strip()


def _query_of(action: RememberCommand) -> str:
    return f"{action.title or ''} {action.body[:QUERY_BODY_CHARACTERS]}".strip()


def _record_text(record: RecordDto) -> str:
    if record.revision is not None:
        return f"{record.revision.title} {record.revision.body or ''}".strip()
    return record.body or ""


def _without(reconciliation: ReconciliationDto, record_id: str) -> ReconciliationDto:
    """A replay finds the record it wrote earlier; it is not its own duplicate."""
    return reconciliation.model_copy(
        update={
            "duplicates": tuple(r for r in reconciliation.duplicates if r.id != record_id),
            "related": tuple(r for r in reconciliation.related if r.id != record_id),
        }
    )


def _next_steps(reconciliation: ReconciliationDto, record_id: str | None) -> tuple[str, ...]:
    return tuple(
        CONSOLIDATE_NEXT_STEP.format(existing=duplicate.id, new=record_id or "<new-id>")
        for duplicate in reconciliation.duplicates
    )


def _preview(
    action: RememberCommand,
    space_id: SpaceId,
    key: str,
    reconciliation: ReconciliationDto,
    targets: list[_Target],
) -> RememberResultDto:
    return RememberResultDto(
        written=False,
        record_type=action.kind.value,
        status="proposed" if action.kind is RememberKindEnum.KNOWLEDGE else None,
        space_id=space_id.value,
        idempotency_key=key,
        reconciliation=reconciliation,
        assertions=tuple(
            RememberedAssertionDto(
                predicate=target.predicate.value, object_ref=target.ref, status="planned"
            )
            for target in targets
        ),
        next_steps=(
            "Run again without --check to write the record.",
            *_next_steps(reconciliation, None),
        ),
    )


def _wrong_kind(ref: str, kind: str, predicate: AssertionPredicateEnum) -> InvalidAssertionError:
    return InvalidAssertionError(
        f"`{predicate.value}` cannot target a {kind} ({ref}).",
        {"field": "object", "ref": ref, "record_type": kind},
        next_steps=["Fix the target."],
    )


def _partial(
    captured: CaptureResultDto, key: str, assertions: list[RememberedAssertionDto]
) -> RememberPartiallyAppliedError:
    failed: list[RememberedAssertionDto] = [a for a in assertions if a.status == "failed"]
    metadata: dict[str, JsonValue] = {
        "record_id": captured.record_id,
        "record_type": captured.record_type,
        "idempotency_key": key,
        "assertions": [a.model_dump(mode="json") for a in assertions],
    }
    return RememberPartiallyAppliedError(
        f"Record {captured.record_id} was written, but {len(failed)} of {len(assertions)} "
        "assertion(s) failed.",
        metadata,
        next_steps=[
            f"Fix the cause and rerun the same command with --idempotency-key {key}; "
            "the record is kept and only the assertions are completed."
        ],
    )
