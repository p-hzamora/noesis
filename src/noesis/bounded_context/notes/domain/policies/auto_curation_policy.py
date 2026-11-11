"""Rules that turn a curator's decision into a stored note, or into a reported skip."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from noesis.bounded_context.notes.domain.entities import Note
from noesis.bounded_context.notes.domain.value_objects import (
    CurationActionEnum,
    CurationDecision,
    NoteDraft,
    NoteOriginEnum,
    NotePath,
    NotePlacement,
    NoteScope,
    NoteSourceRef,
)


class CurationOutcomeEnum(StrEnum):
    """What happened to one decision."""

    CREATED = "created"
    UPDATED = "updated"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True, kw_only=True)
class CurationOutcome:
    """Result of applying one decision.

    Attributes:
        outcome: Created, updated or skipped.
        candidate: The candidate's short name.
        reason: Why it was skipped (or the curator's reason otherwise).
        note: The note to save, for created and updated outcomes.
    """

    outcome: CurationOutcomeEnum
    candidate: str
    reason: str
    note: Note | None = None


class AutoCurationPolicy:
    """Applies a curator decision without a person in the loop.

    A manual note on the same topic (same scope, kind and slug) always wins: the candidate is
    skipped as covered, never merged. CREATE and UPDATE both upsert the auto note, in place
    and with its id kept, so a curator that guesses the wrong verb cannot duplicate or lose
    knowledge. A note is never superseded: it is revised or created.
    """

    def apply(
        self,
        decision: CurationDecision,
        *,
        scope: NoteScope,
        existing_auto: Note | None,
        manual_path: NotePath | None,
        placement: NotePlacement | None,
        sources: tuple[NoteSourceRef, ...],
        now: datetime,
    ) -> CurationOutcome:
        """Decide what to store for one decision.

        Args:
            decision: The curator's verdict.
            scope: Scope of the work's repository.
            existing_auto: The auto note on the decision's topic, if any.
            manual_path: Path of a manual note on the same topic, if any.
            placement: Id, free path and required sections for the draft's kind; None when the
                decision has no draft.
            sources: Source references behind the work.
            now: Current time.

        Returns:
            The outcome, carrying the note to save unless it was skipped.
        """
        draft: NoteDraft | None = decision.draft
        if decision.action is CurationActionEnum.SKIP:
            return CurationOutcome(
                outcome=CurationOutcomeEnum.SKIPPED,
                candidate=decision.candidate,
                reason=decision.reason,
            )
        if draft is None or placement is None:
            return CurationOutcome(
                outcome=CurationOutcomeEnum.SKIPPED,
                candidate=decision.candidate,
                reason="malformed decision: no note draft",
            )
        if manual_path is not None:
            return CurationOutcome(
                outcome=CurationOutcomeEnum.SKIPPED,
                candidate=decision.candidate,
                reason=f"covered by {manual_path.value}",
            )
        if existing_auto is not None:
            existing_auto.revise(
                draft, required_sections=placement.required_sections, sources=sources, now=now
            )
            return CurationOutcome(
                outcome=CurationOutcomeEnum.UPDATED,
                candidate=decision.candidate,
                reason=decision.reason,
                note=existing_auto,
            )
        note = Note.create(
            id=placement.id,
            scope=scope,
            origin=NoteOriginEnum.AUTO,
            path=placement.path,
            draft=draft,
            required_sections=placement.required_sections,
            sources=sources,
            now=now,
        )
        return CurationOutcome(
            outcome=CurationOutcomeEnum.CREATED,
            candidate=decision.candidate,
            reason=decision.reason,
            note=note,
        )
