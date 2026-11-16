"""In-memory fakes of the Knowledge ports, and a ready-wired environment for handler tests."""

import copy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self
from uuid import uuid4

from noesis.bounded_context.knowledge.application.dtos import (
    ActorDto,
    ApplicabilityDto,
    RecordDto,
    RevisionDto,
    SourceDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_experience_handler import (
    CaptureExperienceHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.initialise_store_handler import (
    InitialiseStoreCommand,
    InitialiseStoreHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.revise_knowledge_handler import (
    ReviseKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.get_record_handler import (
    GetRecordHandler,
)
from noesis.bounded_context.knowledge.application.ports.consolidation import (
    IConsolidationGuardLookup,
)
from noesis.bounded_context.knowledge.application.ports.ids import IRecordIdGenerator
from noesis.bounded_context.knowledge.application.ports.ledger import (
    IIdempotencyLedger,
    LedgerEntry,
)
from noesis.bounded_context.knowledge.application.ports.read_repositories import (
    IRecordReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.schema import IStoreSchema
from noesis.bounded_context.knowledge.application.ports.uow import IKnowledgeUnitOfWork
from noesis.bounded_context.knowledge.application.services.schema_steps import CORE_STEP
from noesis.bounded_context.knowledge.domain.entities import (
    Assertion,
    CatalogEntry,
    Experience,
    Knowledge,
    KnowledgeSpace,
    Project,
    Source,
)
from noesis.bounded_context.knowledge.domain.repositories import (
    ICatalogEntryRepository,
    IConsolidationRepository,
    IExperienceRepository,
    IKnowledgeRepository,
    IKnowledgeSpaceRepository,
    IProjectRepository,
    ISourceRepository,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    ActorKindEnum,
    ContentHash,
    FileContent,
    Key,
    RecordId,
    RecordTypeEnum,
    Revision,
    SourceKindEnum,
    SpaceId,
)
from noesis.exceptions import EntryAlreadyExistsError, RevisionConflictError
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.domain import JsonValue

if TYPE_CHECKING:  # C4 modules; the C2 fakes must keep importing without them
    from noesis.bounded_context.knowledge.application.dtos.pending_record_change import (
        PendingRecordChange,
    )
    from noesis.bounded_context.knowledge.application.ports.references.i_record_reference_lookup import (
        IRecordReferenceLookup,
    )
    from noesis.bounded_context.knowledge.domain.repositories.i_assertion_repository import (
        IAssertionRepository,
    )
    from noesis.shared_kernel.contracts.knowledge import RecordChangedContract

NOW: datetime = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
DEFAULT_SPACE_KEY: Key = Key(value="default")
AGENT: Actor = Actor(kind=ActorKindEnum.AGENT, name="claude", session="s-1")


class MutableClock(IClock):
    """A clock that only moves when told to."""

    def __init__(self, now: datetime = NOW) -> None:
        self.current: datetime = now

    def now(self) -> datetime:
        """The current fake time."""
        return self.current

    def advance(self, seconds: int = 1) -> None:
        """Move the clock forward."""
        self.current += timedelta(seconds=seconds)


class SequentialIdGenerator(IRecordIdGenerator):
    """Valid ULIDs from a counter: `00000000000000000000000001`, ..."""

    def __init__(self) -> None:
        self._counter: int = 0

    def _next(self) -> str:
        self._counter += 1
        return f"{self._counter:026d}"

    def new_record_id(self) -> RecordId:
        """The next record id."""
        return RecordId(value=self._next())

    def new_space_id(self) -> SpaceId:
        """The next space id."""
        return SpaceId(value=self._next())


@dataclass(slots=True)
class FakeKnowledgeStore:
    """The committed state every fake unit of work reads and writes."""

    spaces: dict[str, KnowledgeSpace] = field(default_factory=dict)
    projects: dict[str, Project] = field(default_factory=dict)
    sources: dict[str, Source] = field(default_factory=dict)
    knowledge: dict[str, Knowledge] = field(default_factory=dict)
    experiences: dict[str, Experience] = field(default_factory=dict)
    revisions: dict[str, list[Revision]] = field(default_factory=dict)
    ledger: dict[tuple[str, str], LedgerEntry] = field(default_factory=dict)
    commits: int = 0
    changes: list[RecordChangedContract] = field(default_factory=list)
    change_counters: dict[str, int] = field(default_factory=dict)
    # C4 additions (review lifecycle); unused by C2 tests
    assertions: dict[str, Assertion] = field(default_factory=dict)
    catalog_entries: dict[str, CatalogEntry] = field(default_factory=dict)
    decision_keys: set[str] = field(default_factory=set)
    decisions: dict[str, list[Any]] = field(default_factory=dict)

    def source_key(self, source: Source) -> tuple[str, str, str, str | None]:
        """The natural key of a source, as a plain tuple."""
        space, kind, locator, digest = source.natural_key
        return (space.value, kind.value, locator, digest.value if digest else None)


class _Staged:
    """What one fake unit of work has added and not yet committed."""

    def __init__(self) -> None:
        self.spaces: dict[str, KnowledgeSpace] = {}
        self.projects: dict[str, Project] = {}
        self.sources: dict[str, Source] = {}
        self.knowledge: dict[str, Knowledge] = {}
        self.experiences: dict[str, Experience] = {}
        self.revisions: list[tuple[Knowledge, Revision]] = []
        self.ledger: dict[tuple[str, str], LedgerEntry] = {}
        self.ledger_updates: dict[tuple[str, str], LedgerEntry] = {}
        self.changes: list[RecordChangedContract] = []
        self.knowledge_saves: list[Knowledge] = []
        self.assertions: dict[str, Assertion] = {}
        self.assertion_saves: list[Assertion] = []

    def clear(self) -> None:
        """Forget everything staged (the repositories keep sharing this object)."""
        self.spaces.clear()
        self.projects.clear()
        self.sources.clear()
        self.knowledge.clear()
        self.experiences.clear()
        self.revisions.clear()
        self.ledger.clear()
        self.ledger_updates.clear()
        self.changes.clear()
        self.knowledge_saves.clear()
        self.assertions.clear()
        self.assertion_saves.clear()


def _live_key(assertion: Assertion) -> tuple[str, str, str, str, str | None]:
    project = assertion.applicability.project_id
    return (
        assertion.space_id.value,
        assertion.predicate.value,
        assertion.subject_id.value,
        assertion.object_id.value,
        project.value if project else None,
    )


def _exists(kind: str, key: str) -> EntryAlreadyExistsError:
    return EntryAlreadyExistsError(f"{kind} {key} already exists.", {"kind": kind, "key": key})


class _SpaceRepo(IKnowledgeSpaceRepository):
    def __init__(self, store: FakeKnowledgeStore, staged: _Staged) -> None:
        self._store, self._staged = store, staged

    def _all(self) -> list[KnowledgeSpace]:
        return [*self._store.spaces.values(), *self._staged.spaces.values()]

    async def add(self, space: KnowledgeSpace) -> None:
        if any(s.id == space.id or s.key == space.key for s in self._all()):
            raise _exists("space", space.key.value)
        self._staged.spaces[space.id.value] = copy.deepcopy(space)

    async def get(self, space_id: SpaceId) -> KnowledgeSpace | None:
        return next((copy.deepcopy(s) for s in self._all() if s.id == space_id), None)

    async def get_by_key(self, key: Key) -> KnowledgeSpace | None:
        return next((copy.deepcopy(s) for s in self._all() if s.key == key), None)


class _ProjectRepo(IProjectRepository):
    def __init__(self, store: FakeKnowledgeStore, staged: _Staged) -> None:
        self._store, self._staged = store, staged

    def _all(self) -> list[Project]:
        return [*self._store.projects.values(), *self._staged.projects.values()]

    async def add(self, project: Project) -> None:
        if any(
            p.id == project.id or (p.space_id == project.space_id and p.key == project.key)
            for p in self._all()
        ):
            raise _exists("project", project.key.value)
        self._staged.projects[project.id.value] = copy.deepcopy(project)

    async def get(self, project_id: RecordId, *, space_id: SpaceId) -> Project | None:
        return next(
            (
                copy.deepcopy(p)
                for p in self._all()
                if p.id == project_id and p.space_id == space_id
            ),
            None,
        )

    async def get_by_key(self, key: Key, *, space_id: SpaceId) -> Project | None:
        return next(
            (copy.deepcopy(p) for p in self._all() if p.key == key and p.space_id == space_id),
            None,
        )


class _SourceRepo(ISourceRepository):
    def __init__(self, store: FakeKnowledgeStore, staged: _Staged) -> None:
        self._store, self._staged = store, staged

    def _all(self) -> list[Source]:
        return [*self._store.sources.values(), *self._staged.sources.values()]

    async def add(self, source: Source) -> None:
        key = self._store.source_key(source)
        if any(s.id == source.id or self._store.source_key(s) == key for s in self._all()):
            raise _exists("source", source.locator)
        self._staged.sources[source.id.value] = copy.deepcopy(source)

    async def get(self, source_id: RecordId, *, space_id: SpaceId) -> Source | None:
        return next(
            (copy.deepcopy(s) for s in self._all() if s.id == source_id and s.space_id == space_id),
            None,
        )

    async def get_by_natural_key(
        self,
        *,
        space_id: SpaceId,
        kind: SourceKindEnum,
        locator: str,
        digest: ContentHash | None,
    ) -> Source | None:
        wanted = (space_id, kind, locator, digest)
        return next((copy.deepcopy(s) for s in self._all() if s.natural_key == wanted), None)


class _KnowledgeRepo(IKnowledgeRepository):
    def __init__(self, store: FakeKnowledgeStore, staged: _Staged) -> None:
        self._store, self._staged = store, staged

    async def add(self, knowledge: Knowledge) -> None:
        key: str = knowledge.id.value
        if key in self._store.knowledge or key in self._staged.knowledge:
            raise _exists("knowledge", key)
        self._staged.knowledge[key] = copy.deepcopy(knowledge)

    async def get(self, record_id: RecordId, *, space_id: SpaceId) -> Knowledge | None:
        found: Knowledge | None = self._staged.knowledge.get(
            record_id.value
        ) or self._store.knowledge.get(record_id.value)
        return copy.deepcopy(found) if found and found.space_id == space_id else None

    async def get_for_update(self, record_id: RecordId, *, space_id: SpaceId) -> Knowledge | None:
        # The fake has no real lock; tests simulate a lost race by committing in between.
        return await self.get(record_id, space_id=space_id)

    async def append_revision(self, knowledge: Knowledge, revision: Revision) -> None:
        self._staged.revisions.append((copy.deepcopy(knowledge), revision))

    async def save(self, knowledge: Knowledge) -> None:
        self._staged.knowledge_saves.append(copy.deepcopy(knowledge))


class _ExperienceRepo(IExperienceRepository):
    def __init__(self, store: FakeKnowledgeStore, staged: _Staged) -> None:
        self._store, self._staged = store, staged

    async def add(self, experience: Experience) -> None:
        key: str = experience.id.value
        if key in self._store.experiences or key in self._staged.experiences:
            raise _exists("experience", key)
        self._staged.experiences[key] = copy.deepcopy(experience)

    async def get(self, record_id: RecordId, *, space_id: SpaceId) -> Experience | None:
        found: Experience | None = self._staged.experiences.get(
            record_id.value
        ) or self._store.experiences.get(record_id.value)
        return copy.deepcopy(found) if found and found.space_id == space_id else None


class _Ledger(IIdempotencyLedger):
    def __init__(self, store: FakeKnowledgeStore, staged: _Staged) -> None:
        self._store, self._staged = store, staged

    async def get(self, space_id: SpaceId, key: str) -> LedgerEntry | None:
        slot = (space_id.value, key)
        return self._staged.ledger.get(slot) or self._store.ledger.get(slot)

    async def record(self, entry: LedgerEntry) -> None:
        slot = (entry.space_id.value, entry.key)
        if slot in self._store.ledger or slot in self._staged.ledger:
            raise _exists("idempotency key", entry.key)
        self._staged.ledger[slot] = entry

    async def update_extra(
        self,
        space_id: SpaceId,
        key: str,
        *,
        expected_progress_version: int,
        extra: dict[str, JsonValue],
    ) -> None:
        slot = (space_id.value, key)
        current = self._staged.ledger_updates.get(slot) or self._store.ledger.get(slot)
        actual = current.extra.get("progress_version") if current else None
        if current is None or actual != expected_progress_version:
            raise RevisionConflictError(
                f"Expected progress version {expected_progress_version} but it is {actual}.",
                {"key": key},
            )
        self._staged.ledger_updates[slot] = current.model_copy(
            update={"extra": {**extra, "progress_version": expected_progress_version + 1}}
        )


class FakeRecordChangeLog:
    """The change log of one fake unit of work (structural `IRecordChangeLog`).

    `append` assigns the next per-space sequence at once, like the `:ChangeCounter` increment in
    the real transaction; the change joins the store on `commit` and is dropped on rollback.
    The port and kernel contract are imported lazily so this module loads before they exist.
    """

    def __init__(self, store: FakeKnowledgeStore, staged: _Staged) -> None:
        self._store, self._staged = store, staged

    async def append(self, change: PendingRecordChange) -> RecordChangedContract:
        """Stage `change` with the next sequence of its space and return the contract."""
        from noesis.shared_kernel.contracts.knowledge import RecordChangedContract

        sequence: int = (
            self._store.change_counters.get(change.space_id, 0)
            + sum(1 for staged in self._staged.changes if staged.space_id == change.space_id)
            + 1
        )
        contract = RecordChangedContract(
            event_id=uuid4().hex,
            occurred_at=change.occurred_at,
            sequence=sequence,
            space_id=change.space_id,
            record_id=change.record_id,
            record_type=change.record_type,
            change_kind=change.change_kind,
            revision=change.revision,
            status=change.status,
        )
        self._staged.changes.append(contract)
        return contract


class FakeKnowledgeUnitOfWork(IKnowledgeUnitOfWork):
    """Stages writes and applies them on `commit`, re-checking uniqueness against the store.

    That re-check is what makes a lost race observable: whoever commits second gets the same
    duplicate (or revision-conflict) error a constraint would raise.
    """

    def __init__(self, store: FakeKnowledgeStore) -> None:
        self._store: FakeKnowledgeStore = store
        self._staged: _Staged = _Staged()
        self._spaces = _SpaceRepo(store, self._staged)
        self._projects = _ProjectRepo(store, self._staged)
        self._sources = _SourceRepo(store, self._staged)
        self._knowledge = _KnowledgeRepo(store, self._staged)
        self._experiences = _ExperienceRepo(store, self._staged)
        self._ledger = _Ledger(store, self._staged)
        self._changes = FakeRecordChangeLog(store, self._staged)
        self._assertions: IAssertionRepository | None = None
        self._record_references: IRecordReferenceLookup | None = None

    @property
    def changes(self) -> FakeRecordChangeLog:
        """Fake change log (staged until commit)."""
        return self._changes

    @property
    def assertions(self) -> IAssertionRepository:
        """Fake assertion repository (built lazily from `tests.support.review_fakes`)."""
        if self._assertions is None:
            from tests.support.review_fakes import FakeAssertionRepository

            self._assertions = FakeAssertionRepository(self._store, self._staged)
        return self._assertions

    @property
    def record_references(self) -> IRecordReferenceLookup:
        """Fake record-reference lookup (built lazily from `tests.support.review_fakes`)."""
        if self._record_references is None:
            from tests.support.review_fakes import FakeRecordReferenceLookup

            self._record_references = FakeRecordReferenceLookup(self._store)
        return self._record_references

    @property
    def spaces(self) -> IKnowledgeSpaceRepository:
        """Fake space repository."""
        return self._spaces

    @property
    def projects(self) -> IProjectRepository:
        """Fake project repository."""
        return self._projects

    @property
    def sources(self) -> ISourceRepository:
        """Fake source repository."""
        return self._sources

    @property
    def knowledge(self) -> IKnowledgeRepository:
        """Fake knowledge repository."""
        return self._knowledge

    @property
    def experiences(self) -> IExperienceRepository:
        """Fake experience repository."""
        return self._experiences

    @property
    def ledger(self) -> IIdempotencyLedger:
        """Fake ledger."""
        return self._ledger

    @property
    def catalog_entries(self) -> ICatalogEntryRepository:
        """Not stored here: `FakeCatalogUnitOfWork` (catalog_support) overrides it."""
        raise NotImplementedError("use FakeCatalogUnitOfWork for catalog entries")

    @property
    def consolidations(self) -> IConsolidationRepository:
        """Consolidations are covered against Neo4j; the in-memory fake has none."""
        raise NotImplementedError("use the Neo4j environment for consolidations")

    @property
    def consolidation_guard(self) -> IConsolidationGuardLookup:
        """Consolidation guards are covered against Neo4j; the in-memory fake has none."""
        raise NotImplementedError("use the Neo4j environment for consolidations")

    @property
    def link_sets(self):
        """Link tests override this member with a staged repository."""
        raise NotImplementedError("use a link-set unit of work")

    async def __aenter__(self) -> Self:
        self._staged.clear()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.rollback()

    async def commit(self) -> None:
        """Apply the staged writes, or raise the error a constraint would."""
        store, staged = self._store, self._staged
        for space in staged.spaces.values():
            if any(s.id == space.id or s.key == space.key for s in store.spaces.values()):
                raise _exists("space", space.key.value)
        for project in staged.projects.values():
            if any(
                p.space_id == project.space_id and p.key == project.key
                for p in store.projects.values()
            ):
                raise _exists("project", project.key.value)
        for source in staged.sources.values():
            if any(store.source_key(s) == store.source_key(source) for s in store.sources.values()):
                raise _exists("source", source.locator)
        for slot in staged.ledger:
            if slot in store.ledger:
                raise _exists("idempotency key", slot[1])
        for knowledge in staged.knowledge.values():
            if knowledge.id.value in store.knowledge:
                raise _exists("knowledge", knowledge.id.value)
        for knowledge, revision in staged.revisions:
            history: list[Revision] | None = store.revisions.get(knowledge.id.value)
            if history is not None and len(history) >= revision.number:
                actual: int = store.knowledge[knowledge.id.value].head_number
                raise RevisionConflictError(
                    f"Revision {revision.number} already exists.",
                    {
                        "record_id": knowledge.id.value,
                        "expected_revision": revision.number - 1,
                        "actual_revision": actual,
                    },
                )

        self._check_review_constraints()

        store.spaces.update(staged.spaces)
        store.projects.update(staged.projects)
        store.sources.update(staged.sources)
        store.experiences.update(staged.experiences)
        store.ledger.update(staged.ledger)
        store.ledger.update(staged.ledger_updates)
        for knowledge in staged.knowledge.values():
            store.knowledge[knowledge.id.value] = knowledge
            store.revisions[knowledge.id.value] = [knowledge.head]
        for knowledge, revision in staged.revisions:
            store.knowledge[knowledge.id.value] = knowledge
            store.revisions[knowledge.id.value].append(revision)
        for change in staged.changes:
            store.changes.append(change)
            store.change_counters[change.space_id] = change.sequence
        for knowledge in staged.knowledge_saves:
            store.knowledge[knowledge.id.value] = knowledge
            self._keep_decision(knowledge.id.value, knowledge.latest_decision)
        store.assertions.update(staged.assertions)
        for assertion in staged.assertion_saves:
            store.assertions[assertion.id.value] = assertion
            self._keep_decision(assertion.id.value, assertion.latest_decision)
        store.commits += 1
        await self.rollback()

    def _keep_decision(self, record_id: str, decision: Any) -> None:
        if decision is not None:
            self._store.decision_keys.add(f"{record_id}:{decision.seq}")
            self._store.decisions.setdefault(record_id, []).append(decision)

    def _check_review_constraints(self) -> None:
        """The constraints C4 adds: unique decision key per record, one live statement."""
        store, staged = self._store, self._staged
        for record in (*staged.knowledge_saves, *staged.assertion_saves):
            decision = record.latest_decision
            if decision is not None and f"{record.id.value}:{decision.seq}" in store.decision_keys:
                from noesis.exceptions import StatusConflictError

                raise StatusConflictError(
                    f"Another decision for {record.id.value} won the race.",
                    {"record_id": record.id.value, "seq": decision.seq},
                )
        for assertion in (*staged.assertions.values(), *staged.assertion_saves):
            if assertion.status.value not in ("proposed", "accepted"):
                continue
            key = _live_key(assertion)
            for other in store.assertions.values():
                if (
                    other.id != assertion.id
                    and other.status.value in ("proposed", "accepted")
                    and _live_key(other) == key
                ):
                    from noesis.exceptions import DuplicateAssertionError

                    raise DuplicateAssertionError(
                        f"A live assertion {other.id.value} states the same.",
                        {"existing_id": other.id.value},
                    )

    async def rollback(self) -> None:
        """Drop everything staged."""
        self._staged.clear()


class FakeStoreSchema(IStoreSchema):
    """Schema steps held in a set."""

    def __init__(self, steps: tuple[str, ...] = (CORE_STEP,)) -> None:
        self._steps: tuple[str, ...] = steps
        self.applied: set[str] = set()
        self.apply_calls: list[str] = []

    def registered_steps(self) -> tuple[str, ...]:
        """The registered step names."""
        return self._steps

    async def applied_steps(self) -> frozenset[str]:
        """The applied step names."""
        return frozenset(self.applied)

    async def apply_step(self, name: str) -> bool:
        """Apply once; True the first time."""
        self.apply_calls.append(name)
        if name in self.applied:
            return False
        self.applied.add(name)
        return True


def _actor_dto(actor: Actor) -> ActorDto:
    return ActorDto(kind=actor.kind.value, name=actor.name, session=actor.session)


class FakeRecordReadRepository(IRecordReadRepository):
    """Builds read DTOs straight from the fake store's committed state."""

    def __init__(self, store: FakeKnowledgeStore) -> None:
        self._store: FakeKnowledgeStore = store

    async def get_space_id(self, key: Key) -> SpaceId | None:
        """Id of the space with `key`."""
        return next((s.id for s in self._store.spaces.values() if s.key == key), None)

    def _sources(self, ids: tuple[RecordId, ...]) -> tuple[SourceDto, ...]:
        found: list[Source] = [self._store.sources[i.value] for i in ids]
        return tuple(
            SourceDto(
                id=s.id.value,
                kind=s.kind.value,
                locator=s.locator,
                digest=s.digest.value if s.digest else None,
            )
            for s in found
        )

    def _revision(self, revision: Revision) -> RevisionDto:
        content = revision.content
        return RevisionDto(
            number=revision.number,
            actor=_actor_dto(revision.actor),
            created_at=revision.created_at,
            title=content.title,
            body=None if isinstance(content, FileContent) else content.body,
            content_hash=content.content_hash.value if isinstance(content, FileContent) else None,
            file_version_source_id=(
                content.file_version_source_id.value if isinstance(content, FileContent) else None
            ),
            sources=self._sources(revision.source_ids),
        )

    async def get_by_id(self, record_id: RecordId, *, space_id: SpaceId) -> RecordDto | None:
        """The record as a DTO, or None when unknown or in another space."""
        key: str = record_id.value
        if (knowledge := self._store.knowledge.get(key)) and knowledge.space_id == space_id:
            head: RevisionDto = self._revision(knowledge.head)
            project = knowledge.applicability.project_id
            return RecordDto(
                id=key,
                type=RecordTypeEnum.KNOWLEDGE.value,
                space_id=space_id.value,
                project_id=project.value if project else None,
                subtype=knowledge.subtype.value,
                status=knowledge.status.value,
                ownership=knowledge.ownership.value,
                head_revision=knowledge.head_number,
                applicability=ApplicabilityDto(
                    project_id=project.value if project else None,
                    tags=tuple(t.value for t in knowledge.applicability.sorted_tags),
                ),
                revision=head,
                sources=head.sources,
                created_at=knowledge.created_at,
                updated_at=knowledge.updated_at,
            )
        if (exp := self._store.experiences.get(key)) and exp.space_id == space_id:
            return RecordDto(
                id=key,
                type=RecordTypeEnum.EXPERIENCE.value,
                space_id=space_id.value,
                project_id=exp.project_id.value if exp.project_id else None,
                subtype=exp.subtype.value,
                actor=_actor_dto(exp.actor),
                sources=self._sources(exp.source_ids),
                body=exp.body,
                occurred_at=exp.occurred_at,
                session=exp.session,
                environment=exp.environment,
                created_at=exp.created_at,
                updated_at=exp.updated_at,
            )
        if (src := self._store.sources.get(key)) and src.space_id == space_id:
            return RecordDto(
                id=key,
                type=RecordTypeEnum.SOURCE.value,
                space_id=space_id.value,
                source_kind=src.kind.value,
                locator=src.locator,
                digest=src.digest.value if src.digest else None,
                created_at=src.created_at,
                updated_at=src.updated_at,
            )
        if (proj := self._store.projects.get(key)) and proj.space_id == space_id:
            return RecordDto(
                id=key,
                type=RecordTypeEnum.PROJECT.value,
                space_id=space_id.value,
                key=proj.key.value,
                name=proj.name,
                created_at=proj.created_at,
                updated_at=proj.updated_at,
            )
        return None

    async def get_revision(
        self, record_id: RecordId, number: int, *, space_id: SpaceId
    ) -> RevisionDto | None:
        """Revision `number` of knowledge in `space_id`, or None."""
        knowledge = self._store.knowledge.get(record_id.value)
        if knowledge is None or knowledge.space_id != space_id:
            return None
        history: list[Revision] = self._store.revisions.get(record_id.value, [])
        return self._revision(history[number - 1]) if 1 <= number <= len(history) else None


@dataclass(slots=True)
class KnowledgeEnv:
    """Fakes and handlers wired together over one in-memory store."""

    store: FakeKnowledgeStore
    schema: FakeStoreSchema
    ids: SequentialIdGenerator
    clock: MutableClock
    read: FakeRecordReadRepository

    def uow(self) -> FakeKnowledgeUnitOfWork:
        """A fresh unit of work over the store."""
        return FakeKnowledgeUnitOfWork(self.store)

    @property
    def capture_knowledge(self) -> CaptureKnowledgeHandler:
        """Handler wired to the fakes."""
        return CaptureKnowledgeHandler(
            uow_factory=self.uow, clock=self.clock, ids=self.ids, schema=self.schema
        )

    @property
    def capture_experience(self) -> CaptureExperienceHandler:
        """Handler wired to the fakes."""
        return CaptureExperienceHandler(
            uow_factory=self.uow, clock=self.clock, ids=self.ids, schema=self.schema
        )

    @property
    def revise_knowledge(self) -> ReviseKnowledgeHandler:
        """Handler wired to the fakes."""
        return ReviseKnowledgeHandler(
            uow_factory=self.uow, clock=self.clock, ids=self.ids, schema=self.schema
        )

    @property
    def get_record(self) -> GetRecordHandler:
        """Handler wired to the fakes."""
        return GetRecordHandler(read_repository=self.read, schema=self.schema)

    @property
    def initialise_store(self) -> InitialiseStoreHandler:
        """Handler wired to the fakes."""
        return InitialiseStoreHandler(
            uow_factory=self.uow, clock=self.clock, ids=self.ids, schema=self.schema
        )


async def make_env(
    *, initialised: bool = True, steps: tuple[str, ...] = (CORE_STEP,)
) -> KnowledgeEnv:
    """A fresh environment; when `initialised`, `store init` has run (default space `default`)."""
    store = FakeKnowledgeStore()
    env = KnowledgeEnv(
        store=store,
        schema=FakeStoreSchema(steps),
        ids=SequentialIdGenerator(),
        clock=MutableClock(),
        read=FakeRecordReadRepository(store),
    )
    if initialised:
        await env.initialise_store.handle(
            InitialiseStoreCommand(default_space_key=DEFAULT_SPACE_KEY)
        )
    return env
