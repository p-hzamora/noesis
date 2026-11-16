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

    def protect(self, baseline: Sequence[str], extra: Sequence[str]) -> list[str]:
        """The baseline order unchanged, then the records only `extra` holds, in its order.

        Used for identifier-like queries: semantic candidates may add records but never reorder
        what lexical and graph ranked.
        """
        seen: set[str] = set(baseline)
        appended: list[str] = [
            record_id for record_id in dict.fromkeys(extra) if record_id not in seen
        ]
        return [*dict.fromkeys(baseline), *appended]
