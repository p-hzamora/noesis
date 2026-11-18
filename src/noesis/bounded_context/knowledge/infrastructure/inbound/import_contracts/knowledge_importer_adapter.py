"""Contracts in, contracts out: the way the vault import talks to Knowledge.

The single place that turns a typed Knowledge error into a `blocked` outcome. System failures
(`INTEGRATION_103..107`, `KNOWLEDGE_204`, `205`, `208`) are not caught here.
"""

from enum import StrEnum

from noesis.bounded_context.knowledge.application.dtos import ImportKnowledgeResultDto
from noesis.bounded_context.knowledge.application.handlers.commands.import_knowledge_handler import (
    ImportKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.handlers.queries.assess_import_knowledge_handler import (
    AssessImportKnowledgeQuery,
)
from noesis.bounded_context.knowledge.application.services.import_outcomes import (
    ImportBlockReasonEnum,
    ImportOutcomeEnum,
)
from noesis.bounded_context.knowledge.application.services.import_request import (
    ImportHeaderSource,
)
from noesis.bounded_context.knowledge.application.services.link_set_request import (
    LinkSetRequest,
    LinkSetResultDto,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ActorKindEnum,
    ContentHash,
    ImportOnChangeEnum,
    Key,
    RecordId,
    RecordRelationEnum,
    Slug,
    SourceKindEnum,
    Tag,
)
from noesis.bounded_context.knowledge.domain.value_objects.record_link import RecordLink
from noesis.bounded_context.knowledge.domain.value_objects.record_relation import RecordRelation
from noesis.exceptions import (
    AppException,
    EntryAlreadyExistsError,
    IdempotencyKeyReusedError,
    InvalidContentHashError,
    InvalidKeyError,
    InvalidRecordError,
    InvalidRecordIdError,
    InvalidSlugError,
    KnowledgeNotRevisableError,
    RevisionConflictError,
)
from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.contracts.knowledge import (
    ImportKnowledgeOutcomeContract,
    ImportKnowledgeRequestContract,
)
from noesis.shared_kernel.contracts.knowledge.import_link_set_contract import (
    ImportLinkSetOutcomeContract,
    ImportLinkSetRequestContract,
)

_INVALID_METADATA: tuple[type[AppException], ...] = (
    InvalidRecordIdError,
    InvalidSlugError,
    InvalidContentHashError,
    InvalidKeyError,
    InvalidRecordError,
)


class KnowledgeImporterAdapter:
    """Satisfies the interop `IKnowledgeImporter` protocol structurally."""

    def __init__(
        self,
        *,
        importer: IHandler[ImportKnowledgeCommand, ImportKnowledgeResultDto],
        assessor: IHandler[AssessImportKnowledgeQuery, ImportKnowledgeResultDto],
        link_replacer: IHandler[LinkSetRequest, LinkSetResultDto],
        link_assessor: IHandler[LinkSetRequest, LinkSetResultDto],
    ) -> None:
        self._link_replacer = link_replacer
        self._link_assessor = link_assessor
        self._importer: IHandler[ImportKnowledgeCommand, ImportKnowledgeResultDto] = importer
        self._assessor: IHandler[AssessImportKnowledgeQuery, ImportKnowledgeResultDto] = assessor

    async def assess(
        self, request: ImportKnowledgeRequestContract
    ) -> ImportKnowledgeOutcomeContract:
        """What `apply` would do now; writes nothing."""
        if (unknown := _unknown_header_source_kind(request)) is not None:
            return unknown
        try:
            parts: dict[str, object] = _request_parts(request)
            result: ImportKnowledgeResultDto = await self._assessor.handle(
                AssessImportKnowledgeQuery(**parts)
            )
        except _INVALID_METADATA as error:
            return _invalid_metadata(error)
        return _outcome(result)

    async def apply(
        self, request: ImportKnowledgeRequestContract
    ) -> ImportKnowledgeOutcomeContract:
        """Create, revise or propose a successor for the note, as the decision table says."""
        if (unknown := _unknown_header_source_kind(request)) is not None:
            return unknown
        try:
            parts: dict[str, object] = _request_parts(request)
            result: ImportKnowledgeResultDto = await self._importer.handle(
                ImportKnowledgeCommand(**parts)
            )
        except _INVALID_METADATA as error:
            return _invalid_metadata(error)
        except IdempotencyKeyReusedError:
            return _blocked(ImportBlockReasonEnum.IDEMPOTENCY_KEY_REUSED)
        except RevisionConflictError, KnowledgeNotRevisableError:
            return _blocked(ImportBlockReasonEnum.REVISION_CONFLICT)
        except EntryAlreadyExistsError:
            return _blocked(ImportBlockReasonEnum.ID_CONFLICT)
        return _outcome(result)

    async def assess_links(
        self, request: ImportLinkSetRequestContract
    ) -> ImportLinkSetOutcomeContract:
        """Assess without writes; return created/replaced as the planned outcome."""
        result = await self._link_assessor.handle(_link_request(request))
        return ImportLinkSetOutcomeContract(**result.model_dump())

    async def replace_links(
        self, request: ImportLinkSetRequestContract
    ) -> ImportLinkSetOutcomeContract:
        """Replace directly; unchanged is decided under the source lock."""
        result = await self._link_replacer.handle(_link_request(request))
        return ImportLinkSetOutcomeContract(**result.model_dump())


def _link_request(request: ImportLinkSetRequestContract) -> LinkSetRequest:
    return LinkSetRequest(
        space_key=Key(value=request.space_key),
        source_record_id=RecordId(value=request.source_record_id),
        origin_tag=Tag(value=request.origin_tag),
        actor=Actor(
            kind=ActorKindEnum(request.actor.kind),
            name=request.actor.name,
            session=request.actor.session,
        ),
        links=tuple(
            RecordLink(
                target_record_id=RecordId(value=link.target_record_id),
                link_type=link.link_type,
                count=link.count,
                anchors=link.anchors,
            )
            for link in request.links
        ),
        relations=tuple(
            RecordRelation(
                target_record_id=RecordId(value=relation.target_record_id),
                relation=_enum_of(RecordRelationEnum, relation.relation, "relation"),
            )
            for relation in request.relations
        ),
    )


def _unknown_header_source_kind(
    request: ImportKnowledgeRequestContract,
) -> ImportKnowledgeOutcomeContract | None:
    """A `blocked` outcome when a header source's kind is not a Knowledge source kind."""
    known: set[str] = {kind.value for kind in SourceKindEnum}
    for source in request.header_sources:
        if source.kind not in known:
            return _blocked(ImportBlockReasonEnum.INVALID_METADATA, detail="header_sources.kind")
    return None


def _enum_of[E: StrEnum](enum_type: type[E], value: str, field: str) -> E:
    """`value` as a member of `enum_type`; a bad value is a caller bug (`KNOWLEDGE_007`)."""
    try:
        return enum_type(value)
    except ValueError:
        raise InvalidRecordError(f"Unknown {field}: {value!r}") from None


def _request_parts(request: ImportKnowledgeRequestContract) -> dict[str, object]:
    """The request's fields as C2 value objects (their constructors raise `KNOWLEDGE_001..004`)."""
    return {
        "space_key": Key(value=request.space_key),
        "record_id": RecordId(value=request.record_id) if request.record_id is not None else None,
        "origin_tag": Tag(value=request.origin_tag),
        "title": request.title,
        "body": request.body,
        "subtype": Slug(value=request.subtype),
        "project_key": Key(value=request.project_key) if request.project_key is not None else None,
        "tags": tuple(Tag(value=tag) for tag in request.tags),
        "source_locator": request.source_locator,
        "source_digest": ContentHash(value=request.source_digest),
        "header_sources": tuple(
            ImportHeaderSource(kind=SourceKindEnum(source.kind), locator=source.locator)
            for source in request.header_sources
        ),
        "actor": Actor(
            kind=_enum_of(ActorKindEnum, request.actor.kind, "actor.kind"),
            name=request.actor.name,
            session=request.actor.session,
        ),
        "on_change": _enum_of(ImportOnChangeEnum, request.on_change, "on_change"),
    }


def _outcome(result: ImportKnowledgeResultDto) -> ImportKnowledgeOutcomeContract:
    return ImportKnowledgeOutcomeContract(
        outcome=result.outcome,
        record_id=result.record_id,
        revision=result.revision,
        status=result.status,
        target_record_id=result.target_record_id,
        assertion_id=result.assertion_id,
        block_reason=result.block_reason,
        reason=result.reason,
        replayed=result.replayed,
    )


def _blocked(
    reason: ImportBlockReasonEnum, *, detail: str | None = None
) -> ImportKnowledgeOutcomeContract:
    return ImportKnowledgeOutcomeContract(
        outcome=ImportOutcomeEnum.BLOCKED.value, block_reason=reason.value, detail=detail
    )


def _invalid_metadata(error: AppException) -> ImportKnowledgeOutcomeContract:
    return _blocked(ImportBlockReasonEnum.INVALID_METADATA, detail=error.error_code)
