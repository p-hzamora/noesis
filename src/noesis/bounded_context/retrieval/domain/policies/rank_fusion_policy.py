"""Reciprocal-rank fusion of several ranked record lists."""

from collections.abc import Sequence

RANK_FUSION_OFFSET: int = 60


class RankFusionPolicy:
    """Merges ranked lists of record ids by position only.

    Scores of different engines are not comparable, so only positions count: a record several
    lists rank high rises. Ties keep the order of first appearance.
    """

    def fuse(self, rankings: Sequence[Sequence[str]]) -> list[str]:
        """Reciprocal-rank fusion with one entry per record id.

        Args:
            rankings: One list per source, best first.

        Returns:
            Every record id once, best first.
        """
        score: dict[str, float] = {}
        for ranking in rankings:
            for position, record_id in enumerate(ranking):
                score[record_id] = score.get(record_id, 0.0) + 1 / (RANK_FUSION_OFFSET + position)
        return sorted(score, key=lambda record_id: -score[record_id])  # stable: first appearance
