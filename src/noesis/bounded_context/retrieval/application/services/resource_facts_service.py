"""What is known about a resource apart from its text: endorsement, refinements, availability.

Every fact here is read from assertions and runtime observations; none is inferred from
installation or sync. Scope rules follow recall: a project-scoped assertion or memory applies
only when its project is the applied project.
"""

from collections.abc import Mapping, Sequence

from noesis.shared_kernel.contracts.knowledge import (
    AssertionSummaryContract,
    CatalogAvailabilityRequestContract,
    RecordReviewStateContract,
)
from noesis.utils import FrozenObject

from ...domain.enums import DecisionBasisEnum, EndorsementEnum
from ...domain.policies.endorsement_policy import EndorsementPolicy
from ...domain.policies.resource_ref_policy import ResourceRefPolicy
from ...domain.value_objects.endorsement_fact import EndorsementFact
from ..dtos.record_search_dtos import RecordSearchHitDto
from ..dtos.search_dtos import RefinementDto, SearchRuntime
from ..ports.briefing import (
    ICatalogAvailability,
    IRecommendationReader,
    IResourceAssertionReader,
    IReviewReader,
)

RECOMMENDS: str = "recommends"
REFINES: str = "refines"
CATALOG_ENTRY: str = "catalog_entry"
LIVE_STATUSES: frozenset[str] = frozenset({"proposed", "accepted"})


class AssertionFacts(FrozenObject):
    """The assertion-derived facts of one catalog entry.

    Attributes:
        endorsement: `user`, `project`, `proposed` or `none` for the applied project.
        recommended_by: Ids of the applicable `recommends` assertions (history, not endorsement).
        refined_by: Memories that refine the entry within the applied scope.
    """

    endorsement: EndorsementEnum = EndorsementEnum.NONE
    recommended_by: tuple[str, ...] = ()
    refined_by: tuple[RefinementDto, ...] = ()


class AvailabilityObservation(FrozenObject):
    """Availability of cataloged entries per runtime.

    Attributes:
        by_entry: Entry id -> runtime -> `available`, `unavailable` or `unknown`.
        unreadable_runtimes: Runtimes whose probe failed.
        checked: False when no check ran, so no entry has an observed availability.
    """

    by_entry: Mapping[str, Mapping[str, str]] = {}
    unreadable_runtimes: tuple[str, ...] = ()
    checked: bool = False


class ResourceFactsService:
    """Reads assertion and availability facts through Retrieval's ports."""

    def __init__(
        self,
        *,
        reviews: IReviewReader | None,
        recommendations: IRecommendationReader | None,
        assertions: IResourceAssertionReader | None,
        availability: ICatalogAvailability | None,
        refs: ResourceRefPolicy | None = None,
        endorsement: EndorsementPolicy | None = None,
    ) -> None:
        self._reviews = reviews
        self._recommendations = recommendations
        self._assertions = assertions
        self._availability = availability
        self._refs = refs or ResourceRefPolicy()
        self._endorsement = endorsement or EndorsementPolicy()

    async def recommended_entry_ids(
        self,
        hits: Sequence[RecordSearchHitDto],
        *,
        project: str | None,
        space_id: str,
        warnings: list[str],
    ) -> tuple[str, ...]:
        """Catalog entries the record hits recommend, in scope and at the judged revision."""
        if self._recommendations is None or not hits:
            return ()
        ids: list[str] = [hit.record_id for hit in hits]
        assertions = await self._recommendations.by_subjects(ids, space_id=space_id)
        states = await self._states(ids, space_id)
        found: dict[str, None] = {}
        for assertion in assertions:
            if (
                assertion.predicate == RECOMMENDS
                and assertion.object_type == CATALOG_ENTRY
                and self._applies(assertion, states, project, warnings)
            ):
                found.setdefault(assertion.object_id)
        return tuple(found)

    async def assertion_facts(
        self,
        entry_ids: Sequence[str],
        *,
        project: str | None,
        space_id: str,
        warnings: list[str],
    ) -> dict[str, AssertionFacts]:
        """Endorsement, recommenders and refinements of each entry for the applied project."""
        if self._assertions is None or not entry_ids:
            return {}
        assertions = await self._assertions.by_objects(
            list(entry_ids), space_id=space_id, predicates=(RECOMMENDS, REFINES)
        )
        subjects: list[str] = list(dict.fromkeys(item.subject_id for item in assertions))
        states = await self._states(subjects, space_id)
        endorsements: dict[str, list[EndorsementFact]] = {}
        recommenders: dict[str, list[str]] = {}
        refinements: dict[str, list[RefinementDto]] = {}
        for assertion in assertions:
            if assertion.object_type != CATALOG_ENTRY or not self._applies(
                assertion, states, project, warnings
            ):
                continue
            entry: str = assertion.object_id
            if assertion.predicate == RECOMMENDS:
                endorsements.setdefault(entry, []).append(
                    EndorsementFact(
                        status=assertion.status,
                        basis=DecisionBasisEnum.USER
                        if assertion.decision_basis == "user"
                        else DecisionBasisEnum.AGENT,
                        project_key=assertion.project_key,
                    )
                )
                recommenders.setdefault(entry, []).append(assertion.assertion_id)
            elif assertion.predicate == REFINES:
                state = states.get(assertion.subject_id)
                ref = self._refs.record_ref(
                    assertion.subject_id,
                    state.head_revision if state else assertion.subject_at_revision,
                )
                if ref is not None:
                    refinements.setdefault(entry, []).append(
                        RefinementDto(ref=ref, authority=state.authority if state else "unreviewed")
                    )
        return {
            entry: AssertionFacts(
                endorsement=self._endorsement.endorsement(
                    endorsements.get(entry, ()), project_key=project
                ),
                recommended_by=tuple(recommenders.get(entry, ())),
                refined_by=tuple(refinements.get(entry, ())),
            )
            for entry in entry_ids
        }

    async def observe(
        self,
        entry_ids: Sequence[str],
        *,
        runtimes: Sequence[SearchRuntime],
        space_id: str,
        warnings: list[str],
    ) -> AvailabilityObservation:
        """Installed state of cataloged entries per runtime, never guessed."""
        if self._availability is None or not entry_ids or not runtimes:
            return AvailabilityObservation()
        result = await self._availability.check(
            CatalogAvailabilityRequestContract(
                space_id=space_id, entry_ids=tuple(entry_ids), runtimes=tuple(runtimes)
            )
        )
        if result.outcome == "not_checked":
            warnings.append(f"availability not verified: {result.reason_code}")
            return AvailabilityObservation()
        by_entry: dict[str, dict[str, str]] = {entry: {} for entry in entry_ids}
        unreadable: list[str] = []
        for block in result.runtimes:
            for item in block.entries:
                by_entry.setdefault(item.entry_id, {})[block.runtime] = item.status
                if item.reason == "probe_failed" and block.runtime not in unreadable:
                    unreadable.append(block.runtime)
        return AvailabilityObservation(
            by_entry=by_entry, unreadable_runtimes=tuple(unreadable), checked=True
        )

    async def _states(
        self, ids: Sequence[str], space_id: str
    ) -> dict[str, RecordReviewStateContract]:
        if self._reviews is None or not ids:
            return {}
        return {
            state.record_id: state
            for state in await self._reviews.get_states(ids, space_id=space_id)
        }

    def _applies(
        self,
        assertion: AssertionSummaryContract,
        states: Mapping[str, RecordReviewStateContract],
        project: str | None,
        warnings: list[str],
    ) -> bool:
        if assertion.status not in LIVE_STATUSES or assertion.project_key not in (None, project):
            return False
        if self._reviews is None:
            return True
        state = states.get(assertion.subject_id)
        if (
            state is None
            or state.authority == "retracted"
            or state.status == "retracted"
            or state.project_key not in (None, project)
        ):
            return False
        if (
            assertion.subject_at_revision is not None
            and assertion.subject_at_revision != state.head_revision
        ):
            warnings.append(f"stale {assertion.predicate} omitted: {assertion.assertion_id}")
            return False
        return True
