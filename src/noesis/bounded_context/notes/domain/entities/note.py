"""The Note aggregate: one Markdown document of durable knowledge."""

from dataclasses import dataclass
from datetime import datetime
from typing import Self

from noesis.bounded_context.notes.domain.value_objects import (
    NoteDraft,
    NoteFrontmatter,
    NoteId,
    NoteKind,
    NoteOriginEnum,
    NotePath,
    NoteScope,
    NoteSection,
    NoteSourceRef,
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
    required_sections: tuple[str, ...], sections: tuple[NoteSection, ...]
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
        for heading in required_sections
    ]  # canonical heading spelling, whatever casing the draft used
    required_keys: set[str] = {heading.casefold() for heading in required_sections}
    extras: list[NoteSection] = [
        s for s in sections if s.heading.strip().casefold() not in required_keys
    ]
    return (*required, *extras)


@dataclass(slots=True, kw_only=True)
class Note(AggregateRoot["Note"]):
    """A note with its identity, title, sections and provenance.

    Invariants: the required sections of its kind are always present, and a note written
    by a person (`origin: manual`) is never changed by automated curation. Its identity is
    its id, never its path: the file may be moved without changing the note.

    Attributes:
        id: Stable id, kept in the frontmatter.
        scope: Repository or topic the note belongs to.
        kind: What the note records.
        origin: Who wrote it.
        path: Where its file currently sits in the source.
        title: Human title, rendered as the `#` heading.
        sections: Body sections, required ones first.
        sources: Where the knowledge came from (`commit:<sha>`, `session:<id>`).
    """

    id: NoteId
    scope: NoteScope
    kind: NoteKind
    origin: NoteOriginEnum
    path: NotePath
    title: str
    sections: tuple[NoteSection, ...]
    sources: tuple[NoteSourceRef, ...] = ()

    @property
    def is_auto(self) -> bool:
        """Whether noesis wrote it without a person in the loop."""
        return self.origin is NoteOriginEnum.AUTO

    @property
    def frontmatter(self) -> NoteFrontmatter:
        """The identity block written at the top of its file."""
        return NoteFrontmatter(
            id=self.id,
            scope=self.scope,
            kind=self.kind,
            origin=self.origin,
            sources=self.sources,
            updated=self.updated_at.date(),
        )

    @classmethod
    def create(
        cls,
        *,
        id: NoteId,
        scope: NoteScope,
        origin: NoteOriginEnum,
        path: NotePath,
        draft: NoteDraft,
        required_sections: tuple[str, ...],
        sources: tuple[NoteSourceRef, ...] = (),
        now: datetime,
    ) -> Self:
        """Create a note from a draft, completing its required sections.

        Args:
            id: The new note's id.
            scope: Repository or topic the note belongs to.
            origin: Who is writing it.
            path: Free path where its file will be written.
            draft: Kind, slug, title and proposed sections.
            required_sections: Headings every note of the draft's kind has, in order.
            sources: What the knowledge came from.
            now: Creation time.

        Returns:
            The new note, with a `NoteCreated` event pending.
        """
        note: Self = cls(
            id=id,
            scope=scope,
            kind=draft.kind,
            origin=origin,
            path=path,
            title=draft.title.strip(),
            sections=_complete_sections(required_sections, draft.sections),
            sources=tuple(dict.fromkeys(sources)),
            created_at=now,
            updated_at=now,
        )
        note._record(NoteCreated(aggregate_id=id.value, payload={"path": path.value}))
        return note

    def revise(
        self,
        draft: NoteDraft,
        *,
        required_sections: tuple[str, ...],
        sources: tuple[NoteSourceRef, ...],
        now: datetime,
    ) -> None:
        """Replace the content with a newer draft from automated curation, in place.

        Args:
            draft: New title and sections (the kind must match the note).
            required_sections: Headings every note of this kind has, in order.
            sources: References behind the revision; merged with the existing ones.
            now: Revision time.

        Raises:
            ManualNoteProtectedError: The note was written by a person.
        """
        if not self.is_auto:
            raise ManualNoteProtectedError(
                f"{self.path.value} was written by a person; automated curation may not change it.",
                {"path": self.path.value},
            )
        self.title = draft.title.strip() or self.title
        self.sections = _complete_sections(required_sections, draft.sections)
        self.sources = tuple(dict.fromkeys((*self.sources, *sources)))
        self.updated_at = now
        self._record(NoteRevised(aggregate_id=self.id.value, payload={"path": self.path.value}))
