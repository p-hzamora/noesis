"""Rules that turn a curator's decision into a stored note, or into a reported skip."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from noesis.bounded_context.knowledge.domain.entities import Note
from noesis.bounded_context.knowledge.domain.value_objects import (
    CurationActionEnum,
    CurationDecision,
    NoteArea,
    NoteDraft,
    NoteOriginEnum,
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

    Auto notes live only under `<area>/auto/`. A manual note on the same topic (same kind
    and slug) always wins: the candidate is skipped as covered, never merged. CREATE and
    UPDATE both upsert the auto note, so a curator that guesses the wrong verb cannot
    duplicate or lose knowledge.
    """

    def apply(
        self,
        decision: CurationDecision,
        *,
        area: NoteArea,
        existing_auto: Note | None,
        existing_manual: Note | None,
        commits: tuple[str, ...],
        session: str | None,
        now: datetime,
    ) -> CurationOutcome:
        """Decide what to store for one decision.

        Args:
            decision: The curator's verdict.
            area: Vault folder of the work's repository.
            existing_auto: The auto note at the decision's location, if any.
            existing_manual: A manual note with the same kind and slug, if any.
            commits: Commit SHAs behind the work.
            session: Short session id.
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
        if draft is None:
            return CurationOutcome(
                outcome=CurationOutcomeEnum.SKIPPED,
                candidate=decision.candidate,
                reason="malformed decision: no note draft",
            )
        if existing_manual is not None:
            return CurationOutcome(
                outcome=CurationOutcomeEnum.SKIPPED,
                candidate=decision.candidate,
                reason=f"covered by {existing_manual.location.relative_path}",
            )
        if existing_auto is not None:
            existing_auto.revise(draft, commits=commits, session=session, now=now)
            return CurationOutcome(
                outcome=CurationOutcomeEnum.UPDATED,
                candidate=decision.candidate,
                reason=decision.reason,
                note=existing_auto,
            )
        note = Note.create(
            area=area,
            origin=NoteOriginEnum.AUTO,
            draft=draft,
            commits=commits,
            session=session,
            now=now,
        )
        return CurationOutcome(
            outcome=CurationOutcomeEnum.CREATED,
            candidate=decision.candidate,
            reason=decision.reason,
            note=note,
        )
