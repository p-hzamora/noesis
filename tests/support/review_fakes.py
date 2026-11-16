"""In-memory fakes and a ready-wired environment for the C4 review handlers.

Additive to `knowledge_support`: the shared store, staging and commit (decision-key and live
statement uniqueness included) live there; this module adds the assertion repository, the record
reference lookup, the review read repositories, a unit-of-work factory that records and can fail,
and seeding helpers. The C4 modules imported here do not exist until C4 is built.
"""

import copy
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from tests.support.knowledge_support import (
    AGENT,
    DEFAULT_SPACE_KEY,
    FakeKnowledgeStore,
    FakeKnowledgeUnitOfWork,
    FakeRecordReadRepository,
    KnowledgeEnv,
    _exists,
    _Staged,
    make_env,
)

from noesis.bounded_context.knowledge.application.dtos.review_dtos import (
    AssertionDto,
    AssertionSummaryDto,
    PendingEffectDto,
    ReviewQueueItemDto,
    ReviewQueuePageDto,
    ReviewStateDto,
    TaggedProposalDto,
    TagMatchCountsDto,
)
from noesis.bounded_context.knowledge.application.handlers.commands.accept_assertion_handler import (
    AcceptAssertionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.accept_knowledge_handler import (
    AcceptKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.apply_supersession_handler import (
    ApplySupersessionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.bulk_accept_knowledge_by_tag_handler import (
    BulkAcceptKnowledgeByTagHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.capture_knowledge_handler import (
    CaptureKnowledgeCommand,
)
from noesis.bounded_context.knowledge.application.handlers.commands.propose_assertion_handler import (
    ProposeAssertionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.repair_supersession_effects_handler import (
    RepairSupersessionEffectsHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.retract_assertion_handler import (
    RetractAssertionHandler,
)
from noesis.bounded_context.knowledge.application.handlers.commands.retract_knowledge_handler import (
    RetractKnowledgeHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.get_review_states_handler import (
    GetReviewStatesHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.list_assertions_by_subjects_handler import (
    ListAssertionsBySubjectsHandler,
)
from noesis.bounded_context.knowledge.application.handlers.queries.list_review_queue_handler import (
    ListReviewQueueHandler,
)
from noesis.bounded_context.knowledge.application.ports.read_repositories.i_assertion_read_repository import (
    IAssertionReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.read_repositories.i_review_queue_read_repository import (
    IReviewQueueReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.read_repositories.i_review_state_read_repository import (
    IReviewStateReadRepository,
)
from noesis.bounded_context.knowledge.application.ports.references.i_record_reference_lookup import (
    IRecordReferenceLookup,
)
from noesis.bounded_context.knowledge.application.services.inputs import ProjectRef
from noesis.bounded_context.knowledge.application.services.record_reference_resolver import (
    RecordReferenceResolver,
)
from noesis.bounded_context.knowledge.application.services.schema_steps import (
    CORE_STEP,
    REVIEW_STEP,
)
from noesis.bounded_context.knowledge.domain.entities import Assertion, CatalogEntry, Knowledge
from noesis.bounded_context.knowledge.domain.repositories.i_assertion_repository import (
    IAssertionRepository,
)
from noesis.bounded_context.knowledge.domain.services.review_state import (
    authority_of,
    effective_status_of,
)
from noesis.bounded_context.knowledge.domain.value_objects import (
    Actor,
    Applicability,
    AssertionPredicateEnum,
    CatalogEntryKindEnum,
    Key,
    RecordId,
    RecordStatusEnum,
    RecordTypeEnum,
    Slug,
    SpaceId,
    Tag,
)
from noesis.bounded_context.knowledge.domain.value_objects.record_reference import RecordReference
from noesis.bounded_context.knowledge.domain.value_objects.statement_key import StatementKey
from noesis.exceptions import GraphStoreUnavailableError

LIVE: tuple[RecordStatusEnum, ...] = (RecordStatusEnum.PROPOSED, RecordStatusEnum.ACCEPTED)


# ---------------------------------------------------------------------------------------------
# What a stored record looks like to the review side
# ---------------------------------------------------------------------------------------------


@dataclass(slots=True)
class _Inspection:
    reference: RecordReference
    stored_status: RecordStatusEnum | None
    tags: tuple[str, ...]
    project_key: str | None
    decision: Any
    superseded_by: tuple[Assertion, ...]


def _accepted_supersessions_of(
    store: FakeKnowledgeStore, record_id: RecordId
) -> tuple[Assertion, ...]:
    return tuple(
        sorted(
            (
                a
                for a in store.assertions.values()
                if a.predicate is AssertionPredicateEnum.SUPERSEDES
                and a.status is RecordStatusEnum.ACCEPTED
                and a.object_id == record_id
            ),
            key=lambda a: a.id.value,
        )
    )


def _project_key(store: FakeKnowledgeStore, project_id: RecordId | None) -> str | None:
    if project_id is None:
        return None
    return store.projects[project_id.value].key.value


def inspect_record(
    store: FakeKnowledgeStore, record_id: RecordId, space_id: SpaceId
) -> _Inspection | None:
    """Describe a committed record of `space_id`; None when unknown or in another space."""
    key: str = record_id.value
    superseded_by = _accepted_supersessions_of(store, record_id)

    def build(
        record_type: RecordTypeEnum,
        *,
        project_id: RecordId | None = None,
        stored: RecordStatusEnum | None = None,
        head: int | None = None,
        tags: frozenset[Tag] = frozenset(),
        decision: Any = None,
    ) -> _Inspection:
        effective = effective_status_of(stored, superseded_by_accepted=bool(superseded_by))
        return _Inspection(
            reference=RecordReference(
                record_id=record_id,
                record_type=record_type,
                space_id=space_id,
                project_id=project_id,
                effective_status=effective,
                head_revision=head,
            ),
            stored_status=stored,
            tags=tuple(sorted(t.value for t in tags)),
            project_key=_project_key(store, project_id),
            decision=decision,
            superseded_by=superseded_by,
        )

    if (k := store.knowledge.get(key)) and k.space_id == space_id:
        return build(
            RecordTypeEnum.KNOWLEDGE,
            project_id=k.applicability.project_id,
            stored=k.status,
            head=k.head_number,
            tags=k.applicability.tags,
            decision=k.latest_decision,
        )
    if (a := store.assertions.get(key)) and a.space_id == space_id:
        return build(
            RecordTypeEnum.ASSERTION,
            project_id=a.applicability.project_id,
            stored=a.status,
            tags=a.applicability.tags,
            decision=a.latest_decision,
        )
    if (e := store.experiences.get(key)) and e.space_id == space_id:
        return build(RecordTypeEnum.EXPERIENCE, project_id=e.project_id)
    if (s := store.sources.get(key)) and s.space_id == space_id:
        return build(RecordTypeEnum.SOURCE)
    if (p := store.projects.get(key)) and p.space_id == space_id:
        return build(RecordTypeEnum.PROJECT)
    if (c := store.catalog_entries.get(key)) and c.space_id == space_id:
        return build(RecordTypeEnum.CATALOG_ENTRY)
    return None


# ---------------------------------------------------------------------------------------------
# Write side: assertion repository and reference lookup
# ---------------------------------------------------------------------------------------------


class FakeAssertionRepository(IAssertionRepository):
    """Stages assertions in the unit of work's staging area, shared with the Knowledge fake."""

    def __init__(self, store: FakeKnowledgeStore, staged: _Staged) -> None:
        self._store, self._staged = store, staged

    def _all(self) -> list[Assertion]:
        return [*self._store.assertions.values(), *self._staged.assertions.values()]

    async def add(self, assertion: Assertion) -> None:
        if any(a.id == assertion.id for a in self._all()):
            raise _exists("assertion", assertion.id.value)
        self._staged.assertions[assertion.id.value] = copy.deepcopy(assertion)

    async def get_by_id(self, record_id: RecordId, *, space_id: SpaceId) -> Assertion | None:
        found = self._staged.assertions.get(record_id.value) or self._store.assertions.get(
            record_id.value
        )
        return copy.deepcopy(found) if found and found.space_id == space_id else None

    async def get_live_by_statement(self, key: StatementKey) -> Assertion | None:
        for a in self._all():
            if (
                a.status in LIVE
                and a.space_id == key.space_id
                and a.predicate == key.predicate
                and a.subject_id == key.subject_id
                and a.object_id == key.object_id
                and a.applicability.project_id == key.project_id
            ):
                return copy.deepcopy(a)
        return None

    async def save(self, assertion: Assertion) -> None:
        self._staged.assertion_saves.append(copy.deepcopy(assertion))


class FakeRecordReferenceLookup(IRecordReferenceLookup):
    """Describes committed records by id; unknown ids and other-space ids are left out."""

    def __init__(self, store: FakeKnowledgeStore) -> None:
        self._store: FakeKnowledgeStore = store

    async def describe(self, ids: Sequence[RecordId], space_id: SpaceId) -> list[RecordReference]:
        found = (inspect_record(self._store, i, space_id) for i in dict.fromkeys(ids))
        return [f.reference for f in found if f is not None]


# ---------------------------------------------------------------------------------------------
# Unit-of-work factory: records what committed, can fail on the Nth commit
# ---------------------------------------------------------------------------------------------


class _RecordingUnitOfWork(FakeKnowledgeUnitOfWork):
    def __init__(self, store: FakeKnowledgeStore, factory: RecordingUowFactory) -> None:
        super().__init__(store)
        self._factory = factory

    async def commit(self) -> None:
        """Count the commit, fail it when it is the chosen one, else commit and log the writes."""
        factory = self._factory
        factory.commit_attempts += 1
        if factory.commit_attempts == factory.fail_on_commit:
            raise factory.error or GraphStoreUnavailableError(
                "Neo4j connection lost.", {"phase": "commit"}
            )
        written: list[str] = [
            *(k.id.value for k in self._staged.knowledge_saves),
            *(a.id.value for a in self._staged.assertion_saves),
        ]
        await super().commit()
        factory.commit_log.append(written)


class RecordingUowFactory:
    """Opens fake units of work, counts them, logs each commit's saved records, fails on demand.

    Attributes:
        opened: Units of work opened so far.
        commit_attempts: Calls to `commit` so far.
        commit_log: For each successful commit, the ids of the records it saved (Knowledge and
            Assertion saves, in staging order); a one-record-per-unit-of-work rule shows as
            lists of length one.
        fail_on_commit: The 1-based commit attempt that raises instead of committing.
        error: What that attempt raises; `GraphStoreUnavailableError` when None.
    """

    def __init__(
        self,
        store: FakeKnowledgeStore,
        *,
        fail_on_commit: int | None = None,
        error: Exception | None = None,
    ) -> None:
        self._store = store
        self.fail_on_commit = fail_on_commit
        self.error = error
        self.opened: int = 0
        self.commit_attempts: int = 0
        self.commit_log: list[list[str]] = []

    def __call__(self) -> FakeKnowledgeUnitOfWork:
        self.opened += 1
        return _RecordingUnitOfWork(self._store, self)


class CountingSchema:
    """Wraps a schema fake and counts reads, to prove a refusal touched no store."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: int = 0

    def registered_steps(self) -> tuple[str, ...]:
        """Passes through."""
        self.calls += 1
        return self._inner.registered_steps()

    async def applied_steps(self) -> frozenset[str]:
        """Counts, then passes through."""
        self.calls += 1
        return await self._inner.applied_steps()

    async def apply_step(self, name: str) -> bool:
        """Counts, then passes through."""
        self.calls += 1
        return await self._inner.apply_step(name)


# ---------------------------------------------------------------------------------------------
# Read side
# ---------------------------------------------------------------------------------------------


class FakeReviewStateReadRepository(IReviewStateReadRepository):
    """Review states derived from the committed store with the production domain functions."""

    def __init__(self, store: FakeKnowledgeStore) -> None:
        self._store: FakeKnowledgeStore = store

    async def get_states(self, ids: Sequence[RecordId], space_id: SpaceId) -> list[ReviewStateDto]:
        """One state per known id, in the order given."""
        states: list[ReviewStateDto] = []
        for record_id in dict.fromkeys(ids):
            found = inspect_record(self._store, record_id, space_id)
            if found is None:
                continue
            ref = found.reference
            states.append(
                ReviewStateDto(
                    record_id=record_id.value,
                    record_type=ref.record_type.value,
                    status=found.stored_status.value if found.stored_status else None,
                    effective_status=ref.effective_status.value if ref.effective_status else None,
                    authority=authority_of(ref.effective_status).value,
                    head_revision=ref.head_revision,
                    superseded_by_assertion_id=(
                        found.superseded_by[0].id.value if found.superseded_by else None
                    ),
                    superseded_by_record_ids=tuple(a.subject_id.value for a in found.superseded_by),
                    project_key=found.project_key,
                    tags=found.tags,
                    decided_by_kind=found.decision.actor.kind.value if found.decision else None,
                    decided_at=found.decision.decided_at.isoformat() if found.decision else None,
                )
            )
        return states

    async def list_pending_effects(self, space_id: SpaceId) -> list[PendingEffectDto]:
        """Accepted `supersedes` assertions whose object is still stored `accepted`."""
        pending: list[PendingEffectDto] = []
        for a in sorted(self._store.assertions.values(), key=lambda x: x.id.value):
            if (
                a.space_id == space_id
                and a.predicate is AssertionPredicateEnum.SUPERSEDES
                and a.status is RecordStatusEnum.ACCEPTED
            ):
                target = self._store.knowledge.get(a.object_id.value) or self._store.assertions.get(
                    a.object_id.value
                )
                if target is not None and target.status is RecordStatusEnum.ACCEPTED:
                    pending.append(
                        PendingEffectDto(assertion_id=a.id.value, object_id=a.object_id.value)
                    )
        return pending


class FakeAssertionReadRepository(IAssertionReadRepository):
    """Assertion summaries from the committed store; only the batch read is needed by C4's units."""

    def __init__(self, store: FakeKnowledgeStore) -> None:
        self._store: FakeKnowledgeStore = store

    async def get_by_id(self, record_id: RecordId, *, space_id: SpaceId) -> AssertionDto | None:
        """Not needed by the unit tests."""
        raise NotImplementedError

    async def list_about(self, *args: Any, **kwargs: Any) -> Any:
        """Not needed by the unit tests."""
        raise NotImplementedError

    async def list_by_subjects(
        self,
        subject_ids: Sequence[RecordId],
        *,
        space_id: SpaceId,
        predicates: Sequence[AssertionPredicateEnum] = (),
        statuses: Sequence[RecordStatusEnum] = (),
    ) -> list[AssertionSummaryDto]:
        """Assertions whose subject is in `subject_ids`, ascending id; empty filters match all."""
        wanted = set(subject_ids)
        summaries: list[AssertionSummaryDto] = []
        for a in sorted(self._store.assertions.values(), key=lambda x: x.id.value):
            if a.space_id != space_id or a.subject_id not in wanted:
                continue
            if predicates and a.predicate not in predicates:
                continue
            if statuses and a.status not in statuses:
                continue
            target = inspect_record(self._store, a.object_id, space_id)
            summaries.append(
                AssertionSummaryDto(
                    assertion_id=a.id.value,
                    predicate=a.predicate.value,
                    subject_id=a.subject_id.value,
                    subject_at_revision=a.subject_at_revision,
                    object_id=a.object_id.value,
                    object_at_revision=a.object_at_revision,
                    object_type=target.reference.record_type.value if target else "",
                    status=a.status.value,
                    evidence_ids=tuple(e.value for e in a.evidence_ids),
                    project_key=_project_key(self._store, a.applicability.project_id),
                    tags=tuple(t.value for t in a.applicability.sorted_tags),
                )
            )
        return summaries


type PageHook = Callable[[list[TaggedProposalDto]], Awaitable[None]]


class FakeReviewQueueReadRepository(IReviewQueueReadRepository):
    """Queue and tag reads over the committed store; records every `list_proposed_by_tag` call.

    Attributes:
        page_calls: `(after_id, limit)` of every `list_proposed_by_tag` call, in order.
        count_calls: Tags `count_by_tag` was called with, in order.
        after_page: Awaited with each non-empty page right after it is read (lets a test change
            the store between the page read and the per-record unit of work).
    """

    def __init__(self, store: FakeKnowledgeStore, after_page: PageHook | None = None) -> None:
        self._store: FakeKnowledgeStore = store
        self.after_page: PageHook | None = after_page
        self.page_calls: list[tuple[RecordId | None, int]] = []
        self.count_calls: list[Tag] = []
        self._queue_calls: int = 0

    @property
    def calls(self) -> int:
        """Every call of every method."""
        return len(self.page_calls) + len(self.count_calls) + self._queue_calls

    def _tagged(self, space_id: SpaceId, tag: Tag) -> list[Knowledge]:
        return sorted(
            (
                k
                for k in self._store.knowledge.values()
                if k.space_id == space_id and tag in k.applicability.tags
            ),
            key=lambda k: k.id.value,
        )

    async def count_by_tag(self, space_id: SpaceId, tag: Tag) -> TagMatchCountsDto:
        """Knowledge carrying `tag`, and those of them stored `proposed`."""
        self.count_calls.append(tag)
        tagged = self._tagged(space_id, tag)
        return TagMatchCountsDto(
            matched=len(tagged),
            proposed=sum(1 for k in tagged if k.status is RecordStatusEnum.PROPOSED),
        )

    async def list_proposed_by_tag(
        self, space_id: SpaceId, tag: Tag, *, after_id: RecordId | None, limit: int
    ) -> list[TaggedProposalDto]:
        """Proposed Knowledge carrying `tag`, ascending id, after `after_id`, at most `limit`."""
        self.page_calls.append((after_id, limit))
        page = [
            TaggedProposalDto(
                id=k.id.value,
                title=k.head.content.title,
                subtype=k.subtype.value,
                project_key=_project_key(self._store, k.applicability.project_id),
                head_revision=k.head_number,
            )
            for k in self._tagged(space_id, tag)
            if k.status is RecordStatusEnum.PROPOSED
            and (after_id is None or k.id.value > after_id.value)
        ][:limit]
        if page and self.after_page is not None:
            await self.after_page(page)
        return page

    async def list_queue(
        self,
        space_id: SpaceId,
        *,
        project: Key | None,
        global_only: bool,
        record_type: RecordTypeEnum | None,
        predicate: AssertionPredicateEnum | None,
        limit: int,
        cursor: str | None,
    ) -> ReviewQueuePageDto:
        """Records with effective status `proposed`, ascending id, with applicability only.

        `requires` and `decidable_by_caller` are left unset: the handler decides them.
        """
        self._queue_calls += 1
        items: list[ReviewQueueItemDto] = []
        for record in sorted(
            [*self._store.knowledge.values(), *self._store.assertions.values()],
            key=lambda r: r.id.value,
        ):
            found = inspect_record(self._store, record.id, space_id)
            if found is None or found.reference.effective_status is not RecordStatusEnum.PROPOSED:
                continue
            is_assertion = isinstance(record, Assertion)
            if record_type and found.reference.record_type is not record_type:
                continue
            if predicate and not (is_assertion and record.predicate is predicate):
                continue
            if global_only and found.project_key is not None:
                continue
            if project and found.project_key not in (None, project.value):
                continue
            if cursor and record.id.value <= cursor:
                continue
            items.append(
                ReviewQueueItemDto(
                    id=record.id.value,
                    type=found.reference.record_type.value,
                    title=None if is_assertion else record.head.content.title,
                    predicate=record.predicate.value if is_assertion else None,
                    subject_id=record.subject_id.value if is_assertion else None,
                    object_id=record.object_id.value if is_assertion else None,
                    project_id=(
                        found.reference.project_id.value if found.reference.project_id else None
                    ),
                    project_key=found.project_key,
                    tags=found.tags,
                    evidence_count=len(record.evidence_ids) if is_assertion else None,
                    consolidation_id=None,
                )
            )
        page = items[:limit]
        more = len(items) > limit
        return ReviewQueuePageDto(items=tuple(page), next_cursor=page[-1].id if more else None)


# ---------------------------------------------------------------------------------------------
# Environment and seeding
# ---------------------------------------------------------------------------------------------


class ReviewEnv:
    """The C2 environment plus C4's fakes and handler factories.

    Every `handler` method takes an optional `uow_factory`, so a test can swap in a racing or
    failing factory without rebuilding anything else.
    """

    def __init__(self, base: KnowledgeEnv) -> None:
        self.base: KnowledgeEnv = base
        self.store: FakeKnowledgeStore = base.store
        self.schema = base.schema
        self.ids = base.ids
        self.clock = base.clock
        self.records: FakeRecordReadRepository = base.read
        self.queue_read = FakeReviewQueueReadRepository(base.store)
        self.state_read = FakeReviewStateReadRepository(base.store)
        self.assertion_read = FakeAssertionReadRepository(base.store)

    def uow(self) -> FakeKnowledgeUnitOfWork:
        """A fresh unit of work over the store."""
        return FakeKnowledgeUnitOfWork(self.store)

    @property
    def space_id(self) -> SpaceId:
        """Id of the default space."""
        return next(s.id for s in self.store.spaces.values() if s.key == DEFAULT_SPACE_KEY)

    def _deps(self, uow_factory: Callable[[], FakeKnowledgeUnitOfWork] | None) -> dict[str, Any]:
        return {
            "uow_factory": uow_factory or self.uow,
            "clock": self.clock,
            "ids": self.ids,
            "schema": self.schema,
        }

    def propose_assertion(self, uow_factory: Any = None) -> ProposeAssertionHandler:
        """ProposeAssertionHandler over the fakes."""
        return ProposeAssertionHandler(**self._deps(uow_factory))

    def accept_knowledge(self, uow_factory: Any = None) -> AcceptKnowledgeHandler:
        """AcceptKnowledgeHandler over the fakes."""
        return AcceptKnowledgeHandler(**self._deps(uow_factory))

    def accept_assertion(self, uow_factory: Any = None) -> AcceptAssertionHandler:
        """AcceptAssertionHandler over the fakes."""
        return AcceptAssertionHandler(**self._deps(uow_factory))

    def retract_knowledge(self, uow_factory: Any = None) -> RetractKnowledgeHandler:
        """RetractKnowledgeHandler over the fakes."""
        return RetractKnowledgeHandler(**self._deps(uow_factory))

    def retract_assertion(self, uow_factory: Any = None) -> RetractAssertionHandler:
        """RetractAssertionHandler over the fakes."""
        return RetractAssertionHandler(**self._deps(uow_factory))

    def apply_supersession(self, uow_factory: Any = None) -> ApplySupersessionHandler:
        """ApplySupersessionHandler over the fakes."""
        return ApplySupersessionHandler(**self._deps(uow_factory))

    def repair(self, uow_factory: Any = None) -> RepairSupersessionEffectsHandler:
        """RepairSupersessionEffectsHandler over the fakes."""
        return RepairSupersessionEffectsHandler(
            **self._deps(uow_factory), state_reader=self.state_read
        )

    def bulk_accept(
        self, uow_factory: Any = None, *, schema: Any = None, queue_reader: Any = None
    ) -> BulkAcceptKnowledgeByTagHandler:
        """BulkAcceptKnowledgeByTagHandler over the fakes."""
        deps = self._deps(uow_factory)
        if schema is not None:
            deps["schema"] = schema
        return BulkAcceptKnowledgeByTagHandler(**deps, queue_reader=queue_reader or self.queue_read)

    @property
    def get_review_states(self) -> GetReviewStatesHandler:
        """GetReviewStatesHandler over the fakes."""
        return GetReviewStatesHandler(
            read_repository=self.state_read, records=self.records, schema=self.schema
        )

    @property
    def list_assertions_by_subjects(self) -> ListAssertionsBySubjectsHandler:
        """ListAssertionsBySubjectsHandler over the fakes."""
        return ListAssertionsBySubjectsHandler(
            read_repository=self.assertion_read, records=self.records, schema=self.schema
        )

    @property
    def list_review_queue(self) -> ListReviewQueueHandler:
        """ListReviewQueueHandler over the fakes."""
        return ListReviewQueueHandler(
            read_repository=self.queue_read, records=self.records, schema=self.schema
        )


async def make_review_env(*, steps: tuple[str, ...] = (CORE_STEP, REVIEW_STEP)) -> ReviewEnv:
    """A fresh initialised environment whose store registers the `core` and `review` steps."""
    return ReviewEnv(await make_env(steps=steps))


async def seed_knowledge(
    env: ReviewEnv,
    key: str,
    *,
    project: str | None = None,
    tags: tuple[str, ...] = (),
    status: RecordStatusEnum = RecordStatusEnum.PROPOSED,
    title: str = "Retry policy",
    space_key: Key = DEFAULT_SPACE_KEY,
) -> RecordId:
    """Capture graph-owned knowledge through C2's handler, then set its stored status."""
    from tests.support.knowledge_commands import COMMIT

    result = await env.base.capture_knowledge.handle(
        CaptureKnowledgeCommand(
            idempotency_key=key,
            space_key=space_key,
            title=title,
            body="Use retries.",
            subtype=Slug(value="decision"),
            actor=AGENT,
            project=ProjectRef(key=Key(value=project)) if project else None,
            tags=tuple(Tag(value=t) for t in tags),
            sources=(COMMIT,),
        )
    )
    record_id = RecordId(value=result.record_id)
    force_status(env, record_id, status)
    return record_id


async def seed_experience(env: ReviewEnv, key: str = "e1") -> RecordId:
    """Capture an experience through C2's handler."""
    from tests.support.knowledge_commands import experience_command

    result = await env.base.capture_experience.handle(experience_command(key))
    return RecordId(value=result.record_id)


def seed_catalog_entry(
    env: ReviewEnv, kind: CatalogEntryKindEnum = CatalogEntryKindEnum.SKILL
) -> RecordId:
    """Put a catalog entry of `kind` straight into the store."""
    entry = CatalogEntry.create(
        id=env.ids.new_record_id(),
        space_id=env.space_id,
        kind=kind,
        name=f"{kind.value}-entry",
        purpose="does a thing",
        location="https://example.invalid/entry",
        actor=AGENT,
        source_ids=(env.ids.new_record_id(),),
        now=env.clock.now(),
    )
    env.store.catalog_entries[entry.id.value] = entry
    return entry.id


def force_status(env: ReviewEnv, record_id: RecordId, status: RecordStatusEnum) -> None:
    """Set the stored status of committed knowledge or an assertion without a decision."""
    record = env.store.knowledge.get(record_id.value) or env.store.assertions[record_id.value]
    record.status = status


async def seed_assertion(
    env: ReviewEnv,
    predicate: AssertionPredicateEnum,
    subject: RecordId,
    object_: RecordId,
    *,
    project: str | None = None,
    evidence: tuple[RecordId, ...] = (),
    status: RecordStatusEnum = RecordStatusEnum.PROPOSED,
    actor: Actor = AGENT,
    now: datetime | None = None,
) -> RecordId:
    """Create an assertion with `Assertion.propose` and store it with `status`, bypassing handlers."""
    project_id: RecordId | None = await RecordReferenceResolver(
        uow_factory=env.uow, clock=env.clock, ids=env.ids
    ).ensure_project(env.space_id, ProjectRef(key=Key(value=project)) if project else None)
    refs = {
        r.record_id: r
        for r in await FakeRecordReferenceLookup(env.store).describe(
            [subject, object_], env.space_id
        )
    }
    assertion = Assertion.propose(
        id=env.ids.new_record_id(),
        space_id=env.space_id,
        predicate=predicate,
        subject_id=subject,
        object_id=object_,
        subject_at_revision=refs[subject].head_revision,
        object_at_revision=refs[object_].head_revision,
        evidence_ids=evidence,
        rationale="because",
        actor=actor,
        applicability=Applicability(project_id=project_id),
        source_ids=(env.ids.new_record_id(),),
        now=now or env.clock.now(),
    )
    assertion.collect_events()
    assertion.status = status
    env.store.assertions[assertion.id.value] = assertion
    return assertion.id
