"""The search pipeline (D-017): the only implementation of search and similar-records."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from noesis.exceptions import IndexRebuildRequiredError, SemanticIndexUnavailableError
from noesis.shared_kernel.contracts.knowledge import (
    GraphNeighbourContract,
    RecordHitContract,
    RecordStateContract,
)
from noesis.shared_kernel.domain import JsonValue

from ...domain.enums import (
    AuthorityTierEnum,
    CandidateKindEnum,
    ProjectScopeEnum,
    SemanticStateEnum,
)
from ...domain.policies import AuthorityRankingPolicy, RankFusionPolicy
from ...domain.value_objects import RetrievalScope
from ..dtos.record_search_dtos import (
    RecordSearchHitDto,
    RecordSearchRequestDto,
    RecordSearchResultDto,
)
from ..ports.candidates.i_candidate_source import (
    CandidateSourceUnavailableError,
    ICandidateSource,
    RankedCandidatesDto,
)
from ..ports.indexing.i_index_cursor_store import IIndexCursorStore
from ..ports.record_source.i_indexable_record_reader import IIndexableRecordReader
from ..ports.record_source.i_record_change_feed import IRecordChangeFeed
from ..ports.record_source.i_record_neighbour_reader import IRecordNeighbourReader
from ..ports.record_source.i_record_state_reader import IRecordStateReader
from ..ports.record_source.i_record_text_search import IRecordTextSearch

FIRST_FETCH_FACTOR: int = 3
RETRY_FETCH_FACTOR: int = 10
RETRY_FETCH_CAP: int = 200
SEED_COUNT: int = 5
EXPERIENCE_QUERY_CHARACTERS: int = 200
SEARCHABLE_TYPES: frozenset[str] = frozenset({"knowledge", "experience"})
RETRACTED: str = "retracted"


@dataclass(slots=True)
class _Semantic:
    """What one call knows about the semantic source."""

    source: ICandidateSource | None
    state: SemanticStateEnum
    pending_changes: int
    queryable: bool


@dataclass(frozen=True, slots=True)
class _Fused:
    """The outcome of collecting, resolving heads, fusing and expanding."""

    order: list[str]
    states: dict[str, RecordStateContract]
    sources: dict[str, set[CandidateKindEnum]]
    stale_hits: int


@dataclass(slots=True)
class _Lists:
    """Ranked record ids per source, after head resolution."""

    lexical: list[str] = field(default_factory=list)
    semantic: list[str] = field(default_factory=list)
    graph: list[str] = field(default_factory=list)


class RecordSearcher:
    """Finds records of one space by text, shared Sources and (optionally) meaning.

    `search` collects candidates, resolves heads, fuses, expands graph neighbours, filters by
    scope, ranks by authority and retries once when the filters leave too few hits. `similar`
    runs the same collection and expansion for an anchor record. Neither writes.
    """

    def __init__(
        self,
        text_search: IRecordTextSearch,
        states: IRecordStateReader,
        neighbours: IRecordNeighbourReader,
        indexables: IIndexableRecordReader,
        candidate_sources: Sequence[ICandidateSource],
        cursors: IIndexCursorStore,
        feed: IRecordChangeFeed,
        *,
        configured_profiles: Mapping[str, Mapping[str, JsonValue]] | None = None,
        projection_kinds: Sequence[str] = (),
    ) -> None:
        self._text_search: IRecordTextSearch = text_search
        self._states: IRecordStateReader = states
        self._neighbours: IRecordNeighbourReader = neighbours
        self._indexables: IIndexableRecordReader = indexables
        self._semantic_source: ICandidateSource | None = next(
            (source for source in candidate_sources if source.kind is CandidateKindEnum.SEMANTIC),
            None,
        )
        self._cursors: IIndexCursorStore = cursors
        self._feed: IRecordChangeFeed = feed
        self._configured_profiles: Mapping[str, Mapping[str, JsonValue]] = configured_profiles or {}
        self._projection_kinds: tuple[str, ...] = tuple(projection_kinds)
        self._fusion: RankFusionPolicy = RankFusionPolicy()
        self._authority: AuthorityRankingPolicy = AuthorityRankingPolicy()

    async def search(self, request: RecordSearchRequestDto) -> RecordSearchResultDto:
        """Run the pipeline for one request.

        Raises:
            IndexRebuildRequiredError: The semantic source's profile differs from the configured one.
            SemanticIndexUnavailableError: `require_semantic` and the source is absent or
                unavailable.
        """
        semantic: _Semantic = await self._semantic(request.space_id)
        if request.require_semantic and semantic.state in _UNUSABLE:
            raise _semantic_unavailable(semantic.state)
        scope: RetrievalScope = await self._scope(request)
        limit: int = request.limit
        fused: _Fused = await self._collect(
            request.text,
            space_id=request.space_id,
            per_source=FIRST_FETCH_FACTOR * limit,
            graph_limit=limit,
            include_stale=request.include_stale,
            semantic=semantic,
        )
        if request.require_semantic and semantic.state in _UNUSABLE:
            raise _semantic_unavailable(semantic.state)
        hits: list[tuple[str, AuthorityTierEnum]] = self._admitted(fused, request, scope)
        shortfall: bool = False
        if len(hits) < limit:
            fused = await self._collect(
                request.text,
                space_id=request.space_id,
                per_source=min(RETRY_FETCH_FACTOR * limit, RETRY_FETCH_CAP),
                graph_limit=limit,
                include_stale=request.include_stale,
                semantic=semantic,
            )
            hits = self._admitted(fused, request, scope)
            shortfall = len(hits) < limit
        return self._result(
            fused,
            hits[:limit],
            semantic=semantic,
            scope=scope,
            filter_shortfall=shortfall,
        )

    async def similar(self, record_id: str, *, space_id: str, limit: int) -> RecordSearchResultDto:
        """Records related to an anchor: text and graph, in the active space, unfiltered.

        The anchor's title (or the first 200 characters of an Experience's body) is the query and
        the anchor is also a graph seed. The anchor is excluded, `authority` is filled but never
        reorders, and there is no over-fetch.
        """
        semantic: _Semantic = await self._semantic(space_id)
        scope = RetrievalScope(space_id=space_id, all_projects=True)
        anchors: list[RecordStateContract] = await self._states.get_states(
            [record_id], space_id=space_id
        )
        if not anchors or anchors[0].record_type not in SEARCHABLE_TYPES:
            return self._result(
                _Fused(order=[], states={}, sources={}, stale_hits=0),
                [],
                semantic=semantic,
                scope=scope,
                filter_shortfall=False,
            )
        fused: _Fused = await self._collect(
            await self._query_text(anchors[0], space_id=space_id),
            space_id=space_id,
            per_source=FIRST_FETCH_FACTOR * limit,
            graph_limit=limit,
            include_stale=False,
            semantic=semantic,
            anchor=record_id,
        )
        hits: list[tuple[str, AuthorityTierEnum]] = [
            (found, self._authority.tier(fused.states[found].status))
            for found in fused.order
            if fused.states[found].record_type in SEARCHABLE_TYPES
        ]
        return self._result(
            fused, hits[:limit], semantic=semantic, scope=scope, filter_shortfall=False
        )

    async def _query_text(self, anchor: RecordStateContract, *, space_id: str) -> str:
        if anchor.record_type == "experience":
            indexable = await self._indexables.get(anchor.record_id, None, space_id=space_id)
            return indexable.body[:EXPERIENCE_QUERY_CHARACTERS]
        return anchor.title or ""

    async def _semantic(self, space_id: str) -> _Semantic:
        """Step 0: profile check, then the semantic state and the lag."""
        semantic: _Semantic = await self._semantic_state(space_id)
        semantic.pending_changes = max(semantic.pending_changes, await self._pending(space_id))
        return semantic

    async def _pending(self, space_id: str) -> int:
        """The largest `head_sequence - cursor` over every registered projection."""
        kinds: set[str] = set(self._projection_kinds)
        if self._semantic_source is not None:
            kinds.add(self._semantic_source.kind.value)
        if not kinds:
            return 0
        head: int = await self._feed.head_sequence(space_id)
        lags: list[int] = [0]
        for kind in sorted(kinds):
            cursor: int | None = await self._cursors.get(kind, space_id)
            if cursor is not None:
                lags.append(head - cursor)
        return max(lags)

    async def _semantic_state(self, space_id: str) -> _Semantic:
        source: ICandidateSource | None = self._semantic_source
        if source is None:
            return _Semantic(
                source=None, state=SemanticStateEnum.ABSENT, pending_changes=0, queryable=False
            )
        kind: str = source.kind.value
        configured: Mapping[str, JsonValue] | None = self._configured_profiles.get(kind)
        if configured is not None and dict(configured) != source.profile():
            raise IndexRebuildRequiredError(
                f"The {kind} index was built with a different profile than the configured one.",
                {"projection": kind},
                next_steps=["Run `noesis index rebuild --yes`."],
            )
        cursor: int | None = await self._cursors.get(kind, space_id)
        if cursor is None:
            return _Semantic(
                source=source,
                state=SemanticStateEnum.UNAVAILABLE,
                pending_changes=0,
                queryable=False,
            )
        head: int = await self._feed.head_sequence(space_id)
        lagging: bool = cursor < head
        return _Semantic(
            source=source,
            state=SemanticStateEnum.LAGGING if lagging else SemanticStateEnum.READY,
            pending_changes=head - cursor if lagging else 0,
            queryable=True,
        )

    async def _scope(self, request: RecordSearchRequestDto) -> RetrievalScope:
        """Step 1: all projects, the resolved project, or space-wide records only."""
        project_id: str | None = None
        if not request.all_projects and request.project_key is not None:
            project_id = await self._states.find_project_id(
                request.project_key, space_id=request.space_id
            )
        return RetrievalScope(
            space_id=request.space_id,
            project_id=project_id,
            all_projects=request.all_projects,
            tags=request.tags,
        )

    async def _collect(
        self,
        text: str,
        *,
        space_id: str,
        per_source: int,
        graph_limit: int,
        include_stale: bool,
        semantic: _Semantic,
        anchor: str | None = None,
    ) -> _Fused:
        """Steps 2-5: collect, resolve heads, fuse, expand the top seeds and fuse again."""
        lexical_hits: list[RecordHitContract] = await self._text_search.search(
            text, space_id=space_id, limit=per_source
        )
        semantic_keys: list[tuple[str, int | None]] = []
        if semantic.queryable and semantic.source is not None:
            try:
                found: RankedCandidatesDto = await semantic.source.find(
                    text, space_id=space_id, limit=per_source
                )
            except CandidateSourceUnavailableError:
                semantic.state = SemanticStateEnum.UNAVAILABLE
                semantic.queryable = False
            else:
                semantic_keys = [(key.record_id, key.revision) for key in found.hits]
        candidates: list[tuple[str, int | None]] = [
            *((hit.record_id, hit.revision) for hit in sorted(lexical_hits, key=_by_rank)),
            *semantic_keys,
        ]
        wanted: list[str] = list(dict.fromkeys(record_id for record_id, _ in candidates))
        states: dict[str, RecordStateContract] = await self._state_map(wanted, space_id)
        stale: int = 0
        lists = _Lists()
        for target, keys in (
            (lists.lexical, candidates[: len(lexical_hits)]),
            (lists.semantic, candidates[len(lexical_hits) :]),
        ):
            for record_id, revision in keys:
                state: RecordStateContract | None = states.get(record_id)
                if state is None or record_id == anchor or record_id in target:
                    continue
                if revision is not None and revision != state.head_revision:
                    stale += 1
                    if not include_stale:
                        continue
                target.append(record_id)
        first: list[str] = self._fusion.fuse(_non_empty(lists.lexical, lists.semantic))
        seeds: list[str] = list(dict.fromkeys([*([anchor] if anchor else []), *first[:SEED_COUNT]]))
        if seeds:
            lists.graph = await self._graph_candidates(
                seeds, space_id=space_id, limit=graph_limit, states=states, exclude=anchor
            )
        order: list[str] = self._fusion.fuse(_non_empty(lists.lexical, lists.graph, lists.semantic))
        sources: dict[str, set[CandidateKindEnum]] = {}
        for kind, ranked in (
            (CandidateKindEnum.LEXICAL, lists.lexical),
            (CandidateKindEnum.GRAPH, lists.graph),
            (CandidateKindEnum.SEMANTIC, lists.semantic),
        ):
            for record_id in ranked:
                sources.setdefault(record_id, set()).add(kind)
        return _Fused(order=order, states=states, sources=sources, stale_hits=stale)

    async def _graph_candidates(
        self,
        seeds: list[str],
        *,
        space_id: str,
        limit: int,
        states: dict[str, RecordStateContract],
        exclude: str | None,
    ) -> list[str]:
        """Q-013: neighbours by Sources shared (summed over seeds), best seed rank, record id."""
        pairs: list[GraphNeighbourContract] = await self._neighbours.neighbours(
            seeds, space_id=space_id, limit=limit
        )
        pairs = [
            pair for pair in pairs if pair.record_id not in seeds and pair.record_id != exclude
        ]
        states.update(
            await self._state_map(
                [
                    record_id
                    for record_id in dict.fromkeys(p.record_id for p in pairs)
                    if record_id not in states
                ],
                space_id,
            )
        )
        shared: dict[str, int] = {}
        best_seed: dict[str, int] = {}
        for pair in pairs:
            if pair.record_id not in states or pair.seed_id not in seeds:
                continue
            shared[pair.record_id] = shared.get(pair.record_id, 0) + pair.shared_sources
            seed_rank: int = seeds.index(pair.seed_id)
            best_seed[pair.record_id] = min(best_seed.get(pair.record_id, seed_rank), seed_rank)
        ordered: list[str] = sorted(
            shared, key=lambda record_id: (-shared[record_id], best_seed[record_id], record_id)
        )
        return ordered[:limit]

    async def _state_map(
        self, record_ids: list[str], space_id: str
    ) -> dict[str, RecordStateContract]:
        if not record_ids:
            return {}
        found: list[RecordStateContract] = await self._states.get_states(
            record_ids, space_id=space_id
        )
        return {state.record_id: state for state in found}

    def _admitted(
        self, fused: _Fused, request: RecordSearchRequestDto, scope: RetrievalScope
    ) -> list[tuple[str, AuthorityTierEnum]]:
        """Steps 6-7: scope and request filters, retracted handling, then tier and fused rank."""
        types: frozenset[str] = frozenset(request.record_types) or SEARCHABLE_TYPES
        asks_retracted: bool = RETRACTED in request.statuses
        tiered: list[tuple[str, AuthorityTierEnum]] = []
        for record_id in fused.order:
            state: RecordStateContract = fused.states[record_id]
            if state.record_type not in SEARCHABLE_TYPES or state.record_type not in types:
                continue
            if request.statuses and state.status not in request.statuses:
                continue
            if not scope.admits(project_id=state.project_id, tags=state.tags):
                continue
            tier: AuthorityTierEnum = self._authority.tier(state.status)
            if tier is AuthorityTierEnum.RETRACTED and not asks_retracted:
                continue
            tiered.append((record_id, tier))
        return sorted(tiered, key=lambda item: self._authority.order_key(item[1]))  # stable

    def _result(
        self,
        fused: _Fused,
        hits: list[tuple[str, AuthorityTierEnum]],
        *,
        semantic: _Semantic,
        scope: RetrievalScope,
        filter_shortfall: bool,
    ) -> RecordSearchResultDto:
        order: tuple[CandidateKindEnum, ...] = tuple(CandidateKindEnum)
        dtos: list[RecordSearchHitDto] = []
        for rank, (record_id, tier) in enumerate(hits, start=1):
            state: RecordStateContract = fused.states[record_id]
            kinds: set[CandidateKindEnum] = fused.sources.get(record_id, set())
            dtos.append(
                RecordSearchHitDto(
                    record_id=record_id,
                    record_type=state.record_type,
                    subtype=state.subtype,
                    title=state.title,
                    revision=state.head_revision,
                    status=state.status,
                    authority=tier,
                    project_id=state.project_id,
                    sources=tuple(kind for kind in order if kind in kinds),
                    revised_at=state.revised_at,
                    rank=rank,
                )
            )
        return RecordSearchResultDto(
            hits=tuple(dtos),
            pending_changes=semantic.pending_changes,
            stale_hits=fused.stale_hits,
            semantic_state=semantic.state,
            filter_shortfall=filter_shortfall,
            project_scope=scope.kind,
            project_id=scope.project_id if scope.kind is ProjectScopeEnum.PROJECT else None,
        )


_UNUSABLE: frozenset[SemanticStateEnum] = frozenset(
    {SemanticStateEnum.ABSENT, SemanticStateEnum.UNAVAILABLE}
)


def _semantic_unavailable(state: SemanticStateEnum) -> SemanticIndexUnavailableError:
    return SemanticIndexUnavailableError(
        f"Semantic search was required but the semantic index is {state.value}.",
        {"semantic_state": state.value},
        next_steps=["Run `noesis index status`."],
    )


def _by_rank(hit: RecordHitContract) -> int:
    return hit.rank


def _non_empty(*rankings: list[str]) -> list[list[str]]:
    return [ranking for ranking in rankings if ranking]
