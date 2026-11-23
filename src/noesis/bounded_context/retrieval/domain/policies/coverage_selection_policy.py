"""Greedy cover of requirement facets by candidates."""

from collections.abc import Sequence

from ..value_objects.coverage_candidate import CoverageCandidate


class CoverageSelectionPolicy:
    """Pick the candidate that adds the most uncovered facets, then relevance, then authority.

    A facet covered only by a mention is still open to a candidate whose name matches it, so a
    resource named for a facet is not dropped because another one merely mentions it. A
    candidate adding nothing new is skipped when a candidate of its kind was already picked. Candidates matching no requested facet are filler: they
    follow by relevance, so a query without facets still selects by relevance.
    """

    def select(
        self, candidates: Sequence[CoverageCandidate], facets: Sequence[str], limit: int
    ) -> tuple[CoverageCandidate, ...]:
        """At most `limit` candidates in pick order; ties break on id for determinism."""
        wanted = frozenset(facets)
        covered: set[str] = set()
        named: set[str] = set()
        kinds: set[str] = set()
        remaining = list(candidates)
        picked: list[CoverageCandidate] = []
        while remaining and len(picked) < limit:
            best: CoverageCandidate | None = None
            best_key: tuple[int, int, int, int, str] | None = None
            for candidate in remaining:
                relevant = candidate.facets & wanted
                new = len(relevant - covered)
                new_named = len((candidate.named_facets & wanted) - named)
                if new == 0 and new_named == 0 and relevant and candidate.kind in kinds:
                    continue
                key = (
                    -new,
                    -new_named,
                    candidate.relevance_rank,
                    candidate.authority_rank,
                    candidate.id,
                )
                if best_key is None or key < best_key:
                    best, best_key = candidate, key
            if best is None:
                break
            picked.append(best)
            covered |= best.facets & wanted
            named |= best.named_facets & wanted
            kinds.add(best.kind)
            remaining.remove(best)
        return tuple(picked)
