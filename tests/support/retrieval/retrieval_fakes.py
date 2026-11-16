"""In-memory fakes of every Retrieval port, and a seeded `RetrievalWorld` around them.

Fakes record the calls tests assert on (requested limits, lock attempts). Records are plain
strings ("K-A"): the kernel contracts type ids as `str`.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import NamedTuple
from uuid import uuid4

from tests.support.knowledge_support import MutableClock
from tests.support.retrieval.fake_semantic_source import FakeSemanticSource

from noesis.bounded_context.retrieval.application.dtos.record_search_dtos import (
    RecordSearchRequestDto,
)
from noesis.bounded_context.retrieval.application.ports.indexing.i_index_cursor_store import (
    IIndexCursorStore,
    ProjectionManifestDto,
)
from noesis.bounded_context.retrieval.application.ports.record_source.i_indexable_record_reader import (
    IIndexableRecordReader,
)
from noesis.bounded_context.retrieval.application.ports.record_source.i_record_change_feed import (
    IRecordChangeFeed,
)
from noesis.bounded_context.retrieval.application.ports.record_source.i_record_neighbour_reader import (
    IRecordNeighbourReader,
)
from noesis.bounded_context.retrieval.application.ports.record_source.i_record_state_reader import (
    IRecordStateReader,
)
from noesis.bounded_context.retrieval.application.ports.record_source.i_record_text_search import (
    IRecordTextSearch,
)
from noesis.bounded_context.retrieval.application.services.projection_lock import lease_lost
from noesis.bounded_context.retrieval.application.services.record_searcher import RecordSearcher
from noesis.bounded_context.retrieval.domain.enums import BuildStateEnum
from noesis.exceptions import RecordNotFoundError
from noesis.shared_kernel.contracts.knowledge import (
    GraphNeighbourContract,
    GraphNeighboursContract,
    IndexableRecordContract,
    RecordChangedContract,
    RecordHitContract,
    RecordStateContract,
)
from noesis.shared_kernel.domain import JsonValue

SPACE: str = "S"
OTHER_SPACE: str = "T"
T1: datetime = datetime(2026, 1, 1, tzinfo=UTC)
T2: datetime = datetime(2026, 1, 2, tzinfo=UTC)
T3: datetime = datetime(2026, 1, 3, tzinfo=UTC)


def make_state(
    record_id: str,
    *,
    record_type: str = "knowledge",
    subtype: str | None = "decision",
    status: str | None = "proposed",
    project_id: str | None = None,
    head_revision: int | None = 1,
    tags: Sequence[str] = (),
    title: str | None = None,
    revised_at: datetime = T1,
) -> RecordStateContract:
    """A state contract; an Experience is `record_type="experience"` with no revision/status/title."""
    experience: bool = record_type == "experience"
    return RecordStateContract(
        record_id=record_id,
        record_type=record_type,  # type: ignore[arg-type]
        subtype=subtype,
        ownership=None if experience else "graph",
        head_revision=None if experience else head_revision,
        status=None if experience else status,
        project_id=project_id,
        tags=tuple(tags),
        title=None if experience else (title or f"title {record_id}"),
        revised_at=revised_at,
    )


def make_indexable(
    state: RecordStateContract,
    *,
    revision: int | None = None,
    body: str | None = None,
    title: str | None = None,
) -> IndexableRecordContract:
    """The indexable contract of `state` at `revision` (default: its head)."""
    wanted: int | None = state.head_revision if revision is None else revision
    return IndexableRecordContract(
        record_id=state.record_id,
        record_type=state.record_type,
        subtype=state.subtype,
        ownership=state.ownership,
        revision=wanted,
        head_revision=state.head_revision,
        status=state.status,
        project_id=state.project_id,
        tags=state.tags,
        title=title if title is not None else state.title,
        body=body if body is not None else f"body of {state.record_id}",
        revised_at=state.revised_at,
    )


def make_request(
    text: str = "ports",
    *,
    space_id: str = SPACE,
    project_key: str | None = None,
    all_projects: bool = False,
    tags: Sequence[str] = (),
    record_types: Sequence[str] = (),
    statuses: Sequence[str] = (),
    limit: int = 10,
    include_stale: bool = False,
    require_semantic: bool = False,
) -> RecordSearchRequestDto:
    """A search request with every field explicit."""
    return RecordSearchRequestDto(
        text=text,
        space_id=space_id,
        project_key=project_key,
        all_projects=all_projects,
        tags=tuple(tags),
        record_types=tuple(record_types),
        statuses=tuple(statuses),
        limit=limit,
        include_stale=include_stale,
        require_semantic=require_semantic,
    )


class TextSearchCall(NamedTuple):
    """One `IRecordTextSearch.search` call."""

    text: str
    space_id: str
    limit: int


class FakeRecordTextSearch(IRecordTextSearch):
    """Answers seeded record ids best first (ranks 1..n), cut to the requested limit.

    `set_hits(..., text=...)` answers only that query text; otherwise the default list answers.
    """

    def __init__(self) -> None:
        self._default: dict[str, tuple[str, ...]] = {}
        self._by_text: dict[tuple[str, str], tuple[str, ...]] = {}
        self.calls: list[TextSearchCall] = []

    def set_hits(
        self, space_id: str, record_ids: Sequence[str], *, text: str | None = None
    ) -> None:
        """Seed the ids (best first) for the space, optionally only for one query text."""
        if text is None:
            self._default[space_id] = tuple(record_ids)
        else:
            self._by_text[(space_id, text)] = tuple(record_ids)

    @property
    def limits(self) -> list[int]:
        """The limit of every call, in order."""
        return [call.limit for call in self.calls]

    async def search(self, text: str, *, space_id: str, limit: int) -> list[RecordHitContract]:
        """Seeded ids as hits with ranks 1..n."""
        self.calls.append(TextSearchCall(text, space_id, limit))
        ids: tuple[str, ...] = self._by_text.get((space_id, text), self._default.get(space_id, ()))
        return [
            RecordHitContract(record_id=record_id, revision=None, rank=rank)
            for rank, record_id in enumerate(ids[:limit], start=1)
        ]


class FakeRecordStateReader(IRecordStateReader):
    """States by (space, id), projects by (space, key)."""

    def __init__(self) -> None:
        self._states: dict[tuple[str, str], RecordStateContract] = {}
        self._projects: dict[tuple[str, str], str] = {}
        self.get_calls: list[tuple[str, ...]] = []

    def add(self, space_id: str, state: RecordStateContract) -> None:
        """Seed one record state."""
        self._states[(space_id, state.record_id)] = state

    def add_project(self, space_id: str, key: str, project_id: str) -> None:
        """Seed a project of the space."""
        self._projects[(space_id, key)] = project_id

    async def get_states(
        self, record_ids: Sequence[str], *, space_id: str
    ) -> list[RecordStateContract]:
        """The states found, in the order asked; unknown ids are omitted."""
        self.get_calls.append(tuple(record_ids))
        return [
            self._states[(space_id, record_id)]
            for record_id in record_ids
            if (space_id, record_id) in self._states
        ]

    async def scan_states(
        self, space_id: str, *, after_id: str | None, limit: int
    ) -> list[RecordStateContract]:
        """The space's states ordered by id, after `after_id`."""
        ordered: list[RecordStateContract] = sorted(
            (state for (space, _), state in self._states.items() if space == space_id),
            key=lambda state: state.record_id,
        )
        return [s for s in ordered if after_id is None or s.record_id > after_id][:limit]

    async def find_project_id(self, project_key: str, *, space_id: str) -> str | None:
        """The seeded project id, else None."""
        return self._projects.get((space_id, project_key))


class FakeRecordNeighbourReader(IRecordNeighbourReader):
    """Returns every seeded (neighbour, seed) pair whose seed was asked for.

    Unordered and not cut to `limit`: ordering and the cap are the searcher's job (Q-013). The
    asked `limit` is recorded.
    """

    def __init__(self) -> None:
        self._items: dict[str, list[GraphNeighbourContract]] = {}
        self.calls: list[tuple[tuple[str, ...], str, int]] = []

    def add(self, space_id: str, record_id: str, *, seed_id: str, shared_sources: int = 1) -> None:
        """Seed that `record_id` shares `shared_sources` Sources with `seed_id`."""
        self._items.setdefault(space_id, []).append(
            GraphNeighbourContract(
                record_id=record_id,
                seed_id=seed_id,
                relation="shared_source",
                distance=1,
                shared_sources=shared_sources,
            )
        )

    async def neighbours(
        self, seed_ids: Sequence[str], *, space_id: str, limit: int
    ) -> GraphNeighboursContract:
        """The seeded pairs of the asked seeds; seeds are never neighbours."""
        self.calls.append((tuple(seed_ids), space_id, limit))
        return GraphNeighboursContract(
            neighbours=tuple(
                item
                for item in self._items.get(space_id, [])
                if item.seed_id in seed_ids and item.record_id not in seed_ids
            )
        )


class FakeIndexableRecordReader(IIndexableRecordReader):
    """Indexable contracts by (space, id, revision)."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str, int | None], IndexableRecordContract] = {}
        self.gets: list[tuple[str, int | None]] = []

    def add(self, space_id: str, contract: IndexableRecordContract) -> None:
        """Seed one revision (or the Experience, revision None)."""
        self._records[(space_id, contract.record_id, contract.revision)] = contract

    async def get(
        self, record_id: str, revision: int | None, *, space_id: str
    ) -> IndexableRecordContract:
        """The seeded contract.

        Raises:
            RecordNotFoundError: Nothing seeded for that record and revision.
        """
        self.gets.append((record_id, revision))
        try:
            return self._records[(space_id, record_id, revision)]
        except KeyError:
            raise RecordNotFoundError(
                f"{record_id} r{revision} not seeded in {space_id}",
                {"record_id": record_id, "revision": revision, "space_id": space_id},
            ) from None


class FakeRecordChangeFeed(IRecordChangeFeed):
    """A per-space change list with consecutive sequences; `drop` makes a gap."""

    def __init__(self) -> None:
        self._changes: dict[str, list[RecordChangedContract]] = {}
        self._head: dict[str, int] = {}

    def add(
        self,
        space_id: str,
        record_id: str,
        *,
        change_kind: str = "created",
        record_type: str = "knowledge",
        revision: int | None = 1,
        status: str | None = "proposed",
        occurred_at: datetime = T1,
    ) -> RecordChangedContract:
        """Append the next change of the space."""
        sequence: int = self._head.get(space_id, 0) + 1
        change = RecordChangedContract(
            event_id=uuid4().hex,
            occurred_at=occurred_at,
            sequence=sequence,
            space_id=space_id,
            record_id=record_id,
            record_type=record_type,  # type: ignore[arg-type]
            change_kind=change_kind,  # type: ignore[arg-type]
            revision=revision,
            status=status,
        )
        self._changes.setdefault(space_id, []).append(change)
        self._head[space_id] = sequence
        return change

    def drop(self, space_id: str, sequence: int) -> None:
        """Remove one change but keep the head: a gap in the feed."""
        self._changes[space_id] = [c for c in self._changes[space_id] if c.sequence != sequence]

    async def changes_after(
        self, sequence: int, *, space_id: str, limit: int
    ) -> list[RecordChangedContract]:
        """Changes with a sequence above `sequence`, ascending, at most `limit`."""
        found = sorted(
            (c for c in self._changes.get(space_id, []) if c.sequence > sequence),
            key=lambda c: c.sequence,
        )
        return found[:limit]

    async def head_sequence(self, space_id: str) -> int:
        """The highest sequence ever appended; 0 when none."""
        return self._head.get(space_id, 0)


class InMemoryIndexCursorStore(IIndexCursorStore):
    """Cursors, manifests and fenced leases with expiry by the injected clock.

    A cursor set without a manifest reads as `complete` with no profile (a pre-manifest
    cursor), as the Neo4j adapter does.
    """

    def __init__(self, clock: MutableClock | None = None) -> None:
        self._clock: MutableClock = clock or MutableClock()
        self._cursors: dict[tuple[str, str], int] = {}
        self._locks: dict[tuple[str, str], tuple[str, datetime]] = {}
        self._manifests: dict[tuple[str, str], ProjectionManifestDto] = {}
        self.acquire_calls: list[tuple[str, str, str]] = []
        self.advance_calls: list[tuple[str, str, int]] = []
        self.release_calls: list[tuple[str, str, str]] = []
        self.renew_calls: list[tuple[str, str, str]] = []
        self.fail_renewals: bool = False

    def set(self, projection: str, space_id: str, sequence: int) -> None:
        """Test setup: initialise or move a cursor without recording a call."""
        self._cursors[(projection, space_id)] = sequence

    def set_manifest(
        self,
        projection: str,
        space_id: str,
        state: BuildStateEnum,
        profile: dict[str, JsonValue] | None = None,
    ) -> None:
        """Test setup: the build manifest of a projection."""
        self._manifests[(projection, space_id)] = ProjectionManifestDto(
            state=state, profile=profile
        )

    def check_fence(self, projection: str, space_id: str, owner: str) -> None:
        """Raise the fenced-write error unless `owner` holds the live lease."""
        if self.lock_holder(projection, space_id) != owner:
            raise lease_lost(projection, space_id)

    def lock_holder(self, projection: str, space_id: str) -> str | None:
        """Owner of a live lock, else None."""
        held = self._locks.get((projection, space_id))
        return held[0] if held and held[1] > self._clock.now() else None

    def hold(self, projection: str, space_id: str, owner: str, ttl_seconds: int = 300) -> None:
        """Test setup: `owner` holds the lock for `ttl_seconds` from now."""
        self._locks[(projection, space_id)] = (
            owner,
            self._clock.now() + timedelta(seconds=ttl_seconds),
        )

    async def get(self, projection: str, space_id: str) -> int | None:
        """The cursor, None when never initialised."""
        return self._cursors.get((projection, space_id))

    async def advance(
        self, projection: str, space_id: str, sequence: int, *, owner: str | None = None
    ) -> None:
        """Set the cursor; fenced when `owner` is given."""
        if owner is not None:
            self.check_fence(projection, space_id, owner)
        self.advance_calls.append((projection, space_id, sequence))
        self._cursors[(projection, space_id)] = sequence

    async def renew(self, projection: str, space_id: str, owner: str, ttl_seconds: int) -> bool:
        """Extend only a live lease of `owner`."""
        self.renew_calls.append((projection, space_id, owner))
        if self.fail_renewals or self.lock_holder(projection, space_id) != owner:
            return False
        self.hold(projection, space_id, owner, ttl_seconds)
        return True

    async def manifest(self, projection: str, space_id: str) -> ProjectionManifestDto | None:
        """The manifest; a bare cursor reads as complete."""
        found: ProjectionManifestDto | None = self._manifests.get((projection, space_id))
        if found is not None:
            return found
        if (projection, space_id) in self._cursors:
            return ProjectionManifestDto(state=BuildStateEnum.COMPLETE)
        return None

    async def begin_rebuild(self, projection: str, space_id: str, *, owner: str) -> None:
        """Mark rebuilding, fenced."""
        self.check_fence(projection, space_id, owner)
        self.set_manifest(projection, space_id, BuildStateEnum.REBUILDING)

    async def complete_rebuild(
        self,
        projection: str,
        space_id: str,
        *,
        owner: str,
        profile: dict[str, JsonValue],
    ) -> None:
        """Publish the profile, fenced."""
        self.check_fence(projection, space_id, owner)
        self.set_manifest(projection, space_id, BuildStateEnum.COMPLETE, profile)

    async def acquire(self, projection: str, space_id: str, owner: str, ttl_seconds: int) -> bool:
        """Take the lock when free, expired, or already this owner's."""
        self.acquire_calls.append((projection, space_id, owner))
        holder: str | None = self.lock_holder(projection, space_id)
        if holder is not None and holder != owner:
            return False
        self.hold(projection, space_id, owner, ttl_seconds)
        return True

    async def release(self, projection: str, space_id: str, owner: str) -> None:
        """Drop the lock when `owner` holds it."""
        self.release_calls.append((projection, space_id, owner))
        if self.lock_holder(projection, space_id) == owner:
            del self._locks[(projection, space_id)]


class RetrievalWorld:
    """Every fake wired together for space `SPACE`, with seeding helpers."""

    def __init__(self, space_id: str = SPACE) -> None:
        self.space_id: str = space_id
        self.clock: MutableClock = MutableClock()
        self.text_search: FakeRecordTextSearch = FakeRecordTextSearch()
        self.states: FakeRecordStateReader = FakeRecordStateReader()
        self.neighbours: FakeRecordNeighbourReader = FakeRecordNeighbourReader()
        self.indexables: FakeIndexableRecordReader = FakeIndexableRecordReader()
        self.feed: FakeRecordChangeFeed = FakeRecordChangeFeed()
        self.cursors: InMemoryIndexCursorStore = InMemoryIndexCursorStore(self.clock)
        self.semantic: FakeSemanticSource = FakeSemanticSource()

    def add_knowledge(
        self,
        record_id: str,
        *,
        space_id: str | None = None,
        status: str = "proposed",
        project_id: str | None = None,
        revision: int = 1,
        tags: Sequence[str] = (),
        title: str | None = None,
        body: str | None = None,
    ) -> RecordStateContract:
        """Seed a Knowledge record (state and head-revision indexable)."""
        space: str = space_id or self.space_id
        state: RecordStateContract = make_state(
            record_id,
            status=status,
            project_id=project_id,
            head_revision=revision,
            tags=tags,
            title=title,
        )
        self.states.add(space, state)
        self.indexables.add(space, make_indexable(state, body=body))
        return state

    def add_experience(
        self,
        record_id: str,
        *,
        space_id: str | None = None,
        project_id: str | None = None,
        body: str | None = None,
    ) -> RecordStateContract:
        """Seed an Experience (no revision, status or title)."""
        space: str = space_id or self.space_id
        state: RecordStateContract = make_state(
            record_id, record_type="experience", subtype="failure", project_id=project_id
        )
        self.states.add(space, state)
        self.indexables.add(space, make_indexable(state, body=body))
        return state

    def match(self, *record_ids: str, space_id: str | None = None, text: str | None = None) -> None:
        """Make Knowledge's text search answer these ids, best first."""
        self.text_search.set_hits(space_id or self.space_id, record_ids, text=text)

    def searcher(
        self,
        *,
        with_semantic: bool = False,
        configured_profiles: dict[str, dict[str, JsonValue]] | None = None,
    ) -> RecordSearcher:
        """A `RecordSearcher` over the fakes; the semantic source is registered on request."""
        return RecordSearcher(
            text_search=self.text_search,
            states=self.states,
            neighbours=self.neighbours,
            indexables=self.indexables,
            candidate_sources=(self.semantic,) if with_semantic else (),
            cursors=self.cursors,
            feed=self.feed,
            configured_profiles=configured_profiles or {},
        )
