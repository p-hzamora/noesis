"""Unified search: records, catalog resources, requirement coverage, load order and next actions.

Reads only. Record search is `RecordSearcher` unchanged; the briefing is `TaskBriefingService`
unchanged. Nothing here knows any subject: facets come from the caller's needs or the query.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from noesis.shared_kernel.application.handlers import IHandler
from noesis.shared_kernel.application.ports.clock import IClock
from noesis.shared_kernel.contracts.knowledge import (
    CatalogResourceHitContract,
    CatalogResourceLookupContract,
    CatalogResourceQueryContract,
)

from ....domain.enums import (
    AuthorityTierEnum,
    BriefingModeEnum,
    EndorsementEnum,
    NextActionEnum,
    SemanticStateEnum,
    SupportKindEnum,
)
from ....domain.policies.coverage_selection_policy import CoverageSelectionPolicy
from ....domain.policies.coverage_status_policy import CoverageStatusPolicy
from ....domain.policies.facet_match_policy import FacetMatchPolicy
from ....domain.policies.load_order_policy import MAX_DEPTH, LoadOrderPolicy
from ....domain.policies.rank_fusion_policy import RankFusionPolicy
from ....domain.policies.requirement_extraction_policy import RequirementExtractionPolicy
from ....domain.policies.resource_ref_policy import ResourceRefPolicy
from ....domain.value_objects.coverage_candidate import CoverageCandidate
from ....domain.value_objects.facet_support import FacetSupport
from ....domain.value_objects.load_order import LoadOrder
from ....domain.value_objects.requirement_facet import RequirementFacet
from ...dtos.briefing_dtos import RecallRequestDto, RecallResultDto
from ...dtos.record_search_dtos import RecordSearchResultDto
from ...dtos.search_dtos import (
    CatalogIndexDto,
    NextActionDto,
    RequirementDto,
    ResourceDiscoveryDto,
    ResourceWhyDto,
    SearchResourceDto,
    UnifiedSearchRequestDto,
    UnifiedSearchResultDto,
)
from ...ports.candidates.i_candidate_source import (
    CandidateSourceUnavailableError,
    ICandidateSource,
)
from ...ports.catalog import IResourceCatalogReader
from ...services.record_searcher import RecordSearcher
from ...services.resource_facts_service import (
    AssertionFacts,
    AvailabilityObservation,
    ResourceFactsService,
)
from ...services.task_briefing_service import NO_PROJECT_WARNING, TaskBriefingService

CANDIDATE_POOL: int = 40
"""Resources read from the catalog before selection, so coverage has alternatives to choose from."""
MAX_RECORD_ACTIONS: int = 3
"""Records offered under `next_actions`; the rest stay available under `hits`."""
CATALOG_TEXT: str = "catalog_text"
CATALOG_SEMANTIC: str = "catalog_semantic"
RECOMMENDS_CHANNEL: str = "recommends"
PREREQUISITE_CHANNEL: str = "prerequisite"
UNSYNCED_WARNING: str = (
    "{count} installed resource(s) are not in the catalog yet; run `noesis catalog sync`"
)
SEMANTIC_WARNING: str = (
    "semantic search is {state}; results come from the catalog and lexical search only"
)
_ENDORSEMENT_RANK: tuple[EndorsementEnum, ...] = (
    EndorsementEnum.USER,
    EndorsementEnum.PROJECT,
    EndorsementEnum.PROPOSED,
    EndorsementEnum.NONE,
)


@dataclass(slots=True)
class _Entry:
    """A resource under consideration."""

    ref: str
    hit: CatalogResourceHitContract
    channels: list[str] = field(default_factory=list)
    matched: frozenset[str] = frozenset()
    named: frozenset[str] = frozenset()


class UnifiedSearchHandler(IHandler[UnifiedSearchRequestDto, UnifiedSearchResultDto]):
    """Answer a task's request for what to consult.

    Args:
        searcher: The record pipeline.
        resources: The catalog door; None when the capability is not wired.
        facts: Assertion and availability facts.
        briefing: The recall pipeline; None when not wired.
        clock: Stamps the discovery observation.
        catalog_semantic: Finds catalog entries by meaning; None when semantic search is not
            registered. Asked only when the record search found the semantic index usable.
    """

    def __init__(
        self,
        searcher: RecordSearcher,
        *,
        resources: IResourceCatalogReader | None,
        facts: ResourceFactsService,
        briefing: TaskBriefingService | None,
        clock: IClock,
        catalog_semantic: ICandidateSource | None = None,
    ) -> None:
        self._searcher = searcher
        self._resources = resources
        self._facts = facts
        self._briefing = briefing
        self._clock = clock
        self._catalog_semantic = catalog_semantic
        self._fusion = RankFusionPolicy()
        self._extraction = RequirementExtractionPolicy()
        self._matcher = FacetMatchPolicy()
        self._selection = CoverageSelectionPolicy()
        self._load_order = LoadOrderPolicy()
        self._status = CoverageStatusPolicy()
        self._refs = ResourceRefPolicy()

    async def handle(self, action: UnifiedSearchRequestDto) -> UnifiedSearchResultDto:
        """Search.

        Raises:
            IndexRebuildRequiredError: The semantic profile changed.
            SemanticIndexUnavailableError: Semantic search was required and is not usable.
            StoreNotInitialisedError: The catalog schema step is not applied.
        """
        records = await self._searcher.search(action.records)
        briefing: RecallResultDto | None = None
        warnings: list[str] = []
        if action.briefing is not BriefingModeEnum.NONE:
            briefing = await self._brief(action)
            warnings.extend(
                item
                for item in briefing.warnings
                if item not in records.warnings and item != NO_PROJECT_WARNING
            )
        if not action.include_resources:
            return UnifiedSearchResultDto(
                records=records,
                resources_included=False,
                briefing=briefing,
                warnings=tuple(warnings),
            )
        if records.semantic_state in {SemanticStateEnum.ABSENT, SemanticStateEnum.UNAVAILABLE}:
            warnings.append(SEMANTIC_WARNING.format(state=records.semantic_state.value))
        return await self._with_resources(action, records, briefing, warnings)

    async def _brief(self, action: UnifiedSearchRequestDto) -> RecallResultDto:
        if self._briefing is None:
            raise RuntimeError("Briefing was not wired")
        return await self._briefing.brief(
            RecallRequestDto(
                search=action.records,
                runtimes=action.runtimes,
                no_synthesis=action.briefing is BriefingModeEnum.DIGEST,
            ),
            max_evidence_chars=action.budget_chars,
        )

    async def _with_resources(
        self,
        action: UnifiedSearchRequestDto,
        records: RecordSearchResultDto,
        briefing: RecallResultDto | None,
        warnings: list[str],
    ) -> UnifiedSearchResultDto:
        space = action.records.space_id
        project = action.records.project_key if records.project_id is not None else None
        facets = self._extraction.extract(action.records.text, action.needs)
        facet_ids = tuple(facet.id for facet in facets)
        entries: list[_Entry] = []
        catalog: CatalogIndexDto | None = None
        observation = AvailabilityObservation()
        facts: dict[str, AssertionFacts] = {}
        if action.resource_limit > 0 and self._resources is not None:
            candidates = await self._candidates(action, records, facet_ids, project, warnings)
            candidates = await self._with_semantic(candidates, action, records, facet_ids, warnings)
            facts = await self._facts.assertion_facts(
                _entry_ids(candidates.values()), project=project, space_id=space, warnings=warnings
            )
            roots = self._select(candidates, facts, facet_ids, action.resource_limit)
            load = await self._expand(roots, candidates, action, warnings)
            entries = [candidates[ref] for ref in load.order]
            for entry in entries:
                if entry.ref in load.added and PREREQUISITE_CHANNEL not in entry.channels:
                    entry.channels.append(PREREQUISITE_CHANNEL)
                entry.matched = self._matched(facet_ids, entry.hit)
            facts |= await self._facts.assertion_facts(
                [item for item in _entry_ids(entries) if item not in facts],
                project=project,
                space_id=space,
                warnings=warnings,
            )
            observation = await self._facts.observe(
                _entry_ids(entries), runtimes=action.runtimes, space_id=space, warnings=warnings
            )
            warnings.extend(
                f"{runtime} could not be read; availability there is unknown"
                for runtime in observation.unreadable_runtimes
            )
            unsynced = sum(1 for entry in entries if not entry.hit.cataloged)
            if unsynced:
                warnings.append(UNSYNCED_WARNING.format(count=unsynced))
            catalog = CatalogIndexDto(synced=unsynced == 0, unsynced_installed=unsynced)
        resources = self._resource_dtos(entries, facts, observation, action)
        requirements = self._requirements(
            facets,
            entries,
            {resource.ref: resource.available for resource in resources},
            records,
            unreadable=bool(observation.unreadable_runtimes),
        )
        return UnifiedSearchResultDto(
            records=records,
            requirements=requirements,
            resources=resources,
            next_actions=self._next_actions(resources, records),
            catalog=catalog,
            briefing=briefing,
            warnings=tuple(dict.fromkeys(warnings)),
        )

    async def _candidates(
        self,
        action: UnifiedSearchRequestDto,
        records: RecordSearchResultDto,
        facet_ids: tuple[str, ...],
        project: str | None,
        warnings: list[str],
    ) -> dict[str, _Entry]:
        """Text hits of the catalog first, then the entries the record hits recommend."""
        if self._resources is None:
            raise RuntimeError("Resource catalog was not wired")
        space = action.records.space_id
        found = await self._resources.search(
            CatalogResourceQueryContract(
                space_id=space,
                text=action.records.text,
                terms=facet_ids,
                limit=CANDIDATE_POOL,
                runtimes=action.runtimes,
                include_unsynced=True,
            )
        )
        candidates: dict[str, _Entry] = {}
        skipped = 0
        for hit in found:
            ref = self._refs.resource_ref(hit.kind, hit.name)
            if ref is None:
                skipped += 1
            else:
                candidates.setdefault(ref, _Entry(ref=ref, hit=hit, channels=[CATALOG_TEXT]))
        recommended = await self._facts.recommended_entry_ids(
            records.hits, project=project, space_id=space, warnings=warnings
        )
        have = {entry.hit.catalog_id for entry in candidates.values()}
        missing = tuple(item for item in recommended if item not in have)
        if missing:
            for hit in await self._resources.get_by_refs(
                CatalogResourceLookupContract(
                    space_id=space,
                    entry_ids=missing,
                    runtimes=action.runtimes,
                    include_unsynced=True,
                )
            ):
                ref = self._refs.resource_ref(hit.kind, hit.name)
                if ref is None:
                    skipped += 1
                else:
                    candidates.setdefault(ref, _Entry(ref=ref, hit=hit))
        for entry in candidates.values():
            if entry.hit.catalog_id in recommended:
                entry.channels.append(RECOMMENDS_CHANNEL)
            entry.matched = self._matched(facet_ids, entry.hit)
            entry.named = self._matcher.matched(facet_ids, entry.hit.name)
        if skipped:
            warnings.append(f"{skipped} resource(s) skipped: the name is not a valid reference")
        return candidates

    async def _with_semantic(
        self,
        candidates: dict[str, _Entry],
        action: UnifiedSearchRequestDto,
        records: RecordSearchResultDto,
        facet_ids: tuple[str, ...],
        warnings: list[str],
    ) -> dict[str, _Entry]:
        """Add the catalog entries found by meaning and rank both lists by reciprocal fusion.

        Does nothing, and leaves the lexical order as it is, unless the record search found the
        semantic index usable. Entries are deduplicated by ref.
        """
        usable = {SemanticStateEnum.READY, SemanticStateEnum.LAGGING}
        if self._catalog_semantic is None or self._resources is None:
            return candidates
        if records.semantic_state not in usable:
            return candidates
        space = action.records.space_id
        try:
            found = await self._catalog_semantic.find(
                action.records.text, space_id=space, limit=action.resource_limit
            )
        except CandidateSourceUnavailableError:
            warnings.append(SEMANTIC_WARNING.format(state=SemanticStateEnum.UNAVAILABLE.value))
            return candidates
        ids = tuple(key.record_id for key in found.hits)
        if not ids:
            return candidates
        have = {entry.hit.catalog_id: ref for ref, entry in candidates.items()}
        missing = tuple(item for item in ids if item not in have)
        by_id = {
            hit.catalog_id: hit
            for hit in await self._resources.get_by_refs(
                CatalogResourceLookupContract(
                    space_id=space,
                    entry_ids=missing,
                    runtimes=action.runtimes,
                    include_unsynced=True,
                )
            )
            if missing
        }
        semantic_refs: list[str] = []
        for item in ids:
            ref = have.get(item)
            hit = by_id.get(item)
            if ref is None and hit is not None:
                ref = self._refs.resource_ref(hit.kind, hit.name)
                if ref is not None and ref not in candidates:
                    candidates[ref] = _Entry(
                        ref=ref,
                        hit=hit,
                        matched=self._matched(facet_ids, hit),
                        named=self._matcher.matched(facet_ids, hit.name),
                    )
            if ref is not None and ref in candidates:
                semantic_refs.append(ref)
                candidates[ref].channels.append(CATALOG_SEMANTIC)
        order = self._fusion.fuse([list(candidates), semantic_refs])
        return {ref: candidates[ref] for ref in order}

    def _matched(
        self, facet_ids: tuple[str, ...], hit: CatalogResourceHitContract
    ) -> frozenset[str]:
        return self._matcher.matched(facet_ids, hit.name, hit.purpose, *hit.capabilities)

    def _select(
        self,
        candidates: dict[str, _Entry],
        facts: dict[str, AssertionFacts],
        facet_ids: tuple[str, ...],
        limit: int,
    ) -> list[str]:
        """Refs picked for coverage; an endorsed resource wins a tie on relevance."""
        ranked = [
            CoverageCandidate(
                id=entry.ref,
                kind=entry.hit.kind,
                facets=entry.matched,
                named_facets=entry.named,
                relevance_rank=index,
                authority_rank=_ENDORSEMENT_RANK.index(
                    facts[entry.hit.catalog_id].endorsement
                    if entry.hit.catalog_id in facts
                    else EndorsementEnum.NONE
                ),
            )
            for index, entry in enumerate(candidates.values())
        ]
        return [item.id for item in self._selection.select(ranked, facet_ids, limit)]

    async def _expand(
        self,
        roots: list[str],
        known: dict[str, _Entry],
        action: UnifiedSearchRequestDto,
        warnings: list[str],
    ) -> LoadOrder:
        """Fetch declared prerequisites level by level, then order them before their dependants.

        `known` gains each prerequisite that the catalog or a runtime can answer; one that
        nothing answers is reported and left out, never invented.
        """
        if self._resources is None:
            raise RuntimeError("Resource catalog was not wired")
        graph: dict[str, list[str]] = {}
        unresolved: set[str] = set()
        frontier: list[str] = list(roots)
        for _ in range(MAX_DEPTH + 1):
            pending: dict[str, None] = {}
            for ref in frontier:
                children: list[str] = []
                for declared in known[ref].hit.prerequisites:
                    child = self._refs.prerequisite_ref(declared)
                    if child is None:
                        warnings.append(
                            f"a prerequisite of {ref} was skipped: not a valid reference"
                        )
                        continue
                    children.append(child)
                    if child not in known and child not in unresolved:
                        pending.setdefault(child)
                graph[ref] = children
            if not pending:
                break
            for hit in await self._resources.get_by_refs(
                CatalogResourceLookupContract(
                    space_id=action.records.space_id,
                    refs=tuple(self._refs.lookup_key(child) for child in pending),
                    runtimes=action.runtimes,
                    include_unsynced=True,
                )
            ):
                found = self._refs.resource_ref(hit.kind, hit.name)
                if found is not None and found in pending and found not in known:
                    known[found] = _Entry(ref=found, hit=hit)
            unresolved |= {child for child in pending if child not in known}
            warnings.extend(
                f"prerequisite not found: {child}" for child in pending if child not in known
            )
            frontier = [child for child in pending if child in known]
        resolvable = {
            ref: [child for child in children if child in known] for ref, children in graph.items()
        }
        load = self._load_order.order(roots, resolvable)
        warnings.extend(load.warnings)
        return load

    def _resource_dtos(
        self,
        entries: list[_Entry],
        facts: dict[str, AssertionFacts],
        observation: AvailabilityObservation,
        action: UnifiedSearchRequestDto,
    ) -> tuple[SearchResourceDto, ...]:
        observed = self._clock.now() if action.runtimes else None
        resources: list[SearchResourceDto] = []
        for order, entry in enumerate(entries, start=1):
            hit = entry.hit
            load_action = self._refs.action_for(hit.kind)
            if load_action is None:
                continue
            fact = facts.get(hit.catalog_id or "", AssertionFacts())
            resources.append(
                SearchResourceDto(
                    ref=entry.ref,
                    catalog_id=hit.catalog_id,
                    kind=hit.kind,
                    name=hit.name,
                    revision=hit.revision,
                    manifest_digest=hit.manifest_digest,
                    cataloged=hit.cataloged,
                    origin=hit.origin,
                    purpose=hit.purpose,
                    why=ResourceWhyDto(
                        matched=tuple(sorted(entry.matched)), channels=tuple(entry.channels)
                    ),
                    requires=tuple(
                        ref
                        for ref in (self._refs.prerequisite_ref(item) for item in hit.prerequisites)
                        if ref is not None
                    ),
                    discovered=ResourceDiscoveryDto(
                        runtimes=hit.discovered_runtimes, observed_at=observed
                    ),
                    available=_available(entry, observation, action),
                    endorsement=fact.endorsement.value,
                    recommended_by=fact.recommended_by,
                    refined_by=fact.refined_by,
                    load_action=load_action,
                    load_order=order,
                )
            )
        return tuple(resources)

    def _requirements(
        self,
        facets: tuple[RequirementFacet, ...],
        entries: list[_Entry],
        available: dict[str, dict[str, str] | None],
        records: RecordSearchResultDto,
        *,
        unreadable: bool,
    ) -> tuple[RequirementDto, ...]:
        record_matches = {
            hit.record_id: self._matcher.matched((f.id for f in facets), hit.title)
            for hit in records.hits
        }
        requirements: list[RequirementDto] = []
        for facet in facets:
            support: list[FacetSupport] = []
            backing: list[str] = []
            for entry in entries:
                if facet.id in entry.matched:
                    support.append(
                        FacetSupport(
                            kind=SupportKindEnum.RESOURCE, available=_usable(available[entry.ref])
                        )
                    )
                    backing.append(entry.ref)
            for hit in records.hits:
                if facet.id not in record_matches[hit.record_id]:
                    continue
                support.append(FacetSupport(kind=SupportKindEnum.RECORD, authority=hit.authority))
                ref = self._refs.record_ref(hit.record_id, hit.revision)
                if ref is not None and hit.authority in _COUNTED_AUTHORITIES:
                    backing.append(ref)
            requirements.append(
                RequirementDto(
                    id=facet.id,
                    source=facet.source.value,
                    coverage=self._status.status(support, unreadable=unreadable).value,
                    supported_by=tuple(backing),
                )
            )
        return tuple(requirements)

    def _next_actions(
        self, resources: tuple[SearchResourceDto, ...], records: RecordSearchResultDto
    ) -> tuple[NextActionDto, ...]:
        steps: list[tuple[NextActionEnum, str]] = [
            (resource.load_action, resource.ref) for resource in resources
        ]
        readable = (
            self._refs.record_ref(hit.record_id, hit.revision)
            for hit in records.hits
            if hit.authority in _COUNTED_AUTHORITIES
        )
        steps += [(NextActionEnum.READ_RECORD, ref) for ref in readable if ref is not None][
            :MAX_RECORD_ACTIONS
        ]
        return tuple(
            NextActionDto(order=order, action=action, ref=ref)
            for order, (action, ref) in enumerate(steps, start=1)
        )


_COUNTED_AUTHORITIES: frozenset[AuthorityTierEnum] = frozenset(
    {AuthorityTierEnum.AUTHORITATIVE, AuthorityTierEnum.EXPERIENCE, AuthorityTierEnum.PROPOSED}
)


def _entry_ids(entries: Iterable[_Entry]) -> list[str]:
    return [entry.hit.catalog_id for entry in entries if entry.hit.catalog_id]


def _available(
    entry: _Entry, observation: AvailabilityObservation, action: UnifiedSearchRequestDto
) -> dict[str, str] | None:
    """Per requested runtime; null when it was not checked."""
    if not action.runtimes:
        return None
    hit = entry.hit
    if hit.catalog_id is None:
        return {
            runtime: "available" if runtime in hit.discovered_runtimes else "unavailable"
            for runtime in action.runtimes
        }
    if not observation.checked:
        return None
    seen = observation.by_entry.get(hit.catalog_id, {})
    return {runtime: seen.get(runtime, "unknown") for runtime in action.runtimes}


def _usable(available: dict[str, str] | None) -> bool | None:
    """True when some runtime has it, False when every runtime lacks it, else not known."""
    if not available:
        return None
    states = set(available.values())
    if "available" in states:
        return True
    return False if states == {"unavailable"} else None
