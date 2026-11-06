"""How much each signal counts when notes are ranked for recall."""

from pydantic import Field

from noesis.shared_kernel.domain.value_objects import ValueObject

from .note_kind_enum import NoteKindEnum
from .note_origin_enum import NoteOriginEnum


class RecallWeights(ValueObject):
    """Multipliers for the recall score; each factor is in (0, 1], 1 meaning no penalty.

    Kinds weigh gotcha = decision > glossary > run. A note of unknown kind gets
    `neutral_kind` instead. Recency halves every `recency_half_life_days` but never goes
    below `recency_floor`, so an old note is down-weighted, never dropped. A manual note
    outweighs an auto one.

    Attributes:
        gotcha: Weight of a gotcha.
        decision: Weight of a decision.
        glossary: Weight of a glossary term.
        run: Weight of a run outcome.
        neutral_kind: Weight of a note with no kind.
        recency_half_life_days: Days after which the recency factor halves.
        recency_floor: Lowest recency factor; also used when the date is unknown.
        manual: Weight of a manual note.
        auto: Weight of an auto note.
        rank_decay: How fast the engine position loses weight: `1 / (1 + rank_decay * rank)`.
    """

    gotcha: float = Field(default=1.0, gt=0, le=1)
    decision: float = Field(default=1.0, gt=0, le=1)
    glossary: float = Field(default=0.8, gt=0, le=1)
    run: float = Field(default=0.6, gt=0, le=1)
    neutral_kind: float = Field(default=0.8, gt=0, le=1)
    recency_half_life_days: int = Field(default=90, gt=0)
    recency_floor: float = Field(default=0.3, gt=0, le=1)
    manual: float = Field(default=1.0, gt=0, le=1)
    auto: float = Field(default=0.8, gt=0, le=1)
    rank_decay: float = Field(default=0.15, ge=0)

    def kind_weight(self, kind: NoteKindEnum | None) -> float:
        """The weight of `kind`; `neutral_kind` when it is unknown."""
        match kind:
            case NoteKindEnum.GOTCHA:
                return self.gotcha
            case NoteKindEnum.DECISION:
                return self.decision
            case NoteKindEnum.GLOSSARY:
                return self.glossary
            case NoteKindEnum.RUN:
                return self.run
            case None:
                return self.neutral_kind

    def origin_weight(self, origin: NoteOriginEnum) -> float:
        """The weight of a manual or an auto note."""
        return self.manual if origin is NoteOriginEnum.MANUAL else self.auto

    def recency_weight(self, age_days: int | None) -> float:
        """The factor for a note `age_days` old: halves each half-life, never below the floor.

        Args:
            age_days: Days since the last update; None when unknown. A negative age counts as 0.
        """
        if age_days is None:
            return self.recency_floor
        decayed: float = 0.5 ** (max(age_days, 0) / self.recency_half_life_days)
        return max(self.recency_floor, decayed)
