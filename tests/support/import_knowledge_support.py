"""Knowledge-side import helpers: request builder, candidate fake, proposer fake, wiring.

The importer is exercised through `KnowledgeImporterAdapter` (contracts in, contracts out), so
the tests depend on the published contracts and not on the handlers' command shapes.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from tests.support.knowledge_support import (
    FakeKnowledgeStore,
    FakeKnowledgeUnitOfWork,
    KnowledgeEnv,
)

from noesis.bounded_context.knowledge.application.dtos import (
    ImportCandidateDto,
    ImportCandidatesDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.import_knowledge_handler import (
    ImportKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.assess_import_knowledge_handler import (
    AssessImportKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.types import (
    KnowledgeUnitOfWorkFactory,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IImportCandidateReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.ports.supersession import (
    ISupersessionProposer,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    FileContent,
    OwnershipEnum,
    RecordId,
    RecordStatusEnum,
    SourceKindEnum,
    SpaceId,
    Tag,
)
from noesis.bounded_context.knowledge.infrastructure.inbound.import_contracts import (
    KnowledgeImporterAdapter,
)
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.contracts.knowledge import (
    ImportKnowledgeOutcomeContract,
    ImportKnowledgeRequestContract,
)

ASSERTION_ID: str = "01JCKMNPA00000000000000001"
USER_ACTOR: dict[str, Any] = {"kind": "user", "name": "tester", "session": None}


def file_digest(text: str) -> str:
    """`sha256:<hex>` of `text` as UTF-8 bytes, standing for a file's digest."""
    return f"sha256:{hashlib.sha256(text.encode()).hexdigest()}"


def content_hash(title: str, body: str, digest: str) -> str:
    """The idempotency key's content hash, exactly as `20-import.md` (Idempotency) defines it."""
    canonical: str = json.dumps(
        {"body": body, "digest": digest, "title": title},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def locator_hash(locator: str) -> str:
    """Hex `sha256` of the locator, for keys of a create without a `record_id`."""
    return hashlib.sha256(locator.encode()).hexdigest()


def make_request(**overrides: Any) -> ImportKnowledgeRequestContract:
    """A valid request for one note (`vault://fixture/notes/a.md`); override any field."""
    body: str = overrides.get("body", "Body text.")
    fields: dict[str, Any] = {
        "space_key": "default",
        "record_id": None,
        "origin_tag": "origin:migrated",
        "title": "Title",
        "body": body,
        "subtype": "concept",
        "project_key": None,
        "tags": [],
        "source_locator": "vault://fixture/notes/a.md",
        "source_digest": file_digest(body),
        "header_sources": [],
        "actor": USER_ACTOR,
        "on_change": "update",
    }
    fields.update(overrides)
    return ImportKnowledgeRequestContract(**fields)


class FakeImportCandidateReadRepository(IImportCandidateReadRepository):
    """Answers `find_candidates` from the fake store, following `20-import.md` (Record identity).

    Candidates: Knowledge in the space with the given id, or carrying `origin_tag` with a revision
    citing a `file_version` Source of exactly `locator`. The id holder is `graph_knowledge`,
    `other` (another record type, or non-graph Knowledge) or `none`.
    """

    def __init__(self, store: FakeKnowledgeStore, *, blind: bool = False) -> None:
        self._store: FakeKnowledgeStore = store
        self._blind: bool = blind

    def _holder(self, record_id: RecordId | None, space_id: SpaceId) -> str:
        if record_id is None:
            return "none"
        key: str = record_id.value
        knowledge = self._store.knowledge.get(key)
        if knowledge is not None and knowledge.space_id == space_id:
            return "graph_knowledge" if knowledge.ownership is OwnershipEnum.GRAPH else "other"
        others = (self._store.experiences, self._store.projects, self._store.sources)
        if any(key in table and table[key].space_id == space_id for table in others):  # type: ignore[attr-defined]
            return "other"
        return "none"

    async def find_candidates(
        self, record_id: RecordId | None, locator: str, origin_tag: Tag, *, space_id: SpaceId
    ) -> ImportCandidatesDto:
        """The candidates for one note, or nothing when built `blind` (a stubbed read)."""
        if self._blind:
            return ImportCandidatesDto(id_holder="none", candidates=())
        found: list[ImportCandidateDto] = []
        for knowledge in self._store.knowledge.values():
            if knowledge.space_id != space_id:
                continue
            by_id: bool = record_id is not None and knowledge.id == record_id
            history = self._store.revisions.get(knowledge.id.value, [knowledge.head])
            by_locator: bool = origin_tag in knowledge.applicability.tags and any(
                self._store.sources[source_id.value].kind is SourceKindEnum.FILE_VERSION
                and self._store.sources[source_id.value].locator == locator
                for revision in history
                for source_id in revision.source_ids
            )
            if not (by_id or by_locator):
                continue
            head = knowledge.head
            graph = not isinstance(head.content, FileContent)
            found.append(
                ImportCandidateDto(
                    id=knowledge.id.value,
                    status=knowledge.status.value,
                    created_at=knowledge.created_at,
                    head_revision=knowledge.head_number,
                    title=head.content.title,
                    body=head.content.body if graph else None,  # type: ignore[union-attr]
                    head_file_digests=tuple(
                        self._store.sources[source_id.value].digest.value  # type: ignore[union-attr]
                        for source_id in head.source_ids
                        if self._store.sources[source_id.value].kind is SourceKindEnum.FILE_VERSION
                    ),
                )
            )
        return ImportCandidatesDto(
            id_holder=self._holder(record_id, space_id), candidates=tuple(found)
        )


@dataclass(slots=True)
class FakeSupersessionProposer(ISupersessionProposer):
    """Records `propose` calls; can be told to fail."""

    assertion_id: str = ASSERTION_ID
    error: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

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
        """Record the call, then fail or return the scripted assertion id."""
        self.calls.append(
            {
                "subject_id": subject_id.value,
                "object_id": object_id.value,
                "rationale": rationale,
                "source_ids": tuple(source.value for source in source_ids),
                "actor": actor,
                "idempotency_key": idempotency_key,
                "space_id": space_id.value,
            }
        )
        if self.error is not None:
            raise self.error
        return RecordId(value=self.assertion_id)


def build_importer(
    *,
    uow_factory: KnowledgeUnitOfWorkFactory,
    clock: IClock,
    ids: IRecordIdGenerator,
    schema: IStoreSchema,
    candidates: IImportCandidateReadRepository,
    proposer: ISupersessionProposer | None = None,
) -> KnowledgeImporterAdapter:
    """The inbound adapter over both handlers (`ImportKnowledgeHandler(proposer=None)` = no C4)."""
    from noesis.bounded_context.knowledge.application.handlers.commands.replace_link_set_handler import (
        ReplaceLinkSetHandler,
    )
    from noesis.bounded_context.knowledge.application.handlers.queries.assess_link_set_handler import (
        AssessLinkSetHandler,
    )

    return KnowledgeImporterAdapter(
        link_replacer=ReplaceLinkSetHandler(uow_factory=uow_factory, clock=clock),
        link_assessor=AssessLinkSetHandler(uow_factory=uow_factory, clock=clock),
        importer=ImportKnowledgeHandler(
            uow_factory=uow_factory,
            clock=clock,
            ids=ids,
            schema=schema,
            candidates=candidates,
            proposer=proposer,
        ),
        assessor=AssessImportKnowledgeHandler(
            uow_factory=uow_factory,
            clock=clock,
            ids=ids,
            schema=schema,
            candidates=candidates,
            can_link_successor=proposer is not None,
        ),
    )


@dataclass(slots=True)
class FakeImporterHarness:
    """The adapter over C2's in-memory fakes."""

    env: KnowledgeEnv
    adapter: KnowledgeImporterAdapter
    proposer: FakeSupersessionProposer | None

    async def apply(self, **overrides: Any) -> ImportKnowledgeOutcomeContract:
        """Apply `make_request(**overrides)`."""
        return await self.adapter.apply(make_request(**overrides))

    async def assess(self, **overrides: Any) -> ImportKnowledgeOutcomeContract:
        """Assess `make_request(**overrides)`."""
        return await self.adapter.assess(make_request(**overrides))

    def ledger_keys(self) -> list[str]:
        """Every idempotency key in the fake store's ledger, sorted."""
        return sorted(key for _, key in self.env.store.ledger)

    def set_status(self, record_id: str, status: RecordStatusEnum) -> None:
        """Seed a status (C2 has no transition)."""
        self.env.store.knowledge[record_id].status = status


def make_fake_importer(
    env: KnowledgeEnv,
    *,
    proposer: FakeSupersessionProposer | None = None,
    uow_factory: Callable[[], FakeKnowledgeUnitOfWork] | None = None,
    blind: bool = False,
) -> FakeImporterHarness:
    """Wire the import handlers to `env`'s fakes; `uow_factory` can inject a failing unit of work."""
    adapter: KnowledgeImporterAdapter = build_importer(
        uow_factory=uow_factory or env.uow,
        clock=env.clock,
        ids=env.ids,
        schema=env.schema,
        candidates=FakeImportCandidateReadRepository(env.store, blind=blind),
        proposer=proposer,
    )
    return FakeImporterHarness(env=env, adapter=adapter, proposer=proposer)
