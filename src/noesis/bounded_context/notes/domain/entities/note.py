"""The Note aggregate: one Markdown document of durable knowledge."""

from dataclasses import dataclass
from datetime import datetime
from typing import Self

from noesis.bounded_context.notes.domain.value_objects import (
    NoteArea,
    NoteDraft,
    NoteKindEnum,
    NoteLocation,
    NoteOriginEnum,
    NoteSection,
)
from noesis.exceptions import (
    ManualNoteProtectedError,
)
from noesis.shared_kernel.domain.entities import AggregateRoot
from noesis.shared_kernel.domain.events import DomainEvent

NOT_RECORDED: str = "Not recorded"


class NoteCreated(DomainEvent["Note"]):
    """A note was created."""


class NoteRevised(DomainEvent["Note"]):
    """An existing note received new content."""


def _complete_sections(
    kind: NoteKindEnum, sections: tuple[NoteSection, ...]
) -> tuple[NoteSection, ...]:
    """Required sections first, in canonical order and spelling, `Not recorded` when absent; extras after."""
    by_heading: dict[str, NoteSection] = {
        section.heading.strip().casefold(): section for section in sections
    }
    required: list[NoteSection] = [
        NoteSection(
            heading=heading,
            body=found.body if (found := by_heading.get(heading.casefold())) else NOT_RECORDED,
        )
        for heading in kind.required_sections
    ]  # canonical heading spelling, whatever casing the draft used
    required_keys: set[str] = {heading.casefold() for heading in kind.required_sections}
    extras: list[NoteSection] = [
        s for s in sections if s.heading.strip().casefold() not in required_keys
    ]
    return (*required, *extras)


@dataclass(slots=True, kw_only=True)
class Note(AggregateRoot["Note"]):
    """A note with its location, title, sections and provenance.

    Invariants: the required sections of its kind are always present, and a note written
    by a person (`origin: manual`) is never changed by automated curation.

    Attributes:
        location: Where the note lives; also its identity.
        title: Human title, rendered as the `#` heading.
        sections: Body sections, required ones first.
        tags: Free tags.
        commits: Commit SHAs the knowledge came from (auto notes).
        session: Short id of the session that produced it (auto notes).
    """

    location: NoteLocation
    title: str
    sections: tuple[NoteSection, ...]
    tags: tuple[str, ...] = ()
    commits: tuple[str, ...] = ()
    session: str | None = None

    @property
    def id(self) -> str:
        """Stable id: `auto-<kind>-<slug>` or `<kind>-<slug>`."""
        prefix: str = "auto-" if self.is_auto else ""
        return f"{prefix}{self.location.kind.value}-{self.location.slug.value}"

    @property
    def is_auto(self) -> bool:
        """Whether noesis wrote it without a person in the loop."""
        return self.location.origin is NoteOriginEnum.AUTO

    @classmethod
    def create(
        cls,
        *,
        area: NoteArea,
        origin: NoteOriginEnum,
        draft: NoteDraft,
        commits: tuple[str, ...] = (),
        session: str | None = None,
        now: datetime,
    ) -> Self:
        """Create a note from a draft, completing its required sections.

        Args:
            area: Vault folder the note belongs to.
            origin: Who is writing it.
            draft: Kind, slug, title and proposed sections.
            commits: Commit SHAs the knowledge came from.
            session: Short session id, for auto notes.
            now: Creation time.

        Returns:
            The new note, with a `NoteCreated` event pending.
        """
        location = NoteLocation(area=area, origin=origin, kind=draft.kind, slug=draft.slug)
        note: Self = cls(
            location=location,
            title=draft.title.strip(),
            sections=_complete_sections(draft.kind, draft.sections),
            tags=tuple(
                dict.fromkeys(
                    (
                        draft.kind.value,
                        *([area.repository] if area.repository else []),
                        *(["auto"] if origin is NoteOriginEnum.AUTO else []),
                    )
                )
            ),
            commits=tuple(dict.fromkeys(commits)),
            session=session,
            created_at=now,
            updated_at=now,
        )
        note._record(
            NoteCreated(
                aggregate_id=location.relative_path, payload={"path": location.relative_path}
            )
        )
        return note

    def revise(
        self, draft: NoteDraft, *, commits: tuple[str, ...], session: str | None, now: datetime
    ) -> None:
        """Replace the content with a newer draft from automated curation.

        Args:
            draft: New title and sections (kind and slug must match the note).
            commits: Commit SHAs behind the revision; merged with the existing ones.
            session: Short id of the revising session.
            now: Revision time.

        Raises:
            ManualNoteProtectedError: The note was written by a person.
        """
        if not self.is_auto:
            raise ManualNoteProtectedError(
                f"{self.location.relative_path} was written by a person; automated curation may not change it.",
                {"path": self.location.relative_path},
            )
        self.title = draft.title.strip() or self.title
        self.sections = _complete_sections(self.location.kind, draft.sections)
        self.commits = tuple(dict.fromkeys((*self.commits, *commits)))
        self.session = session or self.session
        self.updated_at = now
        self._record(
            NoteRevised(
                aggregate_id=self.location.relative_path,
                payload={"path": self.location.relative_path},
            )
        )
