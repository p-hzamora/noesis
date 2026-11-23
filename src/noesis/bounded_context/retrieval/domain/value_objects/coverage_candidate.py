"""A resource that may be selected to cover requirement facets."""

from noesis.shared_kernel.domain.value_objects import ValueObject


class CoverageCandidate(ValueObject):
    """One candidate of the greedy cover.

    Attributes:
        id: Stable id of the candidate.
        kind: Resource kind (skill, agent, ...); only compared for equality.
        facets: Facet ids the candidate matches.
        named_facets: The subset of `facets` its name matches: a stronger cover than a mention.
        relevance_rank: Position in relevance order; lower is better.
        authority_rank: Authority order (`AuthorityRankingPolicy.order_key`); lower is better.
    """

    id: str
    kind: str
    facets: frozenset[str] = frozenset()
    named_facets: frozenset[str] = frozenset()
    relevance_rank: int = 0
    authority_rank: int = 0
