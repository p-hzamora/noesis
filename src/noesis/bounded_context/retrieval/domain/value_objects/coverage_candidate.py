"""A resource that may be selected to cover requirement facets."""

from noesis.shared_kernel.domain.value_objects import ValueObject


class CoverageCandidate(ValueObject):
    """One candidate of the greedy cover.

    Attributes:
        id: Stable id of the candidate.
        kind: Resource kind (skill, agent, ...); only compared for equality.
        facets: Facet ids the candidate matches.
        relevance_rank: Position in relevance order; lower is better.
        authority_rank: Authority order (`AuthorityRankingPolicy.order_key`); lower is better.
    """

    id: str
    kind: str
    facets: frozenset[str] = frozenset()
    relevance_rank: int = 0
    authority_rank: int = 0
