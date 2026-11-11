"""Merges the ranked answers of several sources into one, by note id."""

from collections.abc import Sequence
from dataclasses import dataclass

from noesis.bounded_context.notes.application.dtos import NoteSummaryDto

RANK_FUSION_OFFSET: int = 60


@dataclass(frozen=True, slots=True, kw_only=True)
class RankedNotes:
    """One source's answer.

    Attributes:
        primary: Whether the answer comes from the primary source.
        notes: The notes, best first.
    """

    primary: bool
    notes: Sequence[NoteSummaryDto]


def fuse_rankings(rankings: Sequence[RankedNotes], *, limit: int) -> list[NoteSummaryDto]:
    """Reciprocal-rank fusion with one entry per note id.

    Only positions count (scores of different engines are not comparable): a note several
    sources rank high rises. When a note appears in more than one source, the primary's copy
    is the one returned. Ties keep the order of first appearance, primary answers first.

    Args:
        rankings: One ranked list per source.
        limit: Most notes returned.

    Returns:
        The fused notes, best first.
    """
    ordered: list[RankedNotes] = sorted(rankings, key=lambda ranked: not ranked.primary)
    score: dict[str, float] = {}
    chosen: dict[str, NoteSummaryDto] = {}
    for ranked in ordered:
        for position, note in enumerate(ranked.notes):
            score[note.id] = score.get(note.id, 0.0) + 1 / (RANK_FUSION_OFFSET + position)
            chosen.setdefault(note.id, note)  # primary lists come first, so its copy wins
    order: list[str] = sorted(score, key=lambda note_id: -score[note_id])  # stable
    return [chosen[note_id] for note_id in order[:limit]]
