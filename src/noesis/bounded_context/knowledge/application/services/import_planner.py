"""Validation, redaction and the read-and-decide step both import handlers share."""

from noesis.bounded_context.knowledge.application.dtos import (
    ImportCandidateDto,
    ImportCandidatesDto,
)
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IImportCandidateReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.services.import_request import (
    ImportHeaderSource,
    ImportRequest,
    PreparedImport,
)
from noesis.bounded_context.knowledge.application.services.record_reference_resolver import (
    RecordReferenceResolver,
)
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CORE_STEP,
    require_steps,
)
from noesis.bounded_context.knowledge.application.services.secret_redactor import SecretRedactor
from noesis.bounded_context.knowledge.domain.services import ImportDecisionPolicy
from noesis.bounded_context.knowledge.domain.value_objects import (
    ContentHash,
    GraphContent,
    IdHolderEnum,
    ImportCandidate,
    ImportDecision,
    RecordId,
    RecordStatusEnum,
    SpaceId,
)
from noesis.shared_kernel.application.ports.clock import IClock


def _redacted(text: str) -> str:
    return SecretRedactor.redact(text.strip())[0]


class ImportPlanner:
    """Prepares a request and decides what to do with it; writes nothing."""

    def __init__(
        self,
        *,
        uow_factory: KnowledgeUnitOfWorkFactory,
        clock: IClock,
        ids: IRecordIdGenerator,
        schema: IStoreSchema,
        candidates: IImportCandidateReadRepository,
    ) -> None:
        self._schema: IStoreSchema = schema
        self._candidates: IImportCandidateReadRepository = candidates
        self._references: RecordReferenceResolver = RecordReferenceResolver(
            uow_factory=uow_factory, clock=clock, ids=ids
        )
        self._policy: ImportDecisionPolicy = ImportDecisionPolicy()

    async def prepare(self, request: ImportRequest) -> PreparedImport:
        """Validate the content, redact what is stored, check the schema and resolve the space.

        Raises:
            InvalidRecordError: A blank title or body.
            StoreNotInitialisedError: The `core` schema step is not applied.
            SpaceNotFoundError: The space key is unknown.
        """
        GraphContent(title=request.title, body=request.body)  # a blank title or body raises
        content: GraphContent = GraphContent(
            title=SecretRedactor.redact(request.title)[0],
            body=SecretRedactor.redact(request.body)[0],
        )
        redacted: ImportRequest = request.model_copy(
            update={
                "title": content.title,
                "body": content.body,
                "source_locator": _redacted(request.source_locator),
                "header_sources": tuple(
                    ImportHeaderSource(kind=source.kind, locator=_redacted(source.locator))
                    for source in request.header_sources
                ),
            }
        )
        await require_steps(self._schema, CORE_STEP)
        space_id: SpaceId = await self._references.resolve_space(request.space_key)
        return PreparedImport(space_id=space_id, request=redacted, content=content)

    async def decide(self, prepared: PreparedImport, *, can_link_successor: bool) -> ImportDecision:
        """Read the candidates of the note and apply the decision table."""
        request: ImportRequest = prepared.request
        found: ImportCandidatesDto = await self._candidates.find_candidates(
            request.record_id,
            request.source_locator,
            request.origin_tag,
            space_id=prepared.space_id,
        )
        return self._policy.decide(
            candidates=tuple(_candidate(dto, request.record_id) for dto in found.candidates),
            id_holder=IdHolderEnum(found.id_holder),
            content=prepared.content,
            digest=request.source_digest,
            on_change=request.on_change,
            can_link_successor=can_link_successor,
        )


def _candidate(dto: ImportCandidateDto, declared: RecordId | None) -> ImportCandidate:
    return ImportCandidate(
        id=RecordId(value=dto.id),
        status=RecordStatusEnum(dto.status),
        created_at=dto.created_at,
        head_revision=dto.head_revision,
        head_content=(
            GraphContent(title=dto.title, body=dto.body) if dto.body is not None else None
        ),
        head_file_digests=tuple(ContentHash(value=digest) for digest in dto.head_file_digests),
        holds_record_id=declared is not None and dto.id == declared.value,
    )
