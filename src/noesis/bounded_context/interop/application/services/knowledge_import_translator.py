"""Maps interop values to and from the kernel contracts (the only module besides the port that
imports `shared_kernel.contracts`)."""

from dataclasses import dataclass

from noesis.bounded_context.interop.application.ports import IKnowledgeImporter
from noesis.bounded_context.interop.domain.value_objects import (
    ImportActor,
    NoteMapping,
    NoteOutcomeEnum,
)
from noesis.bounded_context.interop.domain.value_objects.vault_link import ImportedLink
from noesis.shared_kernel.contracts.knowledge import (
    ImportActorContract,
    ImportHeaderSourceContract,
    ImportKnowledgeOutcomeContract,
    ImportKnowledgeRequestContract,
)
from noesis.shared_kernel.contracts.knowledge.import_link_set_contract import (
    ImportLinkContract,
    ImportLinkSetRequestContract,
)

OUTCOMES: dict[str, NoteOutcomeEnum] = {
    "created": NoteOutcomeEnum.CREATED,
    "unchanged": NoteOutcomeEnum.UNCHANGED,
    "changed": NoteOutcomeEnum.CHANGED_IN_VAULT,
    "revised": NoteOutcomeEnum.REVISED,
    "successor_proposed": NoteOutcomeEnum.SUCCESSOR_PROPOSED,
    "blocked": NoteOutcomeEnum.BLOCKED,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class KnowledgeAnswer:
    """Knowledge's outcome for one note, in interop terms.

    Attributes:
        outcome: The interop outcome (`changed` becomes `changed_in_vault`).
        record_id: The record created, revised or matched.
        revision: Revision written, planned or matched.
        status: Status of the record.
        target_record_id: The accepted record a successor replaces.
        assertion_id: The proposed `supersedes` assertion.
        block_reason: Why the outcome is `blocked`.
        reason: The reduced-behaviour note.
        detail: The error code behind `invalid_metadata`.
    """

    outcome: NoteOutcomeEnum
    record_id: str | None = None
    revision: int | None = None
    status: str | None = None
    target_record_id: str | None = None
    assertion_id: str | None = None
    block_reason: str | None = None
    reason: str | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportPayload:
    """Everything interop knows about one note or file when it asks Knowledge.

    Attributes:
        mapping: The header-derived record fields.
        origin_tag: `origin:migrated` or `origin:imported`.
        body: The normalised body.
        source_locator: Locator of the file.
        source_digest: `sha256:<hex>` of the raw bytes.
        on_change: `report` or `update`.
    """

    mapping: NoteMapping
    origin_tag: str
    body: str
    source_locator: str
    source_digest: str
    on_change: str


class KnowledgeImportTranslator:
    """Builds requests for Knowledge, calls it, and reads its answers."""

    def __init__(self, *, importer: IKnowledgeImporter, space_key: str, actor: ImportActor) -> None:
        self._importer: IKnowledgeImporter = importer
        self._space_key: str = space_key
        self._actor: ImportActor = actor

    async def assess(self, payload: ImportPayload) -> KnowledgeAnswer:
        """What applying `payload` would do now; writes nothing."""
        return self._answer(await self._importer.assess(self._request(payload)))

    async def apply(self, payload: ImportPayload) -> KnowledgeAnswer:
        """Apply `payload` and report what happened."""
        return self._answer(await self._importer.apply(self._request(payload)))

    def _request(self, payload: ImportPayload) -> ImportKnowledgeRequestContract:
        mapping: NoteMapping = payload.mapping
        return ImportKnowledgeRequestContract(
            space_key=self._space_key,
            record_id=mapping.record_id,
            origin_tag=payload.origin_tag,
            title=mapping.title,
            body=payload.body,
            subtype=mapping.subtype,
            project_key=mapping.project_key,
            tags=mapping.tags,
            source_locator=payload.source_locator,
            source_digest=payload.source_digest,
            header_sources=tuple(
                ImportHeaderSourceContract(kind=source.kind, locator=source.locator)
                for source in mapping.header_sources
            ),
            actor=ImportActorContract(
                kind=self._actor.kind, name=self._actor.name, session=self._actor.session
            ),
            on_change=payload.on_change,
        )

    def _answer(self, outcome: ImportKnowledgeOutcomeContract) -> KnowledgeAnswer:
        return KnowledgeAnswer(
            outcome=OUTCOMES[outcome.outcome],
            record_id=outcome.record_id,
            revision=outcome.revision,
            status=outcome.status,
            target_record_id=outcome.target_record_id,
            assertion_id=outcome.assertion_id,
            block_reason=outcome.block_reason,
            reason=outcome.reason,
            detail=outcome.detail,
        )

    async def links(
        self, source: str, links: tuple[ImportedLink, ...], *, apply: bool
    ) -> tuple[str, str | None]:
        """Send only real record ids across the boundary and return interop values."""
        request = ImportLinkSetRequestContract(
            space_key=self._space_key,
            source_record_id=source,
            origin_tag="origin:migrated",
            actor=ImportActorContract(
                kind=self._actor.kind, name=self._actor.name, session=self._actor.session
            ),
            links=tuple(
                ImportLinkContract(
                    target_record_id=link.target_record_id,
                    link_type=link.link_type,
                    count=link.count,
                    anchors=link.anchors,
                )
                for link in links
            ),
        )
        answer = (
            await self._importer.replace_links(request)
            if apply
            else await self._importer.assess_links(request)
        )
        return answer.outcome, answer.block_reason
