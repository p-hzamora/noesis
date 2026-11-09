"""Orders search hits by how useful they are to recall for a task."""

from collections.abc import Iterable
from datetime import date

from noesis.bounded_context.notes.domain.value_objects import RecallCandidate, RecallWeights


class RecallRankingPolicy:
    """Re-ranks the engine's hits with note kind, recency, origin and area.

    The score is `1 / (1 + rank_decay * rank)` times the kind, recency and origin weights, and
    times `elsewhere` for a note outside the preferred area.
    Highest score first; ties break by the engine's rank, then by path, so the order is
    deterministic. Pure: `today` is a parameter and nothing is read or written. A candidate
    is only down-weighted, never dropped.
    """

    def __init__(self, weights: RecallWeights) -> None:
        self._weights: RecallWeights = weights

    def rank(self, candidates: Iterable[RecallCandidate], *, today: date) -> tuple[str, ...]:
        """Candidate paths, most worth recalling first.

        Args:
            candidates: The search hits.
            today: The date recency is measured against.

        Returns:
            Every candidate's path, best first.
        """
        scored: list[tuple[float, int, str]] = [
            (-self._score(candidate, today), candidate.rank, candidate.path)
            for candidate in candidates
        ]
        return tuple(path for _, _, path in sorted(scored))

    def _score(self, candidate: RecallCandidate, today: date) -> float:
        weights: RecallWeights = self._weights
        age_days: int | None = (
            None if candidate.updated is None else (today - candidate.updated).days
        )
        position: float = 1 / (1 + weights.rank_decay * candidate.rank)
        return (
            position
            * weights.kind_weight(candidate.kind)
            * weights.recency_weight(age_days)
            * weights.origin_weight(candidate.origin)
            * (1.0 if candidate.preferred else weights.elsewhere)
        )
